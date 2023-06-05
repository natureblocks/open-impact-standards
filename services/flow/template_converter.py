import json
from enums import field_types
from services.flow.cadence_utils import to_cadence_dict
from flow_py_sdk import cadence


class TemplateConverter:
    def template_to_nodes(
        self, json_file_path, template_id, template_version, state_map_schema_file_path
    ):
        self.template = {"StateMap": json.load(open(json_file_path))}
        self.state_map_schema = json.load(open(state_map_schema_file_path))

        self.unnamed_dependency_set_counter = 0
        self.dependency_counter = 0
        self.dependency_set_reference_counter = 0

        self.graph_nodes = {}
        self.dependencies_inverse = {}
        self.entry_node_ids = []

        # Creating the StateMap GraphNode will recursively create
        # all other GraphNodes and add them to self.graph_nodes
        state_map = self._as_graph_node_recursive(self.template["StateMap"], "StateMap")
        state_map.off_chain_id = "template_" + str(template_id)
        state_map.string_fields["version"] = template_version
        self.graph_nodes[state_map.off_chain_id] = state_map

        self._populate_dependencies_inverse()
        self._find_entry_nodes()

    def graph_nodes_to_cadence(self):
        # parallel arrays
        tags = []
        off_chain_ids = []
        boolean_fields = []
        numeric_fields = []
        string_fields = []
        numeric_list_fields = []
        string_list_fields = []
        edge_off_chain_ids = []
        edge_collection_off_chain_ids = []

        for graph_node in self.graph_nodes.values():
            tags.append(cadence.String(graph_node.tag))
            off_chain_ids.append(cadence.String(graph_node.off_chain_id))

            string_fields.append(
                _wrap_nullable_fields(graph_node.string_fields, cadence.String)
            )
            numeric_fields.append(
                _wrap_nullable_fields(graph_node.numeric_fields, cadence.Fix64)
            )
            boolean_fields.append(
                to_cadence_dict(
                    graph_node.boolean_fields,
                    key_type=cadence.String,
                    value_type=cadence.Bool,
                )
            )
            string_list_fields.append(
                to_cadence_dict(
                    graph_node.string_list_fields,
                    key_type=cadence.String,
                    value_type=[
                        cadence.String,
                        cadence.Optional,
                        cadence.Array,
                        cadence.Optional,
                    ],
                )
            )
            numeric_list_fields.append(
                to_cadence_dict(
                    graph_node.numeric_list_fields,
                    key_type=cadence.String,
                    value_type=[
                        cadence.Fix64,
                        cadence.Optional,
                        cadence.Array,
                        cadence.Optional,
                    ],
                )
            )
            edge_off_chain_ids.append(
                to_cadence_dict(
                    graph_node.edge_off_chain_ids,
                    key_type=cadence.String,
                    value_type=cadence.String,
                )
            )
            edge_collection_off_chain_ids.append(
                to_cadence_dict(
                    graph_node.edge_collection_off_chain_ids,
                    key_type=cadence.String,
                    value_type=[cadence.String, cadence.Array],
                )
            )

        cadence_dependencies_inverse = to_cadence_dict(
            self.dependencies_inverse,
            key_type=cadence.String,
            value_type=[cadence.String, cadence.Array],
        )

        entry_node_ids = cadence.Array(
            [cadence.String(off_chain_id) for off_chain_id in self.entry_node_ids]
        )

        return [
            cadence.Array(tags),
            cadence.Array(off_chain_ids),
            cadence.Array(boolean_fields),
            cadence.Array(numeric_fields),
            cadence.Array(string_fields),
            cadence.Array(numeric_list_fields),
            cadence.Array(string_list_fields),
            cadence.Array(edge_off_chain_ids),
            cadence.Array(edge_collection_off_chain_ids),
            cadence_dependencies_inverse,
            entry_node_ids,
        ]

    def schema_to_cadence(self, json_file_path):
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

    def _as_graph_node_recursive(self, obj, tag):
        graph_node_map = self._get_graph_node_map()

        tag = self._determine_actual_tag(tag, obj)
        node = GraphNode(tag)

        for field_category, fields in graph_node_map[tag].items():
            if isinstance(fields, dict):
                attr = getattr(node, field_category)

                for field_name, template_field_key in fields.items():
                    if (
                        isinstance(template_field_key, dict)
                        and template_field_key["source"] in obj
                    ):
                        value_to_set = obj[template_field_key["source"]]
                    elif callable(template_field_key):
                        value_to_set = template_field_key(obj)
                    elif template_field_key in obj:
                        value_to_set = obj[template_field_key]
                    else:
                        continue

                    # Instantiate any nested objects as GraphNodes
                    if isinstance(value_to_set, dict):
                        # Edge
                        edge_tag = self.state_map_schema["node_definitions"][tag][
                            field_name
                        ]["tag"]
                        edge_node = self._as_graph_node_recursive(
                            value_to_set, edge_tag
                        )
                        self.graph_nodes[edge_node.off_chain_id] = edge_node
                        value_to_set = edge_node.off_chain_id
                    elif (
                        isinstance(value_to_set, list)
                        and len(value_to_set)
                        and isinstance(value_to_set[0], dict)
                    ):
                        # Edge collection
                        edge_tag = self.state_map_schema["node_definitions"][tag][
                            field_name
                        ]["tag"]
                        edge_collection = []
                        for edge in value_to_set:
                            # Skip edges that don't match the specified tag
                            if (
                                "tag" in template_field_key
                                and self._determine_actual_tag(
                                    template_field_key["tag"], edge
                                )
                                != template_field_key["tag"]
                            ):
                                continue

                            edge_node = self._as_graph_node_recursive(edge, edge_tag)
                            edge_collection.append(edge_node.off_chain_id)
                            self.graph_nodes[edge_node.off_chain_id] = edge_node

                        value_to_set = edge_collection

                    attr[field_name] = value_to_set
            elif callable(fields):
                value_to_set = fields(obj) if callable(fields) else obj[fields]
                setattr(node, field_category, value_to_set)
            elif fields in obj:
                setattr(node, field_category, obj[fields])

        return node

    def _get_graph_node_map(self):
        return {
            "StateMap": {
                "off_chain_id": "id",
                "string_fields": {"standard": "standard", "version": "version"},
                "edge_collection_off_chain_ids": {
                    "parties": "parties",
                    "stateNodes": "state_nodes",
                    "referencedDependencySets": "referenced_dependency_sets",
                },
            },
            "Party": {
                "off_chain_id": "name",
                "string_fields": {"name": "name", "flowAddress": "flow_address"},
                "numeric_fields": {"subgraphId": "subgraph_id"},
            },
            "StateNode": {
                "off_chain_id": lambda sn: str(sn["id"]),
                "string_fields": {"description": "description", "nodeTag": "tag"},
                "edge_off_chain_ids": {
                    "party": "applies_to",
                    "dependsOn": "depends_on",
                },
            },
            "DependencySet": {
                "off_chain_id": lambda ds: self._get_dependency_set_id(ds),
                "string_fields": {
                    "gateType": "gate_type",
                    "description": "description",
                },
                "edge_collection_off_chain_ids": {
                    "dependencies": {
                        "source": "dependencies",
                        "tag": "Dependency",
                    },
                    "dependencySetReferences": {
                        "source": "dependencies",
                        "tag": "DependencySetReference",
                    },
                },
            },
            "DependencySetReference": {
                "off_chain_id": lambda dsr: self._next_dependency_set_reference_id(dsr),
                "string_fields": {"alias": "alias"},
            },
            "Dependency": {
                "off_chain_id": lambda dep: self._next_dependency_id(dep),
                "edge_off_chain_ids": {"stateNode": "node_id"},
                "string_fields": {
                    "fieldName": "field_name",
                    "comparisonValueType": "comparison_value_type",
                    "comparisonOperator": "comparison_operator",
                    "stringComparisonValue": "string_comparison_value",
                },
                "numeric_fields": {
                    "numericComparisonValue": "numeric_comparison_value"
                },
                "boolean_fields": {
                    "booleanComparisonValue": "boolean_comparison_value"
                },
                "string_list_fields": {
                    "stringListComparisonValue": "string_list_comparison_value"
                },
                "numeric_list_fields": {
                    "numericListComparisonValue": "numeric_list_comparison_value"
                },
            },
        }

    def _determine_actual_tag(self, tag, obj):
        if tag in ["Dependency", "DependencySetReference"]:
            return "DependencySetReference" if "alias" in obj else "Dependency"

        return tag

    def _get_dependency_set_id(self, dependency_set):
        if "alias" in dependency_set:
            ds_id = dependency_set["alias"]
        else:
            ds_id = f"uds_{str(self.unnamed_dependency_set_counter).zfill(4)}"
            self.unnamed_dependency_set_counter += 1

        return ds_id

    def _next_dependency_set_reference_id(self, _):
        dsr_id = f"dsr_{str(self.dependency_set_reference_counter).zfill(4)}"
        self.dependency_set_reference_counter += 1
        return dsr_id

    def _next_dependency_id(self, _):
        dep_id = f"dep_{str(self.dependency_counter).zfill(4)}"
        self.dependency_counter += 1
        return dep_id

    def _populate_dependencies_inverse(self):
        for off_chain_id, node in self.graph_nodes.items():
            if "dependsOn" in node.edge_off_chain_ids:
                self._populate_dependencies_inverse_recursive(
                    off_chain_id, self.graph_nodes[node.edge_off_chain_ids["dependsOn"]]
                )

    def _populate_dependencies_inverse_recursive(
        self, dependee_node_id, dependency_set
    ):
        if "dependencies" in dependency_set.edge_collection_off_chain_ids:
            for dep_id in dependency_set.edge_collection_off_chain_ids["dependencies"]:
                dependent_node_id = self.graph_nodes[dep_id].edge_off_chain_ids[
                    "stateNode"
                ]

                if dependent_node_id not in self.dependencies_inverse:
                    self.dependencies_inverse[dependent_node_id] = []

                self.dependencies_inverse[dependent_node_id].append(dependee_node_id)

        if "dependencySetReferences" in dependency_set.edge_collection_off_chain_ids:
            for dsr_id in dependency_set.edge_collection_off_chain_ids[
                "dependencySetReferences"
            ]:
                self._populate_dependencies_inverse_recursive(
                    dependee_node_id,
                    self.graph_nodes[self.graph_nodes[dsr_id].string_fields["alias"]],
                )

    def _find_entry_nodes(self):
        for off_chain_id, node in self.graph_nodes.items():
            if node.tag == "StateNode" and "dependsOn" not in node.edge_off_chain_ids:
                self.entry_node_ids.append(off_chain_id)


