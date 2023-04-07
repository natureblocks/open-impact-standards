def basic_schema_with_nodes(num_nodes):
    schema = basic_schema()
    schema["parties"].append({"name": "Project"})

    for i in range(num_nodes):
        schema["nodes"][str(i)] = node(i)

    return schema


def basic_schema():
    return {
        "standard": "basic_test_schema",
        "parties": [],
        "active_nodes": [],
        "nodes": {},
        "dependency_sets": [],
    }


def node(node_id=None):
    return {
        "id": str(node_id) if node_id is not None else "0",
        "description": "test node",
        "node_type": "STATE",
        "applies_to": "Project",
        "dependencies_met": False,
        "completed": False,
    }


def dependency_set(alias, gate_type="AND", num_dependencies=2):
    dependencies = []
    for i in range(num_dependencies):
        dependencies.append(
            {"node_id": str(i), "property": "completed", "equals": True}
        )

    return {"alias": alias, "gate_type": gate_type, "dependencies": dependencies}
