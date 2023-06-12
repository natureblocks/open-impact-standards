import copy
import json
import logging

from tests import fixtures
from validation import templates
from validation.schema_validator import SchemaValidator
from enums import milestones

logger = logging.getLogger("schema_validation")


class TestSchemaValidation:
    def test_validate_schema(self):
        """This test performs validation on the JSON file at the specified json_file_path
        against the schema specification.

        A high-level description of the schema specification can be found in the README:
            https://github.com/natureblocks/open-impact-standards#schema-specification

        The schema specification is formally defined in validation/templates.py.

        Any validation errors are printed as standard output (if using VS Code,
        open the Output tab and select "Python Test Log" from the dropdown).

        The test passes if there are no validation errors.
        """

        # Specify which JSON file to validate.
        json_file_path = "schemas/test/small_example_schema.json"

        validator = SchemaValidator()
        errors = validator.validate(json_file_path=json_file_path)

        if errors:
            print(f"Invalid schema ({json_file_path}):")
            validator.print_errors()

        assert not errors

    def test_get_next_action_id(self):
        """Logs the next action id for the provided JSON schema file.

        Note that skipped action ids will not be returned. For example, if the schema
        contains the following action ids: [0, 1, 3], the next id is 4.

        To run this test and see the output, run the following command in the terminal:
        pytest -v tests/test_schema_validation.py::TestSchemaValidation::test_get_next_action_id --log-cli-level=DEBUG
        """

        # Specify the path to the JSON file.
        json_file_path = "schemas/test/small_example_schema.json"

        next_available_action_id = SchemaValidator().get_next_action_id(json_file_path)
        logger.debug("\nNext available action id: " + str(next_available_action_id))

    def test_get_all_action_ids(self):
        """Logs all action ids that are specified by provided JSON schema file.

        To run this test and see the output, run the following command in the terminal:
        pytest -v tests/test_schema_validation.py::TestSchemaValidation::test_get_all_action_ids --log-cli-level=DEBUG
        """

        # Specify the path to the JSON file.
        json_file_path = "schemas/test/small_example_schema.json"

        action_ids = SchemaValidator().get_all_action_ids(json_file_path)

        logger.setLevel(logging.DEBUG)
        logger.debug(
            "\Action ids in schema:\n" + "\n".join([str(id) for id in action_ids])
        )

    def test_milestones(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)

        schema["actions"][0]["milestones"] = ["FAKE"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert f'root.actions[0].milestones (node id: 0): invalid enum value: expected one of {json.dumps(milestones)}, got "FAKE"'

        # A single Action should not list the same milestone twice
        schema["actions"][0]["milestones"] = ["REAL", "REAL"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            'root.actions: duplicate value provided for unique field "milestones": "REAL"'
            in errors
        )

        # Two Actions should not list the same milestone
        schema["actions"][0]["milestones"] = ["REAL", "ADDITIONAL"]
        schema["actions"][1]["milestones"] = ["REAL"]

        assert len(errors) == 1
        assert (
            'root.actions: duplicate value provided for unique field "milestones": "REAL"'
            in errors
        )

        schema["actions"][1]["milestones"] = ["PERMANENT"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_circular_dependencies(self):
        def _set_dependency_action_id(schema, action_id, dependency_action_id):
            if "depends_on" not in schema["actions"][action_id]:
                schema["actions"][action_id]["depends_on"] = {
                    "dependencies": [fixtures.dependency(dependency_action_id)]
                }
            else:
                schema["actions"][action_id]["depends_on"]["dependencies"][0][
                    "action_id"
                ] = dependency_action_id

        validator = SchemaValidator()

        # A node should not be able to depend on itself
        schema = fixtures.basic_schema_with_actions(1)
        schema["checkpoints"] = [
            fixtures.checkpoint("depends_on_0", num_dependencies=1),
        ]
        assert (
            schema["checkpoints"][0]["dependencies"][0]["node"]["action_id"]
            == schema["actions"][0]["id"]
        )
        schema["actions"][0]["depends_on"] = "depends_on_0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "A node cannot have itself as a dependency (id: 0)"

        # Two nodes should not be able to depend on each other
        schema["actions"].append(fixtures.action(1))
        checkpoint_2 = fixtures.checkpoint("depends_on_1", num_dependencies=1)
        checkpoint_2["dependencies"][0]["node"]["action_id"] = 1
        schema["checkpoints"].append(checkpoint_2)
        schema["actions"][0]["depends_on"] = "depends_on_1"
        schema["actions"][1]["depends_on"] = "depends_on_0"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1])"

        # Three or more nodes should not be able to form a circular dependency
        schema["actions"].append(fixtures.action(2))
        checkpoint_3 = fixtures.checkpoint("depends_on_2", num_dependencies=1)
        checkpoint_3["dependencies"][0]["node"]["action_id"] = 2
        schema["checkpoints"].append(checkpoint_3)
        schema["actions"][1]["depends_on"] = "depends_on_2"
        schema["actions"][2]["depends_on"] = "depends_on_0"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1, 2])"

        # What if a recurring dependency set helps form a circular dependency?
        schema["actions"].append(fixtures.action(3))
        schema["actions"].append(fixtures.action(4))
        checkpoint_4 = fixtures.checkpoint("depends_on_3", num_dependencies=1)
        checkpoint_4["dependencies"][0]["node"]["action_id"] = 3
        schema["checkpoints"].append(checkpoint_4)
        schema["actions"][2]["depends_on"] = "depends_on_3"
        checkpoint_5 = fixtures.checkpoint("depends_on_4", num_dependencies=1)
        checkpoint_5["dependencies"][0]["node"]["action_id"] = 4
        checkpoint_5["dependencies"].append({"checkpoint": "depends_on_0"})
        schema["checkpoints"].append(checkpoint_5)
        schema["actions"][3]["depends_on"] = "depends_on_4"

        errors = validator.validate(json_string=json.dumps(schema))
        assert "Circular dependency detected (dependency path: [0, 1, 2, 3])" in errors

    def test_duplicate_checkpoint_dependencies(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)

        # Two checkpoints cannot have the same dependencies and the same gate type
        schema["checkpoints"] = [
            fixtures.checkpoint("checkpoint_1", "AND", 2),
            fixtures.checkpoint("checkpoint_2", "AND", 2),
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            'root.checkpoints: duplicate value provided for unique field combination "[\\"gate_type\\", \\"dependencies\\"]": {"gate_type": "AND", "dependencies": [{"node": {"action_id": 0, "field_name": "completed", "comparison_operator": "EQUALS", "comparison_value_type": "BOOLEAN", "boolean_comparison_value": true}}, {"node": {"action_id": 1, "field_name": "completed", "comparison_operator": "EQUALS", "comparison_value_type": "BOOLEAN", "boolean_comparison_value": true}}]}'
            in errors[0]
        )

        schema["checkpoints"][1]["dependencies"][0]["boolean_comparison_value"] = False

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_broken_dependency(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"].append(fixtures.checkpoint("test_ds", "AND", 1))
        schema["checkpoints"][0]["dependencies"][0]["node"]["action_id"] = 2
        schema["actions"][1]["depends_on"] = "test_ds"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints[0].dependencies[0].node.action_id: expected any "id" field from root.actions, got 2'
            in errors
        )

    def test_unordered_action_ids(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(5)

        def set_action_id(idx, action_id):
            schema["actions"][idx]["id"] = action_id

        action_ids = {
            0: 5,
            1: 1,
            2: 4,
            3: 2,
            4: 3,
        }

        for idx, action_id in action_ids.items():
            set_action_id(idx, action_id)

        # introduce an error to check if the correct node id is displayed in the context
        action_idx = 0
        schema["actions"][action_idx]["applies_to"] = "Vandelay Industries"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            f'root.actions[0].applies_to (node id: {action_ids[action_idx]}): expected any "name" field from root.parties, got "Vandelay Industries"'
            in errors
        )

        # fix the error
        schema["actions"][action_idx]["applies_to"] = "Project"

        errors = validator.validate(json_string=json.dumps(schema))
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

    def test_edge_definition(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()

        field_types = ["EDGE", "EDGE_COLLECTION"]
        field_names = ["some_edge", "some_edge_collection"]

        for i in range(len(field_types)):
            schema["nodes"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i]
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.nodes.Placeholder.{field_names[i]}: missing required property: tag"
                in errors
            )

            schema["nodes"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i],
                "tag": "NotATag",
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f'root.nodes.Placeholder.{field_names[i]}.tag: expected any key from root.nodes, got "NotATag"'
                in errors
            )

            schema["nodes"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i],
                "tag": "Placeholder",
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert not errors

    def test_required_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()
        del schema["standard"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "root: missing required property: standard"

        schema["standard"] = "test"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_optional_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()
        schema["parties"].append({"name": "Project"})
        schema["actions"].append(fixtures.action())
        assert "references" not in schema["actions"][0]

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["actions"][0]["references"] = ["some reference"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_forbidden_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"].append(fixtures.checkpoint("test_ds", "AND", 1))
        schema["actions"][1]["depends_on"] = "test_ds"

        assert schema["nodes"]["Placeholder"]["completed"]["field_type"] == "BOOLEAN"
        assert (
            schema["checkpoints"][0]["dependencies"][0]["node"]["field_name"]
            == "completed"
        )

        # Include a forbidden property
        schema["checkpoints"][0]["dependencies"][0]["node"][
            "string_comparison_value"
        ] = "some string"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            f"root.checkpoints[0].dependencies[0].node: forbidden property specified: string_comparison_value; reason: comparison_value_type is BOOLEAN"
            in errors
        )

        del schema["checkpoints"][0]["dependencies"][0]["node"][
            "string_comparison_value"
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_mutually_exclusive_properties(self):
        return  # The schema spec does not currently include mutually exclusive properties

        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(1)
        schema["parties"].append({"name": "Project"})
        schema["actions"].append(
            {
                "id": 1,
                "description": "test node",
                "applies_to": "Project",
                "depends_on": {
                    "dependencies": [
                        {
                            "action_id": 0,
                            "field_name": "completed",
                            "comparison_operator": "EQUALS",
                            "comparison_value_type": "BOOLEAN",
                            # Should not be able to specify more than one mutually exclusive property
                            "boolean_comparison_value": True,
                            "string_comparison_value": "yes",
                            "numeric_comparison_value": 1,
                        }
                    ]
                },
            }
        )

        context = "root.actions[1].depends_on.dependencies[0] (node id: 1)"
        conformance_error = f"{context}: object does not conform to any of the allowed template specifications: ['dependency', 'checkpoint_reference']"
        mutually_exclusive = [
            "string_comparison_value",
            "numeric_comparison_value",
            "boolean_comparison_value",
        ]

        # Remove one mutually exclusive property at a time until there is only one left
        while len(mutually_exclusive) > 1:
            errors = validator.validate(json_string=json.dumps(schema))
            assert conformance_error in errors
            assert (
                f"{context}: more than one mutually exclusive property specified: {mutually_exclusive}"
                in errors
            )

            del schema["actions"][1]["depends_on"]["dependencies"][0][
                mutually_exclusive.pop()
            ]

        # Now only one of the mutually exclusive properties is specified
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_modifier(self):
        return  # The schema spec does not currently include template modifiers

    def test_template_conditionals(self):
        validator = SchemaValidator()

        # If a checkpoint has more than one dependency,
        # "gate_type" is required
        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"].append(
            {
                "alias": "test_ds",
                "description": "test dependency set",
                "dependencies": [
                    fixtures.dependency(0),
                    fixtures.dependency(1),
                ],
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert "root.checkpoints[0]: missing required property: gate_type" in errors

        # If a checkpoint has one or fewer dependencies,
        # "gate_type" is optional
        schema["checkpoints"][0]["dependencies"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_switch_statement(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["nodes"]["Placeholder"]["some_string_field"] = {"field_type": "STRING"}

        ds = fixtures.checkpoint("test_ds", num_dependencies=0)
        ds["dependencies"].append(
            fixtures.dependency(
                0,
                field_name="some_string_field",
                comparison_value_type="STRING",
                comparison_operator="GREATER_THAN",
            )
        )
        schema["checkpoints"].append(ds)
        schema["actions"][1]["depends_on"] = "test_ds"

        allowed_comparison_operators = [
            "EQUALS",
            "DOES_NOT_EQUAL",
            "CONTAINS",
            "DOES_NOT_CONTAIN",
            "ONE_OF",
            "NONE_OF",
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            f'root.checkpoints[0].dependencies[0].node.comparison_operator: invalid enum value: expected one of {allowed_comparison_operators}, got "GREATER_THAN"'
            in errors
        )
        assert (
            "root.checkpoints[0].dependencies[0].node: missing required property: string_comparison_value"
            in errors
        )

        schema["checkpoints"][0]["dependencies"][0]["node"] = {
            "action_id": 0,
            "field_name": "some_string_field",
            "comparison_operator": "CONTAINS",
            "comparison_value_type": "STRING",
            "string_comparison_value": "some string",
        }

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_references_any_key_from_object(self):
        validator = SchemaValidator()

        key_reference_template = {
            "type": "object",
            "properties": {
                "referencees": {
                    "type": "object",
                    "keys": {"type": "string"},
                    "values": {"type": "string"},
                },
                "referencers": {
                    "type": "array",
                    "values": {
                        "type": "reference",
                        "references_any": {
                            "from": "root.referencees",
                            "property": "keys",
                        },
                    },
                },
            },
        }

        # Should not be able to reference a nonexistent object key
        validator.schema = {
            "referencees": {"foo": "bar"},
            "referencers": ["bar"],  # not a key from referencees
        }

        errors = validator._validate_field(
            "root", validator.schema, key_reference_template
        )
        assert len(errors) == 1
        assert (
            errors[0]
            == f'root.referencers[0]: expected any key from root.referencees, got "bar"'
        )

        validator.schema["referencers"][0] = "foo"
        errors = validator._validate_field(
            "root", validator.schema, key_reference_template
        )
        assert not errors

    def test_references_any_value_from_object(self):
        validator = SchemaValidator()

        value_reference_template = {
            "type": "object",
            "properties": {
                "referencees": {
                    "type": "object",
                    "keys": {"type": "string"},
                    "values": {"type": "string"},
                },
                "referencers": {
                    "type": "array",
                    "values": {
                        "type": "reference",
                        "references_any": {
                            "from": "root.referencees",
                            "property": "values",
                        },
                    },
                },
            },
        }

        # Should not be able to reference a nonexistent object value
        validator.schema = {
            "referencees": {"foo": "bar"},
            "referencers": ["foo"],  # not a value from referencees
        }

        errors = validator._validate_field(
            "root", validator.schema, value_reference_template
        )
        assert len(errors) == 1
        assert (
            'root.referencers[0]: expected any value from root.referencees, got "foo"'
            in errors
        )

        validator.schema["referencers"][0] = "bar"
        errors = validator._validate_field(
            "root", validator.schema, value_reference_template
        )
        assert not errors

    def test_references_any_property_from_object(self):
        validator = SchemaValidator()

        prop_reference_template = {
            "type": "object",
            "properties": {
                "referencees": {
                    "type": "object",
                    "keys": {"type": "string"},
                    "values": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                        },
                    },
                },
                "referencers": {
                    "type": "array",
                    "values": {
                        "type": "reference",
                        "references_any": {
                            "from": "root.referencees",
                            "property": "name",
                        },
                    },
                },
            },
        }

        # Should not be able to reference a nonexistent object property
        validator.schema = {
            "referencees": {"a": {"name": "foo"}},
            "referencers": ["bar"],  # not a referencee.name
        }

        errors = validator._validate_field(
            "root", validator.schema, prop_reference_template
        )
        assert len(errors) == 1
        assert (
            'root.referencers[0]: expected any "name" field from root.referencees, got "bar"'
            in errors
        )

        validator.schema["referencers"][0] = "foo"
        errors = validator._validate_field(
            "root", validator.schema, prop_reference_template
        )
        assert not errors

    def test_references_any_from_array(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(1)
        assert len(schema["actions"]) == 1

        schema["parties"] = [{"name": "Project"}]
        schema["actions"][0]["applies_to"] = "something else"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.actions[0].applies_to (node id: 0): expected any "name" field from root.parties, got "something else"'
        )

        schema["actions"][0]["applies_to"] = "Project"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_corresponding_value_reference(self):
        validator = SchemaValidator()

        template = {
            "type": "object",
            "keys": {
                "type": "reference",
                "referenced_value": "{corresponding_value}.id",
            },
            "values": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                },
            },
        }

        actual_id = "2"
        wrong_id = "3"

        validator.schema = {wrong_id: {"id": actual_id}}

        errors = validator._validate_field("root", validator.schema, template)
        assert len(errors) == 1
        assert (
            errors[0]
            == f"root: expected {actual_id} ("
            + "{corresponding_value}.id"
            + f"), got {json.dumps(wrong_id)}"
        )

        validator.schema = {actual_id: {"id": actual_id}}
        errors = validator._validate_field("root", validator.schema, template)
        assert not errors

    def test_unique_fields(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)

        schema["checkpoints"] = [
            fixtures.checkpoint("some_alias"),
            fixtures.checkpoint("some_alias"),
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints: duplicate value provided for unique field "alias": "some_alias"'
            in errors
        )

        schema["checkpoints"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_unique_action_ids(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["actions"][0]["id"] = 1
        assert schema["actions"][0]["id"] == schema["actions"][1]["id"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.actions: duplicate value provided for unique field "id": 1'
        )

        schema["actions"][0]["id"] = 0
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
                == f'root: cannot use reserved keyword as property name: "{keyword}"'
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
                assert errors[0] == "root.parties[0]: missing required property: name"
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

        schema = fixtures.basic_schema_with_actions(2)

        # Min length for Checkpoint.dependencies is 1
        schema["checkpoints"].append(
            fixtures.checkpoint("some_alias", num_dependencies=0)
        )

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.checkpoints[0].dependencies: must contain at least 1 item(s), got 0"
        )

        schema["checkpoints"][0]["dependencies"].append(fixtures.dependency(0))
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
                + f", got {json.dumps(invalid_value)}"
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

    def test_string_pattern(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()
        schema["parties"].append({"name": "Party 1", "hex_code": "#000000"})

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        invalid_hex_codes = ["#00000", "000000", "#00000g", "#00000G", "#00000_"]

        for invalid_hex_code in invalid_hex_codes:
            schema["parties"][0]["hex_code"] = invalid_hex_code
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f'root.parties[0].hex_code: string does not match {templates.party["properties"]["hex_code"]["pattern_description"]} pattern: {templates.party["properties"]["hex_code"]["pattern"]}'
            )

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

        template = {"type": "boolean"}

        invalid_booleans = [1, 1.0, "True", None, [], {}]
        for invalid_boolean in invalid_booleans:
            errors = validator._validate_boolean("none", invalid_boolean, template)
            assert len(errors) == 1
            assert (
                errors[0] == f"none: expected boolean, got {str(type(invalid_boolean))}"
            )

        valid_booleans = [True, False]
        for valid_boolean in valid_booleans:
            errors = validator._validate_boolean("none", valid_boolean, template)
            assert not errors
