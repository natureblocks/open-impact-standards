import re
from validation import obj_specs, oisql, pipeline_obj_specs, patterns
from enums import ref_types


def is_template_entity_reference(obj, key, entity_obj_name):
    return (
        isinstance(obj, dict)
        and key in obj
        and is_global_ref(obj[key])
        and parse_ref_type(obj[key]) == entity_obj_name
    )


def is_path(value):
    # TODO: make path validation stricter
    return isinstance(value, str) and (
        "." in value and value[0] != "^" or (value[0] == "{" and value[-1] == "}")
    )


def is_global_ref(value):
    if not isinstance(value, str):
        return False

    first_segment = value.split(".")[0]  # in case it's a path
    split_ref = first_segment.split(":")
    ref_type = split_ref[0]
    ref_id = ":".join(split_ref[1:])

    alias_match = re.match(patterns.global_ref_alias, ref_id)
    identifier_match = re.match(patterns.global_ref_identifier, ref_id)
    return ref_type in ref_types and (alias_match or identifier_match)


def is_variable(value):
    return re.match(patterns.variable, value)


def is_local_variable(value):
    return isinstance(value, str) and re.match(patterns.local_variable, value)


def is_filter_ref(value):
    return isinstance(value, str) and re.match(patterns.filter_ref, value)


def is_import_ref(value):
    split_path = value.split(".")
    return (
        len(split_path) > 1
        and is_global_ref(split_path[0])
        and is_global_ref(split_path[1])
        and parse_ref_type(split_path[0]) == "schema"
    )


def parse_ref_id(value):
    if not is_global_ref(value):
        raise Exception(f"Invalid ref: {value}")

    if is_import_ref(value):
        value = value.split(".")[1]

    ref_id = ":".join(value.split(":")[1:]).split(".")[0]  # "{ref_id}" or "ref_id"

    if ref_id[0] == "{" and ref_id[-1] == "}":
        return ref_id[1:-1]

    return ref_id


def as_ref(value, ref_type, value_is_id=False):
    if ref_type not in ref_types:
        raise Exception(f"Invalid ref type: {ref_type}")

    if value_is_id:
        left_brace = ""
        right_brace = ""
    else:
        left_brace = "{"
        right_brace = "}"

    return ref_type + ":" + left_brace + str(value) + right_brace


def parse_ref_type(value):
    if not is_global_ref(value):
        raise Exception(f"Invalid ref: {value}")

    if is_import_ref(value):
        split_path = value.split(".")
        return parse_ref_type(split_path[1])

    return value.split(":")[0]


def as_namespaced_ref(schema_id, entity_id, entity_type):
    ref = f"{entity_type}:{str(entity_id)}"
    if schema_id is not None:
        # note that imported schemas do not have an "id" field,
        # so the alias reference pattern is always used
        ref = "schema:{" + schema_id + "}." + ref
    return ref

def prepend_schema_id(schema_id, ref):
    if schema_id is not None:
        # note that imported schemas do not have an "id" field,
        # so the alias reference pattern is always used
        return "schema:{" + schema_id + "}." + ref
    return ref

def truncate_schema_id(ref):
    """Removes the schema id from a reference, if it exists.
    """

    if is_import_ref(ref):
        return ".".join(ref.split(".")[1:])

    return ref

def reduce_ref(ref):
    split_ref = ref.split(".")
    num_path_segments = len(split_ref)
    if num_path_segments == 0:
        return None
    
    if num_path_segments == 1:
        return split_ref[0]
    
    if is_import_ref(ref):
        return ".".join(split_ref[:1])
    
    return split_ref[0]

def parse_schema_id(value):
    if not is_import_ref(value):
        return None

    schema_id = value.split(".")[0].split(":")[1]
    if schema_id[0] == "{" and schema_id[-1] == "}":
        return schema_id[1:-1]

    return schema_id


def action_ref_from_dependency_ref(dependency, left_or_right):
    if _is_action_ref(dependency, left_or_right):
        split_ref = dependency["compare"][left_or_right]["ref"].split(".")
        if is_import_ref(dependency["compare"][left_or_right]["ref"]):
            return ".".join(split_ref[:1])

        return split_ref[0]

    return None


def action_id_from_dependency_ref(dependency, left_or_right):
    if _is_action_ref(dependency, left_or_right):
        return parse_ref_id(dependency["compare"][left_or_right]["ref"])
    
    return None


