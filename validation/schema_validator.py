import copy
import hashlib
import json

from validation import templates, utils


class SchemaValidator:
    def __init__(self):
        self.schema = None
        self._node_depencency_sets = {}  # to be collected during validation

    def validate(self, schema=None, json_file=None, json_string=None):
        if schema is not None:
            self.schema = schema
        elif json_file is not None:
            self.schema = json.load(open(json_file))
        elif json_string is not None:
            self.schema = json.loads(json_string)
        else:
            raise TypeError("must provide an argument for schema, json_file, or json_string")

        errors = self._validate_object("root", self.schema, templates.root_object)
        return errors + self._validate_node_depencency_sets()

    def _validate_field(self, path, field, template):
        if "types" in template:
            return self._validate_multi_type_field(path, field, template["types"])

        expected_type = template["type"]
        type_validator = getattr(self, "_validate_" + expected_type, None)

        if type_validator is None:
            raise NotImplementedError(
                "no validation method exists for type: " + expected_type
            )

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

        return [f"{path}: expected one of {allowed_types}, got {str(type(field))}"]

    def _validate_object(self, path, field, template):
        if not isinstance(field, dict):
            return [f"{path}: expected object, got {str(type(field))}"]

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
                    errors += [f"{path}: missing required property: {key}"]

            for key in field:
                if key in template["properties"]:
                    errors += self._validate_field(
                        path=f"{path}.{key}",
                        field=field[key],
                        template=template["properties"][key],
                    )
                elif key in templates.RESERVED_KEYWORDS:
                    errors += [
                        f"{path}: cannot use reserved keyword as property name: {json.dumps(key)}"
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
            f"{path}: object does not conform to any of the allowed template specifications: {str(allowed_templates)}"
        ] + template_errors

    def _validate_array(self, path, field, template):
        if not isinstance(field, list):
            return [f"{path}: expected array, got {str(type(field))}"]

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
                    f"{path}: contains duplicate item(s) (values must be distinct)"
                ]

        if "unique" in template:
            errors += self._validate_unique(path, field, template)

        return errors

    def _validate_enum(self, path, field, template):
        if field in template["values"]:
            return []

        return [
            f"{path}: invalid enum value: expected one of {str(template['values'])}, got {field}"
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
                        f"{path}: invalid key: expected {expected_value} ({'.'.join(reference_path)}), got {field}"
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

        return [f"{path}: expected decimal, got {str(type(field))}"]

    def _validate_integer(self, path, field, template=None):
        if isinstance(field, int) and not isinstance(field, bool):
            return []

        return [f"{path}: expected integer, got {str(type(field))}"]

    def _validate_string(self, path, field, template=None):
        if isinstance(field, str):
            return []

        return [f"{path}: expected string, got {str(type(field))}"]

    def _validate_integer_string(self, path, field, template=None):
        # Allow string representations of negative integers, e.g. "-1"
        if str(field)[0] == "-":
            field = str(field)[1:]

        if not str(field).isdigit():
            return [
                f"{path}: expected a string representation of an integer, got {str(type(field))}"
            ]

        return []

    def _validate_boolean(self, path, field, template=None):
        if isinstance(field, bool):
            return []

        return [f"{path}: expected boolean, got {str(type(field))}"]

    def _field_is_required(self, key, template=None):
        if "optional" in template and key in template["optional"]:
            return False

        return True

    def _validate_min_length(self, path, field, template):
        if "min_length" in template and len(field) < template["min_length"]:
            return [
                f"{path}: must contain at least {template['min_length']} item(s), got {len(field)}"
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
                        f"{path}: duplicate value provided for unique field {json.dumps(field_name)}: {json.dumps(value)}"
                    ]

        return errors

    def _get_field(self, path, obj=None):
        if obj is None:
            obj = self.schema

        for key in path.split("."):
            if key == "root":
                continue

            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            elif isinstance(obj, list):
                raise NotImplementedError(
                    "failed to get field: lists not yet supported"
                )
            else:
                raise Exception(f"invalid path: {path}")

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
                    f"{path}: expected any key from {referenced_path}, got {json.dumps(referenced_value)}"
                ]
            elif referenced_prop == "values":
                for value in objectOrArray.values():
                    if value == referenced_value:
                        return []

                return [
                    f"{path}: expected any value from {referenced_path}, got {json.dumps(referenced_value)}"
                ]
            else:
                for value in objectOrArray.values():
                    if (
                        referenced_prop in value
                        and value[referenced_prop] == referenced_value
                    ):
                        return []

                return [
                    f'{path}: expected any "{referenced_prop}" field from {referenced_path}, got {json.dumps(referenced_value)}'
                ]

        elif isinstance(objectOrArray, list):
            for item in objectOrArray:
                if isinstance(item, dict):
                    if "." in referenced_prop and self._get_field(referenced_prop, obj=item) == referenced_value:
                        return []

                    if (
                        referenced_prop in item
                        and item[referenced_prop] == referenced_value
                    ):
                        return []
                elif item == referenced_value:
                    return []

            return [
                f'{path}: expected any "{referenced_prop}" field from {referenced_path}, got {json.dumps(referenced_value)}'
            ]

        else:
            return [
                f"{path}: reference path {referenced_path} contains invalid type: {str(type(objectOrArray))}"
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
                    f"{path}: more than one mutually exclusive property specified: {included_props}"
                ],
                template,
            )

        return ([], template)

    def _resolve_template(self, path, field, template):
        if "template" in template:
            template_name = template["template"]
            
            if template_name == "dependency_set":
                print("found it!")

            referenced_template = getattr(templates, template_name)

            if template_name == "node":
                self._collect_node_depencency_set(path, field)

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
        if "if" not in template:
            return template

        modified_template = copy.deepcopy(template)
        for condition in template["if"]:
            if self._template_condition_is_true(condition, field):
                for key in condition["then"]:
                    modified_template[key] = condition["then"][key]
            elif "else" in condition:
                raise NotImplementedError(
                    "else conditionals not yet supported for templates"
                )

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

    def _collect_node_depencency_set(self, path, node):
        if (
            "depends_on" not in node
            or "meta" not in node
            or "id" not in node["meta"]
        ):
            return

        dependency_set_is_invalid = len(
            self._validate_object(path, node["depends_on"], templates.dependency_set)
        )
        if dependency_set_is_invalid:
            return

        self._node_depencency_sets[node["meta"]["id"]] = node["depends_on"]

    def _validate_node_depencency_sets(self):
        return (
            self._detect_duplicate_dependency_sets()
            + self._detect_circular_dependencies()
        )

    def _detect_duplicate_dependency_sets(self):
        ds_hashes = {}
        for node_id, dependency_set in self._node_depencency_sets.items():
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
                "Any recurring DependencySet objects (Node.depends_on) should be added to root.recurring_dependencies, and nodes should specify a DependencySetReference with the alias of the DependencySet object."
            ]
            return error_explanation + errors

        return []

    def _detect_circular_dependencies(self):
        return []
