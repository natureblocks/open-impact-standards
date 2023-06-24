from enums import gate_types, field_types, milestones, comparison_operators

RESERVED_KEYWORDS = [
    "root",
    "keys",
    "values",
    "_this",
    "_parent",
    "_item",
    "_corresponding_key",
    "ERROR",
]

root_object = {
    "type": "object",
    "properties": {
        "standard": {"type": "string"},
        "term_definitions": {
            "type": "array",
            "values": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "attributes": {
                        "type": "array",
                        "values": {
                            "type": "string",
                        },
                    },
                },
                "constraints": {
                    "optional": ["attributes"],
                },
            },
        },
        "parties": {
            "type": "array",
            "values": {"type": "object", "template": "party"},
            "constraints": {
                "unique": ["id", "name"],
            },
        },
        "nodes": {
            "type": "object",
            "keys": {
                "type": "string",
            },
            "values": {
                "type": "object",
                "template": "node_definition",
            },
        },
        "actions": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "action",
            },
            "constraints": {
                "unique": ["id", "milestones"],
            },
        },
        "checkpoints": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "checkpoint",
            },
            "constraints": {
                "unique": ["id", "alias"],
                "unique_composites": [
                    ["gate_type", "dependencies"],
                ],
            },
        },
    },
}

node_definition = {
    "type": "object",
    "keys": {
        "type": "string",
    },
    "values": {
        "type": "object",
        "properties": {
            "field_type": {
                "type": "enum",
                "values": list(field_types) + ["EDGE", "EDGE_COLLECTION"],
            },
            "description": {"type": "string"},
        },
        "constraints": {
            "optional": ["description"],
        },
        "if": [
            {
                "property": "field_type",
                "operator": "ONE_OF",
                "value": ["EDGE", "EDGE_COLLECTION"],
                "then": {
                    "add_properties": {
                        "tag": {
                            "type": "string",
                            "expected_value": {
                                "one_of": {
                                    "from": "root.nodes",
                                    "extract": "keys",
                                },
                            },
                        },
                    },
                },
            },
        ],
    },
}

checkpoint_reference = {
    "type": "object",
    "properties": {
        "checkpoint": {
            "type": "ref",
            "ref_types": ["checkpoint"],
        },
    },
}

referenced_operand = {
    "type": "object",
    "properties": {
        "ref": {
            "type": "ref",
            "ref_types": ["action"],
        },
        "field": {
            "type": "string",
            "expected_value": {
                "one_of": {
                    "from": "root.nodes.{$tag}",
                    "extract": "keys",
                },
            },
        },
    },
    "resolvers": {
        "$tag": {
            "from": "root.actions",
            "where": {
                "property": "id",
                "operator": "IS_REFERENCED_BY",
                "value": {
                    "from": "{_this}",
                    "extract": "ref",
                },
            },
            "extract": "tag",
        },
    },
}

literal_operand = {
    "type": "object",
    "properties": {
        "value": {"type": "scalar"},
    },
}

runtime_operand = {
    "type": "object",
    "properties": {
        "ref": {
            "type": "ref",
            "ref_types": ["party", "action"],
        },
        "field": {
            "type": "string",
            "expected_value": {
                "one_of": {
                    "from": "_runtime_fields",
                    "extract": "{ref}._ref_type",
                },
            },
        },
        "context": {
            "type": "enum",
            "values": ["RUNTIME"],
        },
    },
}

dependency = {
    "type": "object",
    "properties": {
        "compare": {
            "type": "object",
            "properties": {
                "left": {
                    "type": "object",
                    "any_of_templates": ["literal_operand", "referenced_operand"],
                },
                "right": {
                    "type": "object",
                    "any_of_templates": ["literal_operand", "referenced_operand"],
                },
                "operator": {
                    "type": "enum",
                    "values": comparison_operators,
                },
            },
            "constraints": {
                "validation_functions": [
                    {
                        "function": "validate_comparison",
                        "args": ["{left}", "{right}", "{operator}"],
                    },
                ],
            },
        },
        "description": {"type": "string"},
    },
    "constraints": {
        "optional": ["description"],
    },
}

