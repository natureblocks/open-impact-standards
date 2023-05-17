import json
import logging

from tests import fixtures
from validation import templates
from validation.schema_validator import SchemaValidator

logger = logging.getLogger("schema_validation")


class TestSchemaValidation:
    def test_validate_schema(self):
        """This test performs validation on the JSON file at the specified json_file_path
        against the schema specification.

        A high-level description of the schema specification can be found in the README:
            https://github.com/natureblocks/open-impact-standards#schema-specification

        The schema specification is formally defined in validation/templates.py.

        Any validation errors are printed.
        The test passes if there are no validation errors.
        """

        # Specify which JSON file to validate.
        json_file_path = "schemas/demo_schema.json"

        validator = SchemaValidator()
        errors = validator.validate(json_file_path=json_file_path)

        if errors:
            print(f"Invalid schema ({json_file_path}):")
            validator.print_errors()

        assert not errors

    def test_get_next_node_id(self):
        """Logs the next node id for the provided JSON schema file.

        Note that skipped node ids will not be returned. For example, if the schema
        contains the following node ids: [0, 1, 3], the next id is 4.

        To run this test and see the output, run the following command in the terminal:
        pytest -v tests/test_schema_validation.py::TestSchemaValidation::test_get_next_node_id --log-cli-level=DEBUG
        """

        # Specify the path to the JSON file.
        json_file_path = "schemas/demo_schema.json"

        next_available_node_id = SchemaValidator().get_next_node_id(json_file_path)
        logger.debug("\nNext available node id: " + str(next_available_node_id))

    def test_get_all_node_ids(self):
        """Logs all node ids that are specified by provided JSON schema file.

        To run this test and see the output, run the following command in the terminal:
        pytest -v tests/test_schema_validation.py::TestSchemaValidation::test_get_all_node_ids --log-cli-level=DEBUG
        """

        # Specify the path to the JSON file.
        json_file_path = "schemas/demo_schema.json"

        node_ids = SchemaValidator().get_all_node_ids(json_file_path)

        logger.setLevel(logging.DEBUG)
        logger.debug(
            "\nNode ids in schema:\n" + "\n".join([str(id) for id in node_ids])
        )

    def test_duplicate_node_dependency_sets(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(4)

        dependency_set = fixtures.dependency_set("common_ds", "AND", 2)
        schema["state_nodes"][2]["depends_on"] = dependency_set
        schema["state_nodes"][3]["depends_on"] = dependency_set

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 2
        assert (
            errors[0]
            == "Any recurring DependencySet objects (Node.depends_on) should be added to root.referenced_dependency_sets, and nodes should specify a DependencySetReference with the alias of the DependencySet object."
        )
        assert (
            errors[1]
            == "The following node ids specify identical dependency sets: [2, 3]"
        )

        schema["referenced_dependency_sets"].append(dependency_set)
        ds_reference = {"alias": "common_ds"}
        schema["state_nodes"][2]["depends_on"] = {"dependencies": [ds_reference]}
        schema["state_nodes"][3]["depends_on"] = {"dependencies": [ds_reference]}
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["state_nodes"].append(fixtures.node(4))
        schema["state_nodes"].append(fixtures.node(5))

        # Same dependency set, but the properties are ordered differently
        schema["state_nodes"][4]["depends_on"] = {
            "alias": "common_ds#2",
            "gate_type": "OR",
            "dependencies": [
                ds_reference,
                fixtures.dependency(3),
            ],
        }
        schema["state_nodes"][5]["depends_on"] = {
            "dependencies": [
                fixtures.dependency(3),
                ds_reference,
            ],
            "gate_type": "OR",
            "alias": "common_ds#2",
        }

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 2
        assert (
            errors[0]
            == "Any recurring DependencySet objects (Node.depends_on) should be added to root.referenced_dependency_sets, and nodes should specify a DependencySetReference with the alias of the DependencySet object."
        )
        assert (
            errors[1]
            == "The following node ids specify identical dependency sets: [4, 5]"
        )

        schema["referenced_dependency_sets"].append(
            schema["state_nodes"][4]["depends_on"]
        )
        ds_reference = {"alias": "common_ds#2"}
        schema["state_nodes"][4]["depends_on"] = {"dependencies": [ds_reference]}
        schema["state_nodes"][5]["depends_on"] = {"dependencies": [ds_reference]}

    def test_circular_dependencies(self):
        def _set_dependency_node_id(schema, node_id, dependency_node_id):
            if "depends_on" not in schema["state_nodes"][node_id]:
                schema["state_nodes"][node_id]["depends_on"] = {
                    "dependencies": [fixtures.dependency(dependency_node_id)]
                }
            else:
                schema["state_nodes"][node_id]["depends_on"]["dependencies"][0][
                    "node_id"
                ] = dependency_node_id

        validator = SchemaValidator()

        # A node should not be able to depend on itself
        schema = fixtures.basic_schema_with_nodes(1)
        _set_dependency_node_id(schema, 0, 0)
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "A node cannot have itself as a dependency (id: 0)"

        # Two nodes should not be able to depend on each other
        schema["state_nodes"].append(fixtures.node(1))
        _set_dependency_node_id(schema, 0, 1)
        _set_dependency_node_id(schema, 1, 0)

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1])"

        # Three or more nodes should not be able to form a circular dependency
        schema["state_nodes"].append(fixtures.node(2))
        _set_dependency_node_id(schema, 1, 2)
        _set_dependency_node_id(schema, 2, 0)

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1, 2])"

        # What if a recurring dependency set helps form a circular dependency?
        schema["state_nodes"].append(fixtures.node(3))
        schema["state_nodes"].append(fixtures.node(4))
        _set_dependency_node_id(schema, 2, 3)
        schema["state_nodes"][1]["data"] = {
            "jumped_through_hoops": {"field_type": "BOOLEAN"}
        }
        schema["referenced_dependency_sets"].append(
            {
                "alias": "common_ds",
                "gate_type": "AND",
                "dependencies": [
                    fixtures.dependency(1),
                    fixtures.dependency(node_id=1, field_name="jumped_through_hoops"),
                ],
            }
        )
        common_ds_reference = {"alias": "common_ds"}
        schema["state_nodes"][3]["depends_on"] = {"dependencies": [common_ds_reference]}
        schema["state_nodes"][4]["depends_on"] = {"dependencies": [common_ds_reference]}

        errors = validator.validate(json_string=json.dumps(schema))
        assert "Circular dependency detected (dependency path: [0, 1, 2, 3])" in errors

    def test_broken_dependency(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(2)
        schema["state_nodes"][1]["depends_on"] = {
            "dependencies": [fixtures.dependency(2)]
        }

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.state_nodes[1].depends_on.dependencies[0].node_id (node id: 1): expected any "id" field from root.state_nodes, got 2'
            in errors
        )

    def test_unordered_node_ids(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(5)

        def set_node_id(idx, node_id):
            schema["state_nodes"][idx]["id"] = node_id

        node_ids = {
            0: 5,
            1: 1,
            2: 4,
            3: 2,
            4: 3,
        }

        for idx, node_id in node_ids.items():
            set_node_id(idx, node_id)

        # introduce an error to check if the correct node id is displayed in the context
        node_idx = 0
        schema["state_nodes"][node_idx]["applies_to"] = "Vandelay Industries"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            f'root.state_nodes[0].applies_to (node id: {node_ids[node_idx]}): expected any "name" field from root.parties, got "Vandelay Industries"'
            in errors
        )

        # fix the error
        schema["state_nodes"][node_idx]["applies_to"] = "Project"

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
            schema["node_definitions"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i]
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.node_definitions.Placeholder.{field_names[i]}: missing required property: tag"
                in errors
            )

            schema["node_definitions"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i],
                "tag": "NotATag",
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f'root.node_definitions.Placeholder.{field_names[i]}.tag: expected any key from root.node_definitions, got "NotATag"'
                in errors
            )

            schema["node_definitions"]["Placeholder"][field_names[i]] = {
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
        schema["state_nodes"].append(fixtures.node())
        assert "references" not in schema["state_nodes"][0]

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["state_nodes"][0]["references"] = ["some reference"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_mutually_exclusive_properties(self):
        return  # The schema spec does not currently include mutually exclusive properties

        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(1)
        schema["parties"].append({"name": "Project"})
        schema["state_nodes"].append(
            {
                "id": 1,
                "description": "test node",
                "node_type": "STATE",
                "applies_to": "Project",
                "depends_on": {
                    "dependencies": [
                        {
                            "node_id": 0,
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

        context = "root.state_nodes[1].depends_on.dependencies[0] (node id: 1)"
        conformance_error = f"{context}: object does not conform to any of the allowed template specifications: ['dependency', 'dependency_set_reference']"
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

            del schema["state_nodes"][1]["depends_on"]["dependencies"][0][
                mutually_exclusive.pop()
            ]

        # Now only one of the mutually exclusive properties is specified
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_modifier(self):
        validator = SchemaValidator()

        # Modifier:
        # "dependencies" property of dependency_set objects
        # in root.referenced_dependency_sets must contain at least two items
        schema = fixtures.basic_schema_with_nodes(2)
        schema["referenced_dependency_sets"] = [
            {
                "alias": "test",
                "gate_type": "AND",
                "dependencies": [fixtures.dependency(0)],
            }
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.referenced_dependency_sets[0].dependencies: must contain at least 2 item(s), got 1"
        )

        schema["referenced_dependency_sets"][0]["dependencies"].append(
            fixtures.dependency(1)
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_conditionals(self):
        validator = SchemaValidator()

        # If a dependency_set has more than one dependency,
        # "alias" and "gate_type" are required
        schema = fixtures.basic_schema_with_nodes(3)
        schema["state_nodes"][2]["depends_on"] = {
            "dependencies": [
                fixtures.dependency(0),
                fixtures.dependency(1),
            ]
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 2
        expected_context = "root.state_nodes[2].depends_on (node id: 2)"
        assert f"{expected_context}: missing required property: alias" in errors
        assert f"{expected_context}: missing required property: gate_type" in errors

        # If a dependency_set has one or fewer dependencies,
        # "alias" and "gate_type" are optional
        schema["state_nodes"][2]["depends_on"]["dependencies"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_switch_statement(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(2)
        schema["node_definitions"]["Placeholder"]["some_string_field"] = {
            "field_type": "STRING"
        }

        schema["state_nodes"][1]["depends_on"] = {
            "dependencies": [
                fixtures.dependency(
                    0,
                    field_name="some_string_field",
                    comparison_value_type="STRING",
                    comparison_operator="GREATER_THAN",
                ),
            ]
        }
        allowed_comparison_operators = [
            "EQUALS",
            "DOES_NOT_EQUAL",
            "MATCHES_REGEX",
            "DOES_NOT_MATCH_REGEX",
            "CONTAINS",
            "DOES_NOT_CONTAIN",
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            f'root.state_nodes[1].depends_on.dependencies[0].comparison_operator (node id: 1): invalid enum value: expected one of {allowed_comparison_operators}, got "GREATER_THAN"'
            in errors
        )
        assert (
            "root.state_nodes[1].depends_on.dependencies[0] (node id: 1): missing required property: string_comparison_value"
            in errors
        )

        schema["state_nodes"][1]["depends_on"]["dependencies"][0][
            "comparison_operator"
        ] = "CONTAINS"
        schema["state_nodes"][1]["depends_on"]["dependencies"][0][
            "string_comparison_value"
        ] = "some string"

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

        schema = fixtures.basic_schema_with_nodes(1)
        assert len(schema["state_nodes"]) == 1

        schema["parties"] = [{"name": "Project"}]
        schema["state_nodes"][0]["applies_to"] = "something else"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.state_nodes[0].applies_to (node id: 0): expected any "name" field from root.parties, got "something else"'
        )

        schema["state_nodes"][0]["applies_to"] = "Project"
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

        schema = fixtures.basic_schema_with_nodes(2)

        schema["referenced_dependency_sets"] = [
            fixtures.dependency_set("some_alias"),
            fixtures.dependency_set("some_alias"),
        ]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.referenced_dependency_sets: duplicate value provided for unique field "alias": "some_alias"'
        )

        schema["referenced_dependency_sets"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_unique_node_ids(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_nodes(2)
        schema["state_nodes"][0]["id"] = 1
        assert (
            schema["state_nodes"][0]["id"]
            == schema["state_nodes"][1]["id"]
        )

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.state_nodes: duplicate value provided for unique field "id": 1'
        )

        schema["state_nodes"][0]["id"] = 0
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

        schema = fixtures.basic_schema_with_nodes(2)
        schema["state_nodes"][1]["depends_on"] = {
            "dependencies": []  # empty array, where min_length is 1
        }

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.state_nodes[1].depends_on.dependencies (node id: 1): must contain at least 1 item(s), got 0"
        )

        schema["state_nodes"][1]["depends_on"]["dependencies"].append(
            fixtures.dependency(0)
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
