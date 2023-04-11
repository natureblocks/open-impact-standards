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
