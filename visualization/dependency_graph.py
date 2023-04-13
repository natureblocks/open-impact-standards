import networkx as nx
import json
from validation.schema_validator import SchemaValidator
from visualization.dependency_chart_layout import DependencyChartLayout
from services.miro import MiroBoard


class DependencyGraph:
    def __init__(self, json_schema_file_path, validate_schema=True):
        self.schema = json.load(open(json_schema_file_path))

        if validate_schema:
            errors = SchemaValidator().validate(self.schema)
            if errors:
                print("\n".join(errors))
                raise Exception("Schema validation failed. See output for details.")

        self.nodes = {}
        self.dependency_sets = []
        self.gates = {}
        self.edge_tuples = []
        self.edge_dict = {}

        self.layout_algorithm = "dependency_chart"
        self.x_coord_factor = 400
        self.y_coord_factor = 100

        # networkx
        self.graph = nx.DiGraph()
        # spring layout options
        self.layout_k = 0.75  # Ideal distance between nodes
        self.layout_iterations = 200
        self.layout_seed = 13434  # Seed random number generators for reproducibility

        self._json_schema_to_graph()

    def _json_schema_to_graph(self):
        self.graph = nx.DiGraph()

        self.nodes = {n["meta"]["id"]: n for n in self.schema["nodes"]}
        self.dependency_sets = self.schema["recurring_dependencies"]

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
            node_meta = node["meta"]
            shape_dict[node_id] = mb.create_shape(
                shape_type=shape_types[node_meta["node_type"]],
                content=node_meta["description"],
                fill_color=node_colors[node_meta["applies_to"]],
                x=self.node_coordinates[node_id][0] * self.x_coord_factor,
                y=self.node_coordinates[node_id][1] * self.y_coord_factor,
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
        for node_id, gate_id in self.edge_tuples:
            mb.create_connector(shape_dict[node_id], shape_dict[gate_id])

    def _add_edge(self, from_node_id, to_node_id):
        self.edge_dict[from_node_id].append(to_node_id)
        self.edge_tuples.append((from_node_id, to_node_id))

    def _set_node_coordinates(self):
        nodes = list(self.nodes.keys()) + list(self.gates.keys())

        if self.layout_algorithm == "dependency_chart":
            self.node_coordinates = DependencyChartLayout().from_graph_data(
                nodes, self.edge_dict, self.edge_tuples
            )
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
}
node_colors = {
    "Land Representative": "#fdeeb7",
    "Project": "#dfb7e6",
    "Project Developer": "#c0e1fa",
    "Financiers / Bankers / Investors": "#b7f0f2",
    "Government Representatives": "#c6c9e8",
    "Carbon Auditor": "#fffcc7",
}
gate_colors = {
    "AND": "#E88E8E",
    "OR": "#50da8b",
    "XOR": "#50da8b",
    "NAND": "#FFBA91",
    "NOR": "#E8A5D8",
    "XNOR": "#E8A5D8",
}
