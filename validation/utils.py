import re
from validation import templates, oisql, pipeline_templates, patterns
from enums import ref_types


def has_reference_to_template_object_type(obj, key, template_object_type):
    return (
        isinstance(obj, dict)
        and key in obj
        and is_global_ref(obj[key])
        and parse_ref_type(obj[key]) == template_object_type
    )


def is_path(value):
    # TODO: make path validation stricter
    return isinstance(value, str) and (
        "." in value and value[0] != "^" or (value[0] == "{" and value[-1] == "}")
    )


def is_global_ref(value):
    if not isinstance(value, str):
        return False

    first_segment = value.split(".")[0]  # in case it's a path
    split_ref = first_segment.split(":")
    ref_type = split_ref[0]
    ref_id = ":".join(split_ref[1:])

    return ref_type in ref_types and re.match(patterns.global_ref_identifier, ref_id)


def is_variable(value):
    return re.match(patterns.variable, value)


def is_local_variable(value):
    return isinstance(value, str) and re.match(patterns.local_variable, value)


def is_filter_ref(value):
    return isinstance(value, str) and re.match(patterns.filter_ref, value)


def parse_ref_id(value):
    if not is_global_ref(value):
        raise Exception(f"Invalid ref: {value}")

    framed_ref_id = ":".join(value.split(":")[1:]).split(".")[0]  # "{ref_id}"
    return framed_ref_id[1:-1]


def parse_ref_type(value):
    if not is_global_ref(value):
        raise Exception(f"Invalid ref: {value}")

    return value.split(":")[0]


def get_template(template_name):
    if hasattr(templates, template_name):
        return getattr(templates, template_name)
    elif hasattr(oisql, template_name):
        return getattr(oisql, template_name)
    elif hasattr(pipeline_templates, template_name):
        return getattr(pipeline_templates, template_name)

    raise Exception(f"Template not found: {template_name}")


def field_type_from_python_type_name(python_type_name):
    type_map = {
        "str": "STRING",
        "int": "NUMERIC",
        "float": "NUMERIC",
        "bool": "BOOLEAN",
        "list": "LIST",
        "dict": "OBJECT",
    }

    if python_type_name in type_map:
        return type_map[python_type_name]

    raise NotImplementedError(
        f"Field type not found for python type: {python_type_name}"
    )
