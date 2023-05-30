import json
from enums import field_types
from services.flow.cadence_utils import to_cadence_dict
from flow_py_sdk import cadence


class TemplateConverter:
    def template_to_cadence(self, json_file_path, template_id, template_version):
        template = json.load(open(json_file_path))

        # parallel arrays
        self.tags = []
        self.off_chain_ids = []
        self.boolean_fields = []
        self.numeric_fields = []
        self.string_fields = []
        self.numeric_list_fields = []
        self.string_list_fields = []
        self.edge_off_chain_ids = []
        self.edge_collection_off_chain_ids = []

        # Some objects need to be enumerated and collected
        # before being added to the parallel arrays
        self.unnamed_dependency_set_counter = 0
        self.dependency_counter = 0
        self.dependency_set_reference_counter = 0
        self.parsed_objects = {
            "DependencySet": {},
            "Dependency": {},
            "DependencySetReference": {},
        }
        self.state_map_edge_collections = {
            "parties": [],
            "stateNodes": [],
            "referencedDependencySets": [],
        }

        for party in template["parties"]:
            self._party_to_cadence(party)

        for state_node in template["state_nodes"]:
            self._state_node_to_cadence(state_node)

        for dependency_set in template["referenced_dependency_sets"]:
            self._dependency_set_to_cadence(dependency_set)

        for tag, collection in self.parsed_objects.items():
            self._parsed_object_to_cadence(tag, collection)

        self.state_map_to_cadence(template, template_id, template_version)

        return [
            cadence.Array(self.tags),
            cadence.Array(self.off_chain_ids),
            cadence.Array(self.boolean_fields),
            cadence.Array(self.numeric_fields),
            cadence.Array(self.string_fields),
            cadence.Array(self.numeric_list_fields),
            cadence.Array(self.string_list_fields),
            cadence.Array(self.edge_off_chain_ids),
            cadence.Array(self.edge_collection_off_chain_ids),
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

    def _party_to_cadence(self, party):
        self.tags.append(cadence.String("Party"))

        self.off_chain_ids.append(cadence.String(party["name"]))
        self.state_map_edge_collections["parties"].append(party["name"])

        party_string_fields = {
            "name": party["name"],
            "flowAddress": None,
        }
        self.string_fields.append(
            _wrap_nullable_fields(party_string_fields, cadence.String)
        )

        party_numeric_fields = {"subgraphId": None}
        self.numeric_fields.append(
            _wrap_nullable_fields(party_numeric_fields, cadence.Fix64)
        )

        # Parties has none of these
        self.boolean_fields.append(cadence.Dictionary([]))
        self.numeric_list_fields.append(cadence.Dictionary([]))
        self.string_list_fields.append(cadence.Dictionary([]))
        self.edge_off_chain_ids.append(cadence.Dictionary([]))
        self.edge_collection_off_chain_ids.append(cadence.Dictionary([]))

    def _state_node_to_cadence(self, state_node):
        self.tags.append(cadence.String("StateNode"))

        self.off_chain_ids.append(cadence.String(str(state_node["id"])))
        self.state_map_edge_collections["stateNodes"].append(str(state_node["id"]))

        state_node_string_fields = {
            "description": state_node["description"],
            "nodeTag": state_node["tag"],
        }
        self.string_fields.append(
            _wrap_nullable_fields(state_node_string_fields, cadence.String)
        )

        state_node_numeric_fields = {
            "id": state_node["id"],
        }
        self.numeric_fields.append(
            _wrap_nullable_fields(state_node_numeric_fields, cadence.Fix64)
        )

        state_node_edges = {
            "party": state_node["applies_to"],
        }
        if "depends_on" in state_node:
            ds_alias = self._dependency_set_to_cadence(state_node["depends_on"])
            state_node_edges["dependsOn"] = ds_alias

        self.edge_off_chain_ids.append(
            to_cadence_dict(
                state_node_edges, key_type=cadence.String, value_type=cadence.String
            )
        )

        # StateNode has none of these
        self.boolean_fields.append(cadence.Dictionary([]))
        self.string_list_fields.append(cadence.Dictionary([]))
        self.numeric_list_fields.append(cadence.Dictionary([]))
        self.edge_collection_off_chain_ids.append(cadence.Dictionary([]))

    def _dependency_set_to_cadence(self, dependency_set):
        if "alias" in dependency_set:
            alias = dependency_set["alias"]
        else:
            alias = f"uds_{str(self.unnamed_dependency_set_counter).zfill(4)}"
            self.unnamed_dependency_set_counter += 1

        self.parsed_objects["DependencySet"][alias] = self._parse_dependency_set(
            dependency_set
        )

        for dependency in dependency_set["dependencies"]:
            # Is it a Dependency or a DependencySetReference?
            if "alias" in dependency:
                # DependencySetReference
                dependency_set_reference_id = (
                    f"dsr_{str(self.dependency_set_reference_counter).zfill(4)}"
                )
                self.dependency_set_reference_counter += 1

                self.parsed_objects["DependencySet"][alias][
                    "edge_collection_off_chain_ids"
                ]["dependencySetReferences"].append(dependency_set_reference_id)

                self.parsed_objects["DependencySetReference"][
                    dependency_set_reference_id
                ] = self._parse_dependency_set_reference(dependency)
            else:
                # Dependency
                dependency_id = f"dep_{str(self.dependency_counter).zfill(4)}"
                self.dependency_counter += 1

                self.parsed_objects["DependencySet"][alias][
                    "edge_collection_off_chain_ids"
                ]["dependencies"].append(dependency_id)

                self.parsed_objects["Dependency"][
                    dependency_id
                ] = self._parse_dependency(dependency)

        return alias

    def _parsed_object_to_cadence(self, tag, collection):
        for node_id, node_data in collection.items():
            self.tags.append(cadence.String(tag))
            self.off_chain_ids.append(cadence.String(node_id))

            self.string_fields.append(
                _wrap_nullable_fields(node_data["string_fields"], cadence.String)
            )
            self.numeric_fields.append(
                _wrap_nullable_fields(node_data["numeric_fields"], cadence.Fix64)
            )
            self.boolean_fields.append(
                to_cadence_dict(
                    node_data["boolean_fields"],
                    key_type=cadence.String,
                    value_type=cadence.Bool,
                )
            )
            self.string_list_fields.append(
                to_cadence_dict(
                    node_data["string_list_fields"],
                    key_type=cadence.String,
                    value_type=[
                        cadence.String,
                        cadence.Optional,
                        cadence.Array,
                        cadence.Optional,
                    ],
                )
            )
            self.numeric_list_fields.append(
                to_cadence_dict(
                    node_data["numeric_list_fields"],
                    key_type=cadence.String,
                    value_type=[
                        cadence.Fix64,
                        cadence.Optional,
                        cadence.Array,
                        cadence.Optional,
                    ],
                )
            )

            self.edge_off_chain_ids.append(
                to_cadence_dict(
                    node_data["edge_off_chain_ids"]
                    if "edge_off_chain_ids" in node_data
                    else {},
                    key_type=cadence.String,
                    value_type=cadence.String,
                )
            )

            self.edge_collection_off_chain_ids.append(
                to_cadence_dict(
                    node_data["edge_collection_off_chain_ids"]
                    if "edge_collection_off_chain_ids" in node_data
                    else {},
                    key_type=cadence.String,
                    value_type=[cadence.String, cadence.Array],
                )
            )

    def state_map_to_cadence(self, template, template_id, template_version):
        self.tags.append(cadence.String("StateMap"))
        self.off_chain_ids.append(cadence.String(str(template_id)))

        state_map_string_fields = {
            "standard": template["standard"],
            "version": template_version,
        }
        self.string_fields.append(
            _wrap_nullable_fields(state_map_string_fields, cadence.String)
        )

        self.edge_collection_off_chain_ids.append(
            to_cadence_dict(
                self.state_map_edge_collections,
                key_type=cadence.String,
                value_type=[cadence.String, cadence.Array],
            )
        )

        # StateMap has none of these
        self.numeric_fields.append(cadence.Dictionary([]))
        self.boolean_fields.append(cadence.Dictionary([]))
        self.numeric_list_fields.append(cadence.Dictionary([]))
        self.string_list_fields.append(cadence.Dictionary([]))
        self.edge_off_chain_ids.append(cadence.Dictionary([]))

    def _parse_dependency_set(self, dependency_set):
        ds = {
            "string_fields": {
                "gateType": dependency_set["gate_type"]
                if "gate_type" in dependency_set
                else None,
                "description": dependency_set["description"]
                if "description" in dependency_set
                else None,
            },
            "edge_collection_off_chain_ids": {
                "dependencies": [],
                "dependencySetReferences": [],
            },
        }

        return _populate_empty_field_types(ds)

    def _parse_dependency_set_reference(self, dependency):
        dsr = {
            "string_fields": {
                "alias": dependency["alias"],
            }
        }

        return _populate_empty_field_types(dsr)

    def _parse_dependency(self, dependency):
        dep = {
            "edges_off_chain_ids": {
                "stateNode": dependency["node_id"],
            },
            "string_fields": {
                "fieldName": dependency["field_name"],
                "comparisonValueType": dependency["comparison_value_type"]
                if "comparison_value_type" in dependency
                else None,
                "comparisonOperator": dependency["comparison_operator"]
                if "comparison_operator" in dependency
                else None,
                "stringComparisonValue": dependency["string_comparison_value"]
                if "string_comparison_value" in dependency
                else None,
            },
            "numeric_fields": {
                "numericComparisonValue": dependency["numeric_comparison_value"]
                if "numeric_comparison_value" in dependency
                else None,
            },
            "boolean_fields": {
                "booleanComparisonValue": dependency["boolean_comparison_value"]
                if "boolean_comparison_value" in dependency
                else None,
            },
            "string_list_fields": {
                "stringListComparisonValue": dependency["string_list_comparison_value"]
                if "string_list_comparison_value" in dependency
                else None,
            },
            "numeric_list_fields": {
                "numericListComparisonValue": dependency[
                    "numeric_list_comparison_value"
                ]
                if "numeric_list_comparison_value" in dependency
                else None,
            },
        }

        return _populate_empty_field_types(dep)


def _populate_empty_field_types(obj):
    for field_type in field_types:
        ft = field_type.lower() + "_fields"
        if ft not in obj:
            obj[ft] = {}

    return obj


def _wrap_nullable_fields(fields_dict, value_type):
    return to_cadence_dict(
        fields_dict,
        key_type=cadence.String,
        value_type=[value_type, cadence.Optional],
    )
