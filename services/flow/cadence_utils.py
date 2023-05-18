import json
from enums import field_types
from flow_py_sdk import cadence


emulator_address = "0xf8d6e0586b0a20c7"


def schema_to_cadence(json_file_path):
    schema = json.load(open(json_file_path))
    node_definitions = schema["node_definitions"]

    node_tags = []

    fields = {}
    for field_type in field_types:
        fields[field_type] = {}

    edges = {}
    edge_collections = {}

    deletable = {}

    # Parse and collect values in the structure that
    # the propose_schema transaction requires.
    for tag, field_definitions in node_definitions.items():
        cadence_tag = cadence.String(tag)
        node_tags.append(cadence_tag)

        for field_type in field_types:
            fields[field_type][cadence_tag] = []

        edges[cadence_tag] = {}
        edge_collections[cadence_tag] = {}

        # TODO: Include deletability in NodeDefinition
        deletable[cadence_tag] = cadence.Bool(True)

        for field_name, field_attributes in field_definitions.items():
            field_type = field_attributes["field_type"]

            obj = None
            if field_type == "EDGE":
                obj = edges
            elif field_type == "EDGE_COLLECTION":
                obj = edge_collections

            if obj:
                obj[cadence_tag][cadence.String(field_name)] = cadence.String(
                    field_attributes["tag"]
                )
            else:
                fields[field_type][cadence_tag].append(cadence.String(field_name))

    # Convert nested objects to cadence values
    for field_type in field_types:
        for tag, field_definitions in fields[field_type].items():
            fields[field_type][tag] = cadence.Array(field_definitions)

    for tag, edge_definitions in edges.items():
        edges[tag] = to_cadence_dict(edge_definitions)

    for tag, edge_collection_definitions in edge_collections.items():
        edge_collections[tag] = to_cadence_dict(edge_collection_definitions)

    notify_email_address = cadence.Optional(None)

    return [
        cadence.Array(node_tags),
        to_cadence_dict(fields["BOOLEAN"]),
        to_cadence_dict(fields["NUMERIC"]),
        to_cadence_dict(fields["STRING"]),
        to_cadence_dict(fields["NUMERIC_LIST"]),
        to_cadence_dict(fields["STRING_LIST"]),
        to_cadence_dict(edges),
        to_cadence_dict(edge_collections),
        to_cadence_dict(deletable),
        notify_email_address,
    ]


def to_cadence_dict(dictionary):
    kvps = []
    for key, value in dictionary.items():
        kvps.append(cadence.KeyValuePair(key, value))
    return cadence.Dictionary(kvps)


def from_cadence_recursive(value):
    if isinstance(value, cadence.Struct):
        return from_cadence_recursive(value.fields)

    if isinstance(value, cadence.Dictionary):
        return {
            from_cadence_recursive(kvp.key): from_cadence_recursive(kvp.value)
            for kvp in value.value
        }

    if isinstance(value, cadence.Array):
        return [from_cadence_recursive(value) for value in value.value]

    if (
        isinstance(value, cadence.String)
        or isinstance(value, cadence.UInt64)
        or isinstance(value, cadence.Bool)
    ):
        return value.value

    if isinstance(value, cadence.Optional):
        return from_cadence_recursive(value.value)

    if isinstance(value, dict):
        return {key: from_cadence_recursive(value) for key, value in value.items()}

    if isinstance(value, list):
        return [from_cadence_recursive(value) for value in value]

    return value
