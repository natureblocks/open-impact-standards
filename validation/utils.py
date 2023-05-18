from validation import templates, oisql


def get_template(template_name):
    if hasattr(templates, template_name):
        return getattr(templates, template_name)
    elif hasattr(oisql, template_name):
        return getattr(oisql, template_name)

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

    raise NotImplementedError(f"Field type not found for python type: {python_type_name}")

def recursive_sort(obj):
    if isinstance(obj, dict):
        return sorted((k, recursive_sort(_normalize_type(v))) for k, v in obj.items())
    if isinstance(obj, list):
        return sorted(recursive_sort(_normalize_type(x)) for x in obj)
    else:
        return obj


def _normalize_type(value):
    if isinstance(value, dict) or isinstance(value, list):
        return value

    # enables comparison between different types when sorting
    return str(value)
