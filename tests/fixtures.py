def basic_schema_with_actions(num_actions):
    schema = basic_schema()
    schema["parties"].append({"id": 0, "name": "Project"})

    for i in range(num_actions):
        schema["actions"].append(action(i))
        schema["object_promises"].append(object_promise(i))

    return schema


def basic_schema():
    return {
        "standard": "basic_test_schema",
        "terms": [],
        "parties": [],
        "actions": [],
        "checkpoints": [],
        "object_types": {
            "Placeholder": {
                "completed": {"field_type": "BOOLEAN"},
                "name": {"field_type": "STRING"},
                "number": {"field_type": "NUMERIC"},
                "numbers": {"field_type": "NUMERIC_LIST"},
                "edge": {"field_type": "EDGE", "object_type": "Placeholder"},
                "objects": {
                    "field_type": "EDGE_COLLECTION",
                    "object_type": "Placeholder",
                },
            }
        },
        "object_promises": [],
        "pipelines": [],
    }


def action(action_id=None):
    if action_id is None:
        action_id = 0

    return {
        "id": action_id,
        "object_promise": "object_promise:" + str(action_id),
        "description": "test action",
        "party": "party:{Project}",
        "operation": {
            "include": ["name"],
        },
    }


def object_promise(op_id=0, object_type="Placeholder"):
    return {
        "id": op_id,
        "name": "object_promise_" + str(op_id),
        "object_type": object_type,
    }


def checkpoint(id, alias, gate_type="AND", num_dependencies=2):
    dependencies = []
    for i in range(num_dependencies):
        dependencies.append(dependency(ref="action:" + str(i)))

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
    path_from_ref="object_promise.completed",
    operator="EQUALS",
    comparison_value=True,
):
    return {
        "compare": {
            "left": {"ref": f"{ref}.{path_from_ref}"},
            "right": {"value": comparison_value},
            "operator": operator,
        },
    }


def thread_group(id, depends_on_id=None):
    thread = {
        "id": id,
        "description": "",
        "spawn": {
            "from": "object_promise:0",
            "foreach": "numbers",
            "as": "$number",
        },
    }

    if depends_on_id is not None:
        thread["depends_on"] = "checkpoint:{" + depends_on_id + "}"

    return thread
