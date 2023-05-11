from enums import gate_types, state_node_types

RESERVED_KEYWORDS = ["root", "keys", "values", "ERROR"]

root_object = {
    "type": "object",
    "properties": {
        "standard": {"type": "string"},
        "parties": {"type": "array", "values": {"type": "object", "template": "party"}},
        "node_definitions": {
            "type": "object",
            "keys": {
                "type": "string",
            },
            "values": {
                "type": "object",
                "template": "node_definition",
            },
        },
        "state_nodes": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "state_node",
            },
            "unique": ["meta.id"],
        },
        "referenced_dependency_sets": {
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
                "values": [
                    "STRING",
                    "NUMERIC",
                    "BOOLEAN",
                    "STRING_LIST",
                    "NUMERIC_LIST",
                    "EDGE",
                    "EDGE_COLLECTION",
                ],
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
                                "from": "root.node_definitions",
                                "property": "keys",
                            },
                        },
                    },
                },
            },
        ],
    },
}

dependency_set_reference = {
    "type": "object",
    "properties": {
        "alias": {
            "type": "reference",
            "references_any": {
                "from": "root.referenced_dependency_sets",
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
                "from": "root.state_nodes",
                "property": "meta.id",
            },
        },
        "field_name": {
            "type": "reference",
            "references_any": {
                "from": "root.node_definitions.{$tag}",
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
                "MATCHES_REGEX",
                "DOES_NOT_MATCH_REGEX",
                "CONTAINS",
                "DOES_NOT_CONTAIN",
                "ANY_OF",
                "NONE_OF",
                "ONE_OF",
                "ALL_OF",
            ],
        },
        "comparison_value_type": {
            "type": "reference",
            "referenced_value": "root.node_definitions.{$tag}.{field_name}.field_type",
        },
        "string_comparison_value": {"type": "string"},
        "numeric_comparison_value": {"type": "decimal"},
        "boolean_comparison_value": {"type": "boolean"},
        "string_list_comparison_value": {
            "type": "array",
            "values": {"type": "string"},
        },
        "numeric_list_comparison_value": {
            "type": "array",
            "values": {"type": "decimal"},
        },
    },
    "resolvers": {
        "$tag": {
            "from": "root.state_nodes",
            "where": {
                "property": "meta.id",
                "operator": "EQUALS",
                "value": {"from": "{this}", "extract": "node_id"},
            },
            "extract": "meta.tag",
        },
    },
    "switch": {
        "property": "comparison_value_type",
        "cases": [
            {
                "equals": "STRING",
                "then": {
                    "optional": [
                        "numeric_comparison_value",
                        "boolean_comparison_value",
                        "string_list_comparison_value",
                        "numeric_list_comparison_value",
                    ],
                    "property_modifiers": {
                        "comparison_operator": {
                            "type": "enum",
                            "values": [
                                "EQUALS",
                                "DOES_NOT_EQUAL",
                                "MATCHES_REGEX",
                                "DOES_NOT_MATCH_REGEX",
                                "CONTAINS",
                                "DOES_NOT_CONTAIN",
                            ],
                        },
                    },
                },
                "break": True,
            },
            {
                "equals": "NUMERIC",
                "then": {
                    "optional": [
                        "string_comparison_value",
                        "boolean_comparison_value",
                        "string_list_comparison_value",
                        "numeric_list_comparison_value",
                    ],
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
                            ],
                        },
                    },
                },
                "break": True,
            },
            {
                "equals": "BOOLEAN",
                "then": {
                    "optional": [
                        "string_comparison_value",
                        "numeric_comparison_value",
                        "string_list_comparison_value",
                        "numeric_list_comparison_value",
                    ],
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
                    "optional": [
                        "string_comparison_value",
                        "numeric_comparison_value",
                        "boolean_comparison_value",
                        "numeric_list_comparison_value",
                    ],
                    "property_modifiers": {
                        "comparison_operator": {
                            "type": "enum",
                            "values": [
                                "EQUALS",
                                "DOES_NOT_EQUAL",
                                "ANY_OF",
                                "NONE_OF",
                                "ONE_OF",
                                "ALL_OF",
                            ],
                        },
                    },
                },
                "break": True,
            },
            {
                "equals": "NUMERIC_LIST",
                "then": {
                    "optional": [
                        "string_comparison_value",
                        "numeric_comparison_value",
                        "boolean_comparison_value",
                        "string_list_comparison_value",
                    ],
                    "property_modifiers": {
                        "comparison_operator": {
                            "type": "enum",
                            "values": [
                                "EQUALS",
                                "DOES_NOT_EQUAL",
                                "ANY_OF",
                                "NONE_OF",
                                "ONE_OF",
                                "ALL_OF",
                            ],
                        },
                    },
                },
                "break": True,
            },
        ],
    },
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
                "any_of_templates": ["dependency", "dependency_set_reference"],
            },
            "min_length": 1,
        },
    },
    "if": [
        {
            "property": "dependencies",
            "attribute": "length",
            "operator": "LESS_THAN_OR_EQUAL_TO",
            "value": 1,
            "then": {"optional": ["alias", "gate_type"]},
        }
    ],
}

state_node = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "tag": {"type": "string"},
                "description": {"type": "string"},
                "node_type": {"type": "enum", "values": state_node_types},
                "applies_to": {
                    "type": "reference",
                    "references_any": {
                        "from": "root.parties",
                        "property": "name",
                    },
                },
            },
        },
        "depends_on": {
            "type": "object",
            "template": "dependency_set",
        },
    },
    "optional": ["depends_on"],
}

party = {"type": "object", "properties": {"name": {"type": "string"}}}
