import hashlib
import json
from validation import templates, oisql


def parse_schema(json_file_path):
    standard = json.load(open(json_file_path))
    node_definitions = standard["node_definitions"]

    schema = {}

    field_type_map = {
        "BOOLEAN": "booleanFields",
        "STRING": "stringFields",
        "NUMERIC": "numericFields",
        "STRING_LIST": "stringListFields",
        "NUMERIC_LIST": "numericListFields",
        "EDGE": "edges",
        "EDGE_COLLECTION": "edgeCollections",
    }

    for tag, field_definitions in node_definitions.items():
        schema[tag] = {}

        for field_type, schema_field_type in field_type_map.items():
            schema[tag][schema_field_type] = []

        schema[tag]["edges"] = {}
        schema[tag]["edgeCollections"] = {}

        # TODO: Include deletability in NodeDefinition
        schema[tag]["isDeletable"] = True

        for field_name, field_attributes in field_definitions.items():
            field_type = field_attributes["field_type"]
            schema_field_type = field_type_map[field_type]

            obj = None
            if field_type == "EDGE" or field_type == "EDGE_COLLECTION":
                obj = schema[tag][schema_field_type]

            if obj is not None:
                obj[field_name] = field_attributes["tag"]
            else:
                schema[tag][schema_field_type].append(field_name)

    return schema


def objects_are_identical(obj1, obj2):
    def hash_sorted_object(obj):
        return hashlib.sha1(json.dumps(recursive_sort(obj)).encode()).digest()

    return hash_sorted_object(obj1) == hash_sorted_object(obj2)


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

    raise NotImplementedError(
        f"Field type not found for python type: {python_type_name}"
    )


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
