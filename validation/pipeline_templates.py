from enums import field_types, gate_types, comparison_operators
from validation import patterns

operation_methods = [
    "ADD",
    "SUBTRACT",
    "MULTIPLY",
    "DIVIDE",
    "APPEND",
    "PREPEND",
    "CONCAT",
    "SELECT",
    "SET",
]
aggregation_operators = [
    "AVERAGE",
    "COUNT",
    "MAX",
    "MIN",
    "SUM",
    "FIRST",
    "LAST",
    "AND",
    "OR",
]

pipeline = {
    "type": "object",
    "properties": {
        "context": {
            "type": "enum",
            "values": ["TEMPLATE", "RUNTIME"],
        },
        "variables": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "variable",
            },
            "constraints": {
                "min_length": 1,
            },
        },
        "traverse": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "traverse",
            },
        },
        "apply": {
            "type": "array",
            "values": {
                "type": "object",
                "template": "apply",
            },
        },
        "output": {
            "type": "array",
            "values": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
            },
            "constraints": {
                "min_length": 1,
            }
        },
    },
    "constraints": {
        "optional": ["traverse", "apply"],
        "validation_functions": [
            {
                "function": "validate_pipeline",
            },
        ],
    },
}

variable = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "pattern": patterns.variable,
            "pattern_description": "variable name ",
        },
        "type": {
            "type": "enum",
            "values": list(field_types) + ["OBJECT", "OBJECT_LIST"],
        },
        "initial": {
            "types": [
                {"type": "scalar"},
                {
                    "type": "array",
                    "values": {"type": "scalar"},
                },
            ],
        },
    },
}

traverse = {
    "type": "object",
    "properties": {
        "ref": {
            "types": [
                {
                    "type": "ref",
                    "ref_types": ["action", "thread"],
                },
                {
                    "type": "string",
                    "pattern": patterns.local_variable,
                    "pattern_description": "local variable name ",
                },
                {
                    "type": "string",
                    "pattern": patterns.variable,
                    "pattern_description": "variable name ",
                },
            ],
        },
        "foreach": {
            "type": "object",
            "properties": {
                "as": {
                    "type": "string",
                    "pattern": patterns.variable,
                },
                "variables": {
                    "type": "array",
                    "values": {
                        "type": "object",
                        "template": "variable",
                    },
                    "constraints": {
                        "min_length": 1,
                    },
                },
                "traverse": {
                    "type": "array",
                    "values": {
                        "type": "object",
                        "template": "traverse",
                    },
                },
                "apply": {
                    "type": "array",
                    "values": {
                        "type": "object",
                        "template": "apply",
                    },
                },
            },
            "constraints": {
                "optional": ["traverse", "variables"],
                "forbidden": {
                    "properties": ["output"],
                    "reason": "pipeline traversals cannot have output -- specify pipeline.output instead",
                },
            },
        },
    },
}

apply = {
    "type": "object",
    "properties": {
        "from": {
            "types": [
                {
                    "type": "string",
                    "pattern": patterns.variable,
                    "pattern_description": "variable name ",
                },
                {
                    "type": "string",
                    "pattern": patterns.local_variable,
                    "pattern_description": "local variable ",
                },
                {
                    "type": "ref",
                    "ref_types": ["action"],
                },
            ],
        },
        "to": {
            "type": "string",
            "pattern": patterns.variable,
            "pattern_description": "variable name ",
        },
        "method": {
            "type": "enum",
            "values": operation_methods,
        },
        "aggregate": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "operator": {
                    "type": "enum",
                    "values": aggregation_operators,
                },
            },
        },
        "filter": {
            "type": "object",
            "properties": {
                "where": {
                    "type": "array",
                    "values": {
                        "type": "object",
                        "any_of_templates": ["filter_comparison", "nested_filter_query"],
                    },
                    "constraints": {
                        "min_length": 1,
                    },
                },
                "gate_type": {
                    "type": "enum",
                    "values": gate_types,
                },
            },
            "if": [
                {
                    "property": "where",
                    "attribute": "length",
                    "operator": "LESS_THAN",
                    "value": 2,
                    "then": {
                        "add_constraints": {
                            "forbidden": {
                                "properties": ["gate_type"],
                                "reason": "gate_type is irrelevant when a query has fewer than 2 comparisons.",
                            },
                        },
                    },
                },
            ],
        },
        "sort": {
            "type": "array",
            "values": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "order": {
                        "type": "enum",
                        "values": ["ASC", "DESC"],
                    },
                },
            },
        },
        "select": {"type": "string"},
    },
    "mutually_exclusive": ["aggregate", "filter", "sort", "select"],
    "property_validation_priority": ["from"],
}

