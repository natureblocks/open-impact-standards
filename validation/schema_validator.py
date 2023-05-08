import copy
import hashlib
import json
import re

from validation import templates, utils


class SchemaValidator:
    def __init__(self):
        self.schema = None
        self._node_dependency_sets = {}  # to be collected during validation

        # for including helpful context information in error messages
        self._path_context = ""

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
            + self._validate_node_dependency_sets()
        )

        return self.errors

    def print_errors(self):
        print("\n".join(self.errors))

    def get_next_node_id(self, json_file_path):
        if self.validate(json_file_path=json_file_path):
            print(f"Invalid schema ({json_file_path}):\n")
            self.print_errors()
            raise Exception(f"Invalid schema")

        next_id = 0
        if "state_nodes" in self.schema:
            node_ids = [node["meta"]["id"] for node in self.schema["state_nodes"]]
            next_id = max(node_ids) + 1

        return next_id

    def get_all_node_ids(self, json_file_path):
        if self.validate(json_file_path=json_file_path):
            print(f"Invalid schema ({json_file_path}):\n")
            self.print_errors()
            raise Exception(f"Invalid schema")

        return [node["meta"]["id"] for node in self.schema["state_nodes"]]

    def _validate_field(self, path, field, template):
        if "types" in template:
            return self._validate_multi_type_field(path, field, template["types"])

        expected_type = template["type"]
        type_validator = getattr(self, "_validate_" + expected_type, None)

        if type_validator is None:
            raise NotImplementedError(
                "no validation method exists for type: " + expected_type
            )

        self._set_path_context(path)
        return type_validator(path, field, template)

    def _validate_multi_type_field(self, path, field, allowed_types):
        for allowed_type in allowed_types:
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
        if not isinstance(field, dict):
            return [f"{self._context(path)}: expected object, got {str(type(field))}"]

        if "templates" in template:
            return self._validate_multi_template_object(path, field, template)

        template = self._resolve_template(path, field, template)

        errors = []
        if "properties" in template:
            (meta__property_errors, template) = self._evaluate_meta_properties(
                path, field, template
            )
            errors += meta__property_errors

            for key in template["properties"]:
                if key not in field and self._field_is_required(key, template):
                    errors += [
                        f"{self._context(path)}: missing required property: {key}"
                    ]

            for key in field:
                if key in template["properties"]:
                    errors += self._validate_field(
                        path=f"{path}.{key}",
                        field=field[key],
                        template=template["properties"][key],
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

        return errors

    def _validate_multi_template_object(self, path, field, template):
        allowed_templates = template["templates"]
        template_errors = []
        for template_name in allowed_templates:
            errors = self._validate_object(
                path, field, getattr(templates, template_name)
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

        if "unique" in template:
            errors += self._validate_unique(path, field, template)

        return errors

    def _validate_enum(self, path, field, template):
        if field in template["values"]:
            return []

        return [
            f"{self._context(path)}: invalid enum value: expected one of {str(template['values'])}, got {json.dumps(field)}"
        ]

    def _validate_reference(self, path, field, template):
        if "referenced_value" in template:
            # looking for a specific value
            reference_path = template["referenced_value"].split(".")
            if reference_path[0] == "{corresponding_value}":
                expected_value = self._get_field(
                    f"{path}.{field}.{'.'.join(reference_path[1:])}"
                )
                if field == expected_value:
                    return []
                else:
                    return [
                        f"{self._context(path)}: invalid key: expected {expected_value} ({'.'.join(reference_path)}), got {json.dumps(field)}"
                    ]
            else:
                raise NotImplementedError(
                    "unexpected reference template: " + str(template)
                )

        elif "references_any" in template:
            # looking for any matching value
            return self._object_or_array_contains(
                path, field, template["references_any"]
            )

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
        if isinstance(field, str):
            return []

        return [f"{self._context(path)}: expected string, got {str(type(field))}"]

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

    def _field_is_required(self, key, template=None):
        if "optional" in template and key in template["optional"]:
            return False

        return True

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

        # { unique_field_name: { field_value: is_unique } }
        unique = {}

        for field_name in template["unique"]:
            unique_values = {}
            for item in field if isinstance(field, list) else field.values():
                if field_name in item:
                    unique_values[item[field_name]] = (
                        item[field_name] not in unique_values
                    )
                elif "." in field_name:
                    val = self._get_field(field_name, obj=item)
                    unique_values[val] = val not in unique_values

            unique[field_name] = unique_values

        errors = []
        for field_name in unique:
            for value, is_unique in unique[field_name].items():
                if not is_unique:
                    errors += [
                        f"{self._context(path)}: duplicate value provided for unique field {json.dumps(field_name)}: {json.dumps(value)}"
                    ]

        return errors

    def _get_field(self, path, obj=None):
        if obj is None:
            obj = self.schema

        for key in path.split("."):
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

        template["optional"] = [
            prop
            for prop in template["mutually_exclusive"]
            if prop not in included_props
        ]

        if len(included_props) > 1:
            return (
                [
                    f"{self._context(path)}: more than one mutually exclusive property specified: {included_props}"
                ],
                template,
            )

        return ([], template)

    def _resolve_template(self, path, field, template):
        if "template" in template:
            template_name = template["template"]
            referenced_template = getattr(templates, template_name)

            if template_name == "state_node":
                self._collect_node_dependency_set(path, field)

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

        return self._evaluate_template_conditionals(field, template)

    def _apply_template_modifiers(self, field, referenced_template, template_modifiers):
        modified_template = copy.deepcopy(referenced_template)

        for prop, prop_modifiers in template_modifiers.items():
            for key, val in prop_modifiers.items():
                modified_template["properties"][prop][key] = val

        return modified_template

    def _evaluate_template_conditionals(self, field, template):
        if "if" not in template and "switch" not in template:
            return template

        modified_template = copy.deepcopy(template)

        if "if" in template:
            for condition in modified_template["if"]:
                if self._template_condition_is_true(condition, field):
                    for key in condition["then"]:
                        modified_template[key] = condition["then"][key]
                elif "else" in condition:
                    raise NotImplementedError(
                        "else conditionals not yet supported for templates"
                    )

        if "switch" in template:
            for case in modified_template["switch"]["cases"]:
                if (
                    template["switch"]["property"] in field
                    and case["equals"] == field[template["switch"]["property"]]
                ):
                    for key in case["then"]:
                        if key == "property_modifiers":
                            for prop, prop_modifiers in case["then"][key].items():
                                modified_template["properties"][prop] = prop_modifiers
                        else:
                            modified_template[key] = case["then"][key]

                    if case["break"]:
                        break

        return modified_template

    def _template_condition_is_true(self, condition, field):
        prop = self._get_field(condition["property"], field)

        if "attribute" in condition:
            if condition["attribute"] == "length":
                prop = len(prop)

        if "equals" in condition:
            return prop == condition["equals"]

        if "greater_than" in condition:
            return prop > condition["greater_than"]

        if "less_than" in condition:
            return prop < condition["less_than"]

        if "greater_than_or_equal_to" in condition:
            return prop >= condition["greater_than_or_equal_to"]

        if "less_than_or_equal_to" in condition:
            return prop <= condition["less_than_or_equal_to"]

        if "contains" in condition:
            return condition["contains"] in prop

        if "does_not_contain" in condition:
            return condition["does_not_contain"] not in prop

        if "one_of" in condition:
            return prop in condition["one_of"]

        raise NotImplementedError(
            "template condition not yet supported: " + str(condition)
        )

    def _collect_node_dependency_set(self, path, node):
        if "depends_on" not in node or "meta" not in node or "id" not in node["meta"]:
            return

        dependency_set_is_invalid = len(
            self._validate_object(path, node["depends_on"], templates.dependency_set)
        )
        if dependency_set_is_invalid:
            return

        self._node_dependency_sets[node["meta"]["id"]] = node["depends_on"]

    def _validate_node_dependency_sets(self):
        return (
            self._detect_duplicate_dependency_sets()
            + self._detect_circular_dependencies()
        )

    def _detect_duplicate_dependency_sets(self):
        ds_hashes = {}
        for node_id, dependency_set in self._node_dependency_sets.items():
            if len(dependency_set["dependencies"]) == 1:
                continue

            dsh = hashlib.sha1(
                json.dumps(utils.recursive_sort(dependency_set)).encode()
            ).digest()

            if dsh in ds_hashes:
                ds_hashes[dsh].append(node_id)
            else:
                ds_hashes[dsh] = [node_id]

        errors = []
        for node_ids in ds_hashes.values():
            if len(node_ids) > 1:
                errors += [
                    f"The following node ids specify identical dependency sets: {json.dumps(node_ids)}"
                ]

        if len(errors):
            error_explanation = [
                "Any recurring DependencySet objects (Node.depends_on) should be added to root.referenced_dependency_sets, and nodes should specify a DependencySetReference with the alias of the DependencySet object."
            ]
            return error_explanation + errors

        return []

    def _detect_circular_dependencies(self):
        def _get_recurring_dependency_set(alias):
            for ds in self.schema["referenced_dependency_sets"]:
                if ds["alias"] == alias:
                    return ds

        def _explore_recursive(node_id, visited, dependency_path):
            if node_id in dependency_path:
                if len(dependency_path) > 1:
                    return [
                        f"Circular dependency detected (dependency path: {dependency_path})"
                    ]
                return [f"A node cannot have itself as a dependency (id: {node_id})"]

            if node_id in visited:
                return []

            visited.add(node_id)

            if node_id not in self._node_dependency_sets:
                return []

            dependency_path.append(node_id)

            errors = []
            for dependency in self._node_dependency_sets[node_id]["dependencies"]:
                # Could be a Dependency object or a DependencySetReference
                if "node_id" in dependency:
                    # Dependency
                    errors += _explore_recursive(
                        dependency["node_id"],
                        visited,
                        dependency_path,
                    )
                elif "alias" in dependency:
                    # DependencySetReference
                    recurring_ds = _get_recurring_dependency_set(dependency["alias"])
                    for dep in recurring_ds["dependencies"]:
                        errors += _explore_recursive(
                            dep["node_id"], visited, dependency_path
                        )

            return [errors[0]] if errors else []

        visited = set()
        for node_id in self._node_dependency_sets.keys():
            errors = _explore_recursive(node_id, visited, dependency_path=[])
            # It's simpler to return immediately when a circular dependency is found
            if errors:
                return errors

        return []

    def _set_path_context(self, path):
        # For paths that should include some sort of context,
        # add the path and context resolver here.
        context_resolvers = {
            "root.state_nodes": lambda path: "node id: "
            + str(self._resolve_node_id(path))
            if path != "root.state_nodes"
            else ""
        }

        self._path_context = []
        for path_segment, context_resolver in context_resolvers.items():
            if path_segment in path:
                self._path_context.append(context_resolver(path))

    def _context(self, path):
        return path + (
            f" ({','.join(self._path_context)})" if self._path_context else ""
        )

    def _resolve_node_id(self, path):
        ex = Exception(
            f"Cannot resolve node id: path does not lead to a node object ({path})"
        )

        if "root.state_nodes" not in path:
            raise ex

        idx = path.find("]")
        if idx == -1:
            raise ex

        node = self._get_field(path[: idx + 1])

        if "meta" not in node or "id" not in node["meta"]:
            raise ex

        return node["meta"]["id"]
