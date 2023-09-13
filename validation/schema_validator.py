import copy
import json
import re
from utils import recursive_sort, hash_sorted_object, objects_are_identical
from validation.field_type_details import FieldTypeDetails
from validation.pipeline_variable import PipelineVariable
from validation.pipeline import Pipeline
from validation.thread_group import ThreadGroup

from validation import obj_specs, oisql, utils, patterns, pipeline_utils
from validation.utils import (
    is_path,
    is_global_ref,
    is_variable,
    is_local_variable,
    is_filter_ref,
    types_are_comparable,
)


class SchemaValidator:
    def __init__(self):
        self.schema = None

        # { action_id: checkpoint_alias }
        self._action_checkpoints = {}  # to be collected during validation
        # { alias: checkpoint}
        self._checkpoints = {}  # to be collected during validation
        self._psuedo_checkpoints = []  # for implicit action dependencies on threads
        self._thread_groups = {}

        # {action_id: Pipeline}
        self._pipelines = {}
        # {object_promise_id: [field_name]}
        self._aggregated_fields = {}

        # once a ref is resolved, it can be cached here.
        # currently only used for action.pipeline.apply.from
        self._type_details_at_path = {}

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
            self._validate_object("root", self.schema, obj_specs.root_object)
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

    def _validate_field(self, path, field, obj_spec, parent_obj_spec=None):
        if "types" in obj_spec:
            return self._validate_multi_type_field(
                path, field, obj_spec["types"], parent_obj_spec
            )

        if "nullable" in obj_spec and obj_spec["nullable"] and field is None:
            return []

        expected_type = obj_spec["type"]

        if expected_type == "any":
            return []

        if is_path(expected_type):
            if "{_corresponding_key}" in expected_type:
                corresponding_key = path.split(".")[-1]
                path_to_expected_type = expected_type.replace(
                    "{_corresponding_key}", corresponding_key
                )

            dynamic_type = self._get_field(path_to_expected_type)

            if not isinstance(dynamic_type, str):
                raise Exception(f"Invalid obj_spec type: {expected_type}")

            expected_type = dynamic_type.lower()

        type_validator = getattr(self, "_validate_" + expected_type, None)

        if type_validator is None:
            raise NotImplementedError(
                "no validation method exists for type: " + expected_type
            )

        return type_validator(path, field, obj_spec, parent_obj_spec)

    def _validate_multi_type_field(self, path, field, allowed_types, parent_obj_spec):
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
                    path, field, {"type": allowed_type}, parent_obj_spec
                )

            if len(errors) == 0:
                return []

        return [
            f"{self._context(path)}: expected one of {json.dumps(allowed_types)}, got {json.dumps(type(field).__name__)}"
        ]

    def _validate_object(self, path, field, obj_spec, parent_obj_spec=None):
        self._object_context = path

        if not isinstance(field, dict):
            return [
                f"{self._context(path)}: {self._obj_spec_error(obj_spec, f'expected object, got {type(field).__name__}')}"
            ]

        if self._bypass_validation_of_object(obj_spec, field):
            return []

        if "any_of_specs" in obj_spec:
            return self._validate_multi_spec_object(
                path, field, obj_spec, parent_obj_spec
            )

        obj_spec = self._resolve_obj_spec(field, obj_spec)

        errors = []
        if "properties" in obj_spec:
            (meta_property_errors, obj_spec) = self._evaluate_meta_properties(
                path, field, obj_spec
            )
            errors += meta_property_errors

            # Check that all required properties are present
            for key in obj_spec["properties"]:
                if key not in field and self._field_is_required(key, obj_spec):
                    errors += [
                        f"{self._context(path)}: missing required property: {key}"
                    ]

            if "constraints" in obj_spec:
                errors += self._validate_constraints(path, field, obj_spec)

            def validate_property(key):
                return self._validate_field(
                    path=f"{path}.{key}",
                    field=field[key],
                    obj_spec=obj_spec["properties"][key],
                    parent_obj_spec=obj_spec,
                )

            validated_properties = []
            if "property_validation_priority" in obj_spec:
                for key in obj_spec["property_validation_priority"]:
                    if key in field:
                        errors += validate_property(key)
                        validated_properties.append(key)

            for key in field:
                if key in validated_properties:
                    continue

                if key in obj_spec["properties"]:
                    errors += validate_property(key)
                elif key in obj_specs.RESERVED_KEYWORDS:
                    errors += [
                        f"{self._context(path)}: cannot use reserved keyword as property name: {json.dumps(key)}"
                    ]

        # For certain objects, the keys are not known ahead of time:
        elif "keys" in obj_spec and "values" in obj_spec:
            for key in field.keys():
                errors += self._validate_string(
                    path=f"{path}.keys", field=key, obj_spec=obj_spec["keys"]
                )

                errors += self._validate_field(
                    path=f"{path}.{key}", field=field[key], obj_spec=obj_spec["values"]
                )

        return errors

    def _validate_multi_spec_object(self, path, field, obj_spec, parent_obj_spec):
        if "any_of_specs" in obj_spec:
            allowed_obj_specs = obj_spec["any_of_specs"]
            obj_spec_errors = []
            for obj_spec_name in allowed_obj_specs:
                errors = self._validate_object(
                    path,
                    field,
                    utils.get_obj_spec(obj_spec_name),
                    parent_obj_spec,
                )
                if not errors:
                    return []
                else:
                    obj_spec_errors += (
                        [f"--- begin '{obj_spec_name}' spec errors ---"]
                        + errors
                        + [f"--- end '{obj_spec_name}' spec errors ---"]
                    )

            return [
                f"{self._context(path)}: object does not conform to any of the allowed object specifications: {str(allowed_obj_specs)}"
            ] + obj_spec_errors

    def _validate_array(self, path, field, obj_spec, parent_obj_spec):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected array, got {str(type(field))}"]

        errors = self._validate_min_length(path, field, obj_spec)

        i = 0
        for item in field:
            errors += self._validate_field(
                path=f"{path}[{i}]", field=item, obj_spec=obj_spec["values"]
            )
            i += 1

        if not errors and "constraints" in obj_spec:
            if (
                "distinct" in obj_spec["constraints"]
                and obj_spec["constraints"]["distinct"]
            ):
                if len(field) != len(set(field)):
                    errors += [
                        f"{self._context(path)}: contains duplicate item(s) (values must be distinct)"
                    ]

            if (
                "unique" in obj_spec["constraints"]
                or "unique_if_not_null" in obj_spec["constraints"]
            ):
                errors += self._validate_unique(path, field, obj_spec)

        return errors

    def _validate_enum(self, path, field, obj_spec, parent_obj_spec):
        if field in obj_spec["values"]:
            return []

        return [
            f"{self._context(path)}: invalid enum value: expected one of {str(obj_spec['values'])}, got {json.dumps(field)}"
        ]

    def _validate_constraints(self, path, field, obj_spec):
        # Note: "mutually_exclusive" properties are evaluated in _evaluate_meta_properties
        # because they result in obj_spec modifications that affect the validation of other constraints.
        errors = []
        constraints = obj_spec["constraints"] if "constraints" in obj_spec else {}
        if "forbidden" in constraints:
            for key in constraints["forbidden"]["properties"]:
                if key in field:
                    errors += [
                        f"{self._context(path)}: forbidden property specified: {key}; reason: {constraints['forbidden']['reason']}"
                    ]

        if "unique" in constraints or "unique_if_not_null" in constraints:
            errors += self._validate_unique(path, field, obj_spec)

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

    def validate_object_promise_fulfillment(self, path, object_promise):
        if "id" not in object_promise:
            return []

        errors = []
        if str(object_promise["id"]) not in self._object_promise_fulfillment_actions:
            errors += [
                f"{self._context(path)}: object promise is never fulfilled by an action"
            ]

        if str(object_promise["id"]) in self._duplicate_object_promise_fulfillments:
            errors += [
                f"{self._context(path)}: object promise is fulfilled by more than one action"
            ]

        return errors

    def validate_action_operation(self, path, action):
        if (
            "id" not in action
            or "operation" not in action
            or not utils.has_reference_to_template_entity(
                action, "object_promise", "object_promise"
            )
            or ("include" in action["operation"] and "exclude" in action["operation"])
        ):
            # validation will have caught this already
            return []

        object_promise = self._resolve_global_ref(action["object_promise"])
        if (
            object_promise is None
            or "id" not in object_promise
            or "object_type" not in object_promise
            or object_promise["object_type"] not in self.schema["object_types"]
        ):
            # validation will have caught this already
            return []

        object_type = self._get_field(f"object_types.{object_promise['object_type']}")
        if object_type is None:
            # validation will have caught this already
            return []

        errors = []

        # "include" / "exclude" must only specify fields from the object definition,
        # or be null.
        operation = action["operation"]
        for inclusion_type in ["include", "exclude"]:
            if inclusion_type not in operation or operation[inclusion_type] is None:
                continue

            if not isinstance(operation[inclusion_type], list):
                return [
                    f"{self._context(f'{path}.operation.{inclusion_type}')}: expected array or null, got {json.dumps(type(operation[inclusion_type]).__name__)}"
                ]

            for field in operation[inclusion_type]:
                if field not in object_type:
                    errors += [
                        f"{self._context(f'{path}.operation.{inclusion_type}')}: field does not exist on object type {object_promise['object_type']}: {json.dumps(field)}"
                    ]

        object_promise_id = str(object_promise["id"])
        action_id = str(action["id"])
        if object_promise_id in self._object_promise_fulfillment_actions:
            if self._object_promise_fulfillment_actions[object_promise_id] == action_id:
                # CREATE operation
                if "default_values" in operation:
                    if not isinstance(operation["default_values"], dict):
                        return [
                            f"{self._context(f'{path}.operation.default_values')}: expected object, got {json.dumps(type(operation['default_values']).__name__)}"
                        ]

                    for key, val in operation["default_values"].items():
                        # keys must be non-edge/edge collection fields on the object promise's object definition
                        if key not in object_type:
                            errors += [
                                f"{self._context(f'{path}.operation.default_values.{key}')}: field does not exist on object type: {json.dumps(object_promise['object_type'])}"
                            ]
                        elif "field_type" not in object_type[key]:
                            # object type validation will have caught this already
                            continue
                        elif object_type[key]["field_type"] == "EDGE":
                            errors += [
                                f"{self._context(f'{path}.operation.default_values.{key}')}: cannot specify default value for edge here; use default_edges instead"
                            ]
                        elif object_type[key]["field_type"] == "EDGE_COLLECTION":
                            errors += [
                                f"{self._context(f'{path}.operation.default_values.{key}')}: setting default values for edge collections is not supported"
                            ]
                        else:
                            # the type of the provided default value must match the type of the field on the object definition
                            expected_type = object_type[key]["field_type"]
                            actual_type = pipeline_utils.field_type_details_from_scalar(
                                val
                            ).to_field_type_string()
                            if actual_type != expected_type:
                                errors += [
                                    f"{self._context(f'{path}.operation.default_values')}: expected value of type {expected_type}, got {actual_type}: {json.dumps(val)}"
                                ]
                if "default_edges" in operation:
                    if not isinstance(operation["default_edges"], dict):
                        return [
                            f"{self._context(f'{path}.operation.default_edges')}: expected object, got {json.dumps(type(operation['default_edges']).__name__)}"
                        ]
                    # keys must be edge/edge collection fields on the object promise's object definition
                    # values must reference an object promise of the applicable object type
                    for key, val in operation["default_edges"].items():
                        if key not in object_type:
                            errors += [
                                f"{self._context(f'{path}.operation.default_edges.{key}')}: field does not exist on object type: {json.dumps(object_promise['object_type'])}"
                            ]
                        elif "field_type" not in object_type[key]:
                            # object type validation will have caught this already
                            continue
                        elif object_type[key]["field_type"] == "EDGE_COLLECTION":
                            errors += [
                                f"{self._context(f'{path}.operation.default_edges.{key}')}: setting default values for edge collections is not supported"
                            ]
                        elif object_type[key]["field_type"] != "EDGE":
                            errors += [
                                f"{self._context(f'{path}.operation.default_edges.{key}')}: cannot specify default value for non-edge here; use default_values instead"
                            ]
                        else:
                            if not utils.has_reference_to_template_entity(
                                operation["default_edges"], key, "object_promise"
                            ):
                                # ref validation will have caught this already
                                continue

                            object_promise_edge = self._resolve_global_ref(val)
                            if object_promise_edge is None:
                                errors += [
                                    f"{self._context(f'{path}.operation.default_edges.{key}')}: could not resolve object promise reference: {json.dumps(val)}"
                                ]
                            elif (
                                "id" not in object_promise_edge
                                or "object_type" not in object_promise_edge
                            ):
                                # object type validation will have caught this already
                                continue
                            elif (
                                object_promise_edge["object_type"]
                                != object_type[key]["object_type"]
                            ):
                                errors += [
                                    f"{self._context(f'{path}.operation.default_edges.{key}')}: object type of referenced object promise does not match the object type definition: {json.dumps(val)}"
                                    + f"; expected {json.dumps(object_type[key]['object_type'])}, got {json.dumps(object_promise_edge['object_type'])}"
                                ]
                            else:
                                fulfiller_id = str(object_promise_edge["id"])
                                if action_id != fulfiller_id and (
                                    fulfiller_id
                                    not in self._object_promise_fulfillment_actions
                                    or self.validate_has_ancestor(
                                        path,
                                        descendant_id=action_id,
                                        descendant_type="action",
                                        ancestor_ref=utils.as_ref(
                                            self._object_promise_fulfillment_actions[
                                                str(object_promise_edge["id"])
                                            ],
                                            "action",
                                        ),
                                    )
                                ):
                                    errors += [
                                        f"{self._context(f'{path}.operation.default_edges.{key}')}: an ancestor of the action must fulfill the referenced object promise: {json.dumps(val)}"
                                    ]

                if utils.has_reference_to_template_entity(
                    operation, "appends_objects_to", "object_promise"
                ):
                    appends_to_object_promise = self._resolve_global_ref(
                        operation["appends_objects_to"]
                    )
                    if not self._object_promise_fulfilled_by_ancestor(
                        path, action, appends_to_object_promise, guarantee_ancestry=True
                    ):
                        errors += [
                            f"{self._context(f'{path}.operation.appends_objects_to')}: the referenced object promise is not guaranteed to be fulfilled by an ancestor of this action"
                        ]

                    split_ref = operation["appends_objects_to"].split(".")
                    edge_collection_details = (
                        self._resolve_type_from_object_promise_ref(
                            global_ref=split_ref[0],
                            path_from_ref=split_ref[1:],
                            resolution_context_thread_group_id=utils.parse_ref_id(
                                action["context"]
                            )
                            if utils.has_reference_to_template_entity(
                                action, "context", "thread_group"
                            )
                            else None,
                        )
                    )
                    if (
                        not isinstance(edge_collection_details, FieldTypeDetails)
                        or edge_collection_details.item_type != "OBJECT"
                        or not edge_collection_details.is_list
                        or edge_collection_details.item_tag
                        != object_promise["object_type"]
                    ):
                        errors += [
                            f"{self._context(f'{path}.operation.appends_objects_to')}: must reference an edge collection with the same object_type as this action's object promise"
                        ]

                    edge_collection_key = operation["appends_objects_to"].split(".")[-1]
                    appends_to_object_promise_id = str(appends_to_object_promise["id"])
                    if (
                        "id" in appends_to_object_promise
                        and appends_to_object_promise_id in self._settable_fields
                        and edge_collection_key
                        in self._settable_fields[appends_to_object_promise_id]
                    ):
                        errors += [
                            f"{self._context(f'{path}.operation.appends_objects_to')}: the referenced edge collection cannot be included in any other action's operation"
                        ]

                    if str(action["id"]) in self._dependee_action_ids:
                        errors += [
                            f"{self._context(f'{path}.operation.appends_objects_to')}: if this property is specified, the parent action cannot be included in any checkpoint dependencies"
                        ]

                    # appender and appendee must have the same context
                    appends_from_context = (
                        action["context"] if "context" in action else None
                    )
                    appends_to_context = (
                        self._object_promise_contexts[appends_to_object_promise_id]
                        if appends_to_object_promise_id in self._object_promise_contexts
                        else None
                    )
                    if appends_from_context != appends_to_context:
                        errors += [
                            f"{self._context(f'{path}.operation.appends_objects_to')}: the action's context must match the context of the object promise referenced by this property ({appends_from_context} != {appends_to_context})"
                        ]

            else:
                # EDIT operation
                if "default_values" in operation:
                    errors += [
                        f"{self._context(f'{path}.operation.default_values')}: default values are not supported for EDIT operations"
                    ]
                if "default_edges" in operation:
                    errors += [
                        f"{self._context(f'{path}.operation.default_edges')}: default edges are not supported for EDIT operations"
                    ]
                if "appends_objects_to" in operation:
                    errors += [
                        f"{self._context(f'{path}.operation.appends_objects_to')}: this property is not supported for EDIT operations."
                    ]

                if (
                    object_promise_id not in self._object_promise_fulfillment_actions
                    or self.validate_has_ancestor(
                        path,
                        descendant_id=action_id,
                        descendant_type="action",
                        ancestor_ref=utils.as_ref(
                            self._object_promise_fulfillment_actions[object_promise_id],
                            "action",
                        ),
                    )
                    != []
                ):
                    errors += [
                        f"{self._context(f'{path}.operation')}: for EDIT operations, an ancestor of the action must fulfill the referenced object promise: {json.dumps(action['object_promise'])}"
                    ]

                # the context of the EDIT action must match the context of the action that fulfills the object promise
                context_error = [
                    f"{self._context(f'{path}')}: cannot edit an object promise outside of the context in which the object promise is fulfilled (fulfillment context: {json.dumps(self._object_promise_contexts[object_promise_id])})"
                ]
                if "context" in action:
                    if (
                        self._object_promise_contexts[object_promise_id]
                        != action["context"]
                    ):
                        errors += context_error
                elif self._object_promise_contexts[object_promise_id] != None:
                    errors += context_error

        return errors

    def _object_promise_fulfilled_by_ancestor(
        self, path, action, object_promise, guarantee_ancestry=False
    ):
        if "id" not in action or "id" not in object_promise:
            # object promise validation will have caught this already
            return True

        if str(object_promise["id"]) not in self._object_promise_fulfillment_actions:
            return False

        fulfiller_id = self._object_promise_fulfillment_actions[
            str(object_promise["id"])
        ]
        return (
            self.validate_has_ancestor(
                path,
                descendant_id=action["id"],
                descendant_type="action",
                ancestor_ref=utils.as_ref(fulfiller_id, "action", value_is_id=True),
                guarantee_ancestry=guarantee_ancestry,
            )
            == []
        )

    def validate_has_ancestor(
        self,
        path,
        descendant_id,
        descendant_type,
        ancestor_ref=None,
        ancestor_source=None,
        ancestor_ids=None,
        guarantee_ancestry=False,  # OR gates allow circumvention of actions, so ancestry is not guaranteed
    ):
        an_ancestor = "a guaranteed ancestor" if guarantee_ancestry else "an ancestor"
        error = [
            f"{self._context(path)}: the value of property {json.dumps(ancestor_source)} must reference {an_ancestor} of {descendant_type} id {json.dumps(descendant_id)}, got {json.dumps(ancestor_ref)}"
        ]

        descendant_id = str(descendant_id)
        if descendant_type == "action":
            if descendant_id not in self._action_checkpoints:
                # does the action have an implicit checkpoint?
                action = self._resolve_global_ref(
                    utils.as_ref(descendant_id, "action", value_is_id=True)
                )
                if not utils.has_reference_to_template_entity(
                    action, "context", "thread_group"
                ):
                    return error

                thread_group_id = utils.parse_ref_id(action["context"])
                if thread_group_id not in self._thread_group_checkpoints:
                    return error
                else:
                    # ancestors of the thread group are implicit ancestors of the action
                    descendant_type = "thread_group"
                    descendant_id = thread_group_id
        elif (
            descendant_type == "thread_group"
            and descendant_id not in self._thread_group_checkpoints
        ):
            return error

        if ancestor_ref is not None:
            if ancestor_ids is not None:
                raise Exception("cannot specify both ancestor_ref and ancestor_ids")
            ancestor_id = utils.parse_ref_id(ancestor_ref)
        else:
            ancestor_id = None
            if ancestor_ids is None:
                raise Exception("must specify either ancestor_ref or ancestor_ids")
            else:
                ancestor_ids.remove(
                    descendant_id
                )  # prevent circular dependency false positive

        def validate_has_ancestor_recursive(
            checkpoint_alias,
            ancestor_id,
            visited_checkpoints=[],
        ):
            if checkpoint_alias is None or checkpoint_alias in visited_checkpoints:
                return error

            if checkpoint_alias not in self._checkpoints:
                # pattern validation will have caught this
                return []

            visited_checkpoints.append(checkpoint_alias)
            checkpoint = self._checkpoints[checkpoint_alias]

            check_all_paths = (
                guarantee_ancestry
                and "gate_type" in checkpoint
                and checkpoint["gate_type"] == "OR"
            )
            for dependency in checkpoint["dependencies"]:
                if "compare" in dependency:
                    for referenced_action_id in [
                        utils.action_id_from_dependency_ref(dependency, "left"),
                        utils.action_id_from_dependency_ref(dependency, "right"),
                    ]:
                        if referenced_action_id is None:
                            continue

                        if referenced_action_id == ancestor_id:
                            if check_all_paths:
                                break
                            else:
                                return []

                        referenced_action_has_ancestor = (
                            str(referenced_action_id) not in self._action_checkpoints
                            or validate_has_ancestor_recursive(
                                self._action_checkpoints[str(referenced_action_id)],
                                ancestor_id,
                                visited_checkpoints,
                            )
                            == []
                        )

                        if check_all_paths:
                            if referenced_action_has_ancestor:
                                break

                            return error
                        elif referenced_action_has_ancestor:
                            return []
                        else:
                            return error

                elif utils.has_reference_to_template_entity(
                    dependency, "checkpoint", "checkpoint"
                ):
                    checkpoint_has_ancestor = (
                        validate_has_ancestor_recursive(
                            utils.parse_ref_id(dependency["checkpoint"]),
                            ancestor_id,
                            visited_checkpoints,
                        )
                        == []
                    )

                    if checkpoint_has_ancestor:
                        if check_all_paths:
                            continue

                        return []
                    elif check_all_paths:
                        return error
                else:
                    return error

            if check_all_paths:
                # if the error hasn't been returned yet,
                # all dependencies have the guaranteed ancestor
                return []
            else:
                # if [] hasn't been returned yet,
                # the ancestor was not found
                return error

        if descendant_type == "action":
            if (
                descendant_id not in self._action_checkpoints
                or self._action_checkpoints[descendant_id] is None
            ):
                return error

            checkpoint_alias = self._action_checkpoints[descendant_id]
        elif descendant_type == "thread_group":
            if descendant_id not in self._thread_group_checkpoints:
                return error

            checkpoint_alias = self._thread_group_checkpoints[descendant_id]
        else:
            raise Exception(
                f"cannot validate ancestry: invalid descendant type: {descendant_type}"
            )

        if ancestor_id is not None:
            return validate_has_ancestor_recursive(checkpoint_alias, ancestor_id)
        elif ancestor_ids is not None:
            # one of the ancestor ids must be an ancestor of the descendant
            for ancestor_id in ancestor_ids:
                if validate_has_ancestor_recursive(checkpoint_alias, ancestor_id) == []:
                    return []

        return error

    def validate_comparison(self, path, left, right, operator):
        if (
            self._validate_object("", left, obj_specs.literal_operand) == []
            and self._validate_object("", right, obj_specs.literal_operand) == []
        ):
            return [
                f"{self._context(path)}: invalid comparison: {left} {operator} {right}: both operands cannot be literals"
            ]

        if objects_are_identical(left, right):
            return [
                f"{self._context(path)}: invalid comparison: {left} {operator} {right}: operands are identical"
            ]

        def extract_field_type(path, operand_object):
            if "ref" in operand_object:
                resolution_context_thread_group_id = None
                # resolve checkpoint context from path
                if re.match("^root\.checkpoints\[\d+\]", ".".join(path.split(".")[:2])):
                    checkpoint = self._get_field(path.split(".")[:2])
                    if utils.has_reference_to_template_entity(
                        checkpoint, "context", "thread_group"
                    ):
                        resolution_context_thread_group_id = utils.parse_ref_id(
                            checkpoint["context"]
                        )

                if is_global_ref(operand_object["ref"]):
                    type_details = self._resolve_type_from_global_ref(
                        operand_object["ref"], resolution_context_thread_group_id
                    )
                elif is_variable(operand_object["ref"]):
                    # thread variable
                    ref_path = operand_object["ref"].split(".")
                    type_details = self._find_thread_variable(
                        ref_path[0], self._get_action_thread_scope(path)
                    )
                    if type_details is None:
                        raise Exception(
                            f"variable not found within thread scope: {json.dumps(ref_path[0])}"
                        )

                    if len(ref_path) > 1:
                        type_details = self._resolve_type_from_variable_path(
                            var_type_details=type_details,
                            path=ref_path[1:],
                        )

                return (
                    type_details.to_field_type_string()
                    if type_details is not None
                    else None
                )
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

        try:
            left_type = extract_field_type(path, left)
            right_type = extract_field_type(path, right)
        except Exception as e:
            return [f"{self._context(path)}: {str(e)}"]

        if types_are_comparable(left_type, right_type, operator):
            return []

        return [
            f"{self._context(path)}: invalid comparison: {left} {operator} {right} ({left_type} {operator} {right_type})"
        ]

    def validate_does_not_depend_on_aggregated_field(self, path, field):
        for operand in ["left", "right"]:
            if (
                operand not in field
                or not isinstance(field[operand], dict)
                or "ref" not in field[operand]
                or not utils.has_reference_to_template_entity(
                    field[operand], "ref", "action"
                )
            ):
                continue

            split_path = field[operand]["ref"].split(".")
            if len(split_path) != 3 or split_path[1] != "object_promise":
                # either it's not a valid ref (let validation catch it elsewhere),
                # or the ref points to a field on an edge,
                # so we can't know whether it will point to an aggregated field or not.
                continue

            action = self._resolve_global_ref(field[operand]["ref"])
            if not utils.has_reference_to_template_entity(
                action, "object_promise", "object_promise"
            ):
                continue

            object_promise = self._resolve_global_ref(action["object_promise"])
            if (
                object_promise is None
                or "id" not in object_promise
                or str(object_promise["id"]) not in self._aggregated_fields
                or split_path[2]
                not in self._aggregated_fields[str(object_promise["id"])]
            ):
                continue

            return [
                f"{self._context(path)}: cannot depend on aggregated field: {json.dumps(field[operand]['ref'])}"
            ]

        return []

    def validate_dependency_scope(self, path, field):
        # field is either an action or a thread
        if not utils.has_reference_to_template_entity(
            field, "depends_on", "checkpoint"
        ):
            return []

        checkpoint = self._resolve_global_ref(field["depends_on"])
        if not utils.has_reference_to_template_entity(
            checkpoint, "context", "thread_group"
        ):
            return []

        # checkpoint has threaded context -- it must be within the scope of field's context
        if not utils.has_reference_to_template_entity(field, "context", "thread_group"):
            return [
                f"{self._context(path + '.depends_on')}: checkpoint with threaded context referenced out of scope: {json.dumps(field['depends_on'])}"
            ]

        checkpoint_thread_group_id = utils.parse_ref_id(checkpoint["context"])
        field_thread_group_id = utils.parse_ref_id(field["context"])
        if not self._thread_groups[field_thread_group_id].has_access_to_context(
            checkpoint_thread_group_id
        ):
            return [
                f"{self._context(path + '.depends_on')}: checkpoint with threaded context referenced out of scope: {json.dumps(field['depends_on'])}"
            ]

        return []

    def validate_checkpoint_context(self, path, checkpoint):
        checkpoint_context = (
            utils.parse_ref_id(checkpoint["context"])
            if utils.has_reference_to_template_entity(
                checkpoint, "context", "thread_group"
            )
            else None
        )

        context_mismatches = []
        for dependency in checkpoint["dependencies"]:
            if utils.has_reference_to_template_entity(
                dependency, "checkpoint", "checkpoint"
            ):
                referenced_checkpoint = self._resolve_global_ref(
                    dependency["checkpoint"]
                )
                if referenced_checkpoint is None:
                    continue

                # if the referenced_checkpoint has a threaded context...
                if utils.has_reference_to_template_entity(
                    referenced_checkpoint, "context", "thread_group"
                ):
                    if checkpoint_context is None:
                        context_mismatches += [
                            f"{self._context(path)}: checkpoint with threaded context referenced out of scope: {json.dumps(dependency['checkpoint'])}"
                        ]
                    else:
                        # the threaded context must be the same as or a parent of the parent checkpoint's context
                        referenced_checkpoint_context = utils.parse_ref_id(
                            referenced_checkpoint["context"]
                        )

                        if not self._thread_groups[
                            checkpoint_context
                        ].has_access_to_context(referenced_checkpoint_context):
                            context_mismatches += [
                                f"{self._context(path)}: checkpoint with threaded context referenced out of scope: {json.dumps(dependency['checkpoint'])}"
                            ]
            elif "compare" in dependency:
                for operand in ["left", "right"]:
                    if operand not in dependency[
                        "compare"
                    ] or not utils.has_reference_to_template_entity(
                        dependency["compare"][operand], "ref", "action"
                    ):
                        continue

                    referenced_action = self._resolve_global_ref(
                        dependency["compare"][operand]["ref"]
                    )
                    if (
                        referenced_action is None
                        or not utils.has_reference_to_template_entity(
                            referenced_action, "context", "thread_group"
                        )
                    ):
                        continue

                    if checkpoint_context is None or not self._thread_groups[
                        checkpoint_context
                    ].has_access_to_context(
                        utils.parse_ref_id(referenced_action["context"])
                    ):
                        context_mismatches += [
                            f"{self._context(path)}: cannot depend on threaded action: {json.dumps(dependency['compare'][operand]['ref'])}"
                        ]

        return context_mismatches

    def validate_thread_group(self, path, thread_group):
        spawn = thread_group["spawn"] if "spawn" in thread_group else None
        if (
            spawn is None
            or "foreach" not in spawn
            or "as" not in spawn
            or "id" not in thread_group
        ):
            # there will already be validation errors for the missing field(s)
            return []

        def resolve_thread_scope_recursive(thread_group):
            # get the scope of the thread
            thread_group_id = str(thread_group["id"])
            if self._thread_groups[thread_group_id].scope is not None:
                return self._thread_groups[thread_group_id].scope

            if "context" not in thread_group:
                # it's a top-level thread
                self._thread_groups[thread_group_id].scope = thread_group_id
                return thread_group_id
            else:
                # it's a nested thread
                if is_global_ref(thread_group["context"]):
                    # resolve all parent threads first
                    parent_thread_group_id = utils.parse_ref_id(thread_group["context"])
                    if parent_thread_group_id not in self._thread_groups:
                        return None  # cannot resolve parent thread scope

                    if (
                        self._thread_groups[parent_thread_group_id].scope is None
                        and resolve_thread_scope_recursive(
                            thread_group=self._resolve_global_ref(
                                thread_group["context"]
                            )
                        )
                        is None
                    ):
                        return None  # could not resolve parent thread scope

                    # record the thread and set its scope
                    scope = f"{self._thread_groups[parent_thread_group_id].scope}.{thread_group_id}"
                    self._thread_groups[thread_group_id].scope = scope

                    return scope

                return None  # cannot resolve scope

        errors = []

        scope = resolve_thread_scope_recursive(thread_group)
        if scope is None:
            return [f"{self._context(path)}: could not resolve thread scope"]

        thread_group_id = str(thread_group["id"])
        if is_global_ref(spawn["foreach"]):
            # if the global ref is an action, it must be an ancestor of the thread
            if utils.parse_ref_type(spawn["foreach"]) == "object_promise":
                errors += self.validate_has_ancestor(
                    path,
                    descendant_id=thread_group_id,
                    descendant_type="thread_group",
                    ancestor_ref=spawn["foreach"],
                    ancestor_source="spawn.foreach",
                )

                if errors:
                    return errors
            try:
                resolution_context_thread_group_id = (
                    utils.parse_ref_id(thread_group["context"])
                    if utils.has_reference_to_template_entity(
                        thread_group, "context", "thread_group"
                    )
                    else None
                )
                thread_variable_type = self._resolve_type_from_global_ref(
                    spawn["foreach"], resolution_context_thread_group_id
                )
            except Exception as e:
                return [f"{self._context(path)}.spawn.foreach: {str(e)}"]

        elif is_variable(spawn["foreach"]):
            from_path = spawn["foreach"].split(".")
            var_name = from_path[0]

            from_var_type_details = self._find_thread_variable(var_name, scope)

            if from_var_type_details is None:
                return [
                    f"{self._context(path)}.spawn.foreach: variable not found within thread scope: {json.dumps(var_name)}"
                ]

            # if there's a path, resolve it from the variable's type
            if len(path) > 1:
                try:
                    thread_variable_type = self._resolve_type_from_variable_path(
                        var_type_details=from_var_type_details,
                        path=from_path[1:],
                    )
                except Exception as e:
                    return [f"{self._context(path)}.spawn.foreach: {str(e)}"]
            else:
                thread_variable_type = from_var_type_details
        else:
            return [
                f"{self._context(path)}.spawn.foreach: expected global ref or thread variable, got {json.dumps(spawn['foreach'])}"
            ]

        if thread_variable_type is None:
            errors += [
                f"{self._context(path)}.spawn.foreach: could not resolve variable type: {json.dumps(spawn['foreach'])}"
            ]
        elif not thread_variable_type.is_list:
            errors += [
                f"{self._context(path)}.spawn.foreach: cannot spawn threads from a non-list object"
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
            thread_variable_type.is_list = False
            # record the variable type
            self._thread_groups[thread_group_id].variables[
                var_name
            ] = thread_variable_type

        return errors

    def _get_action_thread_scope(self, path):
        action = self._get_parent_action(path)
        if action is not None and utils.has_reference_to_template_entity(
            action, "context", "thread_group"
        ):
            thread_group_id = utils.parse_ref_id(action["context"])
            if thread_group_id in self._thread_groups:
                return self._thread_groups[thread_group_id].scope

        return None

    def _find_thread_variable(self, var_name, scope, check_nested_scopes=False):
        if scope is None:
            return None

        # check the current scope
        thread_path = scope.split(".")
        thread_path.reverse()
        for thread_group_id in thread_path:
            if thread_group_id not in self._thread_groups:
                break

            thread_context = self._thread_groups[thread_group_id]
            if var_name in thread_context.variables:
                return thread_context.variables[var_name]

        if check_nested_scopes:

            def check_nested_scopes_recursive(thread_group_id):
                for sub_thread_group_id in self._thread_groups[
                    thread_group_id
                ].sub_thread_group_ids:
                    sub_thread_context = self._thread_groups[sub_thread_group_id]

                    if var_name in sub_thread_context.variables:
                        return sub_thread_context.variables[var_name]

                    if sub_thread_context.sub_thread_group_ids:
                        return check_nested_scopes_recursive(sub_thread_group_id)

            return check_nested_scopes_recursive(thread_group_id)

        return None

    def _record_settable_fields(self, action):
        if (
            "id" not in action
            or "operation" not in action
            or not utils.has_reference_to_template_entity(
                action, "object_promise", "object_promise"
            )
        ):
            return

        object_promise = self._resolve_global_ref(action["object_promise"])
        if (
            object_promise is None
            or "id" not in object_promise
            or "object_type" not in object_promise
            or object_promise["object_type"] not in self.schema["object_types"]
        ):
            return

        object_promise_id = str(object_promise["id"])
        object_definition = self.schema["object_types"][object_promise["object_type"]]
        operation = action["operation"]

        if object_promise_id not in self._settable_fields:
            self._settable_fields[object_promise_id] = set()

        if "include" in operation:
            if isinstance(operation["include"], list):
                for field_name in operation["include"]:
                    if field_name in object_definition:
                        self._settable_fields[object_promise_id].add(field_name)
        elif "exclude" in operation:
            if operation["exclude"] is None:
                # include all fields
                for field_name in object_definition:
                    self._settable_fields[object_promise_id].add(field_name)
            elif isinstance(operation["exclude"], list):
                # deduce included fields
                for field_name in object_definition:
                    if field_name not in operation["exclude"]:
                        self._settable_fields[object_promise_id].add(field_name)

        # default_values can be used to set values
        if "default_values" in operation:
            if isinstance(operation["default_values"], dict):
                for field_name in operation["default_values"]:
                    if field_name in object_definition:
                        self._settable_fields[object_promise_id].add(field_name)

        # default_edges can be used to set values
        if "default_edges" in operation:
            if isinstance(operation["default_edges"], dict):
                for field_name in operation["default_edges"]:
                    if (
                        field_name in object_definition
                        and object_definition[field_name]["field_type"] == "EDGE"
                    ):
                        self._settable_fields[object_promise_id].add(field_name)

    def validate_pipeline(self, path, field):
        if not utils.has_reference_to_template_entity(
            field, "object_promise", "object_promise"
        ):
            # there will already be validation errors for the missing field
            return []

        object_promise = self._resolve_global_ref(field["object_promise"])
        if object_promise is None:
            return [
                f"{self._context(path)}.object_promise: could not resolve object promise"
            ]
        if "id" not in object_promise:
            # there will already be validation errors for the missing field
            return []

        object_promise_context = self._object_promise_contexts[
            str(object_promise["id"])
        ]
        pipeline = Pipeline(
            object_promise_ref=field["object_promise"],
            thread_scope=self._thread_groups[
                utils.parse_ref_id(object_promise_context)
            ].scope
            if utils.is_global_ref(object_promise_context)
            else None,
        )
        self._pipelines[path] = pipeline

        pipeline_scope = "0"
        errors = []

        if "variables" in field and isinstance(field["variables"], list):
            for i in range(len(field["variables"])):
                var = field["variables"][i]

                # check for pipeline variable name collision
                if pipeline.get_variable(var["name"], pipeline_scope):
                    errors += [
                        f"{self._context(f'{path}.variables[{str(i)}].name')}: variable already defined: {json.dumps(var['name'])}"
                    ]
                    continue

                # check for collision with scoped thread variables
                if self._find_thread_variable(var["name"], pipeline.thread_scope):
                    errors += [
                        f"{self._context(f'{path}.variables[{str(i)}].name')}: variable already defined within thread scope: {json.dumps(var['name'])}"
                    ]
                    continue

                try:
                    initial_type_details = (
                        pipeline_utils.field_type_details_from_scalar(
                            value=var["initial"],
                            expected_type=var["type"],
                        )
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

                pipeline.set_variable(
                    pipeline_scope,
                    var["name"],
                    PipelineVariable(
                        type_details=initial_type_details,
                        initial=var["initial"],
                        assigned=False,
                    ),
                )

        if not errors and "traverse" in field and isinstance(field["traverse"], list):
            for i in range(len(field["traverse"])):
                errors += self._validate_pipeline_traversal_recursive(
                    path,
                    pipeline_scope,
                    traversal=field["traverse"][i],
                    traversal_index=i,
                )

        if not errors and "apply" in field and isinstance(field["apply"], list):
            for i in range(len(field["apply"])):
                errors += self._validate_pipeline_application(
                    f"{path}.apply[{str(i)}]",
                    pipeline_scope,
                    apply=field["apply"][i],
                )

        if not errors and "output" in field and isinstance(field["output"], list):
            for i in range(len(field["output"])):
                errors += self._validate_pipeline_output(
                    f"{path}.output[{str(i)}]",
                    output_obj=field["output"][i],
                )

        # were any variables declared but not used?
        for variables in pipeline.variables.values():
            for var_name, var in variables.items():
                if var.is_loop_variable or var.assigned or var.used:
                    continue

                self.warnings.append(
                    f"{self._context(path)}: variable declared but not used: {json.dumps(var_name)}"
                )

        return errors

    def _validate_pipeline_traversal_recursive(
        self, path, pipeline_scope, traversal, traversal_index
    ):
        if "ref" not in traversal or "foreach" not in traversal:
            # there will already be validation errors for the missing fields,
            # and we cannot validate further without them.
            return []

        pipeline = self._get_pipeline_at_path(path)
        path = f"{path}.traverse[{str(traversal_index)}]"
        pipeline_scope = f"{pipeline_scope}.{traversal_index}"

        errors = []

        # resolve the ref type
        ref = traversal["ref"]
        ref_path = ref.split(".")
        if is_variable(ref_path[0]):
            var_name = ref_path[0]
            pipeline_var = pipeline.get_variable(var_name, pipeline_scope)
            if pipeline_var is not None:
                var_type_details = pipeline_var.type_details
                # You may be asking, "What if it's not a loop variable? How can a non-loop variable be used as a traversal ref?"
                # While it's true that such a variable will not have been assigned a value,
                # it may be initialized as a traversable list of values.
                # Note, however, that a traversed variable may not be modified within the traversal or its nested scopes.
                pipeline_var.used = True
                pipeline_var.traversal_scopes.add(pipeline_scope)
            else:
                # look for a thread variable in the current scope
                parent_action = self._get_parent_action(path)
                if "context" in parent_action:
                    parent_thread_group_id = utils.parse_ref_id(
                        parent_action["context"]
                    )
                    var_type_details = self._find_thread_variable(
                        var_name, self._thread_groups[parent_thread_group_id].scope
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
            local_input_error = [
                f"{self._context(f'{path}.ref')}: cannot use field from local object as pipeline input"
            ]

            parent_action = self._get_parent_action(path)
            if is_global_ref(ref):
                # warn if the global ref refers to the local object
                if utils.has_reference_to_template_entity(
                    traversal, "ref", "object_promise"
                ) and utils.parse_ref_id(ref) == utils.parse_ref_id(
                    pipeline.object_promise_ref
                ):
                    self.warnings.append(
                        f'{self._context(f"{path}.ref")}: global ref refers to the local object -- consider using "$_object" instead to reference the local object'
                    )

                    return local_input_error

                ref_type_details = self._resolve_type_from_global_ref(
                    ref,
                    resolution_context_thread_group_id=pipeline.get_thread_group_id(),
                )

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
                return local_input_error
            else:
                return [
                    f"{self._context(f'{path}.ref')}: "
                    + f"expected global reference, local reference, or variable, got {json.dumps(ref)}"
                ]

        item_name = traversal["foreach"]["as"]
        if pipeline.get_variable(item_name, pipeline_scope) is not None:
            return [
                f"{self._context(f'{path}.foreach.as')}: variable already defined within pipeline scope: {item_name}"
            ]
        elif self._find_thread_variable(item_name, pipeline.thread_scope) is not None:
            return [
                f"{self._context(f'{path}.foreach.as')}: variable already defined within thread scope: {item_name}"
            ]

        # de-listify, because the traversal iterates over the items
        ref_type_details.is_list = False

        pipeline.set_variable(
            pipeline_scope,
            item_name,
            PipelineVariable(
                type_details=ref_type_details,
                assigned=True,  # loop variables are automatically assigned a value
                is_loop_variable=True,
            ),
        )

        if "variables" in traversal["foreach"]:
            for i in range(len(traversal["foreach"]["variables"])):
                var = traversal["foreach"]["variables"][i]

                if pipeline.get_variable(var["name"], pipeline_scope) is not None:
                    return [
                        f"{self._context(f'{path}.foreach.variables[{str(i)}].name')}: variable already defined: {var['name']}"
                    ]

                initial_type_details = pipeline_utils.field_type_details_from_scalar(
                    value=var["initial"],
                    expected_type=var["type"],
                )

                if not pipeline_utils.initial_matches_type(
                    initial_type_details, var["type"]
                ):
                    return [
                        f"{self._context(f'{path}.foreach.variables[{str(i)}].initial')}: does not match expected type {var['type']}"
                    ]

                pipeline.set_variable(
                    pipeline_scope,
                    var["name"],
                    PipelineVariable(
                        type_details=initial_type_details,
                        initial=var["initial"],
                        assigned=False,
                    ),
                )

        if "traverse" in traversal["foreach"]:
            for i in range(len(traversal["foreach"]["traverse"])):
                errors += self._validate_pipeline_traversal_recursive(
                    f"{path}.foreach",
                    pipeline_scope=pipeline_scope,
                    traversal=traversal["foreach"]["traverse"][i],
                    traversal_index=i,
                )

        if "apply" in traversal["foreach"]:
            for i in range(len(traversal["foreach"]["apply"])):
                errors += self._validate_pipeline_application(
                    f"{path}.foreach.apply[{str(i)}]",
                    pipeline_scope,
                    apply=traversal["foreach"]["apply"][i],
                )

        return errors

    def resolve_ref_type_details(
        self,
        path,
        ref,
        pipeline_scope,
        resolution_context_thread_group_id=None,
        var_is_being_used=False,
    ):
        from_path = ref.split(".")
        if is_variable(from_path[0]):
            var_name = from_path[0]
            var_type_details = None

            pipeline = self._get_pipeline_at_path(path)
            pipeline_var = pipeline.get_variable(var_name, pipeline_scope)
            if pipeline_var is not None:
                if not pipeline_var.assigned:
                    self.warnings.append(
                        f"{self._context(f'{path}.from')}: variable used before assignment: {json.dumps(var_name)}"
                    )

                var_type_details = pipeline_var.type_details
                if var_is_being_used:
                    pipeline_var.used = True
            else:
                var_type_details = self._find_thread_variable(
                    var_name, pipeline.thread_scope
                )

            if var_type_details is None:
                raise Exception(
                    f"variable not found in pipeline scope: {json.dumps(var_name)}"
                )

            if len(from_path) > 1:
                return self._resolve_type_from_variable_path(
                    var_type_details=var_type_details,
                    path=from_path[1:],
                )
            else:
                return copy.deepcopy(var_type_details)
        elif re.match(patterns.local_variable, ref):
            return self._resolve_type_from_local_ref(ref, path=path)
        elif is_global_ref(ref) and utils.parse_ref_type(ref) == "object_promise":
            # global ref

            return self._resolve_type_from_global_ref(
                ref, resolution_context_thread_group_id
            )
        else:
            # pattern validation will have already caught this
            return None

    def _validate_pipeline_application(self, path, pipeline_scope, apply):
        if "from" not in apply or "to" not in apply or "method" not in apply:
            # there will already be validation errors for the missing fields,
            # and we cannot validate further without them.
            return []

        pipeline = self._get_pipeline_at_path(path)

        # is apply["from"] a global reference to the local object?
        local_input_error = [
            f"{self._context(f'{path}.from')}: cannot use local object as pipeline input"
        ]
        if utils.has_reference_to_template_entity(apply, "from", "object_promise"):
            object_promise = self._resolve_global_ref(apply["from"])
            if (
                object_promise is not None
                and "id" in object_promise
                and utils.parse_ref_id(apply["from"])
                == utils.parse_ref_id(pipeline.object_promise_ref)
            ):
                self.warnings.append(
                    f'{self._context(f"{path}.from")}: global ref refers to the local object -- consider using "$_object" instead to reference the local object.'
                )

                return local_input_error
        elif is_local_variable(apply["from"]):
            return local_input_error

        try:
            ref_type_details = self.resolve_ref_type_details(
                path,
                ref=apply["from"],
                pipeline_scope=pipeline_scope,
                resolution_context_thread_group_id=pipeline.get_thread_group_id(),
                var_is_being_used=True,
            )
        except Exception as e:
            return [f"{self._context(f'{path}.from')}: {str(e)}"]

        if ref_type_details is None:
            return [f"{self._context(f'{path}.from')}: could not resolve type"]

        self._type_details_at_path[path + ".from"] = ref_type_details

        to_var_name = apply["to"]
        if not is_variable(to_var_name):
            # pattern validation will have already caught this
            return []

        to_pipeline_var = pipeline.get_variable(to_var_name, pipeline_scope)
        if to_pipeline_var is None:
            if (
                self._find_thread_variable(to_var_name, pipeline.thread_scope)
                is not None
            ):
                return [
                    f"{self._context(f'{path}.to')}: cannot assign to thread variable: {json.dumps(to_var_name)}"
                ]

            return [
                f"{self._context(f'{path}.to')}: pipeline variable not found in scope: {json.dumps(to_var_name)}"
            ]

        if to_pipeline_var.is_loop_variable:
            return [
                f"{self._context(f'{path}.to')}: cannot assign to loop variable: {json.dumps(to_var_name)}"
            ]

        for traversal_scope in to_pipeline_var.traversal_scopes:
            if pipeline_scope.startswith(traversal_scope):
                return [
                    f"{self._context(f'{path}.to')}: cannot apply to variable within a scope that traverses it: {json.dumps(to_var_name)}"
                ]

        left_operand_type = to_pipeline_var.type_details
        left_operand_is_null = (
            not to_pipeline_var.assigned and to_pipeline_var.initial is None
        )

        try:
            right_operand_type = pipeline_utils.determine_right_operand_type(
                path,
                apply,
                ref_type_details,
                pipeline_scope,
                resolution_context_thread_group_id=pipeline.get_thread_group_id(),
                schema_validator=self,
            )

            pipeline_utils.validate_operation(
                left_operand_type,
                apply["method"],
                right_operand_type,
                left_operand_is_null,
            )

            to_pipeline_var.assigned = True

            # if necessary, set the item_tag
            if to_pipeline_var.type_details.item_tag is None:
                if (
                    to_pipeline_var.type_details.item_type in ["OBJECT", "OBJECT_LIST"]
                    and right_operand_type.item_tag is not None
                ):
                    to_pipeline_var.type_details.item_tag = right_operand_type.item_tag
            elif to_pipeline_var.type_details.item_tag != right_operand_type.item_tag:
                return [
                    f"{self._context(f'{path}.to')}: cannot assign object of type {json.dumps(right_operand_type.item_tag)} to a variable that has object type {json.dumps(to_pipeline_var.item_tag)}"
                ]
        except Exception as e:
            return [f"{self._context(path)}: {str(e)}"]

        return []

    def _validate_pipeline_output(self, path, output_obj):
        pipeline = self._get_pipeline_at_path(path)
        errors = []

        # output.from must be a pipeline variable from the top-level scope
        from_var = None
        if "from" in output_obj and is_variable(output_obj["from"]):
            from_var = pipeline.get_variable(
                var_name=output_obj["from"],
                within_scope="0",  # top-level scope
            )
            if from_var is None:
                errors += [
                    f"{self._context(f'{path}.from')}: variable not found in top-level pipeline scope: {output_obj['from']}"
                ]
            else:
                from_var.used = True

        if pipeline.object_promise_ref is None:
            # can't validate further without the object promise
            return errors

        # output.to must be a field on the promised object
        object_promise = self._resolve_global_ref(pipeline.object_promise_ref)
        if object_promise is not None:
            if (
                "to" in output_obj
                and "object_type" in object_promise
                and object_promise["object_type"] in self.schema["object_types"]
            ):
                if "id" in object_promise:
                    if str(object_promise["id"]) not in self._aggregated_fields:
                        self._aggregated_fields[str(object_promise["id"])] = set()

                    self._aggregated_fields[str(object_promise["id"])].add(
                        output_obj["to"]
                    )

                field_type = self._resolve_type_from_object_path(
                    object_tag=object_promise["object_type"], path=output_obj["to"]
                )
                if field_type is None:
                    errors += [
                        f"{self._context(f'{path}.to')}: field {json.dumps(output_obj['to'])} not found on object type: {object_promise['object_type']}"
                    ]
                elif from_var is not None:
                    if not field_type.matches_type(from_var.type_details):
                        errors += [
                            f'{self._context(path)}: "from" type does not match "to" type ({from_var.type_details.to_string()} != {field_type.to_string()})'
                        ]

            # aggregation output fields cannot be made settable by action operations
            if (
                "id" in object_promise
                and str(object_promise["id"]) in self._settable_fields
                and output_obj["to"] in self._settable_fields[str(object_promise["id"])]
            ):
                errors += [
                    f"{self._context(f'{path}.to')}: cannot use field for aggregation output because the field is included in an action's operation"
                ]

        return errors

    def _get_pipeline_at_path(self, path):
        split_path = path.split(".")
        if split_path[0] != "root" or not re.match("^pipelines\[\d+\]$", split_path[1]):
            return None

        return self._pipelines[f"{split_path[0]}.{split_path[1]}"]

    def _resolve_type_from_variable_path(self, var_type_details, path):
        if var_type_details.item_type == "OBJECT":
            # resolve the type on the object definition
            return self._resolve_type_from_object_path(
                object_tag=var_type_details.item_tag,
                path=path,
            )
        elif utils.is_global_ref(var_type_details.item_type):
            referenced_object = self._resolve_global_ref(var_type_details.item_type)
            if path[0] != "object_promise":
                raise NotImplementedError(
                    "global ref resolution not implemented for action properties"
                )

            return self._resolve_type_from_object_path(
                object_tag=self._resolve_tag_from_action(referenced_object),
                path=path[1:],
            )
        elif path:
            raise Exception(
                f"cannot resolve path from non-object type: {var_type_details.to_string()}"
            )

        return var_type_details

    def _resolve_type_from_global_ref(
        self, ref, resolution_context_thread_group_id=None
    ):
        type_details = None
        if re.match(patterns.global_id_ref, ref):
            matches = re.findall(patterns.global_id_ref, ref)
        elif re.match(patterns.global_alias_ref, ref):
            matches = re.findall(patterns.global_alias_ref, ref)

        if len(matches) and len(matches[0]):
            global_ref = matches[0][0]
            ref_type = matches[0][1]
            path_from_ref = matches[0][2]

            if ref_type == "action":
                split_path = path_from_ref.split(".")
                if split_path[0] != "object_promise":
                    raise NotImplementedError(
                        "global ref resolution not implemented for action properties"
                    )

                action = self._resolve_global_ref(global_ref)
                if action is None or not utils.has_reference_to_template_entity(
                    action, "object_promise", "object_promise"
                ):
                    return None

                # convert to object promise resolution format
                global_ref = action["object_promise"]
                path_from_ref = ".".join(split_path[1:])

            elif ref_type != "object_promise":
                raise NotImplementedError(
                    "global ref resolution not implemented for ref type: " + ref_type
                )

            return self._resolve_type_from_object_promise_ref(
                global_ref,
                path_from_ref,
                resolution_context_thread_group_id,
            )

        return type_details

    def _resolve_type_from_object_promise_ref(
        self, global_ref, path_from_ref, resolution_context_thread_group_id
    ):
        object_promise = self._resolve_global_ref(global_ref)
        # If the object promise's context is part of the resolution_context_thread_group_id scope,
        # then we are dealing with a single threaded object promise
        # that is being referenced from within the thread.
        # Otherwise we are dealing with a list of object promises, because the promise is
        # fulfilled in the context of a thread.
        object_promise_id = str(object_promise["id"])
        if object_promise_id not in self._object_promise_contexts:
            # cannot resolve type
            return None

        # resolution_context_thread_group_id is the context from which we are resolving the object promise ref
        object_promise_context = (
            self._object_promise_contexts[object_promise_id]
            if object_promise_id in self._object_promise_contexts
            else None
        )
        object_promise_context_id = (
            utils.parse_ref_id(object_promise_context)
            if is_global_ref(object_promise_context)
            else None
        )
        is_list_of_object_promises = object_promise_context_id is not None and (
            resolution_context_thread_group_id not in self._thread_groups
            or not self._thread_groups[
                resolution_context_thread_group_id
            ].has_access_to_context(object_promise_context_id)
        )

        type_details = None
        if len(path_from_ref):
            type_details = self._resolve_type_from_object_path(
                object_tag=object_promise["object_type"],
                path=path_from_ref,
            )
            if is_list_of_object_promises:
                if type_details.is_list:
                    raise Exception("nested list types are not supported")

                type_details.is_list = True
        elif (
            "object_type" in object_promise
            and object_promise["object_type"] in self.schema["object_types"]
        ):
            type_details = FieldTypeDetails(
                is_list=is_list_of_object_promises,
                item_type="OBJECT",
                item_tag=object_promise["object_type"],
            )
        else:
            raise Exception(
                f"could not resolve object type of object promise: {object_promise_id}"
            )

        return type_details

    def _resolve_type_from_local_ref(self, local_ref, obj=None, path=None):
        if obj is None:
            if path is None:
                raise Exception("Must provide either obj or path")

            obj = self._get_field(path.split(".")[:2])  # root.action[idx]

        # what are the possible types of local_ref?
        split_ref = local_ref.split(".")
        if split_ref[0] == "$_object":
            return self._resolve_type_from_object_path(
                obj["object_type"], split_ref[1:]
            )
            # follow the path to resolve edges/edge collections until the last item
        elif split_ref[0] == "$_party":
            # obj = self._resolve_party(obj["object_type"])
            raise NotImplementedError("local ref type not implemented: " + split_ref[0])
        else:
            raise NotImplementedError("local ref type not implemented: " + split_ref[0])

    def _resolve_type_from_filter_ref(self, filter_ref, path):
        # The apply.from type details should already have been resolved
        # according to the specified property_validation_priority,
        # so the path can be used to access those type details.
        split_path = path.split(".")
        while not re.match("^apply\[(\d+)\]$", split_path[-1]):
            split_path.pop()

        path_to_collection = ".".join(split_path) + ".from"
        if path_to_collection not in self._type_details_at_path:
            return None

        from_type_details = self._type_details_at_path[path_to_collection]

        if not from_type_details.is_list:
            # validation will already have caught this
            return None

        # de-listify, because the filter iterates over the collection
        type_details = copy.deepcopy(from_type_details)
        type_details.is_list = False

        # resolve the path
        split_filter_ref = filter_ref.split(".")
        if len(split_filter_ref) > 1:
            if type_details.item_tag is None:
                return None

            return self._resolve_type_from_object_path(
                object_tag=type_details.item_tag,
                path=split_filter_ref[1:],
            )

        return type_details

    def _resolve_tag_from_action(self, action):
        if not utils.has_reference_to_template_entity(
            action, "object_promise", "object_promise"
        ):
            return None

        object_promise = self._resolve_global_ref(action["object_promise"])
        if object_promise is None or "object_type" not in object_promise:
            return None

        return object_promise["object_type"]

    def _resolve_type_from_object_path(self, object_tag, path):
        object_definition = self._get_field("root.object_types." + object_tag)

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
                        "root.object_types." + field_definition["object_type"]
                    )

                    if field_definition["field_type"] == "EDGE_COLLECTION":
                        if type_details.is_list:
                            raise Exception("nested list types are not supported")

                        type_details = FieldTypeDetails(
                            is_list=True,
                            item_type="OBJECT",
                            item_tag=field_definition["object_type"],
                        )
                    elif field_definition["field_type"] == "EDGE":
                        type_details = FieldTypeDetails(
                            is_list=type_details.is_list,
                            item_type="OBJECT",
                            item_tag=field_definition["object_type"],
                        )
                elif "_LIST" in field_definition["field_type"]:
                    if type_details.is_list:
                        raise Exception("nested list types are not supported")

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

    def _validate_expected_value(self, path, field, obj_spec, parent_obj_spec):
        obj_spec_vars = (
            parent_obj_spec["obj_spec_vars"]
            if parent_obj_spec and "obj_spec_vars" in parent_obj_spec
            else {}
        )

        if "one_of" in obj_spec["expected_value"]:
            # looking for any matching value
            one_of = copy.deepcopy(obj_spec["expected_value"]["one_of"])
            one_of["from"] = ".".join(
                self._resolve_path_variables(
                    path, one_of["from"].split("."), obj_spec_vars
                )
            )

            return self._object_or_array_contains(path, field, one_of)

        else:

            def extract_value_from_referenced_object(ref_details):
                if "from_ref" not in ref_details or "extract" not in ref_details:
                    raise Exception(
                        "invalid referenced_value spec: " + str(ref_details)
                    )

                ref = self._get_field(
                    self._resolve_path_variables(
                        path, ref_details["from_ref"].split("."), obj_spec_vars
                    )
                )
                referenced_object = self._resolve_global_ref(ref)

                return self._get_field(ref_details["extract"], referenced_object)

            if "referenced_value" in obj_spec["expected_value"]:
                expected_value = extract_value_from_referenced_object(
                    obj_spec["expected_value"]["referenced_value"]
                )

                if field == expected_value:
                    return []
                else:
                    return [
                        f"{self._context(path)}: expected {expected_value}, got {json.dumps(field)}"
                    ]

            elif "equivalent_ref" in obj_spec["expected_value"]:
                ref = extract_value_from_referenced_object(
                    obj_spec["expected_value"]["equivalent_ref"]
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
                    "expected_value spec not implemented: " + str(obj_spec)
                )

    def _validate_ref(self, path, field, obj_spec, parent_obj_spec=None):
        if "local_ref" in obj_spec["ref_types"] and is_local_variable(field):
            referenced_object_type = self._resolve_type_from_local_ref(
                local_ref=field, path=path
            )
        elif "filter_ref" in obj_spec["ref_types"] and is_filter_ref(field):
            referenced_object_type = self._resolve_type_from_filter_ref(
                filter_ref=field, path=path
            )
        else:
            if not is_global_ref(field):
                return [f"{self._context(path)}: expected ref, got {json.dumps(field)}"]

            ref_type = utils.parse_ref_type(field)
            if ref_type not in obj_spec["ref_types"]:
                return [
                    f"{self._context(path)}: invalid ref type: expected one of {json.dumps(obj_spec['ref_types'])}, got {json.dumps(ref_type)}"
                ]

            # TODO: the following line should resolve to a type, not an object.
            # It doesn't make a difference at the moment, but it will.
            referenced_object_type = self._resolve_global_ref(field)

        if referenced_object_type is None:
            return [
                f"{self._context(path)}: invalid ref: object not found: {json.dumps(field)}"
            ]

        if "expected_value" in obj_spec:
            return self._validate_expected_value(path, field, obj_spec, parent_obj_spec)

        return []

    def _resolve_global_ref(self, ref):
        if ref is None:
            return None

        is_alias_reference = re.match(patterns.global_alias_ref, ref)
        ref_id = utils.parse_ref_id(ref)
        ref_type = utils.parse_ref_type(ref)
        ref_config = getattr(obj_specs, ref_type)["ref_config"]

        if "collection" not in ref_config or (
            is_alias_reference and "alias_field" not in ref_config
        ):
            return None

        collection = self._get_field(ref_config["collection"])
        if collection is None:
            return None

        if is_alias_reference:
            ref_field = ref_config["alias_field"]
        else:
            ref_field = "id"

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

    def _validate_scalar(self, path, field, obj_spec=None, parent_obj_spec=None):
        if field is None:
            return []

        valid_types = ["string", "decimal", "boolean", "string_list", "numeric_list"]

        for scalar_type in valid_types:
            if (
                getattr(self, "_validate_" + scalar_type)(
                    path, field, obj_spec, parent_obj_spec
                )
                == []
            ):
                return []

        return [f"{self._context(path)}: expected scalar, got {str(type(field))}"]

    def _validate_decimal(self, path, field, obj_spec=None, parent_obj_spec=None):
        if (isinstance(field, float) or isinstance(field, int)) and not isinstance(
            field, bool
        ):
            return []

        return [f"{self._context(path)}: expected decimal, got {str(type(field))}"]

    def _validate_integer(self, path, field, obj_spec=None, parent_obj_spec=None):
        if isinstance(field, int) and not isinstance(field, bool):
            return []

        return [f"{self._context(path)}: expected integer, got {str(type(field))}"]

    def _validate_string(self, path, field, obj_spec=None, parent_obj_spec=None):
        if not isinstance(field, str):
            return [f"{self._context(path)}: expected string, got {str(type(field))}"]

        if "patterns" in obj_spec:
            for pattern in obj_spec["patterns"]:
                if not re.match(pattern["regex"], field):
                    pattern_description = (
                        f'{pattern["description"]} ' if "description" in pattern else ""
                    )
                    return [
                        f"{self._context(path)}: string does not match {pattern_description}pattern: {pattern['regex']}"
                    ]

        if "expected_value" in obj_spec:
            return self._validate_expected_value(path, field, obj_spec, parent_obj_spec)

        return []

    def _validate_integer_string(
        self, path, field, obj_spec=None, parent_obj_spec=None
    ):
        # Allow string representations of negative integers, e.g. "-1"
        if str(field)[0] == "-":
            field = str(field)[1:]

        if not str(field).isdigit():
            return [
                f"{self._context(path)}: expected a string representation of an integer, got {str(type(field))}"
            ]

        return []

    def _validate_boolean(self, path, field, obj_spec=None, parent_obj_spec=None):
        if isinstance(field, bool):
            return []

        return [f"{self._context(path)}: expected boolean, got {str(type(field))}"]

    def _validate_string_list(self, path, field, obj_spec=None, parent_obj_spec=None):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected list, got {str(type(field))}"]

        for item in field:
            if not isinstance(item, str):
                return [
                    f"{self._context(path)}: expected list of strings, found {str(type(item))}"
                ]

        return []

    def _validate_numeric_list(self, path, field, obj_spec=None, parent_obj_spec=None):
        if not isinstance(field, list):
            return [f"{self._context(path)}: expected list, got {str(type(field))}"]

        for item in field:
            if self._validate_decimal("", item) != []:
                return [
                    f"{self._context(path)}: expected list of numbers, found {str(type(item))}"
                ]

        return []

    def _field_is_required(self, key, obj_spec):
        if "constraints" not in obj_spec:
            return True  # default to required

        if (
            "optional" in obj_spec["constraints"]
            and key in obj_spec["constraints"]["optional"]
        ) or (
            "forbidden" in obj_spec["constraints"]
            and key in obj_spec["constraints"]["forbidden"]["properties"]
        ):
            return False

        return True

    def _field_is_forbidden(self, key, obj_spec):
        return "forbidden" in obj_spec and key in obj_spec["forbidden"]

    def _validate_min_length(self, path, field, obj_spec):
        if "constraints" not in obj_spec or "min_length" not in obj_spec["constraints"]:
            return []

        if len(field) < obj_spec["constraints"]["min_length"]:
            return [
                f"{self._context(path)}: must contain at least {obj_spec['constraints']['min_length']} item(s), got {len(field)}"
            ]

        return []

    def _validate_unique(self, path, field, obj_spec):
        if not isinstance(field, list) and not isinstance(field, dict):
            raise NotImplementedError(
                "unique validation not implemented for type " + str(type(field))
            )

        constraints = obj_spec["constraints"] if "constraints" in obj_spec else {}
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
                    if self._bypass_validation_of_object(obj_spec["values"], item):
                        # avoid psuedo-checkpoint errors
                        continue

                    unique_obj = {}
                    for prop in field_name:
                        if prop in item:
                            unique_obj[prop] = item[prop]

                    obj_hash = hash_sorted_object(unique_obj)

                    unique_values[obj_hash] = obj_hash not in unique_values
                    hash_map[obj_hash] = unique_obj
            else:
                for item in field if isinstance(field, list) else field.values():
                    if isinstance(item, list):
                        for sub_item in item:
                            key = (
                                sub_item
                                if not isinstance(sub_item, dict)
                                else json.dumps(recursive_sort(sub_item))
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

                    errors += [
                        f"{self._context(path)}: {self._obj_spec_error(obj_spec, error)}"
                    ]

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

    def _object_or_array_contains(self, path, referenced_value, reference_obj_spec):
        referenced_path = reference_obj_spec["from"]
        referenced_prop = reference_obj_spec["extract"]

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

    def _evaluate_meta_properties(self, path, field, obj_spec):
        errors = []
        modified_obj_spec = obj_spec.copy()

        if (
            "constraints" in obj_spec
            and "mutually_exclusive" in obj_spec["constraints"]
        ):
            (
                new_errors,
                modified_obj_spec,
            ) = self._validate_mutually_exclusive_properties(path, field, obj_spec)
            errors += new_errors

        return (errors, modified_obj_spec)

    def _validate_mutually_exclusive_properties(self, path, field, obj_spec):
        included_props = []

        for prop in obj_spec["constraints"]["mutually_exclusive"]:
            if prop in field:
                included_props.append(prop)

        modified_obj_spec = copy.deepcopy(obj_spec)

        if "forbidden" not in modified_obj_spec["constraints"]:
            modified_obj_spec["constraints"]["forbidden"] = {"properties": []}

        for prop in modified_obj_spec["constraints"]["mutually_exclusive"]:
            if prop not in included_props:
                modified_obj_spec["constraints"]["forbidden"]["properties"].append(prop)

        if len(included_props) == 0:
            # unless all of the properties are optional, at least one must be specified
            error_msg = [
                f"{self._context(path)}: must specify one of the mutually exclusive properties: {modified_obj_spec['constraints']['mutually_exclusive']}"
            ]
            if "optional" not in modified_obj_spec["constraints"]:
                return (error_msg, modified_obj_spec)

            for prop in modified_obj_spec["constraints"]["mutually_exclusive"]:
                if prop not in modified_obj_spec["constraints"]["optional"]:
                    return (error_msg, modified_obj_spec)

        if len(included_props) > 1:
            return (
                [
                    f"{self._context(path)}: more than one mutually exclusive property specified: {included_props}"
                ],
                modified_obj_spec,
            )

        return ([], modified_obj_spec)

    def _resolve_obj_spec(self, field, obj_spec):
        if "obj_spec_name" in obj_spec:
            obj_spec_name = obj_spec["obj_spec_name"]
            referenced_obj_spec = utils.get_obj_spec(obj_spec_name)

            if (
                "obj_spec_modifiers" in obj_spec
                and obj_spec_name in obj_spec["obj_spec_modifiers"]
            ):
                obj_spec = self._apply_obj_spec_modifiers(
                    referenced_obj_spec,
                    obj_spec["obj_spec_modifiers"][obj_spec_name],
                )
            else:
                obj_spec = referenced_obj_spec

        if "resolvers" in obj_spec:
            obj_spec = self._resolve_obj_spec_variables(field, obj_spec)

        return self._evaluate_obj_spec_conditionals(field, obj_spec)

    def _resolve_path_variables(
        self, path, path_segments_to_resolve, obj_spec_vars={}, parent_object=None
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

            # obj_spec variable?
            if re.match(r"^\{\$\w+\}$", var):
                path_segments_to_resolve[i] = obj_spec_vars[var[1:-1]]

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

    def _apply_obj_spec_modifiers(self, referenced_obj_spec, obj_spec_modifiers):
        modified_obj_spec = copy.deepcopy(referenced_obj_spec)

        for prop, prop_modifiers in obj_spec_modifiers.items():
            for key, val in prop_modifiers.items():
                modified_obj_spec["properties"][prop][key] = val

        return modified_obj_spec

    def _resolve_obj_spec_variables(self, field, obj_spec):
        modified_obj_spec = copy.deepcopy(obj_spec)

        modified_obj_spec["obj_spec_vars"] = {}
        for variable, resolver in obj_spec["resolvers"].items():
            var = self._resolve_query(field, resolver)
            if isinstance(var, str):
                modified_obj_spec["obj_spec_vars"][variable] = var
            else:
                # Query resolution failed -- insert reserved keyword "ERROR".
                # This allows validation to run to completion, which should
                # reveal the root cause of the query resolution failure.
                modified_obj_spec["obj_spec_vars"][variable] = "ERROR"

        return modified_obj_spec

    def _evaluate_obj_spec_conditionals(self, field, obj_spec):
        if "if" not in obj_spec and "switch" not in obj_spec:
            return obj_spec

        modified_obj_spec = copy.deepcopy(obj_spec)

        if "if" in obj_spec:
            for condition in modified_obj_spec["if"]:
                condition_is_satisfied = (
                    self._evaluate_obj_spec_condition_group(condition, field)
                    if "conditions" in condition and "gate_type" in condition
                    else self._evaluate_obj_spec_condition(condition, field)
                )

                if condition_is_satisfied:
                    conditional_modifiers = condition["then"]
                elif "else" in condition:
                    conditional_modifiers = condition["else"]
                else:
                    continue

                modified_obj_spec = self._apply_obj_spec_conditionals(
                    conditional_modifiers, modified_obj_spec
                )

        if "switch" in obj_spec:
            raise NotImplementedError(
                "unit tests are needed for obj_spec switch statements"
            )

            for case in modified_obj_spec["switch"]["cases"]:
                if (
                    obj_spec["switch"]["property"] in field
                    and case["equals"] == field[obj_spec["switch"]["property"]]
                ):
                    modified_obj_spec = self._apply_obj_spec_conditionals(
                        case["then"], modified_obj_spec
                    )

                    if case["break"]:
                        break

        if "add_conditionals" in modified_obj_spec:
            if "if" in modified_obj_spec["add_conditionals"]:
                modified_obj_spec["if"] = modified_obj_spec["add_conditionals"]["if"]
            else:
                del modified_obj_spec["if"]

            if "switch" in modified_obj_spec["add_conditionals"]:
                modified_obj_spec["switch"] = modified_obj_spec["add_conditionals"][
                    "switch"
                ]
            else:
                del modified_obj_spec["switch"]

            del modified_obj_spec["add_conditionals"]

            # Recursively evaluate any conditionals added by the current conditionals
            return self._evaluate_obj_spec_conditionals(field, modified_obj_spec)

        return modified_obj_spec

    def _evaluate_obj_spec_condition_group(self, condition_group, field):
        gate_type = condition_group["gate_type"]
        if gate_type not in ["AND", "OR"]:
            raise NotImplementedError(
                "obj_spec condition gate type not implemented: "
                + condition_group["gate_type"]
            )

        if gate_type == "AND":
            early_return_trigger = False
            early_return_value = False
            late_return_value = True
        elif gate_type == "OR":
            early_return_trigger = True
            early_return_value = True
            late_return_value = False

        for condition in condition_group["conditions"]:
            if (
                self._evaluate_obj_spec_condition(condition, field)
                == early_return_trigger
            ):
                return early_return_value

        return late_return_value

    def _evaluate_obj_spec_condition(self, condition, field):
        required_props = ["property", "operator", "value"]
        if not all(prop in condition for prop in required_props):
            raise Exception(f"Invalid obj_spec condition: {condition}")

        operator = condition["operator"]
        value = (
            self._get_field(condition["value"], field)
            if is_path(condition["value"])
            else condition["value"]
        )

        # does the field contain the key?
        if operator == "CONTAINS_KEY":
            return (
                condition["property"] in field
                and isinstance(field[condition["property"]], dict)
                and value in field[condition["property"]]
            )

        if operator == "DOES_NOT_CONTAIN_KEY":
            return (
                condition["property"] not in field
                or not isinstance(field[condition["property"]], dict)
                or value not in field[condition["property"]]
            )

        # is an optional property specified?
        if operator == "IS_SPECIFIED" and value == True:
            return condition["property"] in field

        try:
            prop = self._get_field(
                condition["property"],
                field,
                throw_on_invalid_path=True,
                exception_context=lambda path: f"Unable to evaluate obj_spec condition for object at path: '{self._object_context}': missing required field: {path}",
            )
        except Exception as _:
            return False

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

        if operator == "MATCHES_PATTERN":
            return isinstance(prop, str) and re.match(prop, value)

        if operator == "DOES_NOT_MATCH_PATTERN":
            return not isinstance(prop, str) or not re.match(value, prop)

        raise NotImplementedError(
            "obj_spec operator not yet supported: " + str(operator)
        )

    def _apply_obj_spec_conditionals(self, conditional_modifiers, to_obj_spec):
        for key in conditional_modifiers:
            if key == "override_properties" or key == "add_properties":
                for prop, prop_modifier in conditional_modifiers[key].items():
                    to_obj_spec["properties"][prop] = prop_modifier
            elif key == "add_constraints":
                if "constraints" not in to_obj_spec:
                    to_obj_spec["constraints"] = {}

                for constraint_name, constraint in conditional_modifiers[key].items():
                    to_obj_spec["constraints"][constraint_name] = constraint
            else:
                raise NotImplementedError(
                    "Unexpected key in conditional modifiers: " + key
                )

        return to_obj_spec

    def _collect_actions_and_checkpoints(self):
        if "actions" not in self.schema or not isinstance(self.schema["actions"], list):
            return

        self._action_checkpoints = {}
        self._checkpoints = {}
        self._dependee_action_ids = set()
        self._thread_group_checkpoints = {}
        self._threaded_action_ids = []
        self._thread_groups = {}
        self._settable_fields = {}
        self._object_promise_actions = {}
        self._object_promise_fulfillment_actions = {}
        self._duplicate_object_promise_fulfillments = []
        self._object_promise_contexts = {}

        if "thread_groups" in self.schema:
            for thread_group in self.schema["thread_groups"]:
                thread_group_id = str(thread_group["id"])
                if thread_group_id not in self._thread_groups:
                    self._thread_groups[thread_group_id] = ThreadGroup()

                if "context" in thread_group:
                    parent_thread_group = self._resolve_global_ref(
                        thread_group["context"]
                    )
                    if (
                        parent_thread_group is None
                        or utils.parse_ref_type(thread_group["context"])
                        != "thread_group"
                        or "depends_on" not in parent_thread_group
                    ):
                        continue

                    parent_thread_group_id = str(parent_thread_group["id"])
                    if parent_thread_group_id not in self._thread_groups:
                        self._thread_groups[parent_thread_group_id] = ThreadGroup()

                    self._thread_groups[
                        parent_thread_group_id
                    ].sub_thread_group_ids.append(thread_group_id)

                    # Normalize to alias (ref could be a different field)
                    checkpoint = self._resolve_global_ref(
                        parent_thread_group["depends_on"]
                    )
                    if checkpoint is None or "alias" not in checkpoint:
                        continue
                    checkpoint_id = checkpoint["alias"]

                    if "depends_on" not in thread_group:
                        self._thread_group_checkpoints[thread_group_id] = checkpoint_id
                    else:
                        # a psuedo-checkpoint is needed to combine the thread's checkpoint
                        # with the parent thread's checkpoint
                        alias = f"_psuedo-thread-checkpoint-{str(thread_group['id'])}"
                        self.schema["checkpoints"].append(
                            {
                                "alias": alias,
                                "gate_type": "AND",
                                "dependencies": [
                                    {"checkpoint": parent_thread_group["depends_on"]},
                                    {"checkpoint": thread_group["depends_on"]},
                                ],
                            }
                        )
                        self._thread_group_checkpoints[thread_group_id] = alias

                        # bypass validation of psuedo-checkpoint fields
                        self._psuedo_checkpoints.append(alias)
                elif "depends_on" in thread_group:
                    if not is_global_ref(thread_group["depends_on"]):
                        # skip invalid refs -- allow validation to fail elsewhere
                        continue

                    self._thread_group_checkpoints[
                        thread_group_id
                    ] = utils.parse_ref_id(thread_group["depends_on"])

        for action in self.schema["actions"]:
            if "id" not in action:
                continue

            # Track which actions reference object promises...
            # Ancestry will be used to determine operation types.
            if "id" in action and utils.has_reference_to_template_entity(
                action, "object_promise", "object_promise"
            ):
                object_promise = self._resolve_global_ref(action["object_promise"])
                if object_promise is not None and "id" in object_promise:
                    if str(object_promise["id"]) not in self._object_promise_actions:
                        self._object_promise_actions[str(object_promise["id"])] = []
                    self._object_promise_actions[str(object_promise["id"])].append(
                        str(action["id"])
                    )

            self._record_settable_fields(action)

            action_id = str(action["id"])
            # if the action has a threaded context...
            if utils.has_reference_to_template_entity(
                action, "context", "thread_group"
            ):
                # the action implicitly depends on the thread's checkpoint
                thread_group = self._resolve_global_ref(action["context"])

                if thread_group is None:
                    continue

                thread_group_id = str(thread_group["id"])

                if thread_group_id not in self._thread_groups:
                    self._thread_groups[thread_group_id] = ThreadGroup()

                self._thread_groups[thread_group_id].action_ids.append(action_id)

                if utils.has_reference_to_template_entity(
                    thread_group, "depends_on", "checkpoint"
                ):
                    # Normalize to alias (ref could be a different field)
                    checkpoint = self._resolve_global_ref(thread_group["depends_on"])
                    if checkpoint is None or "alias" not in checkpoint:
                        continue
                    checkpoint_id = checkpoint["alias"]
                elif (
                    "context" in thread_group
                    and thread_group_id in self._thread_group_checkpoints
                ):
                    checkpoint_id = self._thread_group_checkpoints[thread_group_id]
                else:
                    continue

                self._thread_group_checkpoints[thread_group_id] = checkpoint_id
                self._threaded_action_ids.append(action_id)

                if "depends_on" not in action:
                    # the action implicitly depends on the thread's checkpoint
                    self._action_checkpoints[action_id] = checkpoint_id
                else:
                    # a psuedo-checkpoint is needed to combine the action's checkpoint with the thread's checkpoint
                    alias = f"_psuedo-checkpoint-{str(action['id'])}"

                    thread_checkpoint_ref = "checkpoint:{" + checkpoint_id + "}"
                    if action["depends_on"] == thread_checkpoint_ref:
                        # the action's checkpoint is the same as the thread's checkpoint
                        # TODO: decide whether to raise en error here
                        continue

                    self.schema["checkpoints"].append(
                        {
                            "alias": alias,
                            "gate_type": "AND",
                            "dependencies": [
                                {"checkpoint": thread_checkpoint_ref},
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

        nested_checkpoints = []
        for checkpoint in self.schema["checkpoints"]:
            if "alias" in checkpoint:
                self._checkpoints[checkpoint["alias"]] = checkpoint

                if utils.has_reference_to_template_entity(
                    checkpoint, "context", "thread_group"
                ):
                    thread_group_id = utils.parse_ref_id(checkpoint["context"])
                    if thread_group_id in self._thread_groups:
                        self._thread_groups[thread_group_id].checkpoints.append(
                            checkpoint["alias"]
                        )

            if "dependencies" in checkpoint:
                for dependency in checkpoint["dependencies"]:
                    if "compare" in dependency:
                        for side in ["left", "right"]:
                            dependee_action_id = utils.action_id_from_dependency_ref(
                                dependency, side
                            )
                            if dependee_action_id is not None:
                                self._dependee_action_ids.add(dependee_action_id)
                    elif utils.has_reference_to_template_entity(
                        dependency, "checkpoint", "checkpoint"
                    ):
                        alias = utils.parse_ref_id(dependency["checkpoint"])
                        nested_checkpoints.append(alias)

        self._unreferenced_thread_groups = []
        for thread_group_id, thread_group in self._thread_groups.items():
            if (
                not len(thread_group.action_ids)
                and not len(thread_group.sub_thread_group_ids)
                # note that a checkpoint referencing the thread_group does not count
            ):
                self._unreferenced_thread_groups.append(thread_group_id)

        self._unreferenced_checkpoints = []
        for checkpoint in self.schema["checkpoints"]:
            if "alias" in checkpoint:
                alias = checkpoint["alias"]
                if (
                    alias not in self._action_checkpoints.values()
                    and alias not in self._thread_group_checkpoints.values()
                    and alias not in nested_checkpoints
                ):
                    self._unreferenced_checkpoints.append(checkpoint["alias"])

        # determine which actions fulfill object promises (CREATE operations)
        for object_promise_id, action_ids in self._object_promise_actions.items():
            for action_id in action_ids:
                action = self._resolve_global_ref(
                    utils.as_ref(action_id, "action", value_is_id=True)
                )
                if action is None or "operation" not in action:
                    continue

                if (
                    len(action_ids) == 1
                    or self.validate_has_ancestor(
                        path="",
                        descendant_id=action_id,
                        descendant_type="action",
                        ancestor_ids=copy.deepcopy(action_ids),
                    )
                    != []
                ):
                    # no ancestor references the same object promise...
                    if (
                        object_promise_id
                        not in self._object_promise_fulfillment_actions
                    ):
                        # this action fulfills the object promise
                        self._object_promise_fulfillment_actions[
                            object_promise_id
                        ] = action_id
                        # and therefore the object promise inherits the action's thread scope
                        self._object_promise_contexts[object_promise_id] = (
                            action["context"]
                            if utils.has_reference_to_template_entity(
                                action, "context", "thread_group"
                            )
                            else None
                        )
                    else:
                        # another action already fulfills the same object promise
                        self._duplicate_object_promise_fulfillments.append(
                            object_promise_id
                        )

    def _detect_circular_dependencies(self):
        def _explore_checkpoint_recursive(checkpoint, visited, dependency_path):
            for dependency in checkpoint["dependencies"]:
                # Could be a Dependency or a CheckpointReference
                if "compare" in dependency:
                    # Dependency
                    for operand in ["left", "right"]:
                        if "ref" in dependency["compare"][operand]:
                            if is_variable(dependency["compare"][operand]["ref"]):
                                # It's a thread variable -- use the implicit dependency
                                if not utils.has_reference_to_template_entity(
                                    checkpoint,
                                    "context",
                                    "thread_group",
                                ):
                                    continue

                                thread_group = self._resolve_global_ref(
                                    checkpoint["context"]
                                )
                                if utils.has_reference_to_template_entity(
                                    thread_group,
                                    "depends_on",
                                    "checkpoint",
                                ):
                                    continue

                                thread_group_checkpoint = (
                                    self._resolve_global_ref(thread_group["depends_on"])
                                    if utils.has_reference_to_template_entity(
                                        thread_group, "depends_on", "checkpoint"
                                    )
                                    else None
                                )

                                if thread_group_checkpoint is None:
                                    continue

                                errors = _explore_checkpoint_recursive(
                                    thread_group_checkpoint,
                                    visited,
                                    dependency_path.copy(),
                                )
                            else:
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
                    try:
                        alias = utils.parse_ref_id(dependency["checkpoint"])
                    except:
                        return []

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
                        error += "; NOTE: actions with threaded context implicitly depend on the referenced thread group's checkpoint (ThreadGroup.depends_on)"
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

    def _obj_spec_error(self, obj_spec, error):
        if "error_replacements" in obj_spec:
            for replacement in obj_spec["error_replacements"]:
                if re.search(replacement["pattern"], error):
                    return replacement["replace_with"]

        return error

    def _action_id_from_path(self, path):
        ex = Exception(
            f"Cannot resolve node id: path does not lead to a node object ({path})"
        )

        if "root.actions" not in path:
            raise ex

        idx = path.find("]")
        if idx == -1:
            raise ex

        action = self._get_field(path[: idx + 1])

        if "id" not in action:
            raise ex

        return str(action["id"])

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
        if not self._matches_meta_obj_spec("query", query):
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
        if self._matches_meta_obj_spec("condition", where_clause):
            return self._evaluate_query_condition(where_clause, item, parent_obj)
        elif self._matches_meta_obj_spec("condition_group", where_clause):
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

        if self._matches_meta_obj_spec("query", condition["value"]):
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
            if self._matches_meta_obj_spec("condition", sub_condition):
                if (
                    self._evaluate_query_condition(sub_condition, item, parent_obj)
                    == early_return_trigger
                ):
                    return early_return_value
            elif self._matches_meta_obj_spec("condition_group", sub_condition):
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

    def _matches_meta_obj_spec(self, obj_spec_name, obj):
        return self._validate_object("", obj, getattr(oisql, obj_spec_name)) == []

    def _bypass_validation_of_object(self, obj_spec, field):
        if (
            isinstance(field, dict)
            and "obj_spec_name" in obj_spec
            and obj_spec["obj_spec_name"] == "checkpoint"
            and "alias" in field
            and field["alias"] in self._psuedo_checkpoints
        ):
            return True

        return False
