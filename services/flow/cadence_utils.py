from flow_py_sdk import cadence


emulator_address = "0xf8d6e0586b0a20c7"


def to_cadence_dict(dictionary, key_type=None, value_type=None):
    def to_cadence_type(value, cadence_type_or_list):
        if isinstance(cadence_type_or_list, list):
            cadence_types = cadence_type_or_list.copy()
            # Wrap the nested cadence types in the order they are provided
            while cadence_types:
                cadence_type = cadence_types.pop(0)

                if value is None and cadence_type is not cadence.Optional:
                    continue

                if cadence.Array in cadence_types:
                    if value is None:
                        continue

                    if not isinstance(value, list):
                        raise Exception(
                            "Cannot convert to cadence.Array: value must be a list"
                        )

                    for i in range(len(value)):
                        value[i] = cadence_type(value[i])
                else:
                    value = cadence_type(value)
        elif cadence_type_or_list:
            return cadence_type_or_list(value)

        return value

    kvps = []
    for key, value in dictionary.items():
        kvps.append(
            cadence.KeyValuePair(
                to_cadence_type(key, key_type), to_cadence_type(value, value_type)
            )
        )
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
        return [from_cadence_recursive(v) for v in value.value]

    type_name = type(value).__name__
    if type_name in ["String", "Fix64", "UInt64", "UInt256", "Bool"]:
        return value.value

    if isinstance(value, cadence.Optional):
        return from_cadence_recursive(value.value)

    if isinstance(value, dict):
        return {k: from_cadence_recursive(v) for k, v in value.items()}

    if isinstance(value, list):
        return [from_cadence_recursive(v) for v in value]

    return value


def compare_graph_nodes(expected_nodes, actual_nodes, keys_to_skip=[]):
    differences = []

    if len(expected_nodes) != len(actual_nodes):
        differences.append(
            f"Expected {len(expected_nodes)} nodes, but found {len(actual_nodes)} nodes"
        )

    for i in range(len(expected_nodes)):
        expected_node = expected_nodes[i]
        actual_node = actual_nodes[i]

        for key, value in expected_node.__dict__.items():
            if key in keys_to_skip:
                continue

            if value != actual_node.__dict__[key]:
                differences.append(
                    f"Expected {key} to be {value}, but found {actual_node.__dict__[key]}"
                )

    return differences
