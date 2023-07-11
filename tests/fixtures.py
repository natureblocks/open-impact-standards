def basic_schema_with_actions(num_actions):
    schema = basic_schema()
    schema["parties"].append({"id": 0, "name": "Project"})

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
        "objects": {
            "Placeholder": {
                "completed": {"field_type": "BOOLEAN"},
                "name": {"field_type": "STRING"},
                "number": {"field_type": "NUMERIC"},
                "numbers": {"field_type": "NUMERIC_LIST"},
                "objects": {"field_type": "EDGE_COLLECTION", "object": "Placeholder"},
            }
        },
    }


def action(action_id=None):
    return {
        "id": action_id if action_id is not None else 0,
        "object": "Placeholder",
        "description": "test action",
        "party": "party:{Project}",
        "operation": {
            "type": "CREATE",
            "include": ["name"],
        },
    }


def checkpoint(id, alias, gate_type="AND", num_dependencies=2):
    dependencies = []
    for i in range(num_dependencies):
        dependencies.append(dependency(ref="action:{" + str(i) + "}"))

    checkpoint = {
        "id": id,
        "alias": alias,
        "description": "test dependency set",
        "dependencies": dependencies,
    }

    if num_dependencies > 1:
        checkpoint["gate_type"] = gate_type

    return checkpoint


def dependency(
    ref,
    field="completed",
    operator="EQUALS",
    comparison_value=True,
):
    return {
        "compare": {
            "left": {"ref": ref, "field": field},
            "right": {"value": comparison_value},
            "operator": operator,
        },
    }
