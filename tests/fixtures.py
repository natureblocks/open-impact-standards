def basic_schema_with_nodes(num_nodes):
    schema = basic_schema()
    schema["parties"].append({"name": "Project"})

    for i in range(num_nodes):
        schema["state_nodes"].append(node(i))

    return schema


def basic_schema():
    return {
        "standard": "basic_test_schema",
        "parties": [],
        "state_nodes": [],
        "referenced_dependency_sets": [],
        "node_definitions": {"Placeholder": {"completed": {"field_type": "BOOLEAN"}}},
    }


def node(node_id=None):
    return {
        "meta": {
            "id": node_id if node_id is not None else 0,
            "description": "test node",
            "node_type": "STATE",
            "applies_to": "Project",
            "tag": "Placeholder",
        },
        "data": {"completed": {"field_type": "BOOLEAN"}},
    }


def dependency_set(alias, gate_type="AND", num_dependencies=2):
    dependencies = []
    for i in range(num_dependencies):
        dependencies.append(dependency(node_id=i))

    return {"alias": alias, "gate_type": gate_type, "dependencies": dependencies}


def dependency(
    node_id,
    field_name="completed",
    comparison_operator="EQUALS",
    comparison_value_type="BOOLEAN",
    boolean_comparison_value=True,
):
    return {
        "node_id": node_id,
        "field_name": field_name,
        "comparison_operator": comparison_operator,
        "comparison_value_type": comparison_value_type,
        "boolean_comparison_value": boolean_comparison_value,
    }
