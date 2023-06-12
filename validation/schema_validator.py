import copy
import hashlib
import json
import re

from validation import templates, oisql, utils


class SchemaValidator:
    def __init__(self):
        self.schema = None

        # { action_id: checkpoint_alias }
        self._action_checkpoints = {}  # to be collected during validation
        # { alias: checkpoint}
        self._checkpoints = {}  # to be collected during validation

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

        self.errors = (
            self._validate_object("root", self.schema, templates.root_object)
            + self._detect_circular_dependencies()
        )

        return self.errors

    def print_errors(self):
        print("\n".join(self.errors))

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

    def _validate_field(
        self, path, field, template, parent_object_template=None, parent_object=None
    ):
        if "types" in template:
            return self._validate_multi_type_field(path, field, template["types"])

        expected_type = template["type"]

        if expected_type == "reference":
            return self._validate_reference(
                path, field, template, parent_object_template, parent_object
            )

        type_validator = getattr(self, "_validate_" + expected_type, None)

        if type_validator is None:
            raise NotImplementedError(
                "no validation method exists for type: " + expected_type
            )

        return type_validator(path, field, template)

    def _validate_multi_type_field(self, path, field, allowed_types):
        for allowed_type in allowed_types:
            if isinstance(allowed_type, dict):
                errors = self._validate_field(path, field, allowed_type)
            else:
                type_validator = getattr(self, "_validate_" + allowed_type, None)

                if type_validator is None:
                    raise NotImplementedError(
                        "no validation method exists for type: " + allowed_type
                    )

                errors = type_validator(path, field, {"type": allowed_type})

            if len(errors) == 0:
                return []

        return [
            f"{self._context(path)}: expected one of {allowed_types}, got {str(type(field))}"
        ]

    def _validate_object(self, path, field, template):
        self._object_context = path

        if not isinstance(field, dict):
            return [f"{self._context(path)}: expected object, got {str(type(field))}"]

        if "any_of_templates" in template:
            return self._validate_multi_template_object(path, field, template)

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

            if "forbidden" in template:
                for key in template["forbidden"]["properties"]:
                    if key in field:
                        errors += [
                            f"{self._context(path)}: forbidden property specified: {key}; reason: {template['forbidden']['reason']}"
                        ]

            for key in field:
                if key in template["properties"]:
                    errors += self._validate_field(
                        path=f"{path}.{key}",
                        field=field[key],
                        template=template["properties"][key],
                        parent_object_template=template,
                        parent_object=field,
                    )
                elif key in templates.RESERVED_KEYWORDS:
                    errors += [
                        f"{self._context(path)}: cannot use reserved keyword as property name: {json.dumps(key)}"
                    ]

        # For certain objects, the keys are not known ahead of time:
        elif "keys" in template and "values" in template:
            if template["keys"]["type"] == "reference":
                for key in field.keys():
                    errors += self._validate_reference(path, key, template["keys"])
            else:
                for key in field.keys():
                    errors += self._validate_string(
                        path=f"{path}.keys", field=key, template=template["keys"]
                    )

            for key in field.keys():
                errors += self._validate_field(
                    path=f"{path}.{key}", field=field[key], template=template["values"]
                )

        if "unique" in template or "unique_if_not_null" in template:
            errors += self._validate_unique(path, field, template)

        return errors

    def _validate_multi_template_object(self, path, field, template):
        if "any_of_templates" in template:
            allowed_templates = template["any_of_templates"]
            template_errors = []
            for template_name in allowed_templates:
                errors = self._validate_object(
                    path, field, utils.get_template(template_name)
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

    def _validate_array(self, path, field, template):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected array, got {str(type(field))}"]

        errors = self._validate_min_length(path, field, template)

        i = 0
        for item in field:
            errors += self._validate_field(
                path=f"{path}[{i}]", field=item, template=template["values"]
            )
            i += 1

        if "distinct" in template and template["distinct"]:
            if len(field) != len(set(field)):
                errors += [
                    f"{self._context(path)}: contains duplicate item(s) (values must be distinct)"
                ]

        if "unique" in template or "unique_if_not_null" in template:
            errors += self._validate_unique(path, field, template)

        return errors

    def _validate_enum(self, path, field, template):
        if field in template["values"]:
            return []

        return [
            f"{self._context(path)}: invalid enum value: expected one of {str(template['values'])}, got {json.dumps(field)}"
        ]

    def _validate_reference(
        self, path, field, template, parent_object_template=None, parent_object=None
    ):
        template_vars = (
            parent_object_template["template_vars"]
            if parent_object_template and "template_vars" in parent_object_template
            else {}
        )

        if "referenced_value" in template:
            # looking for a specific value
            reference_path = self._resolve_path_variables(
                template["referenced_value"].split("."), template_vars, parent_object
            )
            sub_path = ".".join(reference_path[1:])

            if reference_path[0] == "{corresponding_value}":
                expected_value = self._get_field(f"{path}.{field}.{sub_path}")
            elif reference_path[0] == "root":
                expected_value = self._get_field(sub_path)
            else:
                raise NotImplementedError(
                    "unexpected reference template: " + str(template)
                )

            if field == expected_value:
                return []
            else:
                return [
                    f"{self._context(path)}: expected {expected_value} ({'.'.join(reference_path)}), got {json.dumps(field)}"
                ]

        elif "references_any" in template:
            # looking for any matching value
            references_any = copy.deepcopy(template["references_any"])
            references_any["from"] = ".".join(
                self._resolve_path_variables(
                    references_any["from"].split("."), template_vars
                )
            )

            return self._object_or_array_contains(path, field, references_any)

        else:
            raise NotImplementedError("unexpected reference template: " + str(template))

    def _validate_decimal(self, path, field, template=None):
        if (isinstance(field, float) or isinstance(field, int)) and not isinstance(
            field, bool
        ):
            return []

        return [f"{self._context(path)}: expected decimal, got {str(type(field))}"]

    def _validate_integer(self, path, field, template=None):
        if isinstance(field, int) and not isinstance(field, bool):
            return []

        return [f"{self._context(path)}: expected integer, got {str(type(field))}"]

    def _validate_string(self, path, field, template=None):
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

        return []

    def _validate_integer_string(self, path, field, template=None):
        # Allow string representations of negative integers, e.g. "-1"
        if str(field)[0] == "-":
            field = str(field)[1:]

        if not str(field).isdigit():
            return [
                f"{self._context(path)}: expected a string representation of an integer, got {str(type(field))}"
            ]

        return []

    def _validate_boolean(self, path, field, template=None):
        if isinstance(field, bool):
            return []

        return [f"{self._context(path)}: expected boolean, got {str(type(field))}"]

    def _field_is_required(self, key, template):
        if ("optional" in template and key in template["optional"]) or (
            "forbidden" in template and key in template["forbidden"]["properties"]
        ):
            return False

        return True

    def _field_is_forbidden(self, key, template):
        return "forbidden" in template and key in template["forbidden"]

    def _validate_min_length(self, path, field, template):
        if "min_length" in template and len(field) < template["min_length"]:
            return [
                f"{self._context(path)}: must contain at least {template['min_length']} item(s), got {len(field)}"
            ]

        return []

    def _validate_unique(self, path, field, template):
        if not isinstance(field, list) and not isinstance(field, dict):
            raise NotImplementedError(
                "unique validation not implemented for type " + str(type(field))
            )

        constraint_map = {
            "unique": template["unique"] if "unique" in template else [],
            "unique_if_not_null": template["unique_if_not_null"]
            if "unique_if_not_null" in template
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
                    elif "." in field_name:
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

        for key in path if isinstance(path, list) else path.split("."):
            if key == "root":
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
        referenced_prop = reference_template["property"]

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
            if "." in referenced_prop:
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
        modified_template["optional"] = [
            prop
            for prop in modified_template["mutually_exclusive"]
            if prop not in included_props
        ]

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

            if template_name == "action":
                self._collect_action_checkpoint(field)
            elif template_name == "checkpoint":
                self._collect_checkpoint(field)

            if (
                "template_modifiers" in template
                and template_name in template["template_modifiers"]
            ):
                template = self._apply_template_modifiers(
                    field,
                    referenced_template,
                    template["template_modifiers"][template_name],
                )
            else:
                template = referenced_template

        if "resolvers" in template:
            template = self._resolve_template_variables(field, template)

        return self._evaluate_template_conditionals(field, template)

    def _resolve_path_variables(self, path_segments, template_vars, parent_object=None):
        if not isinstance(path_segments, list):
            raise Exception("path_segments must be a list")

        for i in range(len(path_segments)):
            var = path_segments[i]
            if isinstance(var, list):
                continue

            # template variable?
            if re.match(r"^\{\$\w+\}$", var):
                path_segments[i] = template_vars[var[1:-1]]

            # referenced field from parent object?
            if re.match(r"^\{\w+\}$", var) and var not in [
                "{this}",
                "{corresponding_value}",
            ]:
                path_segments[i] = self._get_field(var[1:-1], parent_object)

        return path_segments

    def _apply_template_modifiers(self, field, referenced_template, template_modifiers):
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

        operator = condition["operator"]
        value = condition["value"]

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

        raise NotImplementedError(
            "template operator not yet supported: " + str(operator)
        )

    def _apply_template_conditionals(self, conditional_modifiers, to_template):
        for key in conditional_modifiers:
            if key == "property_modifiers":
                for prop, prop_modifier in conditional_modifiers[key].items():
                    to_template["properties"][prop] = prop_modifier
            else:
                to_template[key] = conditional_modifiers[key]

        return to_template

    def _collect_action_checkpoint(self, action):
        if "id" in action and "depends_on" in action:
            self._action_checkpoints[action["id"]] = action["depends_on"]

    def _collect_checkpoint(self, checkpoint):
        if "alias" in checkpoint:
            self._checkpoints[checkpoint["alias"]] = checkpoint

    def _detect_circular_dependencies(self):
        def _explore_checkpoint_recursive(checkpoint, visited, dependency_path):
            for dependency in checkpoint["dependencies"]:
                # Could be a Dependency or a CheckpointReference
                if "node" in dependency:
                    # Dependency
                    errors = _explore_recursive(
                        dependency["node"]["action_id"],
                        visited,
                        dependency_path,
                    )

                    if errors:
                        return errors

                elif "checkpoint" in dependency:
                    # CheckpointReference
                    errors = _explore_checkpoint_recursive(
                        checkpoint=self._checkpoints[dependency["checkpoint"]],
                        visited=visited,
                        dependency_path=dependency_path,
                    )

                    if errors:
                        return errors

            return []

        def _explore_recursive(action_id, visited, dependency_path):
            if action_id in dependency_path:
                if len(dependency_path) > 1:
                    return [
                        f"Circular dependency detected (dependency path: {dependency_path})"
                    ]
                return [f"A node cannot have itself as a dependency (id: {action_id})"]

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
            errors = _explore_recursive(action_id, visited, dependency_path=[])
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
            "root.actions": lambda path: "node id: "
            + str(self._resolve_action_id(path))
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

    def _resolve_action_id(self, path):
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
                - "{this}" (obj argument)
                - "root" (the root schema object)

        "where" is a filter clause to be applied to the "from" clause.
            "property" is the subject of the filter clause

        "extract" is the property to resolve from the result of the above clauses.
        """
        if not self._matches_meta_template("query", query):
            raise Exception(f"Invalid query: {query}")

        from_path = query["from"].split(".")
        if from_path[0] == "{this}":
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
        left_operand = self._get_field(condition["property"], item)

        if self._matches_meta_template("query", condition["value"]):
            right_operand = self._resolve_query(parent_obj, condition["value"])
        else:
            # treat it as a literal value
            right_operand = condition["value"]

        if condition["operator"] == "EQUALS":
            return left_operand == right_operand
        elif condition["operator"] == "IN":
            return left_operand in right_operand
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