def _is_action_ref(dependency, left_or_right):
    return (
        "compare" in dependency
        and left_or_right in dependency["compare"]
        and "ref" in dependency["compare"][left_or_right]
        and is_template_entity_reference(
            dependency["compare"][left_or_right], "ref", "action"
        )
    )


def get_obj_spec(obj_spec_name):
    if hasattr(obj_specs, obj_spec_name):
        return getattr(obj_specs, obj_spec_name)
    elif hasattr(oisql, obj_spec_name):
        return getattr(oisql, obj_spec_name)
    elif hasattr(pipeline_obj_specs, obj_spec_name):
        return getattr(pipeline_obj_specs, obj_spec_name)

    raise Exception(f"obj_spec not found: {obj_spec_name}")


def field_type_from_python_type_name(python_type_name):
    type_map = {
        "str": "STRING",
        "int": "NUMERIC",
        "float": "NUMERIC",
        "bool": "BOOLEAN",
        "list": "LIST",
        "dict": "OBJECT",
    }

    if python_type_name in type_map:
        return type_map[python_type_name]

    raise NotImplementedError(
        f"Field type not found for python type: {python_type_name}"
    )


def types_are_comparable(left_type, right_type, operator):
    # {left_types: {valid_operators: valid_right_type}}
    valid_comparisons = {
        "STRING": {
            "EQUALS": "STRING",
            "DOES_NOT_EQUAL": "STRING",
            "CONTAINS": "STRING",
            "DOES_NOT_CONTAIN": "STRING",
            "ONE_OF": "STRING_LIST",
            "NONE_OF": "STRING_LIST",
        },
        "NUMERIC": {
            "EQUALS": "NUMERIC",
            "DOES_NOT_EQUAL": "NUMERIC",
            "GREATER_THAN": "NUMERIC",
            "LESS_THAN": "NUMERIC",
            "GREATER_THAN_OR_EQUAL_TO": "NUMERIC",
            "LESS_THAN_OR_EQUAL_TO": "NUMERIC",
            "ONE_OF": "NUMERIC_LIST",
            "NONE_OF": "NUMERIC_LIST",
        },
        "BOOLEAN": {"EQUALS": "BOOLEAN"},
        "STRING_LIST": {
            "CONTAINS": "STRING",
            "DOES_NOT_CONTAIN": "STRING",
            "EQUALS": "STRING_LIST",
            "DOES_NOT_EQUAL": "STRING_LIST",
            "CONTAINS_ANY_OF": "STRING_LIST",
            "IS_SUBSET_OF": "STRING_LIST",
            "IS_SUPERSET_OF": "STRING_LIST",
            "CONTAINS_NONE_OF": "STRING_LIST",
        },
        "NUMERIC_LIST": {
            "CONTAINS": "NUMERIC",
            "DOES_NOT_CONTAIN": "NUMERIC",
            "EQUALS": "NUMERIC_LIST",
            "DOES_NOT_EQUAL": "NUMERIC_LIST",
            "CONTAINS_ANY_OF": "NUMERIC_LIST",
            "IS_SUBSET_OF": "NUMERIC_LIST",
            "IS_SUPERSET_OF": "NUMERIC_LIST",
            "CONTAINS_NONE_OF": "NUMERIC_LIST",
        },
        "BOOLEAN_LIST": {
            "CONTAINS": "BOOLEAN",
            "DOES_NOT_CONTAIN": "BOOLEAN",
            "EQUALS": "BOOLEAN_LIST",
            "DOES_NOT_EQUAL": "BOOLEAN_LIST",
            "IS_SUBSET_OF": "BOOLEAN_LIST",
            "IS_SUPERSET_OF": "BOOLEAN_LIST",
        },
        "OBJECT": {
            "EQUALS": "OBJECT",
            "DOES_NOT_EQUAL": "OBJECT",
            "ONE_OF": "OBJECT_LIST",
            "NONE_OF": "OBJECT_LIST",
        },
        "OBJECT_LIST": {
            "CONTAINS": "OBJECT",
            "DOES_NOT_CONTAIN": "OBJECT",
            "EQUALS": "OBJECT_LIST",
            "DOES_NOT_EQUAL": "OBJECT_LIST",
            "CONTAINS_ANY_OF": "OBJECT_LIST",
            "IS_SUBSET_OF": "OBJECT_LIST",
            "IS_SUPERSET_OF": "OBJECT_LIST",
            "CONTAINS_NONE_OF": "OBJECT_LIST",
        },
    }

    return (
        left_type in valid_comparisons
        and operator in valid_comparisons[left_type]
        and right_type == valid_comparisons[left_type][operator]
    )
