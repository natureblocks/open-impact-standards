import json

import pytest
from validation.schema_validator import SchemaValidator
from tests import fixtures
from enums import valid_list_item_types


class TestAggregationPipeline:
    def test_depends_on_aggregated_field(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(6)

        # TODO: determine the valid use-cases for a pipeline that aggregates local fields

        # aggregate from a list (non-threaded)
        schema["actions"][1]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$all_numbers",
                    "type": "NUMERIC_LIST",
                    "initial": [],
                },
                {
                    "name": "$average",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "traverse": [
                {
                    "ref": "action:{0}.object.numbers",
                    "foreach": {
                        "as": "$num",
                        "apply": [
                            {
                                "from": "$num",
                                "method": "APPEND",
                                "to": "$all_numbers",
                            },
                        ],
                    },
                },
            ],
            "apply": [
                {
                    "from": "$all_numbers",
                    "aggregate": {
                        "field": "$_item",
                        "operator": "AVERAGE",
                    },
                    "method": "ADD",
                    "to": "$average",
                },
            ],
            "output": [
                {
                    "from": "$average",
                    "to": "number",
                },
            ],
        }
        depends_on_1 = fixtures.checkpoint(
            id=0, alias="depends-on-1", num_dependencies=1
        )
        depends_on_1["dependencies"][0]["compare"] = {
            "left": {
                "ref": "action:{1}",
                "field": "number",
            },
            "operator": "GREATER_THAN",
            "right": {
                "value": 5,
            },
        }
        schema["checkpoints"] = [depends_on_1]
        schema["actions"][2]["depends_on"] = "checkpoint:{depends-on-1}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors
        del schema["actions"][2]["depends_on"]
        del schema["checkpoints"][0]

        # from outside the thread, aggregate something from a threaded action
        schema["checkpoints"].append(
            fixtures.checkpoint(id=1, alias="depends-on-0", num_dependencies=1)
        )
        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
        ]
        schema["actions"][1]["context"] = "thread:{0}"
        schema["actions"][2]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$all_numbers",
                    "type": "NUMERIC_LIST",
                    "initial": [],
                },
                {
                    "name": "$average",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "traverse": [
                {
                    "ref": "action:{1}.object",
                    "foreach": {
                        "as": "$object",
                        "apply": [
                            {
                                "from": "$object.number",
                                "method": "APPEND",
                                "to": "$all_numbers",
                            },
                        ],
                    },
                },
            ],
            "apply": [
                {
                    "from": "$all_numbers",
                    "aggregate": {
                        "field": "$_item",
                        "operator": "AVERAGE",
                    },
                    "method": "ADD",
                    "to": "$average",
                },
            ],
            "output": [
                {
                    "from": "$average",
                    "to": "number",
                },
            ],
        }
        depends_on_2 = fixtures.checkpoint(
            id=2, alias="depends-on-2", num_dependencies=1
        )
        depends_on_2["dependencies"][0]["compare"] = {
            "left": {
                "ref": "action:{2}",
                "field": "number",
            },
            "operator": "LESS_THAN",
            "right": {
                "value": 10,
            },
        }
        schema["checkpoints"].append(depends_on_2)
        schema["actions"][3]["depends_on"] = "checkpoint:{depends-on-2}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # from inside the thread, aggregate something from a threaded action
        schema["actions"][4]["context"] = "thread:{0}"
        schema["actions"][4]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$edges_by_number",
                    "type": "OBJECT_LIST",
                    "initial": None,
                },
                {
                    "name": "$first_edge",
                    "type": "OBJECT",
                    "initial": None,
                },
            ],
            "apply": [
                {
                    "from": "action:{3}.object.objects",
                    "sort": [
                        {
                            "field": "number",
                            "order": "DESC",
                        }
                    ],
                    "method": "SET",
                    "to": "$edges_by_number",
                },
                {
                    "from": "$edges_by_number",
                    "aggregate": {
                        "field": "$_item",
                        "operator": "FIRST",
                    },
                    "method": "SET",
                    "to": "$first_edge",
                },
            ],
            "output": [
                {
                    "from": "$first_edge",
                    "to": "edge",
                },
            ],
        }
        depends_on_4 = fixtures.checkpoint(
            id=3, alias="depends-on-4", num_dependencies=1
        )
        depends_on_4["dependencies"][0]["compare"] = {
            "left": {
                "ref": "action:{4}.edge",
                "field": "name",
            },
            "operator": "EQUALS",
            "right": {
                "value": "David Michaeloff",
            },
        }
        schema["checkpoints"].append(depends_on_4)
        schema["actions"][5]["context"] = "thread:{0}"
        schema["actions"][5]["depends_on"] = "checkpoint:{depends-on-4}"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_traverse(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(3)
        schema["actions"][1]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "traverse": [
                {
                    "ref": None,
                    "foreach": {
                        "as": "$edge",
                        "variables": [
                            {
                                "name": "$average",
                                "type": "NUMERIC",
                                "initial": 0,
                            },
                        ],
                        "apply": [
                            {
                                "from": "$edge",
                                "method": "ADD",
                                "to": "$average",
                                "aggregate": {
                                    "field": "numbers",
                                    "operator": "AVERAGE",
                                },
                            },
                        ],
                    },
                },
            ],
            "output": [
                {
                    "from": "$some_var",
                    "to": "number",
                }
            ],
        }

        def set_pipeline_value(key1, key2, val):
            if not len(schema["actions"][1]["pipeline"][key1]):
                schema["actions"][1]["pipeline"][key1].append({})

            schema["actions"][1]["pipeline"][key1][0][key2] = val

        schema["checkpoints"] = [
            fixtures.checkpoint(id=0, alias="depends-on-0", num_dependencies=1),
        ]
        schema["actions"][1]["depends_on"] = "checkpoint:{depends-on-0}"

        # should be able to traverse an edge collection
        set_pipeline_value("traverse", "ref", "action:{0}.object.objects")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # foreach.as cannot be explicitly assigned a value
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["variables"].append(
            {
                "name": "$an_object",
                "type": "EDGE",
                "initial": None,
            }
        )
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["apply"].append(
            {
                "from": "$an_object",
                "method": "SET",
                "to": "$edge",  # loop variable
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].pipeline.traverse[0].foreach.apply[1].to (action id: 1): cannot assign to loop variable: "$edge"'
            in errors
        )

        # should be able to traverse threads...
        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
        ]
        schema["actions"][2]["context"] = "thread:{0}"  # action:{2} is now threaded
        set_pipeline_value("variables", "name", "$average_minimums")
        set_pipeline_value("variables", "type", "NUMERIC_LIST")
        set_pipeline_value("variables", "initial", [])
        set_pipeline_value(
            "traverse", "ref", "action:{2}"
        )  # traversing the threaded action
        set_pipeline_value(
            "traverse",
            "foreach",
            {
                "as": "$action",
                "variables": [
                    {
                        "name": "$minimums",
                        "type": "NUMERIC_LIST",
                        "initial": [],
                    },
                ],
                "traverse": [  # nested traversal
                    {
                        "ref": "$action.object.objects",
                        "foreach": {
                            "as": "$edge",
                            "apply": [
                                {
                                    "from": "$edge.numbers",
                                    "aggregate": {
                                        "field": "$_item",
                                        "operator": "MIN",
                                    },
                                    "method": "APPEND",
                                    "to": "$minimums",
                                },
                            ],
                        },
                    },
                ],
                "apply": [
                    {
                        "from": "$minimums",
                        "aggregate": {
                            "field": "$_item",
                            "operator": "AVERAGE",
                        },
                        "method": "APPEND",
                        "to": "$average_minimums",
                    }
                ],
            },
        )
        set_pipeline_value("output", "from", "$average_minimums")
        set_pipeline_value("output", "to", "numbers")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # "ref" properties of sibling traversal objects must be unique
        assert schema["actions"][1]["pipeline"]["traverse"][0]["ref"] == "action:{2}"
        schema["actions"][1]["pipeline"]["traverse"].append(
            {
                "ref": "action:{2}",
                "foreach": {
                    "as": "$edge",
                    "apply": [],
                },
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].pipeline.traverse (action id: 1): sibling "traverse" objects cannot specify the same "ref"'
            in errors
        )

        schema["actions"][1]["pipeline"]["traverse"].pop()

        # the same is true for nested traversal objects
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["traverse"].append(
            {
                "ref": "$action.object.objects",
                "foreach": {
                    "as": "$edge",
                    "apply": [],
                },
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].pipeline.traverse[0].foreach.traverse (action id: 1): sibling "traverse" objects cannot specify the same "ref"'
            in errors
        )

        # should not be able to traverse non-threaded actions
        set_pipeline_value("traverse", "ref", "action:{0}")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[1].pipeline.traverse[0].ref (action id: 1): cannot traverse non-list object"
            in errors
        )

    def test_variable_is_used(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)

        # unused varaibles should throw a warning
        schema["actions"][1]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$total",
                    "type": "NUMERIC",
                    "initial": 0,
                },
                {
                    "name": "$names",
                    "type": "STRING_LIST",
                    "initial": [],
                },
            ],
            "apply": [
                {
                    "from": "$_object",
                    "aggregate": {
                        "field": "numbers",
                        "operator": "SUM",
                    },
                    "method": "ADD",
                    "to": "$total",
                },
            ],
            "output": [
                {
                    "from": "$total",
                    "to": "number",
                },
            ],
        }
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].pipeline (action id: 1): variable declared but not used: "$names"'
            in validator.warnings
        )

        # if a variable from a parent scope is used in a nested traversal scope,
        # there should be no warning
        schema["actions"][1]["pipeline"]["traverse"] = [
            {
                "ref": "$_object.objects",
                "foreach": {
                    "as": "$edge",
                    "apply": [
                        {
                            "from": "$edge",
                            "select": "name",
                            "method": "APPEND",
                            "to": "$names",
                        },
                    ],
                },
            },
        ]
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings

        # if a traversal loop variable is not used, throw a warning
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["apply"][0][
            "from"
        ] = "action:{0}.object"
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].pipeline (action id: 1): loop variable declared but not used: "$edge"'
            in validator.warnings
        )

        # loop variables can be used in nested traversal scopes
        # traveral "ref" counts as a use
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["traverse"] = [
            {
                "ref": "$edge.objects",
                "foreach": {
                    "as": "$nested_edge",
                    "apply": [
                        {
                            "from": "$nested_edge",
                            "select": "name",
                            "method": "APPEND",
                            "to": "$names",
                        },
                    ],
                },
            },
        ]
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings

        # unused varables in traversal scopes should throw warnings
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["variables"] = [
            {
                "name": "$average",
                "type": "NUMERIC",
                "initial": 0,
            }
        ]
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[1].pipeline (action id: 1): variable declared but not used: "$average"'
            in validator.warnings
        )

        # As long as the variable is assigned a value somewhere, there should be no warning.
        # Note that as it stands, validation doesn't care whether a variable contributes to an output.
        schema["actions"][1]["pipeline"]["traverse"][0]["foreach"]["apply"].append(
            {
                "from": "$edge",
                "method": "ADD",
                "to": "$average",
                "aggregate": {
                    "field": "numbers",
                    "operator": "AVERAGE",
                },
            },
        )
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings

    def test_variable_scope(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
                {
                    "name": "$another_var",
                    "type": "NUMERIC_LIST",
                    "initial": [9],
                },
            ],
            "traverse": [
                {
                    "ref": "$_object.objects",
                    "foreach": {
                        "as": "$edge",
                        "variables": [
                            {
                                "name": "$average",
                                "type": "NUMERIC",
                                "initial": 0,
                            },
                        ],
                        "apply": [
                            {
                                "from": "$edge",
                                "method": "ADD",
                                "to": "$average",
                                "aggregate": {
                                    "field": "numbers",
                                    "operator": "AVERAGE",
                                },
                            },
                        ],
                    },
                },
            ],
            "apply": [
                {
                    "from": None,
                    "method": "ADD",
                    "to": "$some_var",
                },
            ],
            "output": [
                {
                    "from": "$another_var",
                    "to": "numbers",
                }
            ],
        }

        def set_pipeline_value(key1, key2, val):
            schema["actions"][0]["pipeline"][key1][0][key2] = val

        # should not be able to reference variables out of scope
        set_pipeline_value("apply", "from", "$average")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[0].from (action id: 0): variable not found in pipeline scope: "$average"'
            in errors
        )

        # assigning from a variable that has not yet been assigned a value should throw a warning
        set_pipeline_value("apply", "from", "$some_var")
        set_pipeline_value("apply", "to", "$another_var")
        set_pipeline_value("apply", "method", "APPEND")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors
        assert (
            'root.actions[0].pipeline.apply[0].from (action id: 0): variable used before assignment: "$some_var"'
            in validator.warnings
        )

        schema["actions"][0]["pipeline"]["apply"].insert(
            0,
            {
                "from": "$_object.number",
                "to": "$some_var",
                "method": "ADD",
            },
        )

        # should not be able to assign to variables out of scope
        set_pipeline_value("apply", "to", "$average")
        set_pipeline_value("apply", "method", "ADD")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[0].to (action id: 0): pipeline variable not found in scope: "$average"'
            in errors
        )

    def test_variable_name_collision(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(2)

        # should not be able to declare variables with the same name
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
                {
                    "name": "$some_var",
                    "type": "STRING",
                    "initial": "",
                },
            ],
            "apply": [],
            "output": [
                {
                    "from": "$some_var",
                    "to": "number",
                }
            ],
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.variables[1].name (action id: 0): variable already defined: "$some_var"'
            in errors
        )

        # should not be able to use an already-declared variable name in a nested scope
        schema["actions"][0]["pipeline"]["variables"] = [
            {
                "name": "$some_var",
                "type": "NUMERIC",
                "initial": 0,
            },
        ]
        schema["actions"][0]["pipeline"]["traverse"] = [
            {
                "ref": "$_object.objects",
                "foreach": {
                    "as": "$edge",
                    "variables": [
                        {
                            "name": "$some_var",
                            "type": "NUMERIC",
                            "initial": 0,
                        },
                    ],
                    "apply": [],
                },
            },
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.traverse[0].foreach.variables[0].name (action id: 0): variable already defined: $some_var"
            in errors
        )

        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["variables"][0][
            "name"
        ] = "$another_var"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # loop variable name cannot collide with...

        # ...variable name from parent scope
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["as"] = "$some_var"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.traverse[0].foreach.as (action id: 0): variable already defined within pipeline scope: $some_var"
            in errors
        )

        # ...variable name from same scope
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"][
            "as"
        ] = "$another_var"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.traverse[0].foreach.variables[0].name (action id: 0): variable already defined: $another_var"
            in errors
        )

        # ...nested loop variable name
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["as"] = "$loop_var"
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["traverse"] = [
            {
                "ref": "$loop_var.numbers",
                "foreach": {
                    "as": "$loop_var",
                    "variables": [],
                    "apply": [],
                },
            },
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.traverse[0].foreach.traverse[0].foreach.as (action id: 0): variable already defined within pipeline scope: $loop_var"
            in errors
        )

        # should be able to use the same variable name in different scopes (e.g. sibling "traverse" objects)
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["traverse"] = [
            {
                "ref": "$loop_var.numbers",
                "foreach": {
                    "as": "$nested_loop_var",
                    "variables": [
                        {
                            "name": "$a_nested_var",
                            "type": "NUMERIC",
                            "initial": 0,
                        },
                    ],
                    "apply": [],
                },
            },
            {
                "ref": "$loop_var.objects",
                "foreach": {
                    "as": "$nested_loop_var",
                    "variables": [
                        {
                            "name": "$a_nested_var",
                            "type": "NUMERIC",
                            "initial": 0,
                        },
                    ],
                    "apply": [],
                },
            },
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # pipeline variables cannot conflict with thread variable names in the same scope

        depends_on_1 = fixtures.checkpoint(
            id=0, alias="depends-on-1", num_dependencies=1
        )
        depends_on_1["dependencies"][0]["compare"]["left"]["ref"] = "action:{1}"
        schema["checkpoints"].append(depends_on_1)
        schema["threads"] = [
            fixtures.thread(0, "depends-on-1"),
        ]
        schema["threads"][0]["spawn"]["from"] = "action:{1}.object"
        schema["actions"][0]["context"] = "thread:{0}"
        schema["threads"][0]["spawn"]["as"] = "$thread_var"

        schema["actions"][0]["pipeline"]["variables"].append(
            {
                "name": "$thread_var",
                "type": "NUMERIC",
                "initial": 0,
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.variables[1].name (action id: 0): variable already defined within thread scope: "$thread_var"'
            in errors
        )

        schema["actions"][0]["pipeline"]["variables"].pop()

        # same for pipeline loop variables
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["as"] = "$thread_var"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.traverse[0].foreach.as (action id: 0): variable already defined within thread scope: $thread_var"
            in errors
        )

        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["as"] = "$loop_var"

        # should be able to reuse a thread variable name in the
        # pipeline of an action that is outside of the thread scope.
        schema["actions"][1]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$thread_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "apply": [],
            "output": [
                {
                    "from": "$thread_var",
                    "to": "number",
                }
            ],
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_filter(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)

        def set_filter_value(key, val):
            schema["actions"][0]["pipeline"]["apply"][0]["filter"]["where"][0][
                key
            ] = val

        # simple filter
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$object_list",
                    "type": "OBJECT_LIST",
                    "initial": [],
                },
                {
                    "name": "$numbers_above_tree_fiddy",
                    "type": "NUMERIC_LIST",
                    "initial": [],
                },
                {
                    "name": "$some_number",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "apply": [
                {
                    "from": "$_object.objects",
                    "filter": {
                        "where": [
                            {
                                "left": {
                                    "ref": "$_item.number",
                                },
                                "operator": "GREATER_THAN",
                                "right": 3.50,
                            },
                        ],
                    },
                    "method": "CONCAT",
                    "to": "$object_list",
                },
                {
                    "from": "$object_list",
                    "select": "number",
                    "method": "CONCAT",
                    "to": "$numbers_above_tree_fiddy",
                },
            ],
            "output": [
                {
                    "from": "$numbers_above_tree_fiddy",
                    "to": "numbers",
                },
            ],
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # the filter reference can be the left or right operand
        set_filter_value("left", 3.50)
        set_filter_value("operator", "LESS_THAN")
        set_filter_value("right", {"ref": "$_item.number"})
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # one of the operands must be a filter variable
        non_filter_variables = [
            {"ref": "$_object.number"},
            {"ref": "action:{0}.object.number"},
            {"ref": "$some_number"},
            4,
        ]
        for var in non_filter_variables:
            set_filter_value("right", var)
            errors = validator.validate(json_string=json.dumps(schema))
            assert (
                'root.actions[0].pipeline.apply[0].filter.where[0].left (action id: 0): "left" and/or "right" must reference the filter variable ("$_item")'
                in errors
            )

        # both operands can be a filter variable
        set_filter_value("left", {"ref": "$_item.number"})
        set_filter_value("operator", "LESS_THAN_OR_EQUAL_TO")
        set_filter_value("right", {"ref": "$_item.edge.number"})
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # operator must be compatible with the operand types
        set_filter_value("operator", "CONTAINS")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.apply[0] (action id: 0): invalid comparison: NUMERIC CONTAINS NUMERIC"
            in errors
        )

        set_filter_value("left", {"ref": "$_item.edge.numbers"})
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # gate_type is forbidden for single conditions
        schema["actions"][0]["pipeline"]["apply"][0]["filter"]["gate_type"] = "AND"
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.apply[0].filter (action id: 0): forbidden property specified: gate_type; reason: gate_type is irrelevant when a query has fewer than 2 comparisons."
            in errors
        )

        # gate_type is required when there is more than one filter condition
        del schema["actions"][0]["pipeline"]["apply"][0]["filter"]["gate_type"]
        schema["actions"][0]["pipeline"]["apply"][0]["filter"]["where"].append(
            {
                "left": {
                    "ref": "$_item.name",
                },
                "operator": "CONTAINS",
                "right": "some string",
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.apply[0].filter (action id: 0): missing required property: gate_type"
            in errors
        )

        schema["actions"][0]["pipeline"]["apply"][0]["filter"]["gate_type"] = "AND"
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # complex gate combinations are allowed
        schema["actions"][0]["pipeline"]["apply"][0]["filter"]["where"].append(
            {
                "where": [
                    {
                        "left": {
                            "ref": "$_item.completed",
                        },
                        "operator": "EQUALS",
                        "right": True,
                    },
                    {
                        "left": {
                            "ref": "$_item.edge.numbers",
                        },
                        "operator": "DOES_NOT_CONTAIN",
                        "right": "$_item.number",
                    },
                ],
                "gate_type": "OR",
            },
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # nested condition groups must specify at least two conditions
        schema["actions"][0]["pipeline"]["apply"][0]["filter"]["where"][2][
            "where"
        ].pop()
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            "root.actions[0].pipeline.apply[0].filter.where[2].where (action id: 0): must contain at least 2 item(s), got 1"
            in errors
        )

        # should be able to nest condition groups to arbitrary depths
        schema["actions"][0]["pipeline"]["apply"][0]["filter"]["where"][2][
            "where"
        ].append(
            {
                "where": [
                    {
                        "left": {
                            "ref": "$_item.edge.edge.completed",
                        },
                        "operator": "EQUALS",
                        "right": False,
                    },
                    {
                        "where": [
                            {
                                "right": 1,
                                "operator": "EQUALS",
                                "left": {
                                    "ref": "$_item.edge.edge.edge.number",
                                },
                            },
                            {
                                "left": {
                                    "ref": "$_item.edge.edge.edge.edge.edge.edge.numbers",  # weeeee!
                                },
                                "operator": "DOES_NOT_CONTAIN",
                                "right": {
                                    "ref": "$_item.number",
                                },
                            },
                        ],
                        "gate_type": "AND",
                    },
                    {
                        "left": {
                            "ref": "$_item.objects.number",
                        },
                        "operator": "CONTAINS",
                        "right": "$_item.number",
                    },
                ],
                "gate_type": "OR",
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_apply(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC",
                    "initial": 0,
                },
            ],
            "apply": [
                {
                    "from": None,
                    "method": "ADD",
                    "to": "$some_var",
                },
            ],
            "output": [
                {
                    "from": "$some_var",
                    "to": "number",
                }
            ],
        }

        def set_pipeline_value(key1, key2, val):
            schema["actions"][0]["pipeline"][key1][0][key2] = val

        # referenced variables must exist
        set_pipeline_value("apply", "from", "$non_existent_var")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[0].from (action id: 0): variable not found in pipeline scope: "$non_existent_var"'
            in errors
        )

        # assigned type must match variable type
        schema["actions"][0]["pipeline"]["variables"][0] = {
            "name": "$some_var",
            "type": "NUMERIC",
            "initial": None,
        }
        schema["actions"][0]["pipeline"]["apply"][0] = {
            "from": "$_object.name",
            "method": "SET",
            "to": "$some_var",
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[0] (action id: 0): cannot set value of type "STRING" to variable of type "NUMERIC"'
            in errors
        )

        set_pipeline_value("variables", "type", "STRING")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

        # "SET" can only be used for the first operation on a variable
        schema["actions"][0]["pipeline"]["variables"].append(
            {
                "name": "$another_var",
                "type": "STRING",
                "initial": "",
            }
        )
        schema["actions"][0]["pipeline"]["apply"].append(
            {
                "from": "$another_var",
                "method": "SET",
                "to": "$some_var",  # already set!
            }
        )
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[1] (action id: 0): the "SET" method can only be used for the first operation on a variable'
            in errors
        )

        # if null is the initial value, the first assignment must be "SET"
        set_pipeline_value("apply", "method", "CONCAT")
        errors = validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[0] (action id: 0): when a variable\'s initial value is null, the "SET" method must be used for the first operation on the variable'
            in errors
        )

        # method must be valid for types
        schema["actions"][0]["pipeline"]["variables"][0] = {
            "name": "$some_var",
            "type": "STRING_LIST",
            "initial": [],
        }
        schema["actions"][0]["pipeline"]["apply"] = [
            {
                "from": "$_object.name",
                "method": "ADD",
                "to": "$some_var",
            }
        ]
        errors = validator.validate(json_string=json.dumps(schema))
        assert errors

        set_pipeline_value("apply", "method", "APPEND")
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_variable_initial(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": None,
                    "initial": None,
                },
            ],
            "output": [
                {
                    "from": "$some_var",
                    "to": "number",
                }
            ],
        }

        def set_type(field_type):
            schema["actions"][0]["pipeline"]["variables"][0]["type"] = field_type

        def set_initial(initial):
            schema["actions"][0]["pipeline"]["variables"][0]["initial"] = initial

        invalid_initial_values = {
            "BOOLEAN": [0, "a", []],
            "NUMERIC": [True, "a", []],
            "STRING": [True, 0, [], {}],
            "NUMERIC_LIST": [True, "a", 0, [True], ["a"], [[]], [0, "a"]],
            "STRING_LIST": [True, "a", 0, [True], [0], [[]], [0, "a"]],
            "BOOLEAN_LIST": [True, "a", 0, ["a"], [0], [[]], [True, 1]],
            "EDGE": [True, "a", 0, []],
            "EDGE_COLLECTION": [True, "a", 0],
        }

        expected_context = (
            "root.actions[0].pipeline.variables[0].initial (action id: 0):"
        )
        for field_type, values in invalid_initial_values.items():
            set_type(field_type)
            for initial in values:
                set_initial(initial)
                errors = validator.validate(json_string=json.dumps(schema))
                assert (
                    f"{expected_context} does not match expected type {json.dumps(field_type)}"
                    in errors
                    or f"{expected_context} list items must be one of the following types: {json.dumps(list(valid_list_item_types))}"
                    in errors
                    or f"{expected_context} cannot mix types in list" in errors
                )

        valid_initial_values = {
            "BOOLEAN": [True, False, None],
            "NUMERIC": [0, 1, 10.5, None],
            "STRING": ["", "test", None],
            "NUMERIC_LIST": [[], [1, 2, 3], None],
            "STRING_LIST": [[], ["a", "b", "c"], None],
            "BOOLEAN_LIST": [[], [True, False], None],
            "OBJECT": [None],
            "OBJECT_LIST": [None, []],
        }

        for field_type, values in valid_initial_values.items():
            set_type(field_type)
            for initial in values:
                set_initial(initial)
                errors = validator.validate(json_string=json.dumps(schema))
                assert not errors

        # referencing a threaded action from the pipeline of an action which shares the same thread context
        # should not result in a list of threaded actions
        schema["checkpoints"] = [
            fixtures.checkpoint(id=0, alias="depends-on-0", num_dependencies=1),
        ]
        schema["threads"] = [
            fixtures.thread(0, "depends-on-0"),
        ]
        schema["actions"].append(fixtures.action(1))
        schema["actions"].append(fixtures.action(2))
        schema["actions"][1]["context"] = "thread:{0}"
        schema["actions"][2]["context"] = "thread:{0}"
        schema["actions"][2]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$numbers",
                    "type": "NUMERIC_LIST",
                    "initial": [],
                },
            ],
            "apply": [
                {
                    "from": "action:{1}.object.numbers",
                    "method": "CONCAT",
                    "to": "$numbers",
                },
                {
                    "from": "action:{1}.object.edge.numbers",
                    "method": "CONCAT",
                    "to": "$numbers",
                },
            ],
            "output": [
                {
                    "from": "$numbers",
                    "to": "numbers",
                },
            ],
        }
        errors = validator.validate(json_string=json.dumps(schema))
        assert not errors

    def test_resolve_type_from_object_path(self):
        validator = SchemaValidator()

        validator.schema = {
            "objects": {
                "NodeA": {
                    "string_field": {"field_type": "STRING"},
                    "numeric_list_field": {"field_type": "NUMERIC_LIST"},
                    "b": {
                        "field_type": "EDGE",
                        "object": "NodeB",
                    },
                },
                "NodeB": {
                    "numeric_field": {"field_type": "NUMERIC"},
                    "string_list_field": {"field_type": "STRING_LIST"},
                    "c_collection": {
                        "field_type": "EDGE_COLLECTION",
                        "object": "NodeC",
                    },
                },
                "NodeC": {
                    "boolean_field": {"field_type": "BOOLEAN"},
                    "d_collection": {
                        "field_type": "EDGE_COLLECTION",
                        "object": "NodeD",
                    },
                },
                "NodeD": {
                    "numeric_field": {"field_type": "NUMERIC"},
                    "numeric_list_field": {"field_type": "NUMERIC_LIST"},
                },
            },
        }

        # simple field
        assert validator._resolve_type_from_object_path(
            "NodeA", "string_field"
        ).__dict__ == {
            "is_list": False,
            "item_type": "STRING",
            "item_tag": None,
        }

        # list field
        assert validator._resolve_type_from_object_path(
            "NodeA", "numeric_list_field"
        ).__dict__ == {
            "is_list": True,
            "item_type": "NUMERIC",
            "item_tag": None,
        }

        # edge
        assert validator._resolve_type_from_object_path("NodeA", "b").__dict__ == {
            "is_list": False,
            "item_type": "OBJECT",
            "item_tag": "NodeB",
        }

        # edge collection
        assert validator._resolve_type_from_object_path(
            "NodeB", "c_collection"
        ).__dict__ == {
            "is_list": True,
            "item_type": "OBJECT",
            "item_tag": "NodeC",
        }

        # field of an edge
        assert validator._resolve_type_from_object_path(
            "NodeA", "b.numeric_field"
        ).__dict__ == {
            "is_list": False,
            "item_type": "NUMERIC",
            "item_tag": None,
        }

        # field of an edge collection
        assert validator._resolve_type_from_object_path(
            "NodeB", "c_collection.boolean_field"
        ).__dict__ == {"is_list": True, "item_type": "BOOLEAN", "item_tag": None}

        # two edges deep
        assert validator._resolve_type_from_object_path(
            "NodeA", "b.c_collection.boolean_field"
        ).__dict__ == {"is_list": True, "item_type": "BOOLEAN", "item_tag": None}

        # nested list (edge collection of an edge collection)
        with pytest.raises(Exception):
            validator._resolve_type_from_object_path(
                "NodeB", "c_collection.d_collection.numeric_field"
            )

        # nested list (list field of an edge collection)
        with pytest.raises(Exception):
            validator._resolve_type_from_object_path(
                "NodeC", "d_collection.numeric_list_field"
            )

    def test_global_ref_refers_to_local_object(self):
        validator = SchemaValidator()
        schema = fixtures.basic_schema_with_actions(1)

        # an "apply" object's "from" property may reference the local object...
        # should throw a warning if a global ref is used to do this.
        schema["actions"][0]["pipeline"] = {
            "context": "TEMPLATE",
            "variables": [
                {
                    "name": "$some_var",
                    "type": "NUMERIC_LIST",
                    "initial": [],
                },
            ],
            "apply": [
                {
                    "from": "action:{0}.object.number",
                    "method": "APPEND",
                    "to": "$some_var",
                },
            ],
            "output": [
                {
                    "from": "$some_var",
                    "to": "numbers",
                },
            ],
        }
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.apply[0].from (action id: 0): global ref refers to the local object -- consider using "$_object" instead to reference the local object.'
            in validator.warnings
        )

        schema["actions"][0]["pipeline"]["apply"][0]["from"] = "$_object.number"
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings

        # a "traverse" object's "ref" property may reference the local object...
        # should throw a warning if a global ref is used to do this.
        schema["actions"][0]["pipeline"]["traverse"] = [
            {
                "ref": "action:{0}.object.objects",
                "foreach": {
                    "as": "$edge",
                    "apply": [
                        {
                            "from": "$edge.number",
                            "method": "APPEND",
                            "to": "$some_var",
                        },
                    ],
                },
            },
        ]
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.traverse[0].ref (action id: 0): global ref refers to the local object -- consider using "$_object" instead to reference the local object'
            in validator.warnings
        )

        schema["actions"][0]["pipeline"]["traverse"][0]["ref"] = "$_object.objects"
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings

        # an "apply" object nested inside a traversal may also reference the local object
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["apply"] = [
            {
                "from": "action:{0}.object.number",
                "method": "APPEND",
                "to": "$some_var",
            },
            {
                "from": "$edge",  # just using this to avoid another warning
                "select": "numbers",
                "method": "CONCAT",
                "to": "$some_var",
            },
        ]
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.traverse[0].foreach.apply[0].from (action id: 0): global ref refers to the local object -- consider using "$_object" instead to reference the local object.'
            in validator.warnings
        )

        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["apply"][0][
            "from"
        ] = "$_object.number"
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings

        # a nested traversal object's "ref" property may reference the local object
        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["traverse"] = [
            {
                "ref": "action:{0}.object.objects",
                "foreach": {
                    "as": "$edge",
                    "apply": [],
                },
            },
        ]
        validator.validate(json_string=json.dumps(schema))
        assert (
            'root.actions[0].pipeline.traverse[0].foreach.traverse[0].ref (action id: 0): global ref refers to the local object -- consider using "$_object" instead to reference the local object'
            in validator.warnings
        )

        schema["actions"][0]["pipeline"]["traverse"][0]["foreach"]["traverse"][0][
            "ref"
        ] = "$_object.objects"
        validator.validate(json_string=json.dumps(schema))
        assert not validator.warnings