nested_filter_query = {
    "type": "object",
    "properties": {
        "where": {
            "type": "array",
            "values": {
                "type": "object",
                "any_of_templates": ["filter_comparison", "nested_filter_query"],
            },
            "constraints": {
                "min_length": 2,
            },
        },
        "gate_type": {
            "type": "enum",
            "values": gate_types,
        },
    },
}

filter_comparison = {
    "type": "object",
    "properties": {
        "left": {
            "types": [
                {
                    "type": "ref",
                    "ref_types": ["filter_ref"],
                },
                {
                    "type": "object",
                    "template": "contextual_ref",
                },
                {"type": "scalar"},
            ],
        },
        "operator": {
            "type": "enum",
            "values": comparison_operators,
        },
        "right": {
            "types": [
                {
                    "type": "ref",
                    "ref_types": ["filter_ref"],
                },
                {
                    "type": "object",
                    "template": "contextual_ref",
                },
                {"type": "scalar"},
            ],
        },
    },
    "if": [
        {
            "conditions": [
                {
                    "property": "left",
                    "operator": "DOES_NOT_CONTAIN_KEY",
                    "value": "ref",
                },
                {
                    "property": "left.ref",
                    "operator": "DOES_NOT_MATCH_PATTERN",
                    "value": patterns.filter_ref,
                }
            ],
            "gate_type": "OR",
            "then": {
                "override_properties": {
                    "right": {
                        "type": "object",
                        "properties": {
                            "ref": {
                                "type": "ref",
                                "ref_types": ["filter_ref"],
                            }
                        },
                        "error_replacements": [
                            {
                                "pattern": "expected object, got ",
                                "replace_with": '"left" and/or "right" must reference the filter variable ("$_item")'
                            },
                        ],
                    },
                },
            },
        },
        {
            "conditions": [
                {
                    "property": "right",
                    "operator": "DOES_NOT_CONTAIN_KEY",
                    "value": "ref",
                },
                {
                    "property": "right.ref",
                    "operator": "DOES_NOT_MATCH_PATTERN",
                    "value": patterns.filter_ref,
                },
            ],
            "gate_type": "OR",
            "then": {
                "override_properties": {
                    "left": {
                        "type": "object",
                        "properties": {
                            "ref": {
                                "type": "ref",
                                "ref_types": ["filter_ref"],
                            }
                        },
                        "error_replacements": [
                            {
                                "pattern": "expected object, got ",
                                "replace_with": '"left" and/or "right" must reference the filter variable ("$_item")'
                            },
                        ],
                    },
                },
            },
        },
    ],
}

contextual_ref = {
    "type": "object",
    "properties": {
        "context": {
            "type": "enum",
            "values": ["TEMPLATE", "RUNTIME"],
        },
        "ref": {
            "types": [
                {
                    "type": "ref",
                    "ref_types": ["action"], #TODO: add other ref types after runtime variables have been determined
                },
                {
                    "type": "string",
                    "pattern": patterns.local_variable,
                    "pattern_description": "local variable name ",
                },
                {
                    "type": "string",
                    "pattern": patterns.variable,
                    "pattern_description": "variable name ",
                },
            ],
        },
    },
    "constraints": {
        "optional": ["context"],
    },
}
