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

    def test_thread_variable_name_collision(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        thread = fixtures.thread(0, "depends-on-0")
        child_thread = fixtures.thread(1)
        child_thread["context"] = "thread:{0}"
        schema["actions"][1]["context"] = "thread:{1}"

        # should not be able to reuse a variable name in the same scope
        thread["spawn"]["as"] = "$some_var"
        child_thread["spawn"]["as"] = "$some_var"
        schema["threads"] = [thread, child_thread]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.threads[1].spawn.as: variable already defined within thread scope: "$some_var"'
            in errors
        )

        # the validation results should be the same
        # regardless of the order of the threads in the schama
        schema["threads"] = [child_thread, thread]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.threads[1].spawn.as: variable already defined within thread scope: "$some_var"'
            in errors
        )

        child_thread["spawn"]["as"] = "$some_other_var"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # should be able to reuse a variable name in a different scope
        sibling_thread = fixtures.thread(2, "depends-on-0")
        sibling_thread["spawn"]["as"] = "$some_var"
        schema["threads"].append(sibling_thread)
        schema["actions"][2]["context"] = "thread:{2}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_thread_spawn(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        schema["threads"] = [
            {
                "id": 0,
                "description": "",
                "party": "party:{0}",
                "spawn": {
                    "from": "",
                    "foreach": "numbers",
                    "as": "$number",
                },
                "depends_on": "checkpoint:{depends-on-0}",
            }
        ]
        schema["actions"][1]["context"] = "thread:{0}"

        def set_thread_value(key, val):
            if isinstance(key, list):
                obj = schema["threads"][0]
                for i in range(len(key) - 1):
                    obj = obj[key[i]]

                obj[key[-1]] = val
            else:
                schema["threads"][0][key] = val

        # spawn.from must be an ancestor of the thread
        set_thread_value(["spawn", "from"], "action:{2}.object")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.threads[0]: the value of property "spawn.from" must reference an ancestor of thread id "0", got "action:{2}.object"'
            in errors
        )

        set_thread_value(["spawn", "from"], "action:{0}.object")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # spawn.foreach must refer to a collection on spawn.from
        set_thread_value(["spawn", "foreach"], "words")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.threads[0].spawn: could not resolve variable type: "action:{0}.object.words"'
            in errors
        )

        set_thread_value(["spawn", "foreach"], "name")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.threads[0].spawn: cannot spawn threads from a non-list object"
            in errors
        )

        # a nested thread should be able to
        # spawn from a collection on a parent thread variable
        set_thread_value(
            ["spawn"],
            {
                "from": "action:{0}.object",
                "foreach": "objects",
                "as": "$object",
            },
        )
        schema["threads"].append(fixtures.thread(1))
        schema["threads"][1]["context"] = "thread:{0}"
        schema["threads"][1]["spawn"] = {
            "from": "$object",
            "foreach": "numbers",
            "as": "$number",
        }
        schema["actions"][2]["context"] = "thread:{1}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        schema["threads"][1]["spawn"] = {
            "from": "$object",
            "foreach": "objects",
            "as": "$sub_object",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_thread_spawn_collections(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["threads"] = [
            fixtures.thread(0),
        ]
        schema["threads"][0]["depends_on"] = "checkpoint:{depends-on-0}"
        schema["actions"][2]["context"] = "thread:{0}"

        # test valid list sources...
        valid_list_sources = [
            ("", "numbers"),  # list of scalars
            ("", "objects"),  # edge collection
            ("objects", "name"),  # field on an edge collection
            ("objects", "edge"),  # edge on an edge collection
            ("edge.edge.edge.objects", "name"),  # just for fun
        ]

        for path_completion, field_name in valid_list_sources:
            schema["threads"][0]["spawn"] = {
                "from": "action:{0}.object"
                + ("." + path_completion if path_completion else ""),
                "foreach": field_name,
                "as": "$var",
            }
            errors = validator.validate(json_string=json.dumps(schema))
            assert not errors

        # field from a threaded action (the threading makes it a list)
        schema["threads"].append(fixtures.thread(1))
        schema["threads"][1]["context"] = "thread:{0}"
        schema["actions"][1]["context"] = "thread:{0}"
        schema["actions"][2]["context"] = "thread:{1}"
        schema["checkpoints"].append(
            fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        )
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:{1}"
        schema["threads"][1]["depends_on"] = "checkpoint:{depends-on-1}"
        schema["threads"][1]["spawn"] = {
            "from": "action:{1}.object",  # list (threaded action)
            "foreach": "name",  # non-list
            "as": "$name",  # should be a list
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # edge on a threaded action (the threading makes it a list)
        schema["threads"][1]["spawn"] = {
            "from": "action:{1}.object",  # list (threaded action)
            "foreach": "edge",  # non-list
            "as": "$edge",  # should be a list
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # non-lists are invalid...
        non_list_sources = [
            "name",  # scalar field
            "edge",  # edge
        ]
        for field_name in non_list_sources:
            schema["threads"][0]["spawn"] = {
                "from": "action:{0}.object",
                "foreach": field_name,
                "as": "$var",
            }
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                "root.threads[0].spawn: cannot spawn threads from a non-list object"
                in errors
            )

        # nested lists are invalid...
        nested_list_sources = [
            (0, "objects", "numbers"),  # edge_collection->list
            (0, "objects.edge", "numbers"),  # edge_collection->edge->list
            (0, "objects.edge", "objects"),  # edge_collection->edge->edge_collection
            (1, "", "numbers"),  # threaded_action->list
            (1, "objects", "name"),  # threaded_action->list
        ]

        for thread_action_id, path_completion, field_name in nested_list_sources:
            schema["threads"][thread_action_id]["spawn"] = {
                "from": "action:{"
                + str(thread_action_id)
                + "}.object"
                + ("." + path_completion if path_completion else ""),
                "foreach": field_name,
                "as": "$var",
            }
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.threads[{thread_action_id}].spawn: nested list types are not supported"
                in errors
            )

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

        set_dependency(0, "action:{0}")
        set_dependency(1, "action:{1}")
        set_dependency(2, "action:{2}")
        set_dependency(3, "action:{3}")

        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
        ]
        schema["actions"][1]["context"] = "thread:{0}"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-1}"
        schema["actions"][3]["depends_on"] = "checkpoint:{depends-on-2}"
        schema["actions"][0][
            "depends_on"
        ] = "checkpoint:{depends-on-3}"  # creates circular dependency

        errors = validator.validate(json_string=json.dumps(schema))
        threaded_context_note = "; NOTE: actions with threaded context implicitly depend on the referenced thread's checkpoint (Thread.depends_on)"
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
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.actions[2] (action id: 2): cannot depend on threaded action: "action:{1}"'
        )

        # a thread cannot depend on an action that references said thread as its context
        schema["actions"][0]["context"] = "thread:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "A node cannot have itself as a dependency (id: 0); NOTE: actions with threaded context implicitly depend on the referenced thread's checkpoint (Thread.depends_on)"
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
        ] = "action:{1}"

        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
            fixtures.thread(1),
        ]
        schema["threads"][0]["spawn"] = {
            "from": "action:{0}.object",
            "foreach": "objects",
            "as": "$object",
        }
        schema["threads"][1]["spawn"] = {
            "from": "$object",  # parent thread variable!
            "foreach": "numbers",
            "as": "$number",
        }
        schema["threads"][1]["context"] = "thread:{0}"
        schema["actions"][1]["context"] = "thread:{1}"
        schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-1}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "Circular dependency detected (dependency path: [0, 1]); NOTE: actions with threaded context implicitly depend on the referenced thread's checkpoint (Thread.depends_on)"
            in errors
        )

        remove_checkpoint(schema["actions"][0]["depends_on"])
        del schema["actions"][0]["depends_on"]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_thread_is_used(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
        ]

        # threads must contain either an action or a nested thread
        errors = validator.validate(json_string=json.dumps(schema))
        assert "root.threads[0]: thread is never referenced" in errors

        schema["actions"][1]["context"] = "thread:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        del schema["actions"][1]["context"]
        schema["threads"].append(fixtures.thread(1))
        schema["threads"][1]["context"] = "thread:{0}"
        schema["threads"][1]["spawn"] = {
            "from": "action:{0}.object",
            "foreach": "objects",
            "as": "$object",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert "root.threads[1]: thread is never referenced" in errors

        schema["actions"][1]["context"] = "thread:{1}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_action_context(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"

        # action.context must be a defined thread
        schema["actions"][1]["context"] = "action:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].context (action id: 1): invalid ref type: expected one of ["thread"], got "action"'
            in errors
        )

        schema["actions"][1]["context"] = "thread:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].context (action id: 1): invalid ref: object not found: "thread:{0}"'
            in errors
        )

        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),  # creates thread:{0}
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # threaded actions must specify the same party as the thread
        schema["threads"][0]["party"] = "party:{Project}"
        schema["parties"].append({"id": 1, "name": "Vandelay Industries"})
        schema["actions"][1]["party"] = "party:{Vandelay Industries}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].party (action id: 1): expected ref equivalent to "party:{Project}", got "party:{Vandelay Industries}"'
            in errors
        )

        schema["actions"][1]["party"] = "party:{Project}"
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

        # A node should not be able to depend on itself
        schema = fixtures.basic_schema_with_actions(1)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
        ]
        assert (
            schema["checkpoints"][0]["dependencies"][0]["compare"]["left"]["ref"]
            == "action:{" + str(schema["actions"][0]["id"]) + "}"
        )
        schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "A node cannot have itself as a dependency (id: 0)"

        # Two nodes should not be able to depend on each other
        schema["actions"].append(fixtures.action(1))
        checkpoint_2 = fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        checkpoint_2["dependencies"][0]["compare"]["left"]["ref"] = "action:{1}"
        schema["checkpoints"].append(checkpoint_2)
        schema["actions"][0]["depends_on"] = "checkpoint:{depends-on-1}"
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1])"

        # Three or more nodes should not be able to form a circular dependency
        schema["actions"].append(fixtures.action(2))
        checkpoint_3 = fixtures.checkpoint(2, "depends-on-2", num_dependencies=1)
        checkpoint_3["dependencies"][0]["compare"]["left"]["ref"] = "action:{2}"
        schema["checkpoints"].append(checkpoint_3)
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-2}"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-0}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert len(errors) == 1
        assert errors[0] == "Circular dependency detected (dependency path: [0, 1, 2])"

        # What if a recurring dependency set helps form a circular dependency?
        schema["actions"].append(fixtures.action(3))
        schema["actions"].append(fixtures.action(4))
        checkpoint_4 = fixtures.checkpoint(3, "depends-on-3", num_dependencies=1)
        checkpoint_4["dependencies"][0]["compare"]["left"]["ref"] = "action:{3}"
        schema["checkpoints"].append(checkpoint_4)
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-3}"
        checkpoint_5 = fixtures.checkpoint(4, "depends-on-4-and-0", num_dependencies=1)
        checkpoint_5["dependencies"][0]["compare"]["left"]["ref"] = "action:{4}"
        checkpoint_5["dependencies"].append({"checkpoint": "checkpoint:{depends-on-0}"})
        schema["checkpoints"].append(checkpoint_5)
        schema["actions"][3]["depends_on"] = "checkpoint:{depends-on-4-and-0}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert "Circular dependency detected (dependency path: [0, 1, 2, 3])" in errors

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

    def test_depends_on_threaded_action(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(4)
        depends_on_1 = fixtures.checkpoint(1, "depends-on-1", num_dependencies=1)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1),
            depends_on_1,
        ]
        schema["checkpoints"][1]["dependencies"][0]["compare"]["left"][
            "ref"
        ] = "action:{1}"
        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
        ]

        # An action cannot depend on a threaded action that is not part of the same context
        schema["actions"][1]["context"] = "thread:{0}"
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-1}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[2] (action id: 2): cannot depend on threaded action: "action:{1}"'
            in errors
        )

        # An action should be able to depend on a threaded action that has the same threaded context
        schema["actions"][2]["context"] = "thread:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # A thread should not be able to depend on an action that is not part of the same context
        # in which the thread was defined
        thread_1 = fixtures.thread(1, "depends-on-1")
        thread_1["spawn"] = {
            "from": "action:{1}.object",
            "foreach": "name",
            "as": "$names",
        }
        schema["threads"].append(thread_1)

        schema["actions"][2]["context"] = "thread:{1}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.threads[1]: cannot depend on threaded action: "action:{1}"' in errors
        )

        # threads should be able to depend on actions that share their context
        schema["threads"][1]["context"] = "thread:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # the same should hold true for nested threads
        thread_2 = fixtures.thread(2)
        thread_2["context"] = "thread:{1}"
        thread_2["spawn"] = {
            "from": "action:{1}.object",
            "foreach": "edge",
            "as": "$edge",
        }
        schema["threads"].append(thread_2)
        schema["actions"][3]["context"] = "thread:{2}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_dependency_operand_rules(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        checkpoint = fixtures.checkpoint(0, "test-ds", num_dependencies=0)

        # Both operands cannot be LiteralOperand objects
        checkpoint["dependencies"].append(
            {
                "compare": {
                    "left": {"value": True},
                    "right": {"value": False},
                    "operator": "EQUALS",
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
        identical_operand = {"ref": "action:{0}", "field": "completed"}
        schema["checkpoints"][0]["dependencies"][0] = {
            "compare": {
                "left": identical_operand,
                "right": identical_operand,
                "operator": "EQUALS",
            },
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert errors

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
        schema["threads"] = [
            fixtures.thread(0, "test-checkpoint"),
        ]
        schema["actions"][1]["context"] = "thread:{0}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # within another checkpoint
        del schema["actions"][1]["context"]
        del schema["threads"][0]
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
            == f"root: expected object, got {str(type(json.loads(invalid_root)))}"
        )

        # An empty root object should yield an error for each required property
        valid_root = "{}"
        errors = validator.validate(json_string=valid_root)
        assert len(errors) == len(templates.root_object["properties"]) - len(
            templates.root_object["constraints"]["optional"]
        )

        # The basic_schema fixture should be valid
        errors = validator.validate(json_string=json.dumps(fixtures.basic_schema()))
        assert not errors

    def test_edge_definition(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema()

        field_types = ["EDGE", "EDGE_COLLECTION"]
        field_names = ["some_edge", "some_edge_collection"]

        for i in range(len(field_types)):
            schema["objects"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i]
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f"root.objects.Placeholder.{field_names[i]}: missing required property: object"
                in errors
            )

            schema["objects"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i],
                "object": "NotAnObject",
            }

            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                f'root.objects.Placeholder.{field_names[i]}.object: expected any key from root.objects, got "NotAnObject"'
                in errors
            )

            schema["objects"]["Placeholder"][field_names[i]] = {
                "field_type": field_types[i],
                "object": "Placeholder",
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
        schema["parties"].append({"id": 0, "name": "Project"})
        schema["actions"].append(fixtures.action())
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

    def test_add_properties(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"].append(fixtures.checkpoint(0, "test-ds", "AND", 1))
        schema["actions"][1]["depends_on"] = "checkpoint:{test-ds}"

        schema["actions"][1]["operation"]["type"] = "EDIT"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].operation (action id: 1): missing required property: ref"
            in errors
        )
        assert (
            'root.actions[1].operation (action id: 1): the value of property "ref" must reference an ancestor of action id 1, got null'
            in errors
        )

        schema["actions"][1]["operation"]["ref"] = "action:{3}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].operation (action id: 1): the value of property "ref" must reference an ancestor of action id 1, got "action:{3}"'
            in errors
        )

        schema["actions"][1]["operation"]["ref"] = "action:{0}"
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
        checkpoint_c["dependencies"][0]["compare"]["left"]["ref"] = "action:{1}"
        schema["checkpoints"].append(checkpoint_c)
        checkpoint_b["dependencies"].append({"checkpoint": "checkpoint:{c}"})
        schema["actions"][3]["depends_on"] = "checkpoint:{c}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_template_conditionals(self):
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
                    fixtures.dependency("action:{0}"),
                    fixtures.dependency("action:{1}"),
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
        assert len(errors) == 1
        assert (
            errors[0]
            == 'root.actions[0].party (action id: 0): invalid ref: object not found: "party:{something else}"'
        )

        schema["actions"][0]["party"] = "party:{Project}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_unique_fields(self):
        validator = SchemaValidator()

        schema = fixtures.basic_schema_with_actions(3)

        schema["checkpoints"] = [
            fixtures.checkpoint(0, "some-alias"),
            fixtures.checkpoint(1, "some-alias"),
        ]
        schema["actions"][2]["depends_on"] = "checkpoint:{some-alias}"

        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.checkpoints: duplicate value provided for unique field "alias": "some-alias"'
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

        template = {
            "type": "array",
            "values": {"type": "string"},
            "constraints": {
                "distinct": True,
            },
        }

        errors = validator._validate_array("none", ["a", "b", "a"], template, None)
        assert len(errors) == 1
        assert errors[0] == "none: contains duplicate item(s) (values must be distinct)"

        errors = validator._validate_array("none", ["a", "b", "c"], template, None)
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

        schema["checkpoints"][0]["dependencies"].append(
            fixtures.dependency("action:{0}")
        )
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
        schema["actions"][0]["operation"]["type"] = None
        errors = validator.validate(json_string=json.dumps(schema))
        assert errors

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

    def test_enum(self):
        validator = SchemaValidator()

        template = {"values": ["a", "b", "c"]}

        invalid_enum_values = [1, 1.0, True, None, [], {}, "test"]
        for invalid_value in invalid_enum_values:
            errors = validator._validate_enum("none", invalid_value, template, None)
            assert len(errors) == 1
            assert (
                errors[0]
                == f"none: invalid enum value: expected one of "
                + str(template["values"])
                + f", got {json.dumps(invalid_value)}"
            )

        for valid_value in template["values"]:
            errors = validator._validate_enum("none", valid_value, template, None)
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
