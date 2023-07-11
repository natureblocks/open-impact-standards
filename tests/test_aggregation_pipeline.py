import json

import pytest
from validation.schema_validator import SchemaValidator
from validation import utils
from tests import fixtures
from enums import valid_list_item_types


class TestAggregationPipeline:
    def test_variable_scope(self):
        schema_validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
                {
                    "name": "$another_var",
                    "type": "NUMERIC_LIST",
                    "initial": [9],
                },
            ],
            "traverse": [
                {
                    "ref": "$_object.objects",
                    "foreach": {
                        "as": "$edge",
                        "variables": [
                            {
                                "name": "$average",
                                "type": "NUMERIC",
                                "initial": 0,
                            },
                        ],
                        "apply": [
                            {
                                "from": "$edge",
                                "method": "ADD",
                                "to": "$average",
                                "aggregate": {
                                    "field": "numbers",
                                    "operator": "AVERAGE",
                                },
                            },
                        ],
                    },
                },
            ],
            "apply": [
                {
                    "from": None,
                    "method": "ADD",
                    "to": "$some_var",
                },
            ],
            "output": [],
        }

        def set_pipeline_value(key1, key2, val):
            schema["actions"][0]["pipeline"][key1][0][key2] = val

        # should not be able to reference variables out of scope
        set_pipeline_value("apply", "from", "$average")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline (action id: 0).from: variable "$average" is not in scope'
            in errors
        )

        # assigning from a variable that has not yet been assigned a value should throw a warning
        set_pipeline_value("apply", "from", "$some_var")
        set_pipeline_value("apply", "to", "$another_var")
        set_pipeline_value("apply", "method", "APPEND")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert not errors
        assert (
            'root.actions[0].pipeline (action id: 0).from: variable used before assignment: "$some_var"'
            in schema_validator.warnings
        )

        schema["actions"][0]["pipeline"]["apply"].insert(
            0,
            {
                "from": "$_object.number",
                "to": "$some_var",
                "method": "ADD",
            },
        )

        # should not be able to assign to variables out of scope
        set_pipeline_value("apply", "to", "$average")
        set_pipeline_value("apply", "method", "ADD")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline (action id: 0).to: variable "$average" is not in scope'
            in errors
        )

    def test_assign(self):
        schema_validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "apply": [
                {
                    "from": None,
                    "method": "ADD",
                    "to": "$some_var",
                },
            ],
            "output": [],
        }

        def set_pipeline_value(key1, key2, val):
            schema["actions"][0]["pipeline"][key1][0][key2] = val

        # referenced variables must exist
        set_pipeline_value("apply", "from", "$non_existent_var")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline (action id: 0).from: variable not found: "$non_existent_var"'
            in errors
        )

        # assigned type must match variable type
        schema["actions"][0]["pipeline"]["variables"][0] = {
            "name": "$some_var",
            "type": "NUMERIC",
            "initial": None,
        }
        schema["actions"][0]["pipeline"]["apply"][0] = {
            "from": "$_object.name",
            "method": "SET",
            "to": "$some_var",
        }
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline (action id: 0): apply: cannot set value of type "STRING" to variable of type "NUMERIC"'
            in errors
        )

        set_pipeline_value("variables", "type", "STRING")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert not errors

        # if null is the initial value, the first assignment must be "SET"
        set_pipeline_value("apply", "method", "CONCAT")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline (action id: 0): apply: when a variable\'s initial value is null, the "SET" method must be used for the first operation on the variable'
            in errors
        )

        # method must be valid for types
        schema["actions"][0]["pipeline"]["variables"][0] = {
            "name": "$some_var",
            "type": "STRING_LIST",
            "initial": [],
        }
        schema["actions"][0]["pipeline"]["apply"][0] = {
            "from": "$_object.name",
            "method": "ADD",
            "to": "$some_var",
        }
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert errors

        set_pipeline_value("apply", "method", "APPEND")
        errors = schema_validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_variable_initial(self):
        schema_validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": None,
                    "initial": None,
                },
            ],
            "output": [],
        }

        def set_type(field_type):
            schema["actions"][0]["pipeline"]["variables"][0]["type"] = field_type

        def set_initial(initial):
            schema["actions"][0]["pipeline"]["variables"][0]["initial"] = initial

        invalid_initial_values = {
            "BOOLEAN": [0, "a", []],
            "NUMERIC": [True, "a", []],
            "STRING": [True, 0, [], {}],
            "NUMERIC_LIST": [True, "a", 0, [True], ["a"], [[]], [0, "a"]],
            "STRING_LIST": [True, "a", 0, [True], [0], [[]], [0, "a"]],
            "BOOLEAN_LIST": [True, "a", 0, ["a"], [0], [[]], [True, 1]],
            "EDGE": [True, "a", 0, []],
            "EDGE_COLLECTION": [True, "a", 0],
        }

        expected_context = (
            "root.actions[0].pipeline (action id: 0): variables[0].initial:"
        )
        for field_type, values in invalid_initial_values.items():
            set_type(field_type)
            for initial in values:
                set_initial(initial)
                errors = schema_validator.validate(json_string=json.dumps(schema))
                assert (
                    f"{expected_context} does not match expected type {json.dumps(field_type)}"
                    in errors
                    or f"{expected_context} list items must be one of the following types: {json.dumps(list(valid_list_item_types))}"
                    in errors
                    or f"{expected_context} cannot mix types in list" in errors
                )

        valid_initial_values = {
            "BOOLEAN": [True, False, None],
            "NUMERIC": [0, 1, 10.5, None],
            "STRING": ["", "test", None],
            "NUMERIC_LIST": [[], [1, 2, 3], None],
            "STRING_LIST": [[], ["a", "b", "c"], None],
            "BOOLEAN_LIST": [[], [True, False], None],
            "EDGE": [None],
            "EDGE_COLLECTION": [None, []],
        }

        for field_type, values in valid_initial_values.items():
            set_type(field_type)
            for initial in values:
                set_initial(initial)
                errors = schema_validator.validate(json_string=json.dumps(schema))
                assert not errors

    def test_resolve_type_from_object_path(self):
        validator = SchemaValidator()

        validator.schema = {
            "objects": {
                "NodeA": {
                    "string_field": {"field_type": "STRING"},
                    "numeric_list_field": {"field_type": "NUMERIC_LIST"},
                    "b": {
                        "field_type": "EDGE",
                        "object": "NodeB",
                    },
                },
                "NodeB": {
                    "numeric_field": {"field_type": "NUMERIC"},
                    "string_list_field": {"field_type": "STRING_LIST"},
                    "c_collection": {
                        "field_type": "EDGE_COLLECTION",
                        "object": "NodeC",
                    },
                },
                "NodeC": {
                    "boolean_field": {"field_type": "BOOLEAN"},
                    "d_collection": {
                        "field_type": "EDGE_COLLECTION",
                        "object": "NodeD",
                    },
                },
                "NodeD": {
                    "numeric_field": {"field_type": "NUMERIC"},
                    "numeric_list_field": {"field_type": "NUMERIC_LIST"},
                },
            },
        }

        # simple field
        assert validator._resolve_type_from_object_path(
            "NodeA", "string_field"
        ).__dict__ == {
            "is_list": False,
            "item_type": "STRING",
            "item_tag": None,
        }

        # list field
        assert validator._resolve_type_from_object_path(
            "NodeA", "numeric_list_field"
        ).__dict__ == {
            "is_list": True,
            "item_type": "NUMERIC",
            "item_tag": None,
        }

        # edge
        assert validator._resolve_type_from_object_path("NodeA", "b").__dict__ == {
            "is_list": False,
            "item_type": "OBJECT",
            "item_tag": "NodeB",
        }

        # edge collection
        assert validator._resolve_type_from_object_path(
            "NodeB", "c_collection"
        ).__dict__ == {
            "is_list": True,
            "item_type": "OBJECT",
            "item_tag": "NodeC",
        }

        # field of an edge
        assert validator._resolve_type_from_object_path(
            "NodeA", "b.numeric_field"
        ).__dict__ == {
            "is_list": False,
            "item_type": "NUMERIC",
            "item_tag": None,
        }

        # field of an edge collection
        assert validator._resolve_type_from_object_path(
            "NodeB", "c_collection.boolean_field"
        ).__dict__ == {"is_list": True, "item_type": "BOOLEAN", "item_tag": None}

        # two edges deep
        assert validator._resolve_type_from_object_path(
            "NodeA", "b.c_collection.boolean_field"
        ).__dict__ == {"is_list": True, "item_type": "BOOLEAN", "item_tag": None}

        # nested list (edge collection of an edge collection)
        with pytest.raises(Exception):
            validator._resolve_type_from_object_path(
                "NodeB", "c_collection.d_collection.numeric_field"
            )

        # nested list (list field of an edge collection)
        with pytest.raises(Exception):
            validator._resolve_type_from_object_path(
                "NodeC", "d_collection.numeric_list_field"
            )
