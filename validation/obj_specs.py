from enums import gate_types, field_types, milestones, comparison_operators
from validation import patterns

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
        "terms": {
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
            "values": {"type": "object", "obj_spec_name": "party"},
            "constraints": {
                "unique": ["id", "name"],
            },
        },
        "object_types": {
            "type": "object",
            "keys": {
                "type": "string",
            },
            "values": {
                "type": "object",
                "obj_spec_name": "object_type",
            },
        },
        "object_promises": {
            "type": "array",
            "values": {
                "type": "object",
                "obj_spec_name": "object_promise",
            },
            "constraints": {
                "unique": ["id", "name"],
            },
        },
        "pipelines": {
            "type": "array",
            "values": {
                "type": "object",
                "obj_spec_name": "pipeline",  # see aggregation_pipeline.py
            },
            "constraints": {
                "unique": ["object_promise"],
            },
        },
        "actions": {
            "type": "array",
            "values": {
                "type": "object",
                "obj_spec_name": "action",
            },
            "constraints": {
                "unique": ["id", "milestones"],
            },
        },
        "thread_groups": {
            "type": "array",
            "values": {
                "type": "object",
                "obj_spec_name": "thread_group",
            },
            "constraints": {
                "unique": ["id"],
            },
        },
        "checkpoints": {
            "type": "array",
            "values": {
                "type": "object",
                "obj_spec_name": "checkpoint",
            },
            "constraints": {
                "unique": ["id", "alias"],
                "unique_composites": [
                    ["gate_type", "dependencies"],
                ],
            },
        },
    },
    "constraints": {
        "optional": ["thread_groups"],
    },
    "property_validation_priority": ["thread_groups", "pipelines"],
}

object_type = {
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
                        "object_type": {
                            "type": "string",
                            "expected_value": {
                                "one_of": {
                                    "from": "root.object_types",
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

object_promise = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "object_type": {
            "type": "string",
            "expected_value": {
                "one_of": {
                    "from": "root.object_types",
                    "extract": "keys",
                },
            },
        },
    },
    "constraints": {
        "optional": ["description"],
        "validation_functions": [
            {
                "function": "validate_object_promise_fulfillment",
            },
        ],
    },
    "ref_config": {
        "fields": ["id", "name"],
        "collection": "root.object_promises",
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
            "types": [
                {
                    "type": "ref",
                    "ref_types": ["action"],
                },
                {
                    "type": "string",
                    "pattern": patterns.variable,
                    "pattern_description": "variable name"
                },
            ],
        },
        "context": {
            "type": "enum",
            "values": ["RUNTIME"],
        },
    },
    "constraints": {
        "optional": ["context"],
    },
}

literal_operand = {
    "type": "object",
    "properties": {
        "value": {"type": "scalar"},
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
                    "any_of_specs": ["literal_operand", "referenced_operand"],
                },
                "right": {
                    "type": "object",
                    "any_of_specs": ["literal_operand", "referenced_operand"],
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
                    {
                        "function": "validate_does_not_depend_on_aggregated_field",
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
        "alias": {"type": "string", "pattern": patterns.alias, "pattern_description": "checkpoint alias"},
        "description": {"type": "string"},
        "abbreviated_description": {"type": "string"},
        "supporting_info": {"type": "array", "values": {"type": "string"}},
        "gate_type": {"type": "enum", "values": gate_types},
        "dependencies": {
            "type": "array",
            "values": {
                "type": "object",
                "any_of_specs": ["dependency", "checkpoint_reference"],
            },
        },
        "context": {
            "type": "ref",
            "ref_types": ["thread_group"],
        },
    },
    "constraints": {
        "optional": ["abbreviated_description", "supporting_info", "context"],
        "validation_functions": [
            {
                "function": "validate_is_referenced",
                "args": ["alias", "checkpoints"],
            },
            {
                "function": "validate_checkpoint_context"
            },
        ],
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
                            "obj_spec_name": "dependency",
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
        "context": {
            "type": "ref",
            "ref_types": ["thread_group"]
        },
        "object_promise": {
            "type": "ref",
            "ref_types": ["object_promise"],
        },
        "description": {"type": "string"},
        "party": {
            "type": "ref",
            "ref_types": ["party"],
        },
        "depends_on": {
            "type": "ref",
            "ref_types": ["checkpoint"],
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
        "operation": {
            "type": "object",
            "properties": {
                "include": {
                    "type": "array",
                    "nullable": True,
                    "values": {"type": "string"},
                },
                "exclude": {
                    "type": "array",
                    "nullable": True,
                    "values": {"type": "string"},
                },
                "default_values": {
                    "type": "object",
                    "keys": {
                        "type": "string",
                    },
                    "values": {
                        "type": "scalar",
                    },
                },
                "default_edges": {
                    "type": "object",
                    "keys": {
                        "type": "string",
                    },
                    "values": {
                        "type": "ref",
                        "ref_types": ["object_promise"],
                    },
                },
            },
            "constraints": {
                "mutually_exclusive": ["include", "exclude"],
                "optional": ["default_values", "default_edges"],
            },
        },
        "milestones": {
            "type": "array",
            "values": {"type": "enum", "values": milestones},
        },
        "supporting_info": {"type": "array", "values": {"type": "string"}},
    },
    "constraints": {
        "optional": [
            "context",
            "depends_on",
            "steps",
            "milestones",
            "supporting_info",
            "pipeline",
        ],
        "validation_functions": [
            {
                "function": "validate_action_operation",
            },
            {
                "function": "validate_dependency_scope",
            },
        ],
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
            "pattern": patterns.hex_code,
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

thread_group = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "description": {"type": "string"},
        "context": {
            "type": "ref",
            "ref_types": ["thread_group"],
        },
        "depends_on": {"type": "ref", "ref_types": ["checkpoint"]},
        "spawn": {
            "type": "object",
            "properties": {
                "from": {
                    "types": [
                        {"type": "ref", "ref_types": ["object_promise"]},
                        {
                            "type": "string",
                            "pattern": patterns.variable,
                            "pattern_description": "variable name"
                        },
                    ],
                },
                "foreach": {"type": "string"},
                "as": {
                    "type": "string",
                    "pattern": patterns.variable,
                    "pattern_description": "variable name"
                },
            },
        },
    },
    "constraints": {
        "optional": ["context", "depends_on"],
        "validation_functions": [
            {
                "function": "validate_is_referenced",
                "args": ["id", "thread_groups"],
            },
            {
                "function": "validate_dependency_scope",
            },
            {
                "function": "validate_thread_group",
            },
        ],
    },
    "ref_config": {
        "fields": ["id"],
        "collection": "root.thread_groups",
    },
}