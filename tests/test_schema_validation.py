import json
import logging
from validation import obj_specs

from tests import fixtures
from validation import utils, patterns
from validation.schema_validator import SchemaValidator
from enums import milestones

logger = logging.getLogger("schema_validation")


class TestSchemaValidation:
    def test_validate_schema(self):
        """This test performs validation on the JSON file at the specified json_file_path
        against the schema specification.

        A high-level description of the schema specification can be found in the README:
            https://github.com/natureblocks/open-impact-standards#schema-specification

        The schema specification is formally defined in validation/obj_specs.py.

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

    def test_all_valid_schemas(self):
        schemas_to_validate = [
            "schemas/test/small_example_schema.json",
            "schemas/test/basic_import.json",
            "schemas/test/imported_action_to_native_checkpoint.json",
            "schemas/test/imported_checkpoint_to_native_action.json",
            "schemas/test/imported_checkpoint_to_native_checkpoint.json",
            "schemas/test/native_checkpoint_to_imported_action.json",
            "schemas/test/native_checkpoint_to_imported_checkpoint.json",
            "schemas/test/recursive_import_example.json",
            "schemas/test/attach_edge_example.json",
        ]

        for json_file_path in schemas_to_validate:
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

    def test_thread_variable_name_collision(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        thread = fixtures.thread_group(0, "depends-on-0")
        child_thread = fixtures.thread_group(1)
        child_thread["context"] = "thread_group:0"
        schema["actions"][1]["context"] = "thread_group:1"
        schema["object_promises"][1]["context"] = "thread_group:1"

        # should not be able to reuse a variable name in the same scope
        thread["spawn"]["as"] = "$some_var"
        child_thread["spawn"]["as"] = "$some_var"
        schema["thread_groups"] = [thread, child_thread]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.thread_groups[1].spawn.as: variable already defined within thread scope: "$some_var"'
            in errors
        )

        # the validation results should be the same
        # regardless of the order of the threads in the schama
        schema["thread_groups"] = [child_thread, thread]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.thread_groups[1].spawn.as: variable already defined within thread scope: "$some_var"'
            in errors
        )

        child_thread["spawn"]["as"] = "$some_other_var"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should be able to reuse a variable name in a different scope
        sibling_thread = fixtures.thread_group(2, "depends-on-0")
        sibling_thread["spawn"]["as"] = "$some_var"
        schema["thread_groups"].append(sibling_thread)
        schema["actions"][2]["context"] = "thread_group:2"
        schema["object_promises"][2]["context"] = "thread_group:2"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_thread_spawn(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        schema["thread_groups"] = [
            {
                "id": 0,
                "name": "thread_group_0",
                "description": "",
                "party": "party:{0}",
                "spawn": {
                    "foreach": "",
                    "as": "$number",
                },
                "depends_on": "checkpoint:{depends-on-0}",
            }
        ]
        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"

        def set_thread_value(key, val):
            if isinstance(key, list):
                obj = schema["thread_groups"][0]
                for i in range(len(key) - 1):
                    obj = obj[key[i]]

                obj[key[-1]] = val
            else:
                schema["thread_groups"][0][key] = val

        # spawn.foreach must be an ancestor of the thread
        set_thread_value(["spawn", "foreach"], "object_promise:2.numbers")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.thread_groups[0]: the value of property "spawn.foreach" must reference an ancestor of "thread_group:0", got "object_promise:2.numbers"'
            in errors
        )

        set_thread_value(["spawn", "foreach"], "object_promise:0.numbers")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # spawn.foreach must refer to a collection on spawn.foreach
        set_thread_value(["spawn", "foreach"], "object_promise:0.words")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.thread_groups[0].spawn.foreach: could not resolve variable type: "object_promise:0.words"'
            in errors
        )

        set_thread_value(["spawn", "foreach"], "object_promise:0.name")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.thread_groups[0].spawn.foreach: cannot spawn threads from a non-list object"
            in errors
        )

        # a nested thread should be able to
        # spawn from a collection on a parent thread variable
        set_thread_value(
            ["spawn"],
            {
                "foreach": "object_promise:0.objects",
                "as": "$object",
            },
        )
        schema["thread_groups"].append(fixtures.thread_group(1))
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["thread_groups"][1]["spawn"] = {
            "foreach": "$object.numbers",
            "as": "$number",
        }
        schema["actions"][2]["context"] = "thread_group:1"
        schema["object_promises"][2]["context"] = "thread_group:1"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["thread_groups"][1]["spawn"] = {
            "foreach": "$object.objects",
            "as": "$sub_object",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_thread_spawn_collections(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(4)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0),
        ]
        schema["thread_groups"][0]["depends_on"] = "checkpoint:{depends-on-0}"
        schema["actions"][2]["context"] = "thread_group:0"
        schema["object_promises"][2]["context"] = "thread_group:0"

        # test valid list sources...
        valid_list_sources = [
            "numbers",  # list of scalars
            "objects",  # edge collection
            "objects.name",  # field on an edge collection
            "objects.edge",  # edge on an edge collection
            "edge.edge.edge.objects.name",  # just for fun
        ]

        for path in valid_list_sources:
            schema["thread_groups"][0]["spawn"] = {
                "foreach": "object_promise:0." + path,
                "as": "$var",
            }
            errors = validator.validate(json_string=json.dumps(schema))
            assert not errors

        # field from a threaded action
        # (the threading DOES NOT make it a list (if it did, why not just continue the same thread?),
        # so a collection must be referenced)
        schema["thread_groups"].append(fixtures.thread_group(1))
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["actions"][1]["context"] = "thread_group:0"
        schema["actions"][2]["context"] = "thread_group:1"
        schema["object_promises"][1]["context"] = "thread_group:0"
        schema["object_promises"][2]["context"] = "thread_group:1"
        schema["checkpoints"].append(
            fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        )
        schema["checkpoints"][1]["context"] = "thread_group:0"
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:1.object_promise.completed"
        schema["thread_groups"][1]["depends_on"] = "checkpoint:{depends-on-1}"
        schema["thread_groups"][1]["spawn"] = {
            # object_promise:1 is a non-list (despite it being a threaded object)
            "foreach": "object_promise:1.numbers",  # numbers is a list
            "as": "$numbers",  # should be a list
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # edge on a threaded action (the threading makes it a list)
        schema["thread_groups"][1]["spawn"] = {
            # object_promise:1 is a non-list (despite it being threaded object)
            "foreach": "object_promise:1.objects",  # objects is a list
            "as": "$edges",  # should be a list
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # non-lists are invalid...
        non_list_sources = [
            "name",  # scalar field
            "edge",  # edge
        ]
        for field_name in non_list_sources:
            schema["thread_groups"][0]["spawn"] = {
                "foreach": "object_promise:0." + field_name,
                "as": "$var",
            }
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                "root.thread_groups[0].spawn.foreach: cannot spawn threads from a non-list object"
                in errors
            )

        # nested lists are invalid...
        nested_list_sources = [
            "objects.numbers",  # edge_collection->list
            "objects.edge.numbers",  # edge_collection->edge->list
            "objects.edge.objects",  # edge_collection->edge->edge_collection
        ]

        for path in nested_list_sources:
            schema["thread_groups"][0]["spawn"] = {
                "foreach": "object_promise:0." + path,
                "as": "$var",
            }
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.thread_groups[0].spawn.foreach: nested list types are not supported"
                in errors
            )

        schema["thread_groups"][0]["spawn"] = {
            "foreach": "object_promise:0.numbers",
            "as": "$number",
        }

        # edge case: spawn a nested thread from a collection on an action from a parent thread scope
        schema["thread_groups"].append(fixtures.thread_group(2))
        schema["thread_groups"][2]["context"] = "thread_group:1"
        schema["thread_groups"][2]["spawn"] = {
            "foreach": "object_promise:1.objects",
            "as": "$object",
        }
        schema["actions"][3]["context"] = "thread_group:2"
        schema["object_promises"][3]["context"] = "thread_group:2"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_thread_dependencies(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(4)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
            fixtures.checkpoint(1, "depends-on-1", num_dependencies=1),
            fixtures.checkpoint(2, "depends-on-2", num_dependencies=1),
            fixtures.checkpoint(3, "depends-on-3", num_dependencies=1),
        ]

        def set_dependency(checkpoint_idx, action_id):
            schema["checkpoints"][checkpoint_idx]["dependencies"][0]["compare"]["left"][
                "ref"
            ] = action_id

        set_dependency(0, "action:0.object_promise.completed")
        set_dependency(1, "action:1.object_promise.completed")
        set_dependency(2, "action:2.object_promise.completed")
        set_dependency(3, "action:3.object_promise.completed")

        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]
        schema["actions"][1]["context"] = "thread_group:0"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-1}"
        schema["actions"][3]["depends_on"] = "checkpoint:{depends-on-2}"
        schema["actions"][0][
            "depends_on"
        ] = "checkpoint:{depends-on-3}"  # creates circular dependency

        errors = validator.validate(json_string=json.dumps(schema))
        threaded_context_note = "; NOTE: actions with threaded context implicitly depend on the referenced thread group's checkpoint (ThreadGroup.depends_on)"
        assert (
            f"Circular dependency detected (dependency path: [0, 3, 2, 1]){threaded_context_note}"
            in errors
        )

        def remove_checkpoint(checkpoint_alias):
            for i in range(len(schema["checkpoints"])):
                if (
                    checkpoint_alias
                    == "checkpoint:{" + schema["checkpoints"][i]["alias"] + "}"
                ):
                    del schema["checkpoints"][i]
                    return

        remove_checkpoint(schema["actions"][0]["depends_on"])
        del schema["actions"][0]["depends_on"]
        errors = validator.validate(json_string=json.dumps(schema))
        # The circular dependency should be gone,
        # but the context mismatch will still cause an error.
        for error in errors:
            assert "Circular dependency detected" not in error

        # a thread cannot depend on an action that references said thread as its context
        schema["actions"][0]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "An action cannot have itself as a dependency (action:0); NOTE: actions with threaded context implicitly depend on the referenced thread group's checkpoint (ThreadGroup.depends_on)"
            in errors
        )

        # nested threads can form circular dependencies
        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
            fixtures.checkpoint(1, "depends-on-1", num_dependencies=1),
        ]
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:1.object_promise.completed"

        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
            fixtures.thread_group(1),
        ]
        schema["thread_groups"][0]["spawn"] = {
            "foreach": "object_promise:0.objects",
            "as": "$object",
        }
        schema["thread_groups"][1]["spawn"] = {
            "foreach": "$object.numbers",  # parent thread variable!
            "as": "$number",
        }
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["actions"][1]["context"] = "thread_group:1"
        schema["object_promises"][1]["context"] = "thread_group:1"
        schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-1}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "Circular dependency detected (dependency path: [0, 1]); NOTE: actions with threaded context implicitly depend on the referenced thread group's checkpoint (ThreadGroup.depends_on)"
            in errors
        )

        remove_checkpoint(schema["actions"][0]["depends_on"])
        del schema["actions"][0]["depends_on"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_depends_on_thread_variable(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(5)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
            fixtures.checkpoint(1, "depends-on-thread-variable", num_dependencies=1),
            fixtures.checkpoint(
                2, "depends-on-thread-variable-path", num_dependencies=1
            ),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]
        schema["thread_groups"][0]["spawn"] = {
            "foreach": "object_promise:0.objects",
            "as": "$object",
        }
        schema["actions"][1]["context"] = "thread_group:0"
        schema["actions"][2]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        schema["object_promises"][2]["context"] = "thread_group:0"
        schema["checkpoints"][1]["context"] = "thread_group:0"
        schema["checkpoints"][2]["context"] = "thread_group:0"
        schema["checkpoints"][1]["dependencies"][0]["compare"] = {
            "left": {
                "ref": "$object",
            },
            "operator": "EQUALS",
            "right": {
                "ref": "action:0.object_promise.edge",
            },
        }
        schema["checkpoints"][2]["dependencies"][0]["compare"] = {
            "left": {
                "ref": "$object.number",
            },
            "operator": "LESS_THAN",
            "right": {
                "ref": "action:0.object_promise.number",
            },
        }

        # should be able to depend on a thread variable
        # or a path from a thread variable
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-thread-variable}"
        schema["actions"][2][
            "depends_on"
        ] = "checkpoint:{depends-on-thread-variable-path}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # if a checkpoint depends on a thread variable,
        # the thread variable must exist within the scope of the checkpoint context
        del schema["actions"][1]["context"]
        del schema["checkpoints"][1]["context"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints[1].dependencies[0].compare: variable not found within thread scope: "$object"'
            in errors
        )

        # should be able to reference a thread variable that was defined in a parent scope
        schema["thread_groups"].append(fixtures.thread_group(1))
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["thread_groups"][1]["spawn"]["as"] = "$child_thread_variable"
        schema["actions"][1]["context"] = "thread_group:1"
        schema["object_promises"][1]["context"] = "thread_group:1"
        schema["checkpoints"][1]["context"] = "thread_group:1"
        assert (
            schema["checkpoints"][1]["dependencies"][0]["compare"]["left"]["ref"]
            == "$object"
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should not be able to reference a thread variable that was defined in a child scope
        assert schema["thread_groups"][1]["context"] == "thread_group:0"
        assert schema["thread_groups"][1]["spawn"]["as"] == "$child_thread_variable"
        schema["checkpoints"][2]["dependencies"][0]["compare"]["left"] = {
            "ref": "$child_thread_variable.number",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints[2].dependencies[0].compare: variable not found within thread scope: "$child_thread_variable"'
            in errors
        )

    def test_thread_is_used(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]

        # threads must contain either an action or a nested thread
        errors = validator.validate(json_string=json.dumps(schema))
        assert "root.thread_groups[0]: thread_group is never referenced" in errors

        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        del schema["actions"][1]["context"]
        schema["thread_groups"].append(fixtures.thread_group(1))
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["thread_groups"][1]["spawn"] = {
            "foreach": "object_promise:0.objects",
            "as": "$object",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert "root.thread_groups[1]: thread_group is never referenced" in errors

        schema["actions"][1]["context"] = "thread_group:1"
        schema["object_promises"][1]["context"] = "thread_group:1"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_duplicate_thread_ids(self):
        # I had a suspicion that thread validation logic might raise an uncaught exception
        # if the schema contained duplicate thread ids, so I wrote this test.
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
            fixtures.thread_group(0, "depends-on-0"),
        ]
        schema["thread_groups"][1]["spawn"]["as"] = "$thread_variable"
        schema["actions"][1]["context"] = "thread_group:0"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.thread_groups: duplicate value provided for unique field "id": 0'
            in errors
        )

    def test_action_context(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"

        # action.context must be a defined thread
        schema["actions"][1]["context"] = "action:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].context (action id: 1): invalid ref type: expected one of ["thread_group"], got action reference'
            in errors
        )

        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].context (action id: 1): invalid ref: object not found: "thread_group:0"'
            in errors
        )

        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),  # creates thread_group:0
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_object_promise_context(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]
        schema["actions"][1]["context"] = "thread_group:0"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.object_promises[1]: object promise context must match the context of the action that fulfills it (action:1)"
            in errors
        )

        schema["object_promises"][1]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["object_promises"][0]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.object_promises[0]: object promise context must match the context of the action that fulfills it (action:0)"
            in errors
        )

        del schema["object_promises"][0]["context"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_action_operations(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"
        schema["actions"][1]["object_promise"] = "object_promise:0"
        schema["actions"][2]["object_promise"] = "object_promise:1"
        schema["object_promises"].pop()

        def set_operation_value(action_idx, key, val):
            schema["actions"][action_idx]["operation"][key] = val

        for action_idx, operation_type in {0: "CREATE", 1: "EDIT"}.items():
            for inclusion_type in ["include", "exclude"]:
                # should be able to specify fields that exist on the object type
                set_operation_value(
                    action_idx,
                    inclusion_type,
                    ["completed", "name", "number", "numbers", "edge", "objects"],
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert not errors

                # should be able to include or exclude null
                set_operation_value(action_idx, inclusion_type, None)
                errors = validator.validate(json_string=json.dumps(schema))
                assert not errors

                # should not be able to inlude fields that do not exist on the object type
                set_operation_value(action_idx, inclusion_type, ["not_a_field"])
                errors = validator.validate(json_string=json.dumps(schema))
                assert (
                    f"root.actions[{action_idx}].operation.{inclusion_type} (action id: {action_idx}): attribute does not exist on object type object_type:"
                    + '{Placeholder}: "not_a_field"'
                    in errors
                )

                # reset
                for inclusion_type in ["include", "exclude"]:
                    if inclusion_type in schema["actions"][action_idx]["operation"]:
                        del schema["actions"][action_idx]["operation"][inclusion_type]

            # should not be able to specify include and exclude
            set_operation_value(action_idx, "include", ["completed", "name", "number"])
            set_operation_value(action_idx, "exclude", ["numbers", "edge", "objects"])
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.actions[{action_idx}].operation (action id: {action_idx}): more than one mutually exclusive property specified: ['include', 'exclude']"
                in errors
            )

            del schema["actions"][action_idx]["operation"]["exclude"]

            if operation_type == "CREATE":
                # should be able to specify default values for fields that exist on the object type
                set_operation_value(
                    action_idx,
                    "default_values",
                    {
                        "completed": True,
                        "name": "default name",
                        "number": 0,
                        "numbers": [0, 1, 2],
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert not errors

                # should not be able to specify default values for...
                #   - fields that do not exist on the object type
                #   - edges (must use "default_edges")
                #   - edge collections
                set_operation_value(
                    action_idx,
                    "default_values",
                    {
                        "not_a_field": True,
                        "edge": "object_promise:0",
                        "objects": ["object_promise:0", "object_promise:1"],
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert {
                    f'root.actions[{action_idx}].operation.default_values.not_a_field (action id: {action_idx}): attribute does not exist on object type: "object_type:'
                    + '{Placeholder}"',
                    f"root.actions[{action_idx}].operation.default_values.edge (action id: {action_idx}): cannot specify default value for edge here; use default_edges instead",
                    f"root.actions[{action_idx}].operation.default_values.objects (action id: {action_idx}): setting default values for edge collections is not supported",
                }.issubset(errors)

                # specified values must match the type defined by the object_type
                set_operation_value(
                    action_idx,
                    "default_values",
                    {
                        "completed": "yes",
                        "name": True,
                        "number": [1],
                        "numbers": 2,
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert {
                    f'root.actions[{action_idx}].operation.default_values (action id: {action_idx}): expected value of type BOOLEAN, got STRING: "yes"',
                    f"root.actions[{action_idx}].operation.default_values (action id: {action_idx}): expected value of type STRING, got BOOLEAN: true",
                    f"root.actions[{action_idx}].operation.default_values (action id: {action_idx}): expected value of type NUMERIC, got NUMERIC_LIST: [1]",
                    f"root.actions[{action_idx}].operation.default_values (action id: {action_idx}): expected value of type NUMERIC_LIST, got NUMERIC: 2",
                }.issubset(errors)

                del schema["actions"][action_idx]["operation"]["default_values"]

                # should be able to specify default edges for edges that exist on the object type
                schema["actions"].append(fixtures.action(3))
                schema["object_promises"].append(fixtures.object_promise(3))
                schema["checkpoints"].append(
                    fixtures.checkpoint(1, "depends-on-3", num_dependencies=1)
                )
                schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
                    "ref"
                ] = "action:3.object_promise.completed"
                schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-3}"
                set_operation_value(
                    action_idx,
                    "default_edges",
                    {
                        "edge": "object_promise:3",
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert not errors
                schema["actions"].pop()
                schema["object_promises"].pop()
                schema["checkpoints"].pop()
                del schema["actions"][0]["depends_on"]

                # - should not be able to specify default edges for edges that do not exist on the object type,
                # - should not be able to specify default values for edge collections
                # - should not be able to specify a default edge if the object promise is not fulfilled by an ancestor
                set_operation_value(
                    action_idx,
                    "default_edges",
                    {
                        "corner": "object_promise:0",
                        "objects": ["object_promise:0", "object_promise:1"],
                        "edge": "object_promise:1",
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert {
                    f'root.actions[{action_idx}].operation.default_edges.corner (action id: {action_idx}): attribute does not exist on object type: "object_type:'
                    + '{Placeholder}"',
                    f"root.actions[{action_idx}].operation.default_edges.objects (action id: {action_idx}): setting default values for edge collections is not supported",
                    f'root.actions[{action_idx}].operation.default_edges.edge (action id: {action_idx}): an ancestor of the action must fulfill the referenced object promise: "{utils.as_ref(1, "object_promise", value_is_id=True)}"',
                }.issubset(errors)

                # specified values must be of the tag defined by the object_type
                schema["object_types"].append(
                    {
                        "id": 1,
                        "name": "SomeOtherType",
                        "attributes": [
                            {
                                "name": "some_field",
                                "type": "STRING",
                            },
                        ],
                    },
                )
                object_promise_count = len(schema["object_promises"])
                schema["object_promises"].append(
                    fixtures.object_promise(object_promise_count, "SomeOtherType")
                )
                set_operation_value(
                    action_idx,
                    "default_edges",
                    {
                        "edge": "object_promise:" + str(object_promise_count),
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                expected_error = (
                    f'root.actions[{action_idx}].operation.default_edges.edge (action id: {action_idx}): object type of referenced object promise does not match the object type definition: "object_promise:{str(object_promise_count)}"; expected "object_type:'
                    + '{Placeholder}", got "object_type:{SomeOtherType}"'
                )
                assert expected_error in errors

                del schema["actions"][action_idx]["operation"]["default_edges"]
                schema["object_promises"].pop()
            elif operation_type == "EDIT":
                # should not be able to specify default values
                set_operation_value(
                    action_idx,
                    "default_values",
                    {
                        "completed": True,
                        "name": "default name",
                        "number": 0,
                        "numbers": [0, 1, 2],
                    },
                )
                set_operation_value(
                    action_idx,
                    "default_edges",
                    {
                        "edge": "object_promise:0",
                    },
                )
                errors = validator.validate(json_string=json.dumps(schema))
                assert {
                    f"root.actions[{action_idx}].operation.default_values (action id: {action_idx}): default values are not supported for EDIT operations",
                    f"root.actions[{action_idx}].operation.default_edges (action id: {action_idx}): default edges are not supported for EDIT operations",
                }.issubset(errors)

        # test operation.appends_objects_to
        schema = fixtures.basic_schema_with_actions(3)

        # appends_objects_to must reference an ancestor's object promise
        schema["actions"][1]["operation"] = {
            "exclude": None,
            "appends_objects_to": "object_promise:0.objects",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation.appends_objects_to (action id: 1): the referenced object promise is not guaranteed to be fulfilled by an ancestor of this action"
            in errors
        )
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # OR gate does not guarantee ancestry...
        schema["actions"].append(fixtures.action(3))
        schema["object_promises"].append(fixtures.object_promise(3))
        schema["checkpoints"][0]["dependencies"].append(
            {
                "compare": {
                    "left": {
                        "ref": "action:3.object_promise.completed",
                    },
                    "operator": "EQUALS",
                    "right": {"value": True},
                }
            }
        )
        schema["checkpoints"][0]["gate_type"] = "OR"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation.appends_objects_to (action id: 1): the referenced object promise is not guaranteed to be fulfilled by an ancestor of this action"
            in errors
        )

        # ...unless every condition references the same action
        schema["checkpoints"][0]["dependencies"][1]["compare"]["left"][
            "ref"
        ] = "action:0.object_promise.completed"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should not matter if a single dependency references two different actions
        schema["checkpoints"][0]["dependencies"][1]["compare"]["right"][
            "ref"
        ] = "action:3.object_promise.completed"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # object type of object promise must match the object type of the referenced edge collection
        schema["object_types"][0]["some_other_objects"] = {
            "type": "EDGE_COLLECTION",
            "object_type": "object_type:{SomeOtherType}",
        }
        invalid_fields = ["some_other_objects", "edge", "numbers", "name"]
        for field_name in invalid_fields:
            schema["actions"][1]["operation"][
                "appends_objects_to"
            ] = f"object_promise:0.{field_name}"
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                "root.actions[1].operation.appends_objects_to (action id: 1): must reference an edge collection with the same object_type as this action's object promise"
                in errors
            )

        schema["actions"][1]["operation"][
            "appends_objects_to"
        ] = "object_promise:0.objects"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # edge collection cannot be included in any other operation
        ways_to_include_edge_collection = [
            {"include": ["objects"]},
            {"exclude": ["name"]},
            {"exclude": None},
        ]
        for operation in ways_to_include_edge_collection:
            schema["actions"][0]["operation"] = operation
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                "root.actions[1].operation.appends_objects_to (action id: 1): the referenced edge collection cannot be included in any other action's operation"
                in errors
            )

        schema["actions"][0]["operation"] = {"include": ["name"]}
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # appender context must match appendee context
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]
        # threaded appender, non-threaded appendee
        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation.appends_objects_to (action id: 1): the action's context must match the context of the object promise referenced by this property (thread_group:0 != None)"
            in errors
        )

        # both threaded, same context (should be valid)
        schema["actions"][1]["operation"][
            "appends_objects_to"
        ] = "object_promise:2.objects"
        schema["actions"][2]["context"] = "thread_group:0"
        schema["object_promises"][2]["context"] = "thread_group:0"
        schema["checkpoints"].append(
            fixtures.checkpoint(1, "depends-on-2", num_dependencies=1)
        )
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:2.object_promise.completed"
        schema["checkpoints"][1]["context"] = "thread_group:0"
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-2}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # both threaded, different context
        schema["thread_groups"].append(fixtures.thread_group(1, "depends-on-2"))
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["thread_groups"][1]["spawn"]["as"] = "$another_number"
        del schema["actions"][1]["depends_on"]
        schema["actions"][1]["context"] = "thread_group:1"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation.appends_objects_to (action id: 1): the action's context must match the context of the object promise referenced by this property (thread_group:1 != thread_group:0)"
            in errors
        )

        # reset
        schema["thread_groups"] = []
        del schema["checkpoints"][1]
        del schema["actions"][1]["context"]
        del schema["actions"][2]["context"]
        del schema["object_promises"][1]["context"]
        del schema["object_promises"][2]["context"]
        schema["actions"][1]["operation"][
            "appends_objects_to"
        ] = "object_promise:0.objects"
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # operation type must be CREATE
        schema["actions"][2]["object_promise"] = "object_promise:1"
        schema["object_promises"].pop()  # unused
        schema["checkpoints"].append(
            fixtures.checkpoint(1, "depends-on-2", num_dependencies=1)
        )
        schema["checkpoints"][-1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:2.object_promise.completed"
        schema["checkpoints"].append(
            {
                "id": 2,
                "description": "test",
                "alias": "depends-on-0-and-2",
                "dependencies": [
                    {"checkpoint": "checkpoint:{depends-on-0}"},
                    {"checkpoint": "checkpoint:{depends-on-2}"},
                ],
                "gate_type": "AND",
            }
        )
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0-and-2}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation.appends_objects_to (action id: 1): this property is not supported for EDIT operations."
            in errors
        )

        # an action whose operation specifies appends_objects_to
        # cannot be referenced by any checkpoint dependencies
        schema["checkpoints"].pop()
        schema["checkpoints"].pop()
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"
        schema["checkpoints"].append(
            fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        )
        schema["checkpoints"][-1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:1.object_promise.completed"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-1}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation.appends_objects_to (action id: 1): if this property is specified, the parent action cannot be included in any checkpoint dependencies"
            in errors
        )

    def test_action_operation_context(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]
        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        schema["actions"][1]["object_promise"] = "object_promise:0"
        schema["actions"][2]["object_promise"] = "object_promise:1"
        del schema["object_promises"][2]  # unused

        # if the object promise is fulfilled outside of a threaded context,
        # then it cannot be edited from within a threaded context
        assert (
            schema["actions"][0]["object_promise"]
            == schema["actions"][1]["object_promise"]
        )
        assert "context" not in schema["actions"][0]
        assert schema["actions"][1]["context"] is not None
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1] (action id: 1): cannot edit an object promise outside of the context in which the object promise is fulfilled (fulfillment context: null)"
            in errors
        )

        schema["checkpoints"].append(
            fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        )
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:1.object_promise.completed"
        schema["checkpoints"][1]["context"] = "thread_group:0"
        schema["thread_groups"].append(fixtures.thread_group(1, "depends-on-1"))
        schema["thread_groups"][1]["context"] = "thread_group:0"
        schema["thread_groups"][1]["spawn"]["as"] = "$another_number"
        schema["actions"][1]["object_promise"] = "object_promise:1"
        schema["actions"][2]["context"] = "thread_group:1"

        # EDIT actions must match the context of the action that fulfills the referenced object promise
        assert (
            schema["actions"][1]["object_promise"]
            == schema["actions"][2]["object_promise"]
        )
        assert schema["actions"][1]["context"] is not None
        assert schema["actions"][2]["context"] is not None
        assert schema["actions"][1]["context"] != schema["actions"][2]["context"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[2] (action id: 2): cannot edit an object promise outside of the context in which the object promise is fulfilled (fulfillment context: "thread_group:0")'
            in errors
        )

        del schema["thread_groups"][1]
        schema["actions"][2]["context"] = "thread_group:0"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-1}"
        assert schema["actions"][1]["context"] == schema["actions"][2]["context"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_milestones(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)

        schema["actions"][0]["milestones"] = ["FAKE"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert f'root.actions[0].milestones (action id: 0): invalid enum value: expected one of {json.dumps(milestones)}, got "FAKE"'

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
        validator = SchemaValidator()

        # An action should not be able to depend on itself
        schema = fixtures.basic_schema_with_actions(1)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        assert (
            schema["checkpoints"][0]["dependencies"][0]["compare"]["left"]["ref"].split(
                "."
            )[0]
            == f"action:{str(schema['actions'][0]['id'])}"
        )
        schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "An action cannot have itself as a dependency (action:0)"

        # Two actions should not be able to depend on each other
        schema["object_promises"].append(fixtures.object_promise(1))
        schema["actions"].append(fixtures.action(1))
        checkpoint_2 = fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        checkpoint_2["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:1.object_promise.completed"
        schema["checkpoints"].append(checkpoint_2)
        schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-1}"
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1])"

        # Three or more actions should not be able to form a circular dependency
        schema["object_promises"].append(fixtures.object_promise(2))
        schema["actions"].append(fixtures.action(2))
        checkpoint_3 = fixtures.checkpoint(2, "depends-on-2", num_dependencies=1)
        checkpoint_3["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:2.object_promise.completed"
        schema["checkpoints"].append(checkpoint_3)
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-2}"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-0}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1, 2])"

        # What if a recurring dependency set helps form a circular dependency?
        schema["actions"].append(fixtures.action(3))
        schema["object_promises"].append(fixtures.object_promise(3))
        schema["actions"].append(fixtures.action(4))
        schema["object_promises"].append(fixtures.object_promise(4))
        checkpoint_4 = fixtures.checkpoint(3, "depends-on-3", num_dependencies=1)
        checkpoint_4["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:3.object_promise.completed"
        schema["checkpoints"].append(checkpoint_4)
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-3}"
        checkpoint_5 = fixtures.checkpoint(4, "depends-on-4-and-0", num_dependencies=1)
        checkpoint_5["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:4.object_promise.completed"
        checkpoint_5["dependencies"].append({"checkpoint": "checkpoint:{depends-on-0}"})
        schema["checkpoints"].append(checkpoint_5)
        schema["checkpoints"][-1]["gate_type"] = "AND"
        schema["actions"][3]["depends_on"] = "checkpoint:{depends-on-4-and-0}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert "Circular dependency detected (dependency path: [0, 1, 2, 3])" in errors

    def test_checkpoint_context(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(8)

        # If a checkpoint has a threaded context,
        # it can reference a thread variable from that context
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
            fixtures.checkpoint(1, "depends-on-thread-variable", num_dependencies=1),
        ]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "depends-on-0"),
        ]
        schema["thread_groups"][0]["spawn"]["as"] = "$thread_variable"
        schema["checkpoints"][1]["context"] = "thread_group:0"
        schema["checkpoints"][1]["dependencies"][0]["compare"] = {
            "left": {"ref": "$thread_variable"},
            "operator": "GREATER_THAN",
            "right": {
                "ref": "action:0.object_promise.number",
            },
        }
        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-thread-variable}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # it cannot reference a thread variable that's out of scope
        schema["thread_groups"].append(fixtures.thread_group(1, "depends-on-0"))
        schema["actions"][2]["context"] = "thread_group:1"
        schema["object_promises"][2]["context"] = "thread_group:1"
        schema["thread_groups"][1]["spawn"]["as"] = "$out_of_scope_thread_variable"
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "$out_of_scope_thread_variable"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints[1].dependencies[0].compare: variable not found within thread scope: "$out_of_scope_thread_variable"'
            in errors
        )

        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "$thread_variable"

        # it cannot reference a checkpoint that's out of scope
        schema["checkpoints"].append(
            fixtures.checkpoint(2, "out-of-scope", num_dependencies=1)
        )
        schema["checkpoints"][2]["context"] = "thread_group:1"
        schema["checkpoints"][2]["dependencies"][0]["compare"]["right"]["value"] = False
        schema["actions"][2]["depends_on"] = "checkpoint:{out-of-scope}"
        # using action 5 to avoid a referenceless checkpoint error further down
        schema["actions"][5]["context"] = "thread_group:1"
        schema["object_promises"][5]["context"] = "thread_group:1"
        schema["actions"][5]["depends_on"] = "checkpoint:{out-of-scope}"
        schema["checkpoints"][1]["dependencies"].append(
            {"checkpoint": "checkpoint:{out-of-scope}"}
        )
        schema["checkpoints"][1]["gate_type"] = "AND"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints[1]: checkpoint with threaded context referenced out of scope: "checkpoint:{out-of-scope}"'
            in errors
        )

        # it can reference a checkpoint that has the same context
        schema["checkpoints"].append(
            fixtures.checkpoint(3, "same-context", num_dependencies=1)
        )
        schema["checkpoints"][3]["dependencies"][0]["compare"] = {
            "left": {"ref": "action:0.object_promise.number"},
            "operator": "GREATER_THAN",
            "right": {"value": 10},
        }
        schema["checkpoints"][3]["context"] = "thread_group:0"
        schema["checkpoints"][1]["dependencies"][1] = {
            "checkpoint": "checkpoint:{same-context}"
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # it can reference a checkpoint that has a parent context
        schema["thread_groups"].append(fixtures.thread_group(2))
        schema["thread_groups"][2]["context"] = "thread_group:0"
        schema["checkpoints"].append(
            fixtures.checkpoint(4, "references-parent-context", num_dependencies=1)
        )
        schema["checkpoints"][4]["context"] = "thread_group:2"
        schema["checkpoints"][4]["dependencies"].append(
            {"checkpoint": "checkpoint:{depends-on-thread-variable}"}
        )
        schema["checkpoints"][4]["gate_type"] = "OR"
        schema["actions"][3]["context"] = "thread_group:2"
        schema["object_promises"][3]["context"] = "thread_group:2"
        schema["actions"][3]["depends_on"] = "checkpoint:{references-parent-context}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # it can be referenced by an action that specifies a nested threaded context in the same scope
        schema["actions"][4]["context"] = "thread_group:2"
        schema["object_promises"][4]["context"] = "thread_group:2"
        schema["actions"][4]["depends_on"] = "checkpoint:{depends-on-thread-variable}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # it cannot be referenced by an action if it's not within the scope of the action's context
        initial_value = schema["actions"][2]["depends_on"]
        assert schema["actions"][2]["context"] == "thread_group:1"
        schema["actions"][2]["depends_on"] = "checkpoint:{references-parent-context}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[2].depends_on (action id: 2): checkpoint with threaded context referenced out of scope: "checkpoint:{references-parent-context}"'
            in errors
        )

        schema["actions"][2]["depends_on"] = initial_value

        # it cannot be referenced by a thread that's not part of the same context
        schema["thread_groups"].append(
            fixtures.thread_group(3, "depends-on-thread-variable")
        )
        schema["actions"][6]["context"] = "thread_group:3"
        schema["object_promises"][6]["context"] = "thread_group:3"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.thread_groups[3].depends_on: checkpoint with threaded context referenced out of scope: "checkpoint:{depends-on-thread-variable}"'
            in errors
        )

        # it can be referenced by a thread that specifies the same threaded context
        schema["thread_groups"][3]["context"] = "thread_group:0"
        schema["thread_groups"][3]["spawn"]["as"] = "$num"  # avoid name collision
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # it can be referenced by a thread that specifies a nested threaded context in the same scope
        schema["thread_groups"].append(fixtures.thread_group(4))
        schema["thread_groups"][4]["context"] = "thread_group:3"
        schema["thread_groups"][4]["spawn"]["as"] = "$n"  # avoid name collision
        schema["actions"][7]["context"] = "thread_group:4"
        schema["object_promises"][7]["context"] = "thread_group:4"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_duplicate_checkpoint_dependencies(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(4)

        # Two checkpoints cannot have the same dependencies and the same gate type
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "checkpoint-1", "AND", 2),
            fixtures.checkpoint(1, "checkpoint-2", "AND", 2),
        ]
        schema["actions"][2]["depends_on"] = "checkpoint:{checkpoint-1}"
        schema["actions"][3]["depends_on"] = "checkpoint:{checkpoint-2}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            'root.checkpoints: duplicate value provided for unique field combination "[\\"gate_type\\", \\"dependencies\\"]"'
            in errors[0]
        )

        schema["checkpoints"][1]["dependencies"][0]["compare"]["right"]["value"] = False

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_dependency_operand_rules(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        checkpoint = fixtures.checkpoint(0, "test-ds", num_dependencies=0)

        # Both operands cannot be LiteralOperand objects
        checkpoint["dependencies"].append(
            {
                "compare": {
                    "left": {"value": True},
                    "operator": "EQUALS",
                    "right": {"value": False},
                },
            },
        )
        schema["checkpoints"].append(checkpoint)
        schema["actions"][1]["depends_on"] = "checkpoint:{test-ds}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.checkpoints[0].dependencies[0].compare: invalid comparison: {'value': True} EQUALS {'value': False}: both operands cannot be literals"
            in errors
        )

        # Operands cannot be identical
        schema["checkpoints"][0]["dependencies"][0] = {
            "compare": {
                "left": {"ref": "action:0.object_promise.completed"},
                "operator": "EQUALS",
                "right": {"ref": "action:0.object_promise.completed"},
            },
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.checkpoints[0].dependencies[0].compare: invalid comparison: {'ref': 'action:0.object_promise.completed'} EQUALS {'ref': 'action:0.object_promise.completed'}: operands are identical"
            in errors
        )

        # operands must be comparable
        schema["checkpoints"][0]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:0.object_promise.name"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.checkpoints[0].dependencies[0].compare: invalid comparison: {'ref': 'action:0.object_promise.name'} EQUALS {'ref': 'action:0.object_promise.completed'} (STRING EQUALS BOOLEAN)"
            in errors
        )

        # referenced operands can be paths
        schema["checkpoints"][0]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:0.object_promise.edge.completed"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should be able to compare two edges
        schema["checkpoints"][0]["dependencies"][0]["compare"] = {
            "left": {"ref": "action:0.object_promise.edge"},
            "operator": "EQUALS",
            "right": {"ref": "action:2.object_promise.edge"},
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should be able to compare edge collections
        schema["checkpoints"][0]["dependencies"][0]["compare"] = {
            "left": {"ref": "action:0.object_promise.objects"},
            "operator": "IS_SUBSET_OF",
            "right": {"ref": "action:2.object_promise.objects"},
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should be able to compare edges with edge collections
        schema["checkpoints"][0]["dependencies"][0]["compare"] = {
            "left": {"ref": "action:2.object_promise.objects"},
            "operator": "CONTAINS",
            "right": {"ref": "action:0.object_promise.edge"},
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_checkpoint_is_referenced(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "test-checkpoint", num_dependencies=1),
        ]

        # there is nothing referencing the checkpoint
        errors = validator.validate(json_string=json.dumps(schema))
        assert "root.checkpoints[0]: checkpoint is never referenced" in errors

        # the error should be resolved by setting the reference...

        # on an action
        schema["actions"][1]["depends_on"] = "checkpoint:{test-checkpoint}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # on a thread
        del schema["actions"][1]["depends_on"]
        schema["thread_groups"] = [
            fixtures.thread_group(0, "test-checkpoint"),
        ]
        schema["actions"][1]["context"] = "thread_group:0"
        schema["object_promises"][1]["context"] = "thread_group:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # within another checkpoint
        del schema["actions"][1]["context"]
        del schema["object_promises"][1]["context"]
        del schema["thread_groups"][0]
        nested_checkpoint = fixtures.checkpoint(
            1, "nested-checkpoint", num_dependencies=1
        )
        nested_checkpoint["dependencies"][0]["compare"]["right"]["value"] = False
        schema["checkpoints"].append(nested_checkpoint)
        schema["checkpoints"][0]["dependencies"].append(
            {"checkpoint": "checkpoint:{nested-checkpoint}"}
        )
        schema["checkpoints"][0]["gate_type"] = "AND"
        schema["actions"][1]["depends_on"] = "checkpoint:{test-checkpoint}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

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
        schema["actions"][action_idx]["party"] = "party:{Vandelay Industries}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            f'root.actions[0].party (action id: {action_ids[action_idx]}): invalid ref: object not found: "party:'
            + "{Vandelay Industries}"
            + '"'
            in errors
        )

        # fix the error
        schema["actions"][action_idx]["party"] = "party:{Project}"

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
            == f"root: expected object, got {type(json.loads(invalid_root)).__name__}"
        )

        # An empty root object should yield an error for each required property
        valid_root = "{}"
        errors = validator.validate(json_string=valid_root)
        assert len(errors) == len(obj_specs.root_object["properties"]) - len(
            obj_specs.root_object["constraints"]["optional"]
        )

        # The basic_schema fixture should be valid
        errors = validator.validate(json_string=json.dumps(fixtures.basic_schema()))
        assert not errors

    def test_edge_definition(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()

        attribute_types = ["EDGE", "EDGE_COLLECTION"]
        field_names = ["some_edge", "some_edge_collection"]

        attribute_count = len(schema["object_types"][0]["attributes"])
        for i in range(len(attribute_types)):
            schema["object_types"][0]["attributes"].append(
                {"name": field_names[i], "type": attribute_types[i]}
            )

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.object_types[0].attributes[{attribute_count}]: missing required property: object_type"
                in errors
            )

            schema["object_types"][0]["attributes"][attribute_count][
                "object_type"
            ] = "object_type:{NotAnObject}"

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f'root.object_types[0].attributes[{attribute_count}].object_type: invalid ref: object not found: "object_type:'
                + '{NotAnObject}"'
                in errors
            )

            schema["object_types"][0]["attributes"][attribute_count][
                "object_type"
            ] = "object_type:{Placeholder}"

            errors = validator.validate(json_string=json.dumps(schema))
            assert not errors

            attribute_count += 1

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
        schema["parties"].append({"id": 0, "name": "Project"})
        schema["actions"].append(fixtures.action())
        schema["object_promises"].append(fixtures.object_promise())
        assert "supporting_info" not in schema["actions"][0]  # optional property

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # include optional property
        schema["actions"][0]["supporting_info"] = [
            "Suspenders are a practical alternative to belts."
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_forbidden_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"].append(fixtures.checkpoint(0, "test-ds", "AND", 1))
        schema["actions"][1]["depends_on"] = "checkpoint:{test-ds}"

        assert len(schema["checkpoints"][0]["dependencies"]) == 1
        assert "gate_type" not in schema["checkpoints"][0]

        # Include a forbidden property
        # (Checkpoint.gate_type is forbidden when the checkpoint contains fewer than two dependencies)
        schema["checkpoints"][0]["gate_type"] = "AND"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            f"root.checkpoints[0]: forbidden property specified: gate_type; reason: gate_type is irrelevant when a checkpoint has fewer than 2 dependencies."
            in errors
        )

        del schema["checkpoints"][0]["gate_type"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_override_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(4)

        checkpoint_a = fixtures.checkpoint(0, "a", num_dependencies=1)
        schema["actions"][1]["depends_on"] = "checkpoint:{a}"
        assert len(checkpoint_a["dependencies"]) == 1
        assert "compare" in checkpoint_a["dependencies"][0]

        # If a Checkpoint contains a single item,
        # the item must be a Dependency object (not a CheckpointReference)
        checkpoint_b = fixtures.checkpoint(1, "b", num_dependencies=0)
        checkpoint_b["dependencies"].append({"checkpoint": "checkpoint:{a}"})
        checkpoint_b["gate_type"] = "OR"
        schema["actions"][2]["depends_on"] = "checkpoint:{b}"
        schema["checkpoints"] = [checkpoint_a, checkpoint_b]
        errors = validator.validate(json_string=json.dumps(schema))
        assert errors

        # If another item is added to the Checkpoint, the CheckpointReference is allowed
        checkpoint_c = fixtures.checkpoint(2, "c", num_dependencies=1)
        checkpoint_c["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:1.object_promise.completed"
        schema["checkpoints"].append(checkpoint_c)
        checkpoint_b["dependencies"].append({"checkpoint": "checkpoint:{c}"})
        schema["actions"][3]["depends_on"] = "checkpoint:{c}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_obj_spec_conditionals(self):
        validator = SchemaValidator()

        # If a checkpoint has more than one dependency,
        # "gate_type" is required
        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"].append(
            {
                "id": 0,
                "alias": "test-ds",
                "description": "test dependency set",
                "dependencies": [
                    fixtures.dependency("action:0"),
                    fixtures.dependency("action:1"),
                ],
            }
        )
        schema["actions"][2]["depends_on"] = "checkpoint:{test-ds}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert "root.checkpoints[0]: missing required property: gate_type" in errors

        # If a checkpoint has one or fewer dependencies,
        # "gate_type" is optional
        schema["checkpoints"][0]["dependencies"].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_ref(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(1)
        assert len(schema["actions"]) == 1

        schema["parties"] = [{"id": 0, "name": "Project"}]
        schema["actions"][0]["party"] = "party:{something else}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].party (action id: 0): invalid ref: object not found: "party:{something else}"'
            in errors
        )

        schema["actions"][0]["party"] = "party:{Project}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["actions"][0]["party"] = "party:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_unique_fields(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)

        schema["checkpoints"] = [
            fixtures.checkpoint(0, "some-alias", num_dependencies=1),
            fixtures.checkpoint(1, "some-alias", num_dependencies=1),
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:0"
        schema["actions"][2]["depends_on"] = "checkpoint:1"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints: duplicate value provided for unique field "alias": "some-alias"'
            in errors
        )

        schema["checkpoints"].pop()
        del schema["actions"][2]["depends_on"]
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
            errors = validator._validate_multi_type_field(
                "none", val, allowed_types, None
            )
            assert len(errors) == 1
            assert (
                errors[0]
                == f"none: expected one of {json.dumps(allowed_types)}, got {json.dumps(type(val).__name__)}"
            )

        valid = ["test", 1]
        for val in valid:
            errors = validator._validate_multi_type_field(
                "none", val, allowed_types, None
            )
            assert not errors

    def test_reserved_keywords(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema()

        for keyword in obj_specs.RESERVED_KEYWORDS:
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
                == f"root.parties[0]: expected object, got {type(invalid_array[0]).__name__}"
            )

        # Arrays must conform to the specified obj_spec
        # (in ths case, obj_specs.party)
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
            assert errors
            if "name" not in invalid_array[0]:
                assert "root.parties[0]: missing required property: name" in errors
            else:
                assert (
                    f"root.parties[0].name: expected string, got {str(type(invalid_array[0]['name']))}"
                    in errors
                )

    def test_distict_array(self):
        validator = SchemaValidator()

        obj_spec = {
            "type": "array",
            "values": {"type": "string"},
            "constraints": {
                "distinct": True,
            },
        }

        errors = validator._validate_array("none", ["a", "b", "a"], obj_spec, None)
        assert len(errors) == 1
        assert errors[0] == "none: contains duplicate item(s) (values must be distinct)"

        errors = validator._validate_array("none", ["a", "b", "c"], obj_spec, None)
        assert not errors

    def test_min_length(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)

        # Min length for Checkpoint.dependencies is 1
        schema["checkpoints"].append(
            fixtures.checkpoint(0, "some-alias", num_dependencies=0)
        )
        schema["actions"][1]["depends_on"] = "checkpoint:{some-alias}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert (
            errors[0]
            == "root.checkpoints[0].dependencies: must contain at least 1 item(s), got 0"
        )

        schema["checkpoints"][0]["dependencies"].append(fixtures.dependency("action:0"))
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_nullable(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(1)

        # Should be able to specify null for a nullable property (Action.operation.include)
        schema["actions"][0]["operation"]["include"] = None
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # Should not be able to specify null for a non-nullable property (Action.operation.type)
        schema["actions"][0]["object_promise"] = None
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].object_promise (action id: 0): expected ref, got null"
            in errors
        )

    def test_mutually_exclusive_properties(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)

        expected_error = "root.actions[0].operation (action id: 0): more than one mutually exclusive property specified: ['include', 'exclude']"

        # Should not be able to specify more than one mutually exclusive property
        schema["actions"][0]["operation"]["exclude"] = ["completed"]
        assert "include" in schema["actions"][0]["operation"]

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == expected_error

        # Nullability should not affect the result
        schema["actions"][0]["operation"]["include"] = None
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == expected_error

        del schema["actions"][0]["operation"]["include"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # Unless all of the mutually exclusive properties are optional,
        # at least one of them must be specified
        del schema["actions"][0]["operation"]["exclude"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].operation (action id: 0): must specify one of the mutually exclusive properties: ['include', 'exclude']"
            in errors
        )

    def test_enum(self):
        validator = SchemaValidator()

        obj_spec = {"values": ["a", "b", "c"]}

        invalid_enum_values = [1, 1.0, True, None, [], {}, "test"]
        for invalid_value in invalid_enum_values:
            errors = validator._validate_enum("none", invalid_value, obj_spec, None)
            assert len(errors) == 1
            assert (
                errors[0]
                == f"none: invalid enum value: expected one of "
                + str(obj_spec["values"])
                + f", got {json.dumps(invalid_value)}"
            )

        for valid_value in obj_spec["values"]:
            errors = validator._validate_enum("none", valid_value, obj_spec, None)
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
        schema["parties"].append({"id": 0, "name": "Party 1", "hex_code": "#000000"})

        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        invalid_hex_codes = ["#00000", "000000", "#00000g", "#00000G", "#00000_"]

        for invalid_hex_code in invalid_hex_codes:
            schema["parties"][0]["hex_code"] = invalid_hex_code
            errors = validator.validate(json_string=json.dumps(schema))
            assert len(errors) == 1
            assert (
                errors[0]
                == f'root.parties[0].hex_code: string does not match {obj_specs.party["properties"]["hex_code"]["patterns"][0]["description"]} pattern: {patterns.hex_code}'
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

        obj_spec = {"type": "boolean"}

        invalid_booleans = [1, 1.0, "True", None, [], {}]
        for invalid_boolean in invalid_booleans:
            errors = validator._validate_boolean("none", invalid_boolean, obj_spec)
            assert len(errors) == 1
            assert (
                errors[0] == f"none: expected boolean, got {str(type(invalid_boolean))}"
            )

        valid_booleans = [True, False]
        for valid_boolean in valid_booleans:
            errors = validator._validate_boolean("none", valid_boolean, obj_spec)
            assert not errors
