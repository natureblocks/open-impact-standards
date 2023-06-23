from enums import gate_types

query = {
    "type": "object",
    "properties": {
        "from": {"type": "string"},
        "where": {
            "type": "object",
            "any_of_templates": ["condition", "condition_group"]
        },
        "extract": {"type": "string"}
    },
    "constraints": {
        "optional": ["where"]
    },
}

condition = {
    "type": "object",
    "properties": {
        "property": {"type": "string"},
        "operator": {
            "type": "enum",
            "values": ["EQUALS", "IN", "IS_REFERENCED_BY"],
        },
        "value": {
            "type": "object",
            "template": "query",
        },
    },
}

condition_group = {
    "type": "object",
    "properties": {
        "gate_type": {
            "type": "enum",
            "values": gate_types
        },
        "conditions": {
            "type": "array",
            "values": {
                "type": "object",
                "any_of_templates": ["condition", "condition_group"]
            }
        }
    }
}