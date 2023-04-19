from enums import gate_types, node_types

RESERVED_KEYWORDS = ["root", "keys", "values"]

root_object = {
    "type": "object",
    "properties": {
        "standard": {"type": "string"},
        "parties": {"type": "array", "values": {"type": "object", "template": "party"}},
        "nodes": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "node",
            },
            "unique": ["meta.id"],
        },
        "recurring_dependencies": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "dependency_set",
                "template_modifiers": {
                    "dependency_set": {"dependencies": {"min_length": 2}},
                },
            },
            "unique": ["alias"],
        },
    },
}

dependency_set_reference = {
    "type": "object",
    "properties": {
        "alias": {
            "type": "reference",
            "references_any": {
                "from": "root.recurring_dependencies",
                "property": "alias",
            },
        }
    },
}

dependency = {
    "type": "object",
    "properties": {
        "node_id": {
            "type": "reference",
            "references_any": {
                "from": "root.nodes",
                "property": "meta.id",
            },
        },
        "property": {
            "type": "reference",
            "references_any": {
                "from": "root.nodes",
                "property": "data.keys",
            },
        },
        "equals": {"types": ["string", "decimal", "boolean"]},
        "does_not_equal": {"types": ["string", "decimal", "boolean"]},
        "greater_than": {"types": ["string", "decimal", "boolean"]},
        "less_than": {"types": ["string", "decimal", "boolean"]},
        "greater_than_or_equal_to": {"types": ["string", "decimal", "boolean"]},
        "less_than_or_equal_to": {"types": ["string", "decimal", "boolean"]},
        "matches_regex": {"type": "string"},
        "does_not_match_regex": {"type": "string"},
        "contains": {"types": ["string", "decimal", "boolean"]},
        "does_not_contain": {"types": ["string", "decimal", "boolean"]},
        "any_of": {
            "type": "array",
            "values": {"types": ["string", "decimal", "boolean"]},
        },
        "none_of": {
            "type": "array",
            "values": {"types": ["string", "decimal", "boolean"]},
        },
        "one_of": {
            "type": "array",
            "values": {"types": ["string", "decimal", "boolean"]},
        },
        "all_of": {
            "type": "array",
            "values": {"types": ["string", "decimal", "boolean"]},
        },
    },
    "mutually_exclusive": [
        "equals",
        "does_not_equal",
        "greater_than",
        "less_than",
        "greater_than_or_equal_to",
        "less_than_or_equal_to",
        "matches_regex",
        "does_not_match_regex",
        "contains",
        "does_not_contain",
        "any_of",
        "none_of",
        "one_of",
        "all_of",
    ],
}

dependency_set = {
    "type": "object",
    "properties": {
        "alias": {"type": "string"},
        "gate_type": {"type": "enum", "values": gate_types},
        "dependencies": {
            "type": "array",
            "values": {
                "type": "object",
                "templates": ["dependency", "dependency_set_reference"],
            },
            "min_length": 1,
        },
    },
    "if": [
        {
            "property": "dependencies",
            "attribute": "length",
            "less_than_or_equal_to": 1,
            "then": {"optional": ["alias", "gate_type"]},
        }
    ],
}

field = {
    "type": "object",
    "properties": {
        "field_type": {"type": "enum", "values": ["STRING", "NUMERIC", "BOOLEAN"]},
        "description": {"type": "string"},
    },
    "optional": ["description"],
}

node = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "description": {"type": "string"},
                "node_type": {"type": "enum", "values": node_types},
                "applies_to": {
                    "type": "reference",
                    "references_any": {
                        "from": "root.parties",
                        "property": "name",
                    },
                }
            },
        },
        "data": {
            "type": "object",
            "keys": {
                "type": "string",
            },
            "values": {
                "type": "object",
                "template": "field",
            },
            "optional": ["string_fields", "numeric_fields", "boolean_fields"],
        },
        "depends_on": {
            "type": "object",
            "template": "dependency_set",
        },
    },
    "optional": ["data", "depends_on"],
}

party = {"type": "object", "properties": {"name": {"type": "string"}}}
