import copy
import hashlib
import json
import re
from validation.field_type_details import FieldTypeDetails
from validation.pipeline_variable import PipelineVariable
from validation.thread import Thread

from validation import templates, oisql, utils, patterns, pipeline_utils
from validation.utils import is_path, is_global_ref, is_variable, is_local_variable


class SchemaValidator:
    def __init__(self):
        self.schema = None

        # { action_id: checkpoint_alias }
        self._action_checkpoints = {}  # to be collected during validation
        # { alias: checkpoint}
        self._checkpoints = {}  # to be collected during validation
        self._psuedo_checkpoints = []  # for implicit action dependencies on threads
        self._threads = {}

        # for including helpful context information in error messages
        self._path_context = ""
        self._context_path = None

    def validate(self, schema_dict=None, json_file_path=None, json_string=None):
        if schema_dict is not None:
            self.schema = schema_dict
        elif json_file_path is not None:
            self.schema = json.load(open(json_file_path))
        elif json_string is not None:
            self.schema = json.loads(json_string)
        elif self.schema is None:
            raise TypeError(
                "must provide an argument for schema, json_file_path, or json_string"
            )

        self._collect_actions_and_checkpoints()

        self.warnings = []
        self.errors = (
            self._validate_object("root", self.schema, templates.root_object)
            + self._detect_circular_dependencies()
        )

        return self.errors

    def print_errors(self, include_warnings=True):
        print(
            "\n".join(self.errors)
            + ("\nWARNINGS:\n".join(self.warnings) if include_warnings else "")
        )

    def get_next_action_id(self, json_file_path):
        if self.validate(json_file_path=json_file_path):
            print(f"Invalid schema ({json_file_path}):\n")
            self.print_errors()
            raise Exception(f"Invalid schema")

        next_id = 0
        if "actions" in self.schema:
            action_ids = [node["id"] for node in self.schema["actions"]]
            next_id = max(action_ids) + 1

        return next_id

    def get_all_action_ids(self, json_file_path):
        if self.validate(json_file_path=json_file_path):
            print(f"Invalid schema ({json_file_path}):\n")
            self.print_errors()
            raise Exception(f"Invalid schema")

        return [action["id"] for action in self.schema["actions"]]

    def _validate_field(self, path, field, template, parent_object_template=None):
        if "types" in template:
            return self._validate_multi_type_field(
                path, field, template["types"], parent_object_template
            )

        if "nullable" in template and template["nullable"] and field is None:
            return []

        expected_type = template["type"]

        if expected_type == "ref":
            return self._validate_ref(path, field, template)

        if is_path(expected_type):
            if "{_corresponding_key}" in expected_type:
                corresponding_key = path.split(".")[-1]
                path_to_expected_type = expected_type.replace(
                    "{_corresponding_key}", corresponding_key
                )

            dynamic_type = self._get_field(path_to_expected_type)

            if not isinstance(dynamic_type, str):
                raise Exception(f"Invalid template type: {expected_type}")

            expected_type = dynamic_type.lower()

        type_validator = getattr(self, "_validate_" + expected_type, None)

        if type_validator is None:
            raise NotImplementedError(
                "no validation method exists for type: " + expected_type
            )

        return type_validator(path, field, template, parent_object_template)

    def _validate_multi_type_field(
        self, path, field, allowed_types, parent_object_template
    ):
        for allowed_type in allowed_types:
            if isinstance(allowed_type, dict):
                errors = self._validate_field(path, field, allowed_type)
            else:
                type_validator = getattr(self, "_validate_" + allowed_type, None)

                if type_validator is None:
                    raise NotImplementedError(
                        "no validation method exists for type: " + allowed_type
                    )

                errors = type_validator(
                    path, field, {"type": allowed_type}, parent_object_template
                )

            if len(errors) == 0:
                return []

        return [
            f"{self._context(path)}: expected one of {json.dumps(allowed_types)}, got {json.dumps(type(field).__name__)}"
        ]

    def _validate_object(self, path, field, template, parent_object_template=None):
        self._object_context = path

        if not isinstance(field, dict):
            return [f"{self._context(path)}: expected object, got {str(type(field))}"]

        if self._bypass_validation_of_object(template, field):
            return []

        if "any_of_templates" in template:
            return self._validate_multi_template_object(
                path, field, template, parent_object_template
            )

        template = self._resolve_template(field, template)

        errors = []
        if "properties" in template:
            (meta_property_errors, template) = self._evaluate_meta_properties(
                path, field, template
            )
            errors += meta_property_errors

            # Check that all required properties are present
            for key in template["properties"]:
                if key not in field and self._field_is_required(key, template):
                    errors += [
                        f"{self._context(path)}: missing required property: {key}"
                    ]

            if "constraints" in template:
                errors += self._validate_constraints(
                    path, field, template["constraints"]
                )

            def validate_property(key):
                return self._validate_field(
                    path=f"{path}.{key}",
                    field=field[key],
                    template=template["properties"][key],
                    parent_object_template=template,
                )

            validated_properties = []
            if "property_validation_priority" in template:
                for key in template["property_validation_priority"]:
                    if key in field:
                        errors += validate_property(key)
                        validated_properties.append(key)

            for key in field:
                if key in validated_properties:
                    continue

                if key in template["properties"]:
                    errors += validate_property(key)
                elif key in templates.RESERVED_KEYWORDS:
                    errors += [
                        f"{self._context(path)}: cannot use reserved keyword as property name: {json.dumps(key)}"
                    ]

        # For certain objects, the keys are not known ahead of time:
        elif "keys" in template and "values" in template:
            for key in field.keys():
                errors += self._validate_string(
                    path=f"{path}.keys", field=key, template=template["keys"]
                )

                errors += self._validate_field(
                    path=f"{path}.{key}", field=field[key], template=template["values"]
                )

        return errors

    def _validate_multi_template_object(
        self, path, field, template, parent_object_template
    ):
        if "any_of_templates" in template:
            allowed_templates = template["any_of_templates"]
            template_errors = []
            for template_name in allowed_templates:
                errors = self._validate_object(
                    path,
                    field,
                    utils.get_template(template_name),
                    parent_object_template,
                )
                if not errors:
                    return []
                else:
                    template_errors += (
                        [f"--- begin '{template_name}' template errors ---"]
                        + errors
                        + [f"--- end '{template_name}' template errors ---"]
                    )

            return [
                f"{self._context(path)}: object does not conform to any of the allowed template specifications: {str(allowed_templates)}"
            ] + template_errors

    def _validate_array(self, path, field, template, parent_object_template):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected array, got {str(type(field))}"]

        errors = self._validate_min_length(path, field, template)

        i = 0
        for item in field:
            errors += self._validate_field(
                path=f"{path}[{i}]", field=item, template=template["values"]
            )
            i += 1

        if not errors and "constraints" in template:
            if (
                "distinct" in template["constraints"]
                and template["constraints"]["distinct"]
            ):
                if len(field) != len(set(field)):
                    errors += [
                        f"{self._context(path)}: contains duplicate item(s) (values must be distinct)"
                    ]

            if (
                "unique" in template["constraints"]
                or "unique_if_not_null" in template["constraints"]
            ):
                errors += self._validate_unique(path, field, template["constraints"])

        return errors

    def _validate_enum(self, path, field, template, parent_object_template):
        if field in template["values"]:
            return []

        return [
            f"{self._context(path)}: invalid enum value: expected one of {str(template['values'])}, got {json.dumps(field)}"
        ]

    def _validate_constraints(self, path, field, constraints):
        errors = []

        if "forbidden" in constraints:
            for key in constraints["forbidden"]["properties"]:
                if key in field:
                    errors += [
                        f"{self._context(path)}: forbidden property specified: {key}; reason: {constraints['forbidden']['reason']}"
                    ]

        if "unique" in constraints or "unique_if_not_null" in constraints:
            errors += self._validate_unique(path, field, constraints)

        if "validation_functions" in constraints:
            for function_call in constraints["validation_functions"]:
                fn = getattr(self, function_call["function"], None)
                if callable(fn):
                    parent_object = self._get_parent_object(path)
                    arguments = []
                    if "args" in function_call:
                        for a in function_call["args"]:
                            split_arg_path = a.split(".")
                            resolved_path_or_obj = self._resolve_path_variables(
                                path, a.split("."), parent_object=parent_object
                            )
                            if len(split_arg_path) == 1:
                                arguments.append(resolved_path_or_obj[0])
                            else:
                                arguments.append(
                                    self._get_field(resolved_path_or_obj, field)
                                )

                        errors += fn(path, *arguments)
                    else:
                        errors += fn(path, field)

        return errors

    def validate_is_referenced(self, path, referenced_value_path, ref_type):
        referenced_value = self._get_field(
            self._resolve_path_variables(
                path, f"{path}.{referenced_value_path}".split(".")
            )
        )

        if referenced_value is None:
            # ref validation will have alrady caught this
            return []

        if str(referenced_value) in getattr(self, "_unreferenced_" + ref_type):
            return [f"{self._context(path)}: {ref_type[:-1]} is never referenced"]

        return []

    def validate_has_ancestor(
        self, path, descendant_id, descendant_type, ancestor_ref, ancestor_source
    ):
        error = [
            f"{self._context(path)}: the value of property {json.dumps(ancestor_source)} must reference an ancestor of {descendant_type} id {json.dumps(descendant_id)}, got {json.dumps(ancestor_ref)}"
        ]

        descendant_id = str(descendant_id)
        if ancestor_ref is None or (
            descendant_id not in self._action_checkpoints
            and descendant_id not in self._thread_checkpoints
        ):
            return error

        ancestor_id = utils.parse_ref_id(ancestor_ref)

        def action_id_from_dependency_ref(dependency, left_or_right):
            if "ref" not in dependency["compare"][left_or_right]:
                return None
            return utils.parse_ref_id(dependency["compare"][left_or_right]["ref"])

        def validate_has_ancestor_recursive(checkpoint_alias, visited_checkpoints):
            if not checkpoint_alias in self._checkpoints:
                # pattern validation will have caught this
                return []

            if checkpoint_alias is None or checkpoint_alias in visited_checkpoints:
                return error

            visited_checkpoints.append(checkpoint_alias)

            checkpoint = self._checkpoints[checkpoint_alias]
            for dependency in checkpoint["dependencies"]:
                if "compare" in dependency:
                    if (
                        action_id_from_dependency_ref(dependency, "left") == ancestor_id
                        or action_id_from_dependency_ref(dependency, "right")
                        == ancestor_id
                    ):
                        return []

                elif "checkpoint" in dependency:
                    if validate_has_ancestor_recursive(
                        dependency["checkpoint"], visited_checkpoints
                    ):
                        return []

            return error

        if descendant_type == "action":
            if descendant_id not in self._action_checkpoints:
                return error

            return validate_has_ancestor_recursive(
                self._action_checkpoints[descendant_id], []
            )
        elif descendant_type == "thread":
            if descendant_id not in self._thread_checkpoints:
                return error

            return validate_has_ancestor_recursive(
                self._thread_checkpoints[descendant_id], []
            )
        else:
            raise Exception(
                f"cannot validate ancestry: invalid descendant type: {descendant_type}"
            )

    def validate_comparison(self, path, left, right, operator):
        if (
            self._validate_object("", left, templates.literal_operand) == []
            and self._validate_object("", right, templates.literal_operand) == []
        ):
            return [
                f"{self._context(path)}: invalid comparison: {left} {operator} {right}: both operands cannot be literals"
            ]

        def hash_sorted_object(obj):
            return hashlib.sha1(json.dumps(utils.recursive_sort(obj)).encode()).digest()

        if hash_sorted_object(left) == hash_sorted_object(right):
            return [
                f"{self._context(path)}: invalid comparison: {left} {operator} {right}: operands are identical"
            ]

        def extract_field_type(operand_object):
            if "ref" in operand_object:
                referenced_obj = self._resolve_global_ref(operand_object["ref"])
                if referenced_obj is None:
                    raise Exception("Failed to resolve ref: " + operand_object["ref"])

                ref_type = utils.parse_ref_type(operand_object["ref"])
                if ref_type != "action":
                    raise NotImplementedError(
                        "comparison validation not implemented for ref type: "
                        + ref_type
                    )

                if "object" not in referenced_obj:
                    raise Exception(
                        "Referenced action does not have an 'object' property: "
                        + operand_object["ref"]
                    )

                node_definition = self._get_field(f"objects.{referenced_obj['object']}")
                if node_definition is None:
                    raise Exception(
                        "'object' not found for referenced action: "
                        + operand_object["ref"]
                    )

                return node_definition[operand_object["field"]]["field_type"]
            else:
                field_type = utils.field_type_from_python_type_name(
                    type(operand_object["value"]).__name__
                )
                if field_type == "OBJECT":
                    raise NotImplementedError(
                        "comparison validation not implemented for type: " + field_type
                    )
                elif field_type == "LIST":
                    if self._validate_string_list("", right) == []:
                        return "STRING_LIST"
                    if self._validate_numeric_list("", right) == []:
                        return "NUMERIC_LIST"

                return field_type

        left_type = extract_field_type(left)
        right_type = extract_field_type(right)

        # recurring operator subsets
        scalar_with_list = ["ONE_OF", "NONE_OF"]
        list_with_scalar = ["CONTAINS", "DOES_NOT_CONTAIN"]
        list_with_list = [
            "EQUALS",
            "DOES_NOT_EQUAL",
            "CONTAINS_ANY_OF",
            "IS_SUBSET_OF",
            "IS_SUPERSET_OF",
            "CONTAINS_NONE_OF",
        ]

        if left_type == "STRING":
            if right_type == "STRING":
                if operator in [
                    "EQUALS",
                    "DOES_NOT_EQUAL",
                    "CONTAINS",
                    "DOES_NOT_CONTAIN",
                ]:
                    return []
            elif right_type == "STRING_LIST":
                if operator in scalar_with_list:
                    return []
        elif left_type == "NUMERIC":
            if right_type == "NUMERIC":
                if operator in [
                    "EQUALS",
                    "DOES_NOT_EQUAL",
                    "GREATER_THAN",
                    "LESS_THAN",
                    "GREATER_THAN_OR_EQUAL_TO",
                    "LESS_THAN_OR_EQUAL_TO",
                ]:
                    return []
            elif right_type == "NUMERIC_LIST":
                if operator in scalar_with_list:
                    return []
        elif left_type == "BOOLEAN":
            if right_type == "BOOLEAN" and operator == "EQUALS":
                return []
        elif left_type == "STRING_LIST":
            if right_type == "STRING":
                if operator in list_with_scalar:
                    return []
            elif right_type == "STRING_LIST":
                if operator in list_with_list:
                    return []
        elif left_type == "NUMERIC_LIST":
            if right_type == "NUMERIC":
                if operator in list_with_scalar:
                    return []
            elif right_type == "NUMERIC_LIST":
                if operator in list_with_list:
                    return []

        return [f"{self._context(path)}: invalid comparison: {left} {operator} {right}"]

    def validate_thread(self, path, thread):
        spawn = thread["spawn"] if "spawn" in thread else None
        if (
            spawn is None
            or "from" not in spawn
            or "foreach" not in spawn
            or "as" not in spawn
        ):
            # there will already be validation errors for the missing field(s)
            return []

        def resolve_thread_scope_recursive(thread):
            # get the scope of the thread
            thread_id = str(thread["id"])
            if self._threads[thread_id].scope is not None:
                return self._threads[thread_id].scope

            if "context" not in thread:
                # it's a top-level thread
                self._threads[thread_id].scope = thread_id
                return thread_id
            else:
                # it's a nested thread
                if is_global_ref(thread["context"]):
                    # resolve all parent threads first
                    parent_thread_id = utils.parse_ref_id(thread["context"])
                    if parent_thread_id not in self._threads:
                        return None  # cannot resolve parent thread scope

                    if (
                        self._threads[parent_thread_id].scope is None
                        and resolve_thread_scope_recursive(
                            thread=self._resolve_global_ref(thread["context"])
                        )
                        is None
                    ):
                        return None  # could not resolve parent thread scope

                    # record the thread and set its scope
                    scope = f"{self._threads[parent_thread_id].scope}.{thread_id}"
                    self._threads[thread_id].scope = scope

                    return scope

                return None  # cannot resolve scope

        errors = []

        scope = resolve_thread_scope_recursive(thread)
        if scope is None:
            return [f"{self._context(path)}: could not resolve thread scope"]

        thread_id = str(thread["id"])
        if is_global_ref(spawn["from"]):
            # if the global ref is an action, it must be an ancestor of the thread
            if utils.parse_ref_type(spawn["from"]) == "action":
                errors += self.validate_has_ancestor(
                    path,
                    descendant_id=thread_id,
                    descendant_type="thread",
                    ancestor_ref=spawn["from"],
                    ancestor_source="spawn.from",
                )

                if errors:
                    return errors
            try:
                from_object_type = self._resolve_type_from_global_ref(ref=spawn["from"])
            except Exception as e:
                return [f"{self._context(path)}.spawn: {str(e)}"]

        elif is_variable(spawn["from"]):
            from_path = spawn["from"].split(".")
            var_name = from_path[0]

            from_var_type_details = self._find_thread_variable(var_name, scope)

            if from_var_type_details is None:
                return [
                    f"{self._context(path)}.spawn.from: variable not found within thread scope: {json.dumps(var_name)}"
                ]

            # if there's a path, resolve it from the variable's type
            if len(path) > 1:
                try:
                    from_object_type = self._resolve_type_from_variable_path(
                        var_type_details=from_var_type_details,
                        path=from_path[1:],
                    )
                except Exception as e:
                    return [f"{self._context(path)}.spawn.from: {str(e)}"]
            else:
                from_object_type = from_var_type_details
        else:
            return [
                f"{self._context(path)}.spawn.from: expected global ref or thread variable, got {json.dumps(spawn['from'])}"
            ]

        if from_object_type is None:
            errors += [
                f"{self._context(path)}.spawn.from: could not resolve object type"
            ]
        else:
            # from_object_type must be an object or template object
            if from_object_type.item_type == "OBJECT":
                variable_type = self._resolve_type_from_object_path(
                    from_object_type.item_tag, spawn["foreach"]
                )
            elif is_global_ref(from_object_type.item_type):
                variable_type = self._resolve_type_from_global_ref(
                    ref=from_object_type.item_type + "." + spawn["foreach"]
                )
            else:
                errors += [
                    f"{self._context(path)}.spawn.from: invalid type ({from_object_type.to_string()})"
                ]

            if variable_type is None:
                errors += [
                    f"{self._context(path)}.spawn: could not resolve variable type: {json.dumps(spawn['from'] + '.' + spawn['foreach'])}"
                ]
            else:
                if variable_type.is_list:
                    if from_object_type.is_list:
                        errors += [
                            f"{self._context(path)}.spawn: nested list types are not supported"
                        ]
                else:
                    if not from_object_type.is_list:
                        errors += [
                            f"{self._context(path)}.spawn: cannot spawn threads from a non-list object"
                        ]

        # check for variable name collision
        var_name = spawn["as"]
        if (
            self._find_thread_variable(var_name, scope, check_nested_scopes=True)
            is not None
        ):
            errors += [
                f"{self._context(path)}.spawn.as: variable already defined within thread scope: {json.dumps(var_name)}"
            ]
        elif not errors:
            # thread variables are essentially loop variables, so the collection is de-listified here for convenience
            variable_type.is_list = False
            # record the variable type
            self._threads[thread_id].variables[var_name] = variable_type

        return errors

    def _get_action_thread_scope(self, path):
        action = self._get_parent_action(path)
        if (
            action is not None
            and "context" in action
            and utils.parse_ref_type(action["context"]) == "thread"
            and is_global_ref(action["context"])
        ):
            thread_id = utils.parse_ref_id(action["context"])
            if thread_id in self._threads:
                return self._threads[thread_id].scope

        return None

    def _find_thread_variable(self, var_name, scope, check_nested_scopes=False):
        if scope is None:
            return None

        # check the current scope
        thread_path = scope.split(".")
        thread_path.reverse()
        for thread_id in thread_path:
            if thread_id not in self._threads:
                break

            thread_context = self._threads[thread_id]
            if var_name in thread_context.variables:
                return thread_context.variables[var_name]

        if check_nested_scopes:

            def check_nested_scopes_recursive(thread_id):
                for sub_thread_id in self._threads[thread_id].sub_thread_ids:
                    sub_thread_context = self._threads[sub_thread_id]

                    if var_name in sub_thread_context.variables:
                        return sub_thread_context.variables[var_name]

                    if sub_thread_context.sub_thread_ids:
                        return check_nested_scopes_recursive(sub_thread_id)

            return check_nested_scopes_recursive(thread_id)

        return None

    def _find_pipeline_variable(self, pipeline_vars, scope, var_name):
        if scope is None:
            return None

        scope_path = scope.split(".")
        while len(scope_path):
            scope = ".".join(scope_path)
            scope_path.pop()

            if scope not in pipeline_vars:
                continue

            if var_name in pipeline_vars[scope]:
                return pipeline_vars[scope][var_name]

        return None

    def validate_pipeline(self, path, field):
        errors = []

        # {scope: {var_name: PipelineVariable}}
        pipeline_vars = {}
        pipeline_scope = "0"

        thread_scope = self._get_action_thread_scope(path)

        pipeline_vars[pipeline_scope] = {}
        if "variables" in field and isinstance(field["variables"], list):
            for i in range(len(field["variables"])):
                var = field["variables"][i]

                # check for pipeline variable name collision
                if self._find_pipeline_variable(
                    pipeline_vars, pipeline_scope, var["name"]
                ):
                    errors += [
                        f"{self._context(f'{path}.variables[{str(i)}].name')}: variable already defined: {json.dumps(var['name'])}"
                    ]
                    continue

                # check for collision with scoped thread variables
                if self._find_thread_variable(var["name"], thread_scope):
                    errors += [
                        f"{self._context(f'{path}.variables[{str(i)}].name')}: variable already defined within thread scope: {json.dumps(var['name'])}"
                    ]
                    continue

                try:
                    initial_type_details = (
                        pipeline_utils.field_type_details_from_initial_value(var)
                    )
                except Exception as e:
                    errors += [
                        f"{self._context(f'{path}.variables[{str(i)}].initial')}: {str(e)}"
                    ]
                    continue

                if not pipeline_utils.initial_matches_type(
                    initial_type_details, var["type"]
                ):
                    errors += [
                        f"{self._context(f'{path}.variables[{str(i)}].initial')}: does not match expected type {json.dumps(var['type'])}"
                    ]
                    continue

                pipeline_vars[pipeline_scope][var["name"]] = PipelineVariable(
                    type_details=initial_type_details,
                    initial=var["initial"],
                    assigned=False,
                )

        if not errors and "traverse" in field and isinstance(field["traverse"], list):
            for i in range(len(field["traverse"])):
                errors += self._validate_pipeline_traversal_recursive(
                    f"{path}.traverse[{str(i)}]",
                    pipeline_vars,
                    field["traverse"][i],
                    f"{pipeline_scope}.{i}",
                    thread_scope,
                )

        if not errors and "apply" in field and isinstance(field["apply"], list):
            for i in range(len(field["apply"])):
                errors += self._validate_pipeline_application(
                    f"{path}.apply[{str(i)}]",
                    pipeline_vars,
                    field["apply"][i],
                    pipeline_scope,
                    thread_scope,
                )

        return errors

    def _validate_pipeline_traversal_recursive(
        self, path, pipeline_vars, traversal, pipeline_scope, thread_scope
    ):
        if "ref" not in traversal or "foreach" not in traversal:
            # there will already be validation errors for the missing fields,
            # and we cannot validate further without them.
            return []

        errors = []

        # resolve the ref type
        ref = traversal["ref"]
        ref_path = ref.split(".")
        if is_variable(ref_path[0]):
            var_name = ref_path[0]
            pipeline_var = self._find_pipeline_variable(
                pipeline_vars, pipeline_scope, var_name
            )
            if pipeline_var is not None:
                var_type_details = pipeline_var.type_details
            else:
                # look for a thread variable in the current scope
                parent_action = self._get_parent_action(path)
                if "context" in parent_action:
                    parent_thread_id = utils.parse_ref_id(parent_action["context"])
                    var_type_details = self._find_thread_variable(
                        var_name, self._threads[parent_thread_id].scope
                    )
                else:
                    var_type_details = None

                if var_type_details is None:
                    return [
                        f"{self._context(f'{path}.ref')}: variable not found in pipeline scope: {json.dumps(var_name)}"
                    ]

            if len(ref_path) > 1:
                try:
                    ref_type_details = self._resolve_type_from_variable_path(
                        var_type_details=var_type_details,
                        path=ref_path[1:],
                    )
                except Exception as e:
                    return [f"{self._context(f'{path}.ref')}: {str(e)}"]
            else:
                ref_type_details = copy.deepcopy(var_type_details)
        else:  # ref is not a variable, so it's a global or local ref
            parent_action = self._get_parent_action(path)
            if is_global_ref(ref):
                errors += self.validate_has_ancestor(
                    path,
                    descendant_id=parent_action["id"],
                    descendant_type="action",
                    ancestor_ref=ref,
                    ancestor_source="ref",
                )

                ref_type_details = self._resolve_type_from_global_ref(ref)

                if ref_type_details is None:
                    return [
                        f"{self._context(f'{path}.ref')}: could not resolve object type"
                    ]

                if is_global_ref(
                    ref_type_details.item_type
                ) and not ref_type_details.item_type.startswith("action:"):
                    raise NotImplementedError(
                        "iteration not implemented for ref type: "
                        + ref_type_details.item_type
                    )

                if not ref_type_details.is_list:
                    return [
                        f"{self._context(f'{path}.ref')}: cannot traverse non-list object"
                    ]

            elif is_local_variable(ref):
                ref_type_details = self._resolve_type_from_local_ref(
                    local_ref=ref, obj=parent_action
                )
            else:
                return [
                    f"{self._context(f'{path}.ref')}: "
                    + f"expected global reference, local reference, or variable, got {json.dumps(ref)}"
                ]

        item_name = traversal["foreach"]["as"]
        if (
            self._find_pipeline_variable(pipeline_vars, pipeline_scope, item_name)
            is not None
        ):
            return [
                f"{self._context(f'{path}.foreach.as')}: variable already defined within pipeline scope: {item_name}"
            ]
        elif self._find_thread_variable(item_name, thread_scope) is not None:
            return [
                f"{self._context(f'{path}.foreach.as')}: variable already defined within thread scope: {item_name}"
            ]

        # de-listify, because the traversal iterates over the items
        ref_type_details.is_list = False

        pipeline_vars[pipeline_scope] = {}
        pipeline_vars[pipeline_scope][item_name] = PipelineVariable(
            type_details=ref_type_details,
            assigned=True,  # loop variables are automatically assigned a value
            is_loop_variable=True,
        )

        if "variables" in traversal["foreach"]:
            for i in range(len(traversal["foreach"]["variables"])):
                var = traversal["foreach"]["variables"][i]

                if (
                    self._find_pipeline_variable(
                        pipeline_vars, pipeline_scope, var["name"]
                    )
                    is not None
                ):
                    return [
                        f"{self._context(f'{path}.foreach.variables[{str(i)}].name')}: variable already defined: {var['name']}"
                    ]

                initial_type_details = (
                    pipeline_utils.field_type_details_from_initial_value(var)
                )

                if not pipeline_utils.initial_matches_type(
                    initial_type_details, var["type"]
                ):
                    return [
                        f"{self._context(f'{path}.foreach.variables[{str(i)}].initial')}: does not match expected type {var['type']}"
                    ]

                pipeline_vars[pipeline_scope][var["name"]] = PipelineVariable(
                    type_details=initial_type_details,
                    initial=var["initial"],
                    assigned=False,
                )

        if "traverse" in traversal["foreach"]:
            for i in range(len(traversal["foreach"]["traverse"])):
                errors += self._validate_pipeline_traversal_recursive(
                    f"{path}.foreach.traverse[{str(i)}]",
                    pipeline_vars,
                    traversal["foreach"]["traverse"][i],
                    f"{pipeline_scope}.{i}",
                    thread_scope,
                )

        if "apply" in traversal["foreach"]:
            for i in range(len(traversal["foreach"]["apply"])):
                errors += self._validate_pipeline_application(
                    f"{path}.foreach.apply[{str(i)}]",
                    pipeline_vars,
                    traversal["foreach"]["apply"][i],
                    pipeline_scope,
                    thread_scope,
                )

        return errors

    def _validate_pipeline_application(
        self, path, pipeline_vars, apply, pipeline_scope, thread_scope
    ):
        from_path = apply["from"].split(".")
        if is_variable(from_path[0]):
            var_name = from_path[0]
            var_type_details = None

            pipeline_var = self._find_pipeline_variable(
                pipeline_vars, pipeline_scope, var_name
            )
            if pipeline_var is not None:
                if not pipeline_var.assigned:
                    self.warnings.append(
                        f"{self._context(f'{path}.from')}: variable used before assignment: {json.dumps(var_name)}"
                    )

                var_type_details = pipeline_var.type_details
            else:
                var_type_details = self._find_thread_variable(var_name, thread_scope)

            if var_type_details is None:
                return [
                    f"{self._context(f'{path}.from')}: variable not found in pipeline scope: {json.dumps(var_name)}"
                ]

            if len(from_path) > 1:
                try:
                    ref_type_details = self._resolve_type_from_variable_path(
                        var_type_details=var_type_details,
                        path=from_path[1:],
                    )
                except Exception as e:
                    return [f"{self._context(f'{path}.ref')}: {str(e)}"]
            else:
                ref_type_details = copy.deepcopy(var_type_details)
        elif re.match(patterns.local_variable, apply["from"]):
            ref_type_details = self._resolve_type_from_local_ref(
                apply["from"], path=path
            )
        elif (
            self._validate_ref("", apply["from"], {"ref_types": ["action", "thread"]})
            == []
        ):
            # global ref
            ref_type_details = self._resolve_type_from_object_path(
                object_tag=self._resolve_global_ref(apply["from"]),
                path=apply["from"][len(self._resolve_global_ref(apply["from"])) :],
            )
        else:
            # pattern validation will have already caught this
            return []

        to_var_name = apply["to"]
        if not is_variable(to_var_name):
            # pattern validation will have already caught this
            return []

        to_pipeline_var = self._find_pipeline_variable(
            pipeline_vars, pipeline_scope, to_var_name
        )
        if to_pipeline_var is None:
            return [
                f"{self._context(f'{path}.to')}: pipeline variable not found in scope: {json.dumps(to_var_name)}"
            ]

        if to_pipeline_var.is_loop_variable:
            return [
                f"{self._context(f'{path}.to')}: cannot assign to loop variable: {json.dumps(to_var_name)}"
            ]

        left_operand_type = to_pipeline_var.type_details
        left_operand_is_null = (
            not to_pipeline_var.assigned and to_pipeline_var.initial is None
        )
        right_operand_type = pipeline_utils.determine_right_operand_type(
            apply, ref_type_details, self
        )

        try:
            pipeline_utils.validate_operation(
                left_operand_type,
                apply["method"],
                right_operand_type,
                left_operand_is_null,
            )

            to_pipeline_var.assigned = True
        except Exception as e:
            return [f"{self._context(path)}: {str(e)}"]

        return []

    def _resolve_type_from_variable_path(self, var_type_details, path):
        if var_type_details.item_type == "OBJECT":
            # resolve the type on the object definition
            return self._resolve_type_from_object_path(
                object_tag=var_type_details.item_tag,
                path=path,
            )
        elif re.match(patterns.global_ref, var_type_details.item_type):
            referenced_object = self._resolve_global_ref(var_type_details.item_type)
            if path[0] != "object":
                raise NotImplementedError(
                    "global ref resolution not implemented for action properties"
                )

            return self._resolve_type_from_object_path(
                object_tag=referenced_object["object"],
                path=path[1:],
            )
        elif path:
            raise Exception(
                f"cannot resolve path from non-object type: {var_type_details.to_string()}"
            )

        return var_type_details

    def _resolve_type_from_global_ref(self, ref):
        matches = re.findall(patterns.global_ref, ref)
        if len(matches) and len(matches[0]):
            global_ref = matches[0][0]
            ref_type = matches[0][1]
            ref_path = matches[0][2]

            template_object = self._resolve_global_ref(global_ref)

            if ref_type == "action":
                is_threaded_action = (
                    "context" in template_object
                    and is_global_ref(template_object["context"])
                    and utils.parse_ref_type(template_object["context"]) == "thread"
                )

                if len(ref_path):
                    split_ref_path = ref_path.split(".")
                    if split_ref_path[0] == "object":
                        type_details = self._resolve_type_from_object_path(
                            object_tag=template_object["object"],
                            path=split_ref_path[1:],
                        )

                        if is_threaded_action:
                            if type_details.is_list:
                                raise Exception("nested list types are not supported")

                            type_details.is_list = True

                        return type_details
                    else:
                        raise NotImplementedError(
                            "global ref resolution not implemented for action properties"
                        )
                else:
                    return FieldTypeDetails(
                        is_list=is_threaded_action,
                        item_type=global_ref,
                        item_tag=None,
                    )
            else:
                raise NotImplementedError(
                    "global ref resolution not implemented for ref type: " + ref_type
                )

        return None

    def _resolve_type_from_local_ref(self, local_ref, obj=None, path=None):
        if obj is None:
            if path is None:
                raise Exception("Must provide either obj or path")

            obj = self._get_field(path.split(".")[:2])  # root.action[idx]

        # what are the possible types of local_ref?
        split_ref = local_ref.split(".")
        if split_ref[0] == "$_object":
            return self._resolve_type_from_object_path(obj["object"], split_ref[1:])
            # follow the path to resolve edges/edge collections until the last item
        elif split_ref[0] == "$_party":
            # obj = self._resolve_party(obj["object"])
            raise NotImplementedError("local ref type not implemented: " + split_ref[0])
        else:
            raise NotImplementedError("local ref type not implemented: " + split_ref[0])

    def _resolve_type_from_object_path(self, object_tag, path):
        object_definition = self._get_field("root.objects." + object_tag)

        if object_definition is None:
            return None

        type_details = FieldTypeDetails(
            is_list=False,
            item_type="OBJECT",
            item_tag=object_tag,
        )

        if path:
            for segment in path if isinstance(path, list) else path.split("."):
                if segment not in object_definition:
                    return None

                # get the next field
                field_definition = object_definition[segment]
                if field_definition["field_type"][:4] == "EDGE":
                    object_definition = self._get_field(
                        "root.objects." + field_definition["object"]
                    )

                    if field_definition["field_type"] == "EDGE_COLLECTION":
                        if type_details.is_list:
                            raise Exception("nested lists not supported")

                        type_details = FieldTypeDetails(
                            is_list=True,
                            item_type="OBJECT",
                            item_tag=field_definition["object"],
                        )
                    elif field_definition["field_type"] == "EDGE":
                        type_details = FieldTypeDetails(
                            is_list=type_details.is_list,
                            item_type="OBJECT",
                            item_tag=field_definition["object"],
                        )
                elif "_LIST" in field_definition["field_type"]:
                    if type_details.is_list:
                        raise Exception("nested lists not supported")

                    return FieldTypeDetails(
                        is_list=True,
                        item_type=field_definition["field_type"].split("_")[0],
                        item_tag=None,
                    )
                else:
                    return FieldTypeDetails(
                        is_list=type_details.is_list,
                        item_type=field_definition["field_type"].split("_")[0],
                        item_tag=None,
                    )

        # resolving some object type
        return type_details

    def _validate_expected_value(self, path, field, template, parent_object_template):
        template_vars = (
            parent_object_template["template_vars"]
            if parent_object_template and "template_vars" in parent_object_template
            else {}
        )

        if "one_of" in template["expected_value"]:
            # looking for any matching value
            one_of = copy.deepcopy(template["expected_value"]["one_of"])
            one_of["from"] = ".".join(
                self._resolve_path_variables(
                    path, one_of["from"].split("."), template_vars
                )
            )

            return self._object_or_array_contains(path, field, one_of)

        else:

            def extract_value_from_referenced_object(ref_details):
                if "from_ref" not in ref_details or "extract" not in ref_details:
                    raise Exception(
                        "invalid referenced_value template: " + str(ref_details)
                    )

                ref = self._get_field(
                    self._resolve_path_variables(
                        path, ref_details["from_ref"].split("."), template_vars
                    )
                )
                referenced_object = self._resolve_global_ref(ref)

                return self._get_field(ref_details["extract"], referenced_object)

            if "referenced_value" in template["expected_value"]:
                expected_value = extract_value_from_referenced_object(
                    template["expected_value"]["referenced_value"]
                )

                if field == expected_value:
                    return []
                else:
                    return [
                        f"{self._context(path)}: expected {expected_value}, got {json.dumps(field)}"
                    ]

            elif "equivalent_ref" in template["expected_value"]:
                ref = extract_value_from_referenced_object(
                    template["expected_value"]["equivalent_ref"]
                )

                if ref is None or not is_global_ref(ref) or not is_global_ref(field):
                    # validation errors will already have been raised
                    return []

                # no need to resolve the refs if they are identical
                if ref == field:
                    return []

                ref_type_a = utils.parse_ref_type(ref)
                ref_type_b = utils.parse_ref_type(field)
                if ref_type_a != ref_type_b:
                    return [
                        f"{self._context(path)}: expected ref type {json.dumps(ref_type_a)}, got {json.dumps(ref_type_b)}"
                    ]

                # resolve the refs and check whether they have the same id
                obj_a = self._resolve_global_ref(ref)
                obj_b = self._resolve_global_ref(field)

                if (
                    obj_a is None
                    or obj_b is None
                    or "id" not in obj_a
                    or "id" not in obj_b
                ):
                    # validation errors will already have been raised
                    return []

                if obj_a["id"] == obj_b["id"]:
                    return []
                else:
                    return [
                        f"{self._context(path)}: expected ref equivalent to {json.dumps(ref)}, got {json.dumps(field)}"
                    ]
            else:
                raise NotImplementedError(
                    "expected_value template not implemented: " + str(template)
                )

    def _validate_ref(self, path, field, template, parent_object_template=None):
        if "local_ref" in template["ref_types"] and is_local_variable(field):
            referenced_object = self._resolve_type_from_local_ref(
                local_ref=field, path=path
            )
        else:
            if not is_global_ref(field):
                return [f"{self._context(path)}: expected ref, got {json.dumps(field)}"]

            ref_type = utils.parse_ref_type(field)
            if ref_type not in template["ref_types"]:
                return [
                    f"{self._context(path)}: invalid ref type: expected one of {json.dumps(template['ref_types'])}, got {json.dumps(ref_type)}"
                ]

            referenced_object = self._resolve_global_ref(field)

        if referenced_object is None:
            return [
                f"{self._context(path)}: invalid ref: object not found: {json.dumps(field)}"
            ]

        if "expected_value" in template:
            return self._validate_expected_value(
                path, field, template, parent_object_template
            )

        return []

    def _resolve_global_ref(self, ref):
        ref_id = utils.parse_ref_id(ref)
        ref_type = utils.parse_ref_type(ref)
        ref_config = getattr(templates, ref_type)["ref_config"]
        collection = self._get_field(ref_config["collection"])

        if collection is None:
            return None

        for ref_field in ref_config["fields"]:
            for item in collection:
                if ref_field not in item:
                    continue

                if str(item[ref_field]) == ref_id:
                    return item

        return None

    def _resolve_party(self, party_name):
        for party in self.schema["parties"]:
            if party["name"] == party_name:
                return party

    def _validate_scalar(self, path, field, template=None, parent_object_template=None):
        if field is None:
            return []

        valid_types = ["string", "decimal", "boolean", "string_list", "numeric_list"]

        for scalar_type in valid_types:
            if (
                getattr(self, "_validate_" + scalar_type)(
                    path, field, template, parent_object_template
                )
                == []
            ):
                return []

        return [f"{self._context(path)}: expected scalar, got {str(type(field))}"]

    def _validate_decimal(
        self, path, field, template=None, parent_object_template=None
    ):
        if (isinstance(field, float) or isinstance(field, int)) and not isinstance(
            field, bool
        ):
            return []

        return [f"{self._context(path)}: expected decimal, got {str(type(field))}"]

    def _validate_integer(
        self, path, field, template=None, parent_object_template=None
    ):
        if isinstance(field, int) and not isinstance(field, bool):
            return []

        return [f"{self._context(path)}: expected integer, got {str(type(field))}"]

    def _validate_string(self, path, field, template=None, parent_object_template=None):
        if not isinstance(field, str):
            return [f"{self._context(path)}: expected string, got {str(type(field))}"]

        if "pattern" in template and not re.match(template["pattern"], field):
            pattern_description = (
                f'{template["pattern_description"]} '
                if "pattern_description" in template
                else ""
            )
            return [
                f"{self._context(path)}: string does not match {pattern_description}pattern: {template['pattern']}"
            ]

        if "expected_value" in template:
            return self._validate_expected_value(
                path, field, template, parent_object_template
            )

        return []

    def _validate_integer_string(
        self, path, field, template=None, parent_object_template=None
    ):
        # Allow string representations of negative integers, e.g. "-1"
        if str(field)[0] == "-":
            field = str(field)[1:]

        if not str(field).isdigit():
            return [
                f"{self._context(path)}: expected a string representation of an integer, got {str(type(field))}"
            ]

        return []

    def _validate_boolean(
        self, path, field, template=None, parent_object_template=None
    ):
        if isinstance(field, bool):
            return []

        return [f"{self._context(path)}: expected boolean, got {str(type(field))}"]

    def _validate_string_list(
        self, path, field, template=None, parent_object_template=None
    ):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected list, got {str(type(field))}"]

        for item in field:
            if not isinstance(item, str):
                return [
                    f"{self._context(path)}: expected list of strings, found {str(type(item))}"
                ]

        return []

    def _validate_numeric_list(
        self, path, field, template=None, parent_object_template=None
    ):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected list, got {str(type(field))}"]

        for item in field:
            if self._validate_decimal("", item) != []:
                return [
                    f"{self._context(path)}: expected list of numbers, found {str(type(item))}"
                ]

        return []

    def _field_is_required(self, key, template):
        if "constraints" not in template:
            return True  # default to required

        if (
            "optional" in template["constraints"]
            and key in template["constraints"]["optional"]
        ) or (
            "forbidden" in template["constraints"]
            and key in template["constraints"]["forbidden"]["properties"]
        ):
            return False

        return True

    def _field_is_forbidden(self, key, template):
        return "forbidden" in template and key in template["forbidden"]

    def _validate_min_length(self, path, field, template):
        if "constraints" not in template or "min_length" not in template["constraints"]:
            return []

        if len(field) < template["constraints"]["min_length"]:
            return [
                f"{self._context(path)}: must contain at least {template['constraints']['min_length']} item(s), got {len(field)}"
            ]

        return []

    def _validate_unique(self, path, field, constraints):
        if not isinstance(field, list) and not isinstance(field, dict):
            raise NotImplementedError(
                "unique validation not implemented for type " + str(type(field))
            )

        unique_fields = constraints["unique"] if "unique" in constraints else []
        unique_composites = (
            constraints["unique_composites"]
            if "unique_composites" in constraints
            else []
        )
        constraint_map = {
            "unique": unique_fields + unique_composites,
            "unique_if_not_null": constraints["unique_if_not_null"]
            if "unique_if_not_null" in constraints
            else [],
        }

        # { unique_field_name: { field_value: is_unique } }
        unique = {}

        for field_name in (
            constraint_map["unique"] + constraint_map["unique_if_not_null"]
        ):
            unique_values = {}
            hash_map = {}

            if isinstance(field_name, list):
                # The unique constraint applies to a combination of fields
                for item in field if isinstance(field, list) else field.values():
                    unique_obj = {}
                    for prop in field_name:
                        if prop in item:
                            unique_obj[prop] = item[prop]

                    obj_hash = hashlib.sha1(
                        json.dumps(utils.recursive_sort(unique_obj)).encode()
                    ).digest()

                    unique_values[obj_hash] = obj_hash not in unique_values
                    hash_map[obj_hash] = unique_obj
            else:
                for item in field if isinstance(field, list) else field.values():
                    if isinstance(item, list):
                        for sub_item in item:
                            key = (
                                sub_item
                                if not isinstance(sub_item, dict)
                                else json.dumps(utils.recursive_sort(sub_item))
                            )
                            unique_values[key] = key not in unique_values
                    elif field_name in item:
                        if isinstance(item[field_name], list):
                            # Note that if a field of type "array" is specified as unique,
                            # a value cannot be repeated within the array or across arrays.
                            for sub_item in item[field_name]:
                                unique_values[sub_item] = sub_item not in unique_values
                        else:
                            unique_values[item[field_name]] = (
                                item[field_name] not in unique_values
                            )
                    elif is_path(field_name):
                        val = self._get_field(field_name, obj=item)
                        unique_values[val] = val not in unique_values

            unique[
                json.dumps(field_name) if isinstance(field_name, list) else field_name
            ] = unique_values

        errors = []
        for field_name in unique:
            for value, is_unique in unique[field_name].items():
                if field_name in constraint_map["unique_if_not_null"]:
                    if value is None:
                        continue

                if not is_unique:
                    if value in hash_map:
                        error = f"duplicate value provided for unique field combination {json.dumps(field_name)}: {json.dumps(hash_map[value])}"
                    else:
                        error = f"duplicate value provided for unique field {json.dumps(field_name)}: {json.dumps(value)}"

                    errors += [f"{self._context(path)}: {error}"]

        return errors

    def _get_field(
        self, path, obj=None, throw_on_invalid_path=False, exception_context=None
    ):
        if not path:
            return obj

        if obj is None:
            obj = self.schema
        elif is_local_variable(path[0]):
            path[0] = path[0][2:]  # remove "$_" prefix

        for key in path if isinstance(path, list) else path.split("."):
            if key == "root":
                obj = self.schema
                continue

            if isinstance(obj, dict):
                key_includes_array_index = re.match(r"^(\w*)\[(\d+)\]$", key)
                if key_includes_array_index:
                    key = key_includes_array_index.group(1)
                    idx = int(key_includes_array_index.group(2))

                    if key in obj and idx < len(obj[key]):
                        obj = obj[key][idx]
                        continue

                elif key in obj:
                    obj = obj[key]
                    continue

            # If a continue statement was not reached, the path leads nowhere
            if throw_on_invalid_path:
                if exception_context is None:
                    message = f"Invalid path: {path}"
                elif callable(exception_context):
                    message = exception_context(path)
                else:
                    exception_context

                raise Exception(message)

            return None

        return obj

    def _object_or_array_contains(self, path, referenced_value, reference_template):
        referenced_path = reference_template["from"]
        referenced_prop = reference_template["extract"]

        objectOrArray = self._get_field(referenced_path)

        if isinstance(objectOrArray, dict):
            if referenced_prop == "keys":
                for key in objectOrArray.keys():
                    if key == str(referenced_value):
                        return []

                return [
                    f"{self._context(path)}: expected any key from {referenced_path}, got {json.dumps(referenced_value)}"
                ]
            elif referenced_prop == "values":
                for value in objectOrArray.values():
                    if value == referenced_value:
                        return []

                return [
                    f"{self._context(path)}: expected any value from {referenced_path}, got {json.dumps(referenced_value)}"
                ]
            else:
                for value in objectOrArray.values():
                    if (
                        referenced_prop in value
                        and value[referenced_prop] == referenced_value
                    ):
                        return []

                return [
                    f'{self._context(path)}: expected any "{referenced_prop}" field from {referenced_path}, got {json.dumps(referenced_value)}'
                ]

        elif isinstance(objectOrArray, list):
            if is_path(referenced_prop):
                referenced_prop_path = referenced_prop.split(".")
                referenced_prop_name = (
                    referenced_prop_path.pop()
                    if len(referenced_prop_path) > 0
                    else referenced_prop
                )
            else:
                referenced_prop_path = None

            for item in objectOrArray:
                if isinstance(item, dict):
                    if referenced_prop_path:
                        if referenced_prop_name == "keys":
                            # Looking for any matching key in a nested object
                            referenced_obj = self._get_field(
                                ".".join(referenced_prop_path), obj=item
                            )
                            if (
                                isinstance(referenced_obj, dict)
                                and referenced_value in referenced_obj.keys()
                            ):
                                return []
                        elif (
                            self._get_field(referenced_prop, obj=item)
                            == referenced_value
                        ):
                            return []

                    if (
                        referenced_prop in item
                        and item[referenced_prop] == referenced_value
                    ):
                        return []

            return [
                f'{self._context(path)}: expected any "{referenced_prop}" field from {referenced_path}, got {json.dumps(referenced_value)}'
            ]

        else:
            return [
                f"{self._context(path)}: reference path {referenced_path} contains invalid type: {str(type(objectOrArray))}"
            ]

    def _evaluate_meta_properties(self, path, field, template):
        errors = []
        modified_template = template.copy()

        if "mutually_exclusive" in template:
            (
                new_errors,
                modified_template,
            ) = self._validate_mutually_exclusive_properties(
                path, field, modified_template
            )
            errors += new_errors

        return (errors, modified_template)

    def _validate_mutually_exclusive_properties(self, path, field, template):
        included_props = []

        for prop in template["mutually_exclusive"]:
            if prop in field:
                included_props.append(prop)

        modified_template = copy.deepcopy(template)

        if "constraints" not in modified_template:
            modified_template["constraints"] = {}

        if "forbidden" not in modified_template["constraints"]:
            modified_template["constraints"]["forbidden"] = {"properties": []}

        for prop in modified_template["mutually_exclusive"]:
            if prop not in included_props:
                modified_template["constraints"]["forbidden"]["properties"].append(prop)

        if len(included_props) > 1:
            return (
                [
                    f"{self._context(path)}: more than one mutually exclusive property specified: {included_props}"
                ],
                modified_template,
            )

        return ([], modified_template)

    def _resolve_template(self, field, template):
        if "template" in template:
            template_name = template["template"]
            referenced_template = utils.get_template(template_name)

            if (
                "template_modifiers" in template
                and template_name in template["template_modifiers"]
            ):
                template = self._apply_template_modifiers(
                    referenced_template,
                    template["template_modifiers"][template_name],
                )
            else:
                template = referenced_template

        if "resolvers" in template:
            template = self._resolve_template_variables(field, template)

        return self._evaluate_template_conditionals(field, template)

    def _resolve_path_variables(
        self, path, path_segments_to_resolve, template_vars={}, parent_object=None
    ):
        if not isinstance(path_segments_to_resolve, list):
            raise Exception("path_segments must be a list")

        if path_segments_to_resolve[0] == "{_parent}":
            # Replace "{_parent}" with the parent object's path
            path_segments_to_resolve = (
                path.split(".")[:-1] + path_segments_to_resolve[1:]
            )

        for i in range(len(path_segments_to_resolve)):
            var = path_segments_to_resolve[i]
            if isinstance(var, list):
                continue

            # template variable?
            if re.match(r"^\{\$\w+\}$", var):
                path_segments_to_resolve[i] = template_vars[var[1:-1]]

            # referenced field from parent object?
            if re.match(r"^\{\w+\}$", var) and var not in [
                "{_this}",
                "{_corresponding_key}",
                "{_item}",
            ]:
                path_segments_to_resolve[i] = self._get_field(
                    var[1:-1], self._get_field(path)
                )

        return path_segments_to_resolve

    def _get_parent_object(self, path):
        return self._get_field(path.split(".")[:-1])

    def _get_parent_action(self, path):
        return self._get_field(path.split(".")[:2])

    def _apply_template_modifiers(self, referenced_template, template_modifiers):
        modified_template = copy.deepcopy(referenced_template)

        for prop, prop_modifiers in template_modifiers.items():
            for key, val in prop_modifiers.items():
                modified_template["properties"][prop][key] = val

        return modified_template

    def _resolve_template_variables(self, field, template):
        modified_template = copy.deepcopy(template)

        modified_template["template_vars"] = {}
        for variable, resolver in template["resolvers"].items():
            var = self._resolve_query(field, resolver)
            if isinstance(var, str):
                modified_template["template_vars"][variable] = var
            else:
                # Query resolution failed -- insert reserved keyword "ERROR".
                # This allows validation to run to completion, which should
                # reveal the root cause of the query resolution failure.
                modified_template["template_vars"][variable] = "ERROR"

        return modified_template

    def _evaluate_template_conditionals(self, field, template):
        if "if" not in template and "switch" not in template:
            return template

        modified_template = copy.deepcopy(template)

        if "if" in template:
            for condition in modified_template["if"]:
                if self._template_condition_is_true(condition, field):
                    modified_template = self._apply_template_conditionals(
                        condition["then"], modified_template
                    )
                elif "else" in condition:
                    modified_template = self._apply_template_conditionals(
                        condition["else"], modified_template
                    )

        if "switch" in template:
            raise NotImplementedError(
                "unit tests are needed for template switch statements"
            )

            for case in modified_template["switch"]["cases"]:
                if (
                    template["switch"]["property"] in field
                    and case["equals"] == field[template["switch"]["property"]]
                ):
                    modified_template = self._apply_template_conditionals(
                        case["then"], modified_template
                    )

                    if case["break"]:
                        break

        if "add_conditionals" in modified_template:
            if "if" in modified_template["add_conditionals"]:
                modified_template["if"] = modified_template["add_conditionals"]["if"]
            else:
                del modified_template["if"]

            if "switch" in modified_template["add_conditionals"]:
                modified_template["switch"] = modified_template["add_conditionals"][
                    "switch"
                ]
            else:
                del modified_template["switch"]

            del modified_template["add_conditionals"]

            # Recursively evaluate any conditionals added by the current conditionals
            return self._evaluate_template_conditionals(field, modified_template)

        return modified_template

    def _template_condition_is_true(self, condition, field):
        required_props = ["property", "operator", "value"]
        if not all(prop in condition for prop in required_props):
            raise Exception(f"Invalid template condition: {condition}")

        operator = condition["operator"]
        value = (
            self._get_field(condition["value"], field)
            if is_path(condition["value"])
            else condition["value"]
        )

        # special case:
        # is an optional property specified?
        if operator == "IS_SPECIFIED" and value == True:
            return condition["property"] in field

        prop = self._get_field(
            condition["property"],
            field,
            throw_on_invalid_path=True,
            exception_context=lambda path: f"Unable to evaluate template condition for object at path: '{self._object_context}': missing required field: {path}",
        )

        if "attribute" in condition:
            if condition["attribute"] == "length":
                prop = len(prop)
            elif condition["attribute"] == "type":
                prop = utils.field_type_from_python_type_name(type(prop).__name__)

        if operator == "EQUALS":
            return prop == value

        if operator == "GREATER_THAN":
            return prop > value

        if operator == "LESS_THAN":
            return prop < value

        if operator == "GREATER_THAN_OR_EQUAL_TO":
            return prop >= value

        if operator == "LESS_THAN_OR_EQUAL_TO":
            return prop <= value

        if operator == "CONTAINS":
            return value in prop

        if operator == "DOES_NOT_CONTAIN":
            return value not in prop

        if operator == "ONE_OF":
            return prop in value

        if operator == "IS_REFERENCED_BY":
            return is_global_ref(value) and utils.parse_ref_id(value) == prop

        raise NotImplementedError(
            "template operator not yet supported: " + str(operator)
        )

    def _apply_template_conditionals(self, conditional_modifiers, to_template):
        for key in conditional_modifiers:
            if key == "override_properties" or key == "add_properties":
                for prop, prop_modifier in conditional_modifiers[key].items():
                    to_template["properties"][prop] = prop_modifier
            elif key == "add_constraints":
                if "constraints" not in to_template:
                    to_template["constraints"] = {}

                for constraint_name, constraint in conditional_modifiers[key].items():
                    to_template["constraints"][constraint_name] = constraint
            else:
                raise NotImplementedError(
                    "Unexpected key in conditional modifiers: " + key
                )

        return to_template

    def _collect_actions_and_checkpoints(self):
        if "actions" not in self.schema or not isinstance(self.schema["actions"], list):
            return

        self._action_checkpoints = {}
        self._checkpoints = {}
        self._thread_checkpoints = {}
        self._threaded_action_ids = []
        self._threads = {}

        if "threads" in self.schema:
            for thread in self.schema["threads"]:
                thread_id = str(thread["id"])
                if thread_id not in self._threads:
                    self._threads[thread_id] = Thread()

                if "context" in thread:
                    parent_thread = self._resolve_global_ref(thread["context"])
                    if (
                        parent_thread is None
                        or utils.parse_ref_type(thread["context"]) != "thread"
                        or "depends_on" not in parent_thread
                    ):
                        continue

                    parent_thread_id = str(parent_thread["id"])
                    if parent_thread_id not in self._threads:
                        self._threads[parent_thread_id] = Thread()

                    self._threads[parent_thread_id].sub_thread_ids.append(thread_id)

                    checkpoint_id = utils.parse_ref_id(parent_thread["depends_on"])

                    if "depends_on" not in thread:
                        self._thread_checkpoints[thread_id] = checkpoint_id
                    else:
                        # a psuedo-checkpoint is needed to combine the thread's checkpoint
                        # with the parent thread's checkpoint
                        alias = f"_psuedo-thread-checkpoint-{str(thread['id'])}"
                        self.schema["checkpoints"].append(
                            {
                                "alias": alias,
                                "gate_type": "AND",
                                "dependencies": [
                                    {"checkpoint": parent_thread["depends_on"]},
                                    {"checkpoint": thread["depends_on"]},
                                ],
                            }
                        )
                        self._thread_checkpoints[thread_id] = alias

                        # bypass validation of psuedo-checkpoint fields
                        self._psuedo_checkpoints.append(alias)
                elif "depends_on" in thread:
                    if not is_global_ref(thread["depends_on"]):
                        # skip invalid refs -- allow validation to fail elsewhere
                        continue

                    self._thread_checkpoints[thread_id] = utils.parse_ref_id(
                        thread["depends_on"]
                    )

        for action in self.schema["actions"]:
            if "id" in action:
                action_id = str(action["id"])
                # if the action has a threaded context...
                if "context" in action:
                    # the action implicitly depends on the thread's checkpoint
                    thread = self._resolve_global_ref(action["context"])

                    if (
                        thread is None
                        or utils.parse_ref_type(action["context"]) != "thread"
                    ):
                        continue

                    thread_id = str(thread["id"])

                    if thread_id not in self._threads:
                        self._threads[thread_id] = Thread()

                    self._threads[thread_id].action_ids.append(action_id)

                    if "depends_on" in thread:
                        checkpoint_id = utils.parse_ref_id(thread["depends_on"])
                    elif "context" in thread and thread_id in self._thread_checkpoints:
                        checkpoint_id = self._thread_checkpoints[thread_id]
                    else:
                        continue

                    self._thread_checkpoints[thread_id] = checkpoint_id
                    self._threaded_action_ids.append(action_id)

                    if "depends_on" not in action:
                        # the action implicitly depends on the thread's checkpoint
                        self._action_checkpoints[action_id] = checkpoint_id
                    else:
                        # a psuedo-checkpoint is needed to combine the action's checkpoint with the thread's checkpoint
                        alias = f"_psuedo-checkpoint-{str(action['id'])}"
                        self.schema["checkpoints"].append(
                            {
                                "alias": alias,
                                "gate_type": "AND",
                                "dependencies": [
                                    {"checkpoint": thread["depends_on"]},
                                    {"checkpoint": action["depends_on"]},
                                ],
                            }
                        )
                        self._action_checkpoints[action_id] = alias

                        # bypass validation of psuedo-checkpoint fields
                        self._psuedo_checkpoints.append(alias)
                else:
                    self._action_checkpoints[action_id] = (
                        utils.parse_ref_id(action["depends_on"])
                        if "depends_on" in action
                        else None
                    )

        self._unreferenced_threads = []
        for thread_id, thread in self._threads.items():
            if not len(thread.action_ids) and not len(thread.sub_thread_ids):
                self._unreferenced_threads.append(thread_id)

        self._unreferenced_checkpoints = []
        for checkpoint in self.schema["checkpoints"]:
            if "alias" in checkpoint:
                self._checkpoints[checkpoint["alias"]] = checkpoint

                if (
                    checkpoint["alias"] not in self._action_checkpoints.values()
                    and checkpoint["alias"] not in self._thread_checkpoints.values()
                ):
                    self._unreferenced_checkpoints.append(checkpoint["alias"])

    def _detect_circular_dependencies(self):
        def _explore_checkpoint_recursive(checkpoint, visited, dependency_path):
            for dependency in checkpoint["dependencies"]:
                # Could be a Dependency or a CheckpointReference
                if "compare" in dependency:
                    # Dependency
                    for operand in ["left", "right"]:
                        if "ref" in dependency["compare"][operand]:
                            errors = _explore_recursive(
                                utils.parse_ref_id(
                                    dependency["compare"][operand]["ref"]
                                ),
                                visited,
                                dependency_path.copy(),
                            )

                            if errors:
                                return errors

                elif "checkpoint" in dependency:
                    # CheckpointReference
                    alias = utils.parse_ref_id(dependency["checkpoint"])
                    if alias not in self._checkpoints:
                        # CheckpointReference is invalid -- allow validation to fail elsewhere
                        return []

                    errors = _explore_checkpoint_recursive(
                        checkpoint=self._checkpoints[alias],
                        visited=visited,
                        dependency_path=dependency_path.copy(),
                    )

                    if errors:
                        return errors

            return []

        def _explore_recursive(action_id, visited, dependency_path):
            if action_id in dependency_path:
                if len(dependency_path) > 1:
                    dependency_path_string = json.dumps(dependency_path).replace(
                        '"', ""
                    )
                    error = f"Circular dependency detected (dependency path: {dependency_path_string})"
                else:
                    error = (
                        f"A node cannot have itself as a dependency (id: {action_id})"
                    )

                for action_id in dependency_path:
                    if action_id in self._threaded_action_ids:
                        error += "; NOTE: actions with threaded context implicitly depend on the referenced thread's checkpoint (Thread.depends_on)"
                        break

                return [error]

            if action_id in visited:
                return []

            visited.add(action_id)

            if action_id not in self._action_checkpoints:
                return []

            dependency_path.append(action_id)

            alias = self._action_checkpoints[action_id]
            if not isinstance(alias, str) or alias not in self._checkpoints:
                return []

            errors = _explore_checkpoint_recursive(
                checkpoint=self._checkpoints[alias],
                visited=visited,
                dependency_path=dependency_path,
            )

            return [errors[0]] if errors else []

        visited = set()
        for action_id in self._action_checkpoints.keys():
            errors = _explore_recursive(str(action_id), visited, dependency_path=[])
            # It's simpler to return immediately when a circular dependency is found
            if errors:
                return errors

        return []

    def _set_path_context(self, path):
        if self._context_path and self._context_path in path:
            return

        # For paths that should include some sort of context,
        # add the path and context resolver here.
        context_resolvers = {
            "root.actions": lambda path: "action id: "
            + str(self._action_id_from_path(path))
            if path != "root.actions"
            else ""
        }

        self._path_context = []
        self._context_path = None
        for path_segment, context_resolver in context_resolvers.items():
            if path_segment in path:
                context = context_resolver(path)
                if context:
                    self._path_context.append(context)
                    self._context_path = path

    def _context(self, path):
        self._set_path_context(path)
        return path + (
            f" ({','.join(self._path_context)})" if self._path_context else ""
        )

    def _action_id_from_path(self, path):
        ex = Exception(
            f"Cannot resolve node id: path does not lead to a node object ({path})"
        )

        if "root.actions" not in path:
            raise ex

        idx = path.find("]")
        if idx == -1:
            raise ex

        node = self._get_field(path[: idx + 1])

        if "id" not in node:
            raise ex

        return node["id"]

    def _resolve_query(self, obj, query):
        """Query components:

        "from" is a schema property or path to be resolved as the query source.
            - Must begin with one of the following:
                - "{_this}" (obj argument)
                - "root" (the root schema object)

        "where" is a filter clause to be applied to the "from" clause.
            "property" is the subject of the filter clause

        "extract" is the property to resolve from the result of the above clauses.
        """
        if not self._matches_meta_template("query", query):
            raise Exception(f"Invalid query: {query}")

        from_path = query["from"].split(".")
        if from_path[0] == "{_this}":
            from_collection = self._get_field(".".join(from_path[1:]), obj)
        elif from_path[0] == "root":
            from_collection = self._get_field(".".join(from_path[1:]))
        else:
            raise Exception(f"Query 'from' clause not supported: {query['from']}")

        if "where" in query:
            if isinstance(from_collection, list):
                from_collection = [
                    item
                    for item in from_collection
                    if self._matches_where_clause(item, query["where"], obj)
                ]
            else:
                raise NotImplementedError(
                    "Query 'where' clause not implemented for non-lists"
                )

        if isinstance(from_collection, list):
            result = [
                self._get_field(query["extract"], item) for item in from_collection
            ]

            return result[0] if len(result) == 1 else result
        else:
            return self._get_field(query["extract"], from_collection)

    def _matches_where_clause(self, item, where_clause, parent_obj):
        if self._matches_meta_template("condition", where_clause):
            return self._evaluate_query_condition(where_clause, item, parent_obj)
        elif self._matches_meta_template("condition_group", where_clause):
            return self._evaluate_query_condition_group_recursive(
                where_clause, item, parent_obj
            )
        else:
            raise Exception(f"Invalid 'where' clause in query: {where_clause}")

    def _evaluate_query_condition(self, condition, item, parent_obj):
        prop = (
            condition["property"].replace("{_item}", item)
            if isinstance(item, str)
            else condition["property"]
        )
        left_operand = self._get_field(prop, item)

        if self._matches_meta_template("query", condition["value"]):
            right_operand = self._resolve_query(parent_obj, condition["value"])
        else:
            # treat it as a literal value
            right_operand = condition["value"]

        if condition["operator"] == "EQUALS":
            return left_operand == right_operand
        elif condition["operator"] == "IN":
            return left_operand in right_operand
        elif condition["operator"] == "IS_REFERENCED_BY":
            if right_operand is None:
                print("...")
            return str(left_operand) == utils.parse_ref_id(right_operand)
        else:
            raise Exception(
                f"Query 'where' clause operator not implemented: {condition['operator']}"
            )

    def _evaluate_query_condition_group_recursive(self, condition, item, parent_obj):
        raise NotImplementedError(
            "Recursive query condition group functionality is untested"
        )

        if condition["gate_type"] == "AND":
            early_return_trigger = False
            early_return_value = False
            late_return_value = True
        elif condition["gate_type"] == "OR":
            early_return_trigger = True
            early_return_value = True
            late_return_value = False
        else:
            raise Exception(
                f"Query 'gate_type' not implemented: {condition['gate_type']}"
            )

        for sub_condition in condition["conditions"]:
            if self._matches_meta_template("condition", sub_condition):
                if (
                    self._evaluate_query_condition(sub_condition, item, parent_obj)
                    == early_return_trigger
                ):
                    return early_return_value
            elif self._matches_meta_template("condition_group", sub_condition):
                if (
                    self._evaluate_query_condition_group_recursive(
                        sub_condition, item, parent_obj
                    )
                    == early_return_trigger
                ):
                    return early_return_value
            else:
                raise Exception(
                    f"Invalid condition in query 'where' clause: {sub_condition}"
                )

        return late_return_value

    def _matches_meta_template(self, template_name, obj):
        return self._validate_object("", obj, getattr(oisql, template_name)) == []

    def _bypass_validation_of_object(self, template, field):
        if (
            "template" in template
            and template["template"] == "checkpoint"
            and "alias" in field
            and field["alias"] in self._psuedo_checkpoints
        ):
            return True

        return False
