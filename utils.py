import hashlib
import json


def objects_are_identical(obj1, obj2):
    return hash_sorted_object(obj1) == hash_sorted_object(obj2)


def hash_sorted_object(obj):
    return hashlib.sha1(json.dumps(recursive_sort(obj)).encode()).digest()


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
