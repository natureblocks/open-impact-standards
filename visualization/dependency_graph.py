import hashlib
import networkx as nx
import json
from validation.schema_validator import SchemaValidator
from validation.utils import recursive_sort
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

        self.actions = {}
        self.checkpoints = []
        self.gates = {}
        self.edge_tuples = []
        self.edge_dict = {}
        self.dependency_hashes = (
            {}
        )  # used to prevent duplicate dependencies from being added to a gate

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

        self.actions = {n["id"]: n for n in self.schema["actions"]}
        self.checkpoints = {c["alias"]: c for c in self.schema["checkpoints"]}

        self.edge_tuples = []
        self.gates = {}
        self.dependency_hashes = {}

        for action_id, action in self.actions.items():
            if "depends_on" not in action:
                continue

            self.edge_dict[action_id] = []
            self._explore_edges_recursive(
                action_id, checkpoint_alias=action["depends_on"]
            )

        self._set_node_coordinates()

    def _explore_edges_recursive(self, dependent_id, checkpoint_alias):
        def hash_sorted_object(obj):
            return hashlib.sha1(json.dumps(recursive_sort(obj)).encode()).digest()

        checkpoint = self.checkpoints[checkpoint_alias]
        num_dependencies = len(checkpoint["dependencies"])

        if num_dependencies > 1:
            # represent the checkpoint as a node
            self.graph.add_node(checkpoint_alias)
            self._add_edge(dependent_id, checkpoint_alias)
            self.gates[checkpoint_alias] = checkpoint["gate_type"]

            if checkpoint_alias not in self.edge_dict:
                self.edge_dict[checkpoint_alias] = []

            if checkpoint_alias not in self.dependency_hashes:
                self.dependency_hashes[checkpoint_alias] = []

            # connect the gate to the nodes it depends on
            for dep in checkpoint["dependencies"]:
                # checkpoints can contain standalone dependencies and checkpoint references
                if "node" in dep:
                    # if there is already a connection from the gate to this node,
                    # compare the dependencies and skip any duplicates.
                    dependency_hash = hash_sorted_object(dep["node"])
                    if dependency_hash in self.dependency_hashes[checkpoint_alias]:
                        continue
                    self.dependency_hashes[checkpoint_alias].append(dependency_hash)

                    to_action_id = dep["node"]["action_id"]
                    self._add_edge(checkpoint_alias, to_action_id)
                elif "checkpoint" in dep:
                    self._explore_edges_recursive(checkpoint_alias, dep["checkpoint"])

        elif num_dependencies == 1:
            # standalone dependency
            dependency = checkpoint["dependencies"][0]

            # prevent edge duplication for identical dependencies
            dependency_hash = hash_sorted_object(dependency["node"])
            if (
                dependent_id in self.dependency_hashes
                and dependency_hash in self.dependency_hashes[dependent_id]
            ):
                return

            if dependent_id not in self.dependency_hashes:
                self.dependency_hashes[dependent_id] = []
            self.dependency_hashes[dependent_id].append(dependency_hash)

            to_action_id = dependency["node"]["action_id"]
            self._add_edge(dependent_id, to_action_id)

            action = self.actions[to_action_id]
            if "depends_on" in action:
                return self._explore_edges_recursive(to_action_id, action["depends_on"])

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

        for action_id, node in self.actions.items():
            x = self.node_coordinates[action_id][0] * self.x_coord_factor
            y = self.node_coordinates[action_id][1] * self.y_coord_factor

            shape_dict[action_id] = mb.create_shape(
                shape_type=shape_types["ACTION"],
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

    def _add_edge(self, from_action_id, to_action_id):
        self.edge_dict[from_action_id].append(to_action_id)
        self.edge_tuples.append((from_action_id, to_action_id))

    def _set_node_coordinates(self):
        nodes = list(self.actions.keys()) + list(self.gates.keys())

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
}
