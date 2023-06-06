import networkx as nx
import json
from validation.schema_validator import SchemaValidator
from visualization.dependency_chart_layout import DependencyChartLayout
from services.miro import MiroBoard


class DependencyGraph:
    def __init__(
        self, schema_dict=None, json_schema_file_path=None, validate_schema=True
    ):
        if schema_dict is not None:
            self.schema = schema_dict
        elif json_schema_file_path is not None:
            self.schema = json.load(open(json_schema_file_path))
        else:
            raise Exception(
                "must provide an argument for schema_dict or json_schema_file_path"
            )

        if validate_schema:
            validator = SchemaValidator()
            errors = validator.validate(schema_dict=self.schema)
            if errors:
                validator.print_errors()
                raise Exception("Schema validation failed. See output for details.")

        self.nodes = {}
        self.dependency_sets = []
        self.gates = {}
        self.edge_tuples = []
        self.edge_dict = {}

        self.layout_algorithm = "dependency_chart"
        self.node_height = 2
        self.node_spacing = 1
        self.x_coord_factor = 400
        self.y_coord_factor = 100
        # When multiple dependencies point from a gate to the same node,
        # the connection is split into strands.
        self.strand_spacing = 0.5

        # networkx
        self.graph = nx.DiGraph()
        # spring layout options
        self.layout_k = 0.75  # Ideal distance between nodes
        self.layout_iterations = 200
        self.layout_seed = 13434  # Seed random number generators for reproducibility

        self._default_node_color = "#ffffff"
        self.party_colors = {}
        if "parties" in self.schema:
            for party in self.schema["parties"]:
                self.party_colors[party["name"]] = (
                    party["hex_code"]
                    if "hex_code" in party
                    else self._default_node_color
                )

        self._json_schema_to_graph()

    def _json_schema_to_graph(self):
        self.graph = nx.DiGraph()

        self.nodes = {n["id"]: n for n in self.schema["state_nodes"]}
        self.dependency_sets = self.schema["referenced_dependency_sets"]

        self.edge_tuples = []
        self.gates = {}

        for node_id, node in self.nodes.items():
            if "depends_on" not in node:
                continue

            self.edge_dict[node_id] = []
            nodeDS = node["depends_on"]
            numDependencies = len(nodeDS["dependencies"])
            if numDependencies > 1:
                # represent the gate as a node
                gate = nodeDS["alias"]
                self.graph.add_node(gate)
                self._add_edge(node_id, gate)
                self.gates[gate] = nodeDS["gate_type"]

                if gate not in self.edge_dict:
                    self.edge_dict[gate] = []

                # connect the gate to the nodes it depends on
                for dep in nodeDS["dependencies"]:
                    # dependency sets can contain standalone dependencies and alias references
                    if "node_id" in dep:
                        to_node_id = dep["node_id"]
                        self._add_edge(gate, to_node_id)
                    elif "alias" in dep:
                        subGate = dep["alias"]
                        self._add_edge(gate, subGate)

            elif numDependencies == 1:
                if "alias" in nodeDS["dependencies"][0]:
                    # single alias reference
                    gate = nodeDS["dependencies"][0]["alias"]
                    self._add_edge(node_id, gate)

                    if gate not in self.edge_dict:
                        self.edge_dict[gate] = []

                else:  # standalone dependency
                    to_node_id = nodeDS["dependencies"][0]["node_id"]
                    self._add_edge(node_id, to_node_id)

        for ds in self.dependency_sets:
            gate = ds["alias"]

            self.gates[gate] = ds["gate_type"]
            if gate not in self.edge_dict:
                self.edge_dict[gate] = []

            for dep in ds["dependencies"]:
                if "node_id" in dep:
                    to_node_id = dep["node_id"]
                    self._add_edge(gate, to_node_id)
                elif "alias" in dep:
                    subGate = dep["alias"]
                    self._add_edge(gate, subGate)

        self._set_node_coordinates()

    def generate_miro_board(self, board_id=None, board_name=None):
        mb = MiroBoard(board_id)

        if board_id is None:
            if board_name is None:
                raise Exception(
                    "Cannot generate Miro Board: must provide either board_id or board_name"
                )

            mb.create(board_name)

        shape_dict = self._generate_miro_shapes(mb)
        self._generate_miro_connectors(mb, shape_dict)

    def _generate_miro_shapes(self, mb):
        shape_dict = {}

        for node_id, node in self.nodes.items():
            x = self.node_coordinates[node_id][0] * self.x_coord_factor
            y = self.node_coordinates[node_id][1] * self.y_coord_factor

            shape_dict[node_id] = mb.create_shape(
                shape_type=shape_types[
                    node["node_type"] if "node_type" in node else "STATE"
                ],
                content=node["description"] if "description" in node else node["id"],
                fill_color=self.party_colors[node["applies_to"]]
                if "applies_to" in node
                else self._default_node_color,
                x=x,
                y=y,
            )

            if "supporting_info" in node:
                mb.create_shape(
                    shape_type=shape_types["SUPPORTING_INFO"],
                    content="- " + "<br/>- ".join(node["supporting_info"]),
                    text_align="left",
                    fill_color="#D0E78C",
                    x=x + self.node_spacing * self.x_coord_factor / 5,
                    y=y - self.node_height * self.y_coord_factor / 2,
                )

        for alias, gate_type in self.gates.items():
            shape_dict[alias] = mb.create_shape(
                shape_type=shape_types["GATE"],
                content=gate_type,
                fill_color=gate_colors[gate_type],
                x=self.node_coordinates[alias][0] * self.x_coord_factor,
                y=self.node_coordinates[alias][1] * self.y_coord_factor,
            )

        return shape_dict

    def _generate_miro_connectors(self, mb, shape_dict):
        # If there are multiple connectors between two shapes, they need to be spaced out
        tuple_occurences = {}
        for from_id, to_id in self.edge_tuples:
            if (from_id, to_id) not in tuple_occurences:
                tuple_occurences[(from_id, to_id)] = 0
            tuple_occurences[(from_id, to_id)] += 1

        for from_id, to_id in self.edge_tuples:
            if tuple_occurences[(from_id, to_id)] == 1:
                mb.create_connector(shape_dict[from_id], shape_dict[to_id])
            else:
                # "elbow" shapes are needed to space out the multiple connectors
                num_strands = tuple_occurences[(from_id, to_id)]

                elbow_x = (
                    self.node_coordinates[from_id][0] + self.node_coordinates[to_id][0]
                ) / 2

                # Space the elbows evenly around the average of the two y coords
                column_height = self.strand_spacing * (num_strands - 1)
                y_center = (
                    self.node_coordinates[from_id][1] + self.node_coordinates[to_id][1]
                ) / 2
                elbow_y = y_center - (column_height / 2)
                for i in range(num_strands):
                    elbow_id = mb.create_invisible_shape(
                        x=elbow_x * self.x_coord_factor,
                        y=elbow_y * self.y_coord_factor,
                    )
                    elbow_y += self.strand_spacing

                    # Connect the gate and node through the elbow
                    # using two connector segments
                    mb.create_connector(
                        shape_dict[from_id], elbow_id, end_stroke_cap="none"
                    )
                    mb.create_connector(elbow_id, shape_dict[to_id])

    def _add_edge(self, from_node_id, to_node_id):
        self.edge_dict[from_node_id].append(to_node_id)
        self.edge_tuples.append((from_node_id, to_node_id))

    def _set_node_coordinates(self):
        nodes = list(self.nodes.keys()) + list(self.gates.keys())

        if self.layout_algorithm == "dependency_chart":
            layout = DependencyChartLayout(
                node_height=self.node_height, node_spacing=self.node_spacing
            )
            self.node_coordinates = layout.from_graph_data(
                nodes, self.edge_dict, self.edge_tuples
            )
            self.strand_spacing = layout.node_spacing / 2
        elif self.layout_algorithm == "networkx":
            self.graph.add_nodes_from(nodes)
            self.graph.add_edges_from(self.edge_tuples)

            self.node_coordinates = nx.spring_layout(
                self.graph,
                k=self.layout_k,
                iterations=self.layout_iterations,
                seed=self.layout_seed,
            )


shape_types = {
    "STATE": "rectangle",
    "ACTION": "round_rectangle",
    "QUESTION": "triangle",
    "GATE": "circle",
    "SUPPORTING_INFO": "wedge_round_rectangle_callout",
}
gate_colors = {
    "AND": "#E88E8E",
    "OR": "#50da8b",
    "XOR": "#50da8b",
    "NAND": "#FFBA91",
    "NOR": "#E8A5D8",
    "XNOR": "#E8A5D8",
}