def _wrap_nullable_fields(fields_dict, value_type):
    return to_cadence_dict(
        fields_dict,
        key_type=cadence.String,
        value_type=[value_type, cadence.Optional],
    )


class GraphNode:
    def __init__(self, tag=None):
        self.tag = tag
        self.off_chain_id = None
        self.on_chain_id = None

        self.string_fields = {}
        self.numeric_fields = {}
        self.boolean_fields = {}
        self.string_list_fields = {}
        self.numeric_list_fields = {}
        self.edge_off_chain_ids = {}
        self.edge_collection_off_chain_ids = {}
        self.edges = {}
        self.edgeCollections = {}

    def from_node_dict(self, node_dict):
        self.tag = node_dict["meta"]["tag"]
        self.on_chain_id = node_dict["meta"]["id"]
        self.off_chain_id = node_dict["meta"]["offChainID"]

        self.boolean_fields = node_dict["data"]["booleanFields"]
        self.numeric_fields = node_dict["data"]["numericFields"]
        self.string_fields = node_dict["data"]["stringFields"]
        self.numeric_list_fields = node_dict["data"]["numericListFields"]
        self.string_list_fields = node_dict["data"]["stringListFields"]
        self.edges = node_dict["data"]["edges"]
        self.edgeCollections = node_dict["data"]["edgeCollections"]

        return self