checkpoint = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "alias": {"type": "string"},
        "description": {"type": "string"},
        "abbreviated_description": {"type": "string"},
        "supporting_info": {"type": "array", "values": {"type": "string"}},
        "gate_type": {"type": "enum", "values": gate_types},
        "dependencies": {
            "type": "array",
            "values": {
                "type": "object",
                "any_of_templates": ["dependency", "checkpoint_reference"],
            },
        },
    },
    "constraints": {
        "optional": ["abbreviated_description", "supporting_info"],
    },
    "if": [
        {
            "property": "dependencies",
            "attribute": "length",
            "operator": "LESS_THAN",
            "value": 2,
            "then": {
                "add_constraints": {
                    "forbidden": {
                        "properties": ["gate_type"],
                        "reason": "gate_type is irrelevant when a checkpoint has fewer than 2 dependencies.",
                    },
                },
                "override_properties": {
                    "dependencies": {
                        "type": "array",
                        "values": {
                            "type": "object",
                            "template": "dependency",
                        },
                        "constraints": {
                            "min_length": 1,
                        },
                    },
                },
            },
        },
    ],
    "ref_config": {
        "fields": ["id", "alias"],
        "collection": "root.checkpoints",
    },
}

action = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "tag": {"type": "string"},
        "description": {"type": "string"},
        "party": {
            "type": "ref",
            "ref_types": ["party"],
        },
        "depends_on": {"type": "ref", "ref_types": ["checkpoint"]},
        "steps": {
            "type": "array",
            "values": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "operation": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "enum",
                    "values": ["CREATE", "EDIT"],
                },
                "include": {
                    "type": "array",
                    "nullable": True,
                    "values": {
                        "type": "string",
                        "one_of": {
                            "from": "root.nodes.{tag}",
                            "extract": "keys",
                        },
                    },
                },
                "exclude": {
                    "type": "array",
                    "nullable": True,
                    "values": {
                        "type": "string",
                        "one_of": {
                            "from": "root.nodes.{tag}",
                            "extract": "keys",
                        },
                    },
                },
            },
            "mutually_exclusive": ["include", "exclude"],
            "if": [
                {
                    "property": "type",
                    "operator": "EQUALS",
                    "value": "CREATE",
                    "then": {
                        "add_properties": {
                            "default_values": {
                                "type": "object",
                                "keys": {
                                    "type": "string",
                                    "expected_value": {
                                        "one_of": {
                                            "from": "root.nodes.{tag}",
                                            "where": {
                                                "property": "root.nodes.{tag}.{_item}.field_type",
                                                "operator": "NOT_IN",
                                                "value": ["EDGE", "EDGE_COLLECTION"],
                                            },
                                            "extract": "keys",
                                        },
                                    },
                                },
                                "values": {
                                    "type": "root.nodes.{tag}.{_corresponding_key}.field_type",
                                },
                            },
                            "default_edges": {
                                "type": "object",
                                "keys": {
                                    "type": "string",
                                    "expected_value": {
                                        "one_of": {
                                            "from": "root.nodes.{tag}",
                                            "property": "keys",
                                            "where": {
                                                "property": "root.nodes.{tag}.{_item}.field_type",
                                                "operator": "IN",
                                                "value": ["EDGE", "EDGE_COLLECTION"],
                                            },
                                        },
                                    },
                                },
                                "values": {
                                    "type": "ref",
                                    "ref_types": ["action"],
                                },
                            },
                        },
                        "add_constraints": {
                            "optional": ["default_values", "default_edges"],
                        },
                    },
                    "else": {
                        "add_properties": {
                            "ref": {
                                "type": "ref",
                                "ref_types": ["action"],
                            },
                        },
                        "add_constraints": {
                            "validation_functions": [
                                {
                                    "function": "has_ancestor",
                                    "args": ["{_parent}.id", "{ref}", "ref"],
                                }
                            ],
                        },
                    },
                },
            ],
        },
        "milestones": {
            "type": "array",
            "values": {"type": "enum", "values": milestones},
        },
        "supporting_info": {"type": "array", "values": {"type": "string"}},
    },
    "constraints": {
        "optional": ["depends_on", "steps", "milestones", "supporting_info"],
    },
    "ref_config": {
        "fields": ["id"],
        "collection": "root.actions",
    },
}

party = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "hex_code": {
            "type": "string",
            "pattern": "^#(?:[0-9a-fA-F]{3}){1,2}$",
            "pattern_description": "hex color code",
        },
    },
    "constraints": {
        "optional": ["hex_code"],
    },
    "ref_config": {
        "fields": ["id", "name"],
        "collection": "root.parties",
    },
}
