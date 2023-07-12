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
            "values": list(field_types) + ["EDGE", "EDGE_COLLECTION"],
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
                    "ref_types": ["action", "thread"],
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
            "template": "pipeline_query",
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
}

pipeline_query = {
    "type": "object",
    "properties": {
        "gate": {
            "type": "enum",
            "values": gate_types,
        },
        "where": {
            "type": "array",
            "values": {
                "type": "object",
                "any_of_templates": ["comparison", "pipeline_query"],
            },
        },
    },
}

comparison = {
    "type": "object",
    "properties": {
        "left": {
            "types": [
                {"type": "string"},
                {
                    "type": "object",
                    "template": "contextual_ref",
                },
            ],
        },
        "operator": {
            "type": "enum",
            "values": comparison_operators,
        },
        "right": {
            "types": [
                {"type": "string"},
                {
                    "type": "object",
                    "template": "contextual_ref",
                },
            ],
        },
    },
}

contextual_ref = {
    "type": "object",
    "properties": {
        "context": {
            "type": "enum",
            "values": ["TEMPLATE", "RUNTIME"],
        },
        "ref": {"type": "string"},
    },
    "optional": ["context"],
}
