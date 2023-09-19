import json
from validation.schema_validator import SchemaValidator
from tests import fixtures


class TestSchemaImports:
    def test_native_checkpoint_to_imported_action(self):
        # an imported action should be able to depend on a native checkpoint
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        schema["imports"] = [
            {
                "file_name": "test/basic_import",
                "connections": [
                    {
                        "to_ref": "schema:{test/basic_import}.action:0",
                        "add_dependency": "checkpoint:{depends-on-0}",
                    }
                ],
            }
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # if the imported action already has a checkpoint,
        # the stitching process should create a new checkpoint
        schema["imports"][0]["connections"][0][
            "to_ref"
        ] = "schema:{test/basic_import}.action:1"
        num_native_checkpoints = len(schema["checkpoints"])
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors
        assert len(validator.schema["checkpoints"]) == num_native_checkpoints + 1
        new_checkpoint = validator.schema["checkpoints"][-1]
        assert len(new_checkpoint["dependencies"]) == 2
        has_added_dependency = False
        for dependency in new_checkpoint["dependencies"]:
            if (
                "checkpoint" in dependency
                and dependency["checkpoint"] == "checkpoint:{depends-on-0}"
            ):
                has_added_dependency = True
                break
        assert has_added_dependency

    def test_native_checkpoint_to_imported_checkpoint(self):
        # an imported checkpoint should be able to depend on a native checkpoint
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        schema["imports"] = [
            {
                "file_name": "test/basic_import",
                "connections": [
                    {
                        "to_ref": "schema:{test/basic_import}.checkpoint:0",
                        "add_dependency": "checkpoint:{depends-on-0}",
                    }
                ],
            }
        ]
        num_native_checkpoints = len(schema["checkpoints"])
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # the stitching process should have created a new checkpoint
        # with the same dependencies as the imported checkpoint
        assert len(validator.schema["checkpoints"]) == num_native_checkpoints + 1
        new_checkpoint = validator.schema["checkpoints"][-1]
        assert len(new_checkpoint["dependencies"]) == 1
        assert (
            new_checkpoint["dependencies"][0]["compare"]["left"]["ref"]
            == "schema:{test/basic_import}.action:0.object_promise.completed"
        )
        imported_checkpoint = validator.schema["imported_schemas"]["test/basic_import"][
            "checkpoints"
        ][0]
        # the stitching process should have updated the imported checkpoint
        # to reference the new native checkpoint and the added dependency checkpoint
        referenced_checkpoints = [
            dependency["checkpoint"] if "checkpoint" in dependency else None
            for dependency in imported_checkpoint["dependencies"]
        ]
        assert "checkpoint:{depends-on-0}" in referenced_checkpoints
        assert f"checkpoint:{num_native_checkpoints}" in referenced_checkpoints
        assert imported_checkpoint["gate_type"] == "AND"

    def test_imported_checkpoint_to_native_action(self):
        # a native action should be able to depend on an imported checkpoint
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)
        schema["imports"] = [
            {
                "file_name": "test/basic_import",
            }
        ]
        schema["actions"][-1]["depends_on"] = "schema:{test/basic_import}.checkpoint:1"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_imported_checkpoint_to_native_checkpoint(self):
        # a native checkpoint should be able to depend on an imported checkpoint
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-0", num_dependencies=1)
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:0"
        schema["imports"] = [
            {
                "file_name": "test/basic_import",
            }
        ]
        schema["checkpoints"][0]["dependencies"].append(
            {
                "checkpoint": "schema:{test/basic_import}.checkpoint:0",
            }
        )
        schema["checkpoints"][0]["gate_type"] = "OR"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_imported_action_to_native_checkpoint(self):
        # a native checkpoint should be able to depend on an imported action
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)
        schema["imports"] = [
            {
                "file_name": "test/basic_import",
            }
        ]
        schema["checkpoints"] = [
            fixtures.checkpoint(0, "depends-on-imported-action", num_dependencies=1)
        ]
        # should be able to reference a field from an imported object type
        schema["checkpoints"][0]["dependencies"][0]["compare"] = {
            "left": {
                "ref": "schema:{test/basic_import}.action:1.object_promise.some_numeric_field"
            },
            "operator": "EQUALS",
            "right": {
                "value": 1,
            },
        }
        schema["actions"][1]["depends_on"] = "checkpoint:0"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_recursive_import(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)
        schema["imports"] = [
            {
                "file_name": "test/secondary_import",
            }
        ]
        schema["actions"][0]["depends_on"] = "schema:{test/basic_import}.checkpoint:1"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        assert (
            validator.schema["imported_schemas"]["test/basic_import"]["actions"][0][
                "depends_on"
            ]
            == "schema:{test/secondary_import}.checkpoint:1"
        )

