from enums import gate_types, field_types, milestones

RESERVED_KEYWORDS = ["root", "keys", "values", "ERROR"]

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
                "optional": ["attributes"],
            },
        },
        "parties": {"type": "array", "values": {"type": "object", "template": "party"}},
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
            "unique": ["id", "milestones"],
        },
        "checkpoints": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "checkpoint",
            },
            "unique": [
                "alias",
                ["gate_type", "dependencies"]
            ],
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
                "values": list(field_types) + ["EDGE", "EDGE_COLLECTION"]
            },
            "description": {"type": "string"},
        },
        "optional": ["description"],
        "if": [
            {
                "property": "field_type",
                "operator": "ONE_OF",
                "value": ["EDGE", "EDGE_COLLECTION"],
                "then": {
                    "property_modifiers": {
                        "tag": {
                            "type": "reference",
                            "references_any": {
                                "from": "root.nodes",
                                "property": "keys",
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
            "type": "reference",
            "references_any": {
                "from": "root.checkpoints",
                "property": "alias",
            },
        }
    },
}

dependency = {
    "type": "object",
    "properties": {
        "node": {
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "reference",
                    "references_any": {
                        "from": "root.actions",
                        "property": "id",
                    },
                },
                "field_name": {
                    "type": "reference",
                    "references_any": {
                        "from": "root.nodes.{$tag}",
                        "property": "keys",
                    },
                },
                "comparison_operator": {
                    "type": "enum",
                    "values": [
                        "EQUALS",
                        "DOES_NOT_EQUAL",
                        "GREATER_THAN",
                        "LESS_THAN",
                        "GREATER_THAN_OR_EQUAL_TO",
                        "LESS_THAN_OR_EQUAL_TO",
                        "ONE_OF",
                        "NONE_OF",
                        "CONTAINS",
                        "DOES_NOT_CONTAIN",
                        "CONTAINS_ANY_OF",
                        "CONTAINS_ALL_OF",
                        "CONTAINS_NONE_OF",
                    ],
                },
                "comparison_value_type": {
                    "type": "reference",
                    "referenced_value": "root.nodes.{$tag}.{field_name}.field_type",
                },
                "string_comparison_value": {"type": "string"},
                "numeric_comparison_value": {"type": "decimal"},
                "boolean_comparison_value": {"type": "boolean"},
                "string_list_comparison_value": {
                    "types": [
                        {
                            "type": "array",
                            "values": {"type": "string"},
                        },
                        {"type": "string"}
                    ]
                },
                "numeric_list_comparison_value": {
                    "types": [
                        {
                            "type": "array",
                            "values": {"type": "decimal"},
                        },
                        {"type": "decimal"}
                    ],
                },
                "description": {"type": "string"},
            },
            "optional": ["description"],
            "resolvers": {
                "$tag": {
                    "from": "root.actions",
                    "where": {
                        "property": "id",
                        "operator": "EQUALS",
                        "value": {"from": "{this}", "extract": "action_id"},
                    },
                    "extract": "tag",
                },
            },
            "switch": {
                "property": "comparison_value_type",
                "cases": [
                    {
                        "equals": "STRING",
                        "then": {
                            "forbidden": {
                                "properties": [
                                    "numeric_comparison_value",
                                    "boolean_comparison_value",
                                    "string_list_comparison_value",
                                    "numeric_list_comparison_value",
                                ],
                                "reason": "comparison_value_type is STRING"
                            },
                            "property_modifiers": {
                                "comparison_operator": {
                                    "type": "enum",
                                    "values": [
                                        "EQUALS",
                                        "DOES_NOT_EQUAL",
                                        "CONTAINS",
                                        "DOES_NOT_CONTAIN",
                                        "ONE_OF",
                                        "NONE_OF",
                                    ],
                                },
                            },
                        },
                        "break": True,
                    },
                    {
                        "equals": "NUMERIC",
                        "then": {
                            "forbidden": {
                                "properties": [
                                    "string_comparison_value",
                                    "boolean_comparison_value",
                                    "string_list_comparison_value",
                                    "numeric_list_comparison_value",
                                ],
                                "reason": "comparison_value_type is NUMERIC"
                            },
                            "property_modifiers": {
                                "comparison_operator": {
                                    "type": "enum",
                                    "values": [
                                        "EQUALS",
                                        "DOES_NOT_EQUAL",
                                        "GREATER_THAN",
                                        "LESS_THAN",
                                        "GREATER_THAN_OR_EQUAL_TO",
                                        "LESS_THAN_OR_EQUAL_TO",
                                        "ONE_OF",
                                        "NONE_OF",
                                    ],
                                },
                            },
                        },
                        "break": True,
                    },
                    {
                        "equals": "BOOLEAN",
                        "then": {
                            "forbidden": {
                                "properties": [
                                    "string_comparison_value",
                                    "numeric_comparison_value",
                                    "string_list_comparison_value",
                                    "numeric_list_comparison_value",
                                ],
                                "reason": "comparison_value_type is BOOLEAN"
                            },
                            "property_modifiers": {
                                "comparison_operator": {
                                    "type": "enum",
                                    "values": ["EQUALS"],
                                },
                            },
                        },
                        "break": True,
                    },
                    {
                        "equals": "STRING_LIST",
                        "then": {
                            "forbidden": {
                                "properties": [
                                    "string_comparison_value",
                                    "numeric_comparison_value",
                                    "boolean_comparison_value",
                                    "numeric_list_comparison_value",
                                ],
                                "reason": "comparison_value_type is STRING_LIST"
                            },
                            "add_conditionals": {
                                "if": [
                                    {
                                        "property": "string_list_comparison_value",
                                        "attribute": "type",
                                        "operator": "EQUALS",
                                        "value": "STRING",
                                        "then": {
                                            "property_modifiers": {
                                                "comparison_operator": {
                                                    "type": "enum",
                                                    "values": [
                                                        "CONTAINS",
                                                        "DOES_NOT_CONTAIN",
                                                    ],
                                                },
                                            },
                                        },
                                        "else": {
                                            "property_modifiers": {
                                                "comparison_operator": {
                                                    "type": "enum",
                                                    "values": [
                                                        "EQUALS",
                                                        "DOES_NOT_EQUAL",
                                                        "CONTAINS_ANY_OF",
                                                        "CONTAINS_ALL_OF",
                                                        "CONTAINS_NONE_OF",
                                                    ],
                                                },
                                            },
                                        }
                                    }
                                ]
                            }
                        },
                        "break": True,
                    },
                    {
                        "equals": "NUMERIC_LIST",
                        "then": {
                            "forbidden": {
                                "properties": [
                                    "string_comparison_value",
                                    "numeric_comparison_value",
                                    "boolean_comparison_value",
                                    "string_list_comparison_value",
                                ],
                                "reason": "comparison_value_type is NUMERIC_LIST",
                            },
                            "add_conditionals": {
                                "if": [
                                    {
                                        "property": "numeric_list_comparison_value",
                                        "attribute": "type",
                                        "operator": "EQUALS",
                                        "value": "NUMERIC",
                                        "then": {
                                            "property_modifiers": {
                                                "comparison_operator": {
                                                    "type": "enum",
                                                    "values": [
                                                        "CONTAINS",
                                                        "DOES_NOT_CONTAIN",
                                                    ],
                                                },
                                            },
                                        },
                                        "else": {
                                            "property_modifiers": {
                                                "comparison_operator": {
                                                    "type": "enum",
                                                    "values": [
                                                        "EQUALS",
                                                        "DOES_NOT_EQUAL",
                                                        "CONTAINS_ANY_OF",
                                                        "CONTAINS_ALL_OF",
                                                        "CONTAINS_NONE_OF",
                                                    ],
                                                },
                                            },
                                        }
                                    }
                                ]
                            }
                        },
                        "break": True,
                    },
                ],
            },
        }
    }
}

checkpoint = {
    "type": "object",
    "properties": {
        "alias": {"type": "string"},
        "description": {"type": "string"},
        "gate_type": {"type": "enum", "values": gate_types},
        "dependencies": {
            "type": "array",
            "values": {
                "type": "object",
                "any_of_templates": ["dependency", "checkpoint_reference"],
            },
            "min_length": 1,
        },
    },
    "if": [
        {
            "property": "dependencies",
            "attribute": "length",
            "operator": "LESS_THAN",
            "value": 2,
            "then": {
                "forbidden": {
                    "properties": ["gate_type"],
                    "reason": "gate_type is irrelevant when a checkpoint has fewer than 2 dependencies.",
                },
                "property_modifiers": {
                    "dependencies": {
                        "type": "array",
                        "values": {
                            "type": "object",
                            "template": "dependency",
                        },
                        "min_length": 1,
                    },
                }
            },
        },
    ],
}

action = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "tag": {"type": "string"},
        "description": {"type": "string"},
        "applies_to": {
            "type": "reference",
            "references_any": {
                "from": "root.parties",
                "property": "name",
            },
        },
        "depends_on": {
            "type": "reference",
            "references_any": {
                "from": "root.checkpoints",
                "property": "alias",
            },
        },
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
        "milestones": {
            "type": "array",
            "values": {
                "type": "enum",
                "values": milestones
            },
        },
        "supporting_info": {
            "type": "array",
            "values": {"type": "string"}
        },
    },
    "optional": ["depends_on", "steps", "milestones", "supporting_info"],
}

party = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "hex_code": {
            "type": "string",
            "pattern": "^#(?:[0-9a-fA-F]{3}){1,2}$",
            "pattern_description": "hex color code",
        },
    },
    "optional": ["hex_code"],
}
