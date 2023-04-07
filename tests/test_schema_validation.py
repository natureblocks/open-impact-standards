import json

from tests import fixtures
from validation import templates
from validation.schema_validator import SchemaValidator


class TestSchemaValidation:
    def test_validate_demo_schema(self):
        validator = SchemaValidator()
        errors = validator.validate(json_file="schemas/demo_schema.json")
        assert not errors

    def test_root_object(self):
        validator = SchemaValidator()

        # Test that the root object is an object
        invalid_root = "[]"
        errors = validator.validate(json_string=invalid_root)
        assert len(errors) == 1
        assert (
            errors[0]
            == f"root: expected object, got {str(type(json.loads(invalid_root)))}"
        )

        # An empty root object should yield an error for each required property
        valid_root = "{}"
        errors = validator.validate(json_string=valid_root)
        assert len(errors) == len(templates.root_object["properties"])

        # The basic_schema fixture should be valid
        errors = validator.validate(json_string=json.dumps(fixtures.basic_schema()))
        assert not errors

    def test_required_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()
        del schema["standard"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "root: missing required field: standard"

        schema["standard"] = "test"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_optional_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()
        schema["parties"].append({"name": "Project"})
        schema["nodes"]["0"] = fixtures.node()
        assert "references" not in schema["nodes"]["0"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["nodes"]["0"]["references"] = ["some reference"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_mutually_exclusive_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()
        schema["parties"].append({"name": "Project"})
        schema["nodes"]["0"] = {
            "id": "0",
            "description": "test node",
            "node_type": "STATE",
            "applies_to": "Project",
            "dependency_set": {
                "dependencies": [
                    {
                        "node_id": "0",
                        "property": "completed",
                        # Should not be able to specify more than one mutually exclusive property
                        "equals": True,
                        "greater_than": 0,
                        "one_of": ["a", "b", "c"],
                    }
                ]
            },
            "dependencies_met": False,
            "completed": False,
        }

        path = "root.nodes.0.dependency_set.dependencies[0]"
        conformance_error = f"{path}: object does not conform to any of the allowed template specifications: ['dependency', 'dependency_set_reference']"
        mutually_exclusive = ["equals", "greater_than", "one_of"]

        # Remove one mutually exclusive property at a time until there is only one left
        while len(mutually_exclusive) > 1:
            errors = validator.validate(json_string=json.dumps(schema))
            assert conformance_error in errors
            assert (
                f"{path}: more than one mutually exclusive property specified: {mutually_exclusive}"
                in errors
            )

            del schema["nodes"]["0"]["dependency_set"]["dependencies"][0][
                mutually_exclusive.pop()
            ]

        # Now only one of the mutually exclusive properties is specified
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_modifier(self):
        validator = SchemaValidator()

        # Modifier:
        # "dependencies" property of dependency_set objects
        # in root.dependency_sets must contain at least two items
        schema = fixtures.basic_schema_with_nodes(2)
        schema["dependency_sets"] = [
            {
                "alias": "test",
                "gate_type": "AND",
                "dependencies": [
                    {"node_id": "0", "property": "completed", "equals": True}
                ],
            }
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.dependency_sets[0].dependencies: must contain at least 2 item(s), got 1"
        )

        schema["dependency_sets"][0]["dependencies"].append(
            {"node_id": "1", "property": "completed", "equals": True}
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_conditionals(self):
        validator = SchemaValidator()

        # If a dependency_set has more than one dependency,
        # "alias" and "gate_type" are required
        schema = fixtures.basic_schema_with_nodes(3)
        schema["nodes"]["2"]["dependency_set"] = {
            "dependencies": [
                {"node_id": "0", "property": "completed", "equals": True},
                {"node_id": "1", "property": "completed", "equals": True},
            ]
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 2
        assert "root.nodes.2.dependency_set: missing required field: alias" in errors
        assert (
            "root.nodes.2.dependency_set: missing required field: gate_type" in errors
        )

        # If a dependency_set has one or fewer dependencies,
        # "alias" and "gate_type" are optional
        schema["nodes"]["2"]["dependency_set"]["dependencies"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_references_any_from_object(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(1)
        assert len(schema["nodes"]) == 1
        assert schema["nodes"]["0"]["id"] == "0"
        nonexistent_node_id = "1"
        assert nonexistent_node_id not in schema["nodes"]

        # Should not be able to reference a nonexistent object key
        schema["active_nodes"] = [nonexistent_node_id]
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == f"root.active_nodes[0]: referenced object key of root.nodes does not exist: {json.dumps(nonexistent_node_id)}"
        )

        schema["active_nodes"] = ["0"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # Should not be able to reference a nonexistent object property
        schema["dependency_sets"] = [fixtures.dependency_set("some_alias")]
        schema["nodes"]["0"]["dependency_set"] = {
            "dependencies": [{"alias": "nonexistent_alias"}]
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.nodes.0.dependency_set.dependencies[0].alias: invalid value: expected any 'alias' field from root.dependency_sets, got \"nonexistent_alias\""
            in errors
        )

        schema["nodes"]["0"]["dependency_set"]["dependencies"][0][
            "alias"
        ] = "some_alias"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_references_any_from_array(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(1)
        assert len(schema["nodes"]) == 1

        schema["parties"] = [{"name": "Project"}]
        schema["nodes"]["0"]["applies_to"] = "something else"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.nodes.0.applies_to: invalid value: expected any 'name' field from root.parties, got \"something else\""
        )

        schema["nodes"]["0"]["applies_to"] = "Project"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_corresponding_value_reference(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(2)
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        actual_node_id = 2
        erroneous_key = "3"
        schema["nodes"][erroneous_key] = fixtures.node(node_id=actual_node_id)
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == f"root.nodes: invalid key: expected {actual_node_id} ("
            + "{corresponding_value}.id"
            + "), got "
            + erroneous_key
        )

    def test_unique_fields(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()

        schema["dependency_sets"] = [
            fixtures.dependency_set("some_alias"),
            fixtures.dependency_set("some_alias"),
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.dependency_sets: duplicate value provided for unique field 'alias': \"some_alias\""
        )

        schema["dependency_sets"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_multi_type_field(self):
        validator = SchemaValidator()

        allowed_types = ["string", "integer"]

        invalid = [True, None, {}, []]
        for val in invalid:
            errors = validator._validate_multi_type_field("none", val, allowed_types)
            assert len(errors) == 1
            assert (
                errors[0]
                == f"none: expected one of {allowed_types}, got {str(type(val))}"
            )

        valid = ["test", 1]
        for val in valid:
            errors = validator._validate_multi_type_field("none", val, allowed_types)
            assert not errors

    def test_reserved_keywords(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema()

        for keyword in templates.RESERVED_KEYWORDS:
            schema[keyword] = "test"
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f"root: cannot use reserved keyword as property name: '{keyword}'"
            )

            del schema[keyword]

        schema["not_reserved"] = "test"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_array(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema()

        not_arrays = [1, 1.0, True, None, {}, "test"]
        for invalid_array in not_arrays:
            schema["parties"] = invalid_array
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f"root.parties: expected array, got {str(type(invalid_array))}"
            )

        # Arrays must contain the specified type
        # (in this case, object)
        invalid_arrays = [[1], [1.0], [True], [None], ["test"]]
        for invalid_array in invalid_arrays:
            schema["parties"] = invalid_array
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f"root.parties[0]: expected object, got {str(type(invalid_array[0]))}"
            )

        # Arrays must conform to the specified template
        # (in ths case, templates.party)
        invalid_object_arrays = [
            [{}],
            [{"name": 1}],
            [{"name": 1.0}],
            [{"name": True}],
            [{"name": None}],
            [{"name": []}],
        ]
        for invalid_array in invalid_object_arrays:
            schema["parties"] = invalid_array
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            if "name" not in invalid_array[0]:
                assert errors[0] == "root.parties[0]: missing required field: name"
            else:
                assert (
                    errors[0]
                    == f"root.parties[0].name: expected string, got {str(type(invalid_array[0]['name']))}"
                )

    def test_distict_array(self):
        validator = SchemaValidator()

        template = {"type": "array", "values": {"type": "string"}, "distinct": True}

        errors = validator._validate_array("none", ["a", "b", "a"], template)
        assert len(errors) == 1
        assert errors[0] == "none: contains duplicate item(s) (values must be distinct)"

        errors = validator._validate_array("none", ["a", "b", "c"], template)
        assert not errors

    def test_min_length(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(2)
        schema["nodes"]["1"]["dependency_set"] = {
            "dependencies": []  # empty array, where min_length is 1
        }

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.nodes.1.dependency_set.dependencies: must contain at least 1 item(s), got 0"
        )

        schema["nodes"]["1"]["dependency_set"]["dependencies"].append(
            {"node_id": "0", "property": "completed", "equals": True}
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_enum(self):
        validator = SchemaValidator()

        template = {"values": ["a", "b", "c"]}

        invalid_enum_values = [1, 1.0, True, None, [], {}, "test"]
        for invalid_value in invalid_enum_values:
            errors = validator._validate_enum("none", invalid_value, template)
            assert len(errors) == 1
            assert (
                errors[0]
                == f"none: invalid enum value: expected one of "
                + str(template["values"])
                + f", got {str(invalid_value)}"
            )

        for valid_value in template["values"]:
            errors = validator._validate_enum("none", valid_value, template)
            assert not errors

    def test_number(self):
        validator = SchemaValidator()

        invalid_numbers = [True, None, [], {}, "1"]
        for invalid_number in invalid_numbers:
            errors = validator._validate_decimal("none", invalid_number)
            assert len(errors) == 1
            assert (
                errors[0] == f"none: expected decimal, got {str(type(invalid_number))}"
            )

        valid_numbers = [1, 1.0, 0, -1, -1.0]
        for valid_number in valid_numbers:
            errors = validator._validate_decimal("none", valid_number)
            assert not errors

    def test_integer_string(self):
        validator = SchemaValidator()

        invalid_integer_strings = [1.0, True, None, [], {}, "1.0", "--1"]
        for invalid_integer_string in invalid_integer_strings:
            errors = validator._validate_integer_string("none", invalid_integer_string)
            assert len(errors) == 1
            assert (
                errors[0]
                == f"none: expected a string representation of an integer, got {str(type(invalid_integer_string))}"
            )

        valid_integer_strings = ["1", "0", "-1", 1, 0, -1]
        for valid_integer_string in valid_integer_strings:
            errors = validator._validate_integer_string("none", valid_integer_string)
            assert not errors

    def test_integer(self):
        validator = SchemaValidator()

        invalid_integers = [1.0, True, None, [], {}, "1", "--1"]
        for invalid_integer in invalid_integers:
            errors = validator._validate_integer("none", invalid_integer)
            assert len(errors) == 1
            assert (
                errors[0] == f"none: expected integer, got {str(type(invalid_integer))}"
            )

        valid_integers = [1, 0, -1]
        for valid_integer in valid_integers:
            errors = validator._validate_integer("none", valid_integer)
            assert not errors

    def test_string(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema()

        invalid_strings = [1, 1.0, True, None, [], {}]

        for invalid_string in invalid_strings:
            schema["standard"] = invalid_string
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f"root.standard: expected string, got {str(type(invalid_string))}"
            )

        schema["standard"] = "test"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_boolean(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_nodes(1)

        invalid_booleans = [1, 1.0, "True", None, [], {}]
        for invalid_boolean in invalid_booleans:
            schema["nodes"]["0"]["completed"] = invalid_boolean
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f"root.nodes.0.completed: expected boolean, got {str(type(invalid_boolean))}"
            )

        valid_booleans = [True, False]
        for valid_boolean in valid_booleans:
            schema["nodes"]["0"]["completed"] = valid_boolean
            errors = validator.validate(json_string=json.dumps(schema))
            assert not errors
