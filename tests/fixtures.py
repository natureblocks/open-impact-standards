def basic_schema_with_actions(num_actions):
    schema = basic_schema()
    schema["parties"].append({"name": "Project"})

    for i in range(num_actions):
        schema["actions"].append(action(i))

    return schema


def basic_schema():
    return {
        "standard": "basic_test_schema",
        "term_definitions": [],
        "parties": [],
        "actions": [],
        "checkpoints": [],
        "nodes": {
            "Placeholder": {
                "completed": {"field_type": "BOOLEAN"},
                "name": {"field_type": "STRING"},
            }
        },
    }


def action(action_id=None):
    return {
        "id": action_id if action_id is not None else 0,
        "description": "test action",
        "applies_to": "Project",
        "tag": "Placeholder",
        "data": {"completed": {"field_type": "BOOLEAN"}},
    }


def checkpoint(alias, gate_type="AND", num_dependencies=2):
    dependencies = []
    for i in range(num_dependencies):
        dependencies.append(dependency(action_id=i))

    checkpoint = {
        "alias": alias,
        "description": "test dependency set",
        "dependencies": dependencies,
    }

    if num_dependencies > 1:
        checkpoint["gate_type"] = gate_type

    return checkpoint


def dependency(
    action_id,
    field_name="completed",
    comparison_operator="EQUALS",
    comparison_value_type="BOOLEAN",
    boolean_comparison_value=True,
):
    return {
        "node": {
            "action_id": action_id,
            "field_name": field_name,
            "comparison_operator": comparison_operator,
            "comparison_value_type": comparison_value_type,
            "boolean_comparison_value": boolean_comparison_value,
        }
    }
