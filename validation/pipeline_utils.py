import json
from validation import utils
from validation.field_type_details import FieldTypeDetails
from enums import valid_list_item_types


def validate_operation(
    left_operand_type, method, right_operand_type, left_operand_is_null=False
):
    r = right_operand_type.to_string()
    l = left_operand_type.to_string()

    if left_operand_is_null:
        if method != "SET":
            raise Exception(
                'when a variable\'s initial value is null, the "SET" method must be used for the first operation on the variable'
            )

        if l != r:
            raise Exception(
                f"cannot set value of type {json.dumps(r)} to variable of type {json.dumps(l)}"
            )

        return

    # {left_operand_type: {right_operand_type: [methods]}}
    valid_methods = {
        "STRING": {"STRING": ["CONCAT"]},
        "NUMERIC": {"NUMERIC": ["ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"]},
        "BOOLEAN": {"BOOLEAN": ["AND", "OR"]},
        "NUMERIC_LIST": {
            "NUMERIC_LIST": ["CONCAT"],
            "NUMERIC": ["APPEND", "PREPEND"],
        },
        "STRING_LIST": {
            "STRING_LIST": ["CONCAT"],
            "STRING": ["APPEND", "PREPEND"],
        },
        "NULL": {
            "OBJECT": ["SET"],
            "STRING": ["SET"],
            "NUMERIC": ["SET"],
            "BOOLEAN": ["SET"],
            "STRING_LIST": ["SET"],
            "NUMERIC_LIST": ["SET"],
        },
    }

    if (
        l not in valid_methods
        or r not in valid_methods[l]
        or method not in valid_methods[l][r]
    ):
        raise Exception(
            f"invalid method for operand types {json.dumps(l)} and {json.dumps(r)}: {json.dumps(method)}"
        )


def determine_right_operand_type(operation, ref_type_details, schema_validator):
    if "aggregate" in operation:
        field_to_aggregate = operation["aggregate"]["field"]
        operator = operation["aggregate"]["operator"]

        # determine the field type to aggregate
        if field_to_aggregate == "$_item":
            # aggregating a list of ref_type_details.item_type
            field_type_to_aggregate = ref_type_details
        else:  # ref must be an edge collection
            if not ref_type_details.item_type == "OBJECT":
                raise Exception(
                    f'invalid field specified for {ref_type_details.item_type}_LIST aggregation: expected "$_item", got {json.dumps(field_to_aggregate)}'
                )

            field_type_to_aggregate = schema_validator._resolve_type_from_object_path(
                ref_type_details.item_tag, field_to_aggregate
            )

            if field_type_to_aggregate is None:
                raise Exception(
                    f"field {json.dumps(field_to_aggregate)} not found on object type {json.dumps(ref_type_details.item_tag)}"
                )

        if not field_type_to_aggregate.is_list:
            raise Exception("cannot aggregate non-list type")

        compatible_operators = {
            "BOOLEAN": ["AND", "OR", "COUNT"],
            "STRING": ["FIRST", "LAST", "COUNT"],
            "NUMERIC": [
                "FIRST",
                "LAST",
                "COUNT",
                "SUM",
                "AVERAGE",
                "MIN",
                "MAX",
            ],
            "OBJECT": ["FIRST", "LAST", "COUNT"],
            # TODO: decide whether to support aggregating lists of lists
        }

        if field_type_to_aggregate.item_type not in compatible_operators:
            raise Exception(
                f"cannot aggregate items of type: {json.dumps(field_type_to_aggregate.item_type)}"
            )

        # is the operator valid for the type of items in the list?
        if operator not in compatible_operators[field_type_to_aggregate.item_type]:
            item_type_string = (
                "EDGE_COLLECTION"
                if field_type_to_aggregate.item_type == "OBJECT"
                else ref_type_details.item_type + "_LIST"
            )
            raise Exception(
                f"invalid aggregation operator for {json.dumps(item_type_string)} items: {json.dumps(operator)}"
            )

        if operator in ["FIRST", "LAST"]:
            return FieldTypeDetails(
                is_list=False,
                item_type=ref_type_details.item_type,
                item_tag=ref_type_details.item_tag,
            )
        else:
            return FieldTypeDetails(
                is_list=False,
                item_type="BOOLEAN" if operator in ["AND", "OR"] else "NUMERIC",
                item_tag=None,
            )

    if "sort" in operation:
        if not ref_type_details.is_list:
            raise Exception("cannot sort non-list type")

        return ref_type_details

    if "filter" in operation:
        if not ref_type_details.is_list:
            raise Exception("cannot filter non-list type")

        # TODO: validate filter where clause
        return ref_type_details

    if "select" in operation:
        # ref must be an edge or edge collection
        if ref_type_details.item_tag is None:
            raise Exception("cannot select from non-edge type")

        # try to resolve the path
        resulting_type = schema_validator._resolve_type_from_object_path(
            ref_type_details.item_tag, operation["select"]
        )

        if resulting_type is None:
            raise Exception(
                f"field {json.dumps(operation['select'])} not found on object type {json.dumps(ref_type_details.item_tag)}"
            )

        return resulting_type

    # no operation specified
    return ref_type_details


def initial_matches_type(initial_type_details, var_type):
    initial_field_type_string = initial_type_details.to_string()
    return (
        initial_field_type_string == "NULL"
        or initial_field_type_string == var_type
        or (
            initial_field_type_string == "LIST"
            and ("_LIST" in var_type or var_type == "EDGE_COLLECTION")
        )
    )


def field_type_details_from_initial_value(variable):
    value = variable["initial"]
    if value is None:
        return FieldTypeDetails(
            is_list=False,
            item_type=variable["type"],
            item_tag=None,
        )

    if not isinstance(value, list):
        return FieldTypeDetails(
            is_list=False,
            item_type=utils.field_type_from_python_type_name(type(value).__name__),
            item_tag=None,
        )

    item_type = None
    for item in value:
        if item_type is None:
            item_type = utils.field_type_from_python_type_name(type(item).__name__)
        elif item_type != utils.field_type_from_python_type_name(type(item).__name__):
            raise Exception("cannot mix types in list")

        if item_type not in valid_list_item_types:
            raise Exception(
                f"list items must be one of the following types: {json.dumps(valid_list_item_types)}"
            )

    return FieldTypeDetails(
        is_list=True,
        item_type=item_type or variable["type"][: -len("_LIST")]
        if variable["type"].endswith("_LIST")
        else None,
        item_tag=None,
    )
