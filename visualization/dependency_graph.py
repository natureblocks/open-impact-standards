import networkx as nx
import json
from utils import hash_sorted_object
from validation.schema_validator import SchemaValidator
from validation.utils import parse_ref_id
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
        self.edge_captions = {}
        self.dependency_hashes = (
            {}
        )  # this is used to prevent duplicate dependencies from being added to a gate

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

        self.actions = {str(n["id"]): n for n in self.schema["actions"]}
        self.checkpoints = {c["alias"]: c for c in self.schema["checkpoints"]}

        self.edge_tuples = []
        self.gates = {}
        self.dependency_hashes = {}

        for action_id, action in self.actions.items():
            if "depends_on" not in action:
                continue

            self._explore_edges_recursive(
                action_id, checkpoint_alias=parse_ref_id(action["depends_on"])
            )

        self._set_node_coordinates()

    def _explore_edges_recursive(self, dependent_id, checkpoint_alias):
        def is_duplicate_dependency(dependent_id, dependency_obj):
            if dependent_id not in self.dependency_hashes:
                self.dependency_hashes[dependent_id] = []

            dependency_hash = hash_sorted_object(dependency_obj)
            if dependency_hash in self.dependency_hashes[dependent_id]:
                return True

            self.dependency_hashes[dependent_id].append(dependency_hash)
            return False

        checkpoint = self.checkpoints[checkpoint_alias]
        num_dependencies = len(checkpoint["dependencies"])

        if num_dependencies > 1:
            if is_duplicate_dependency(dependent_id, checkpoint):
                return

            # represent the checkpoint as a node
            self.graph.add_node(checkpoint_alias)
            self._add_edge(
                dependent_id, checkpoint_alias, checkpoint_dependency=checkpoint
            )
            self.gates[checkpoint_alias] = checkpoint["gate_type"]

            if checkpoint_alias not in self.dependency_hashes:
                self.dependency_hashes[checkpoint_alias] = []

            # connect the gate to the nodes it depends on
            for dep in checkpoint["dependencies"]:
                # checkpoints can contain standalone dependencies and checkpoint references
                if "compare" in dep:
                    if is_duplicate_dependency(checkpoint_alias, dep):
                        continue

                    for operand in ["left", "right"]:
                        if (
                            operand not in dep["compare"]
                            or "ref" not in dep["compare"][operand]
                        ):
                            continue

                        if "ref" in dep["compare"][operand]:
                            self._add_edge(
                                checkpoint_alias,
                                parse_ref_id(dep["compare"][operand]["ref"]),
                                action_dependency=dep["compare"],
                            )
                elif "checkpoint" in dep:
                    self._explore_edges_recursive(
                        checkpoint_alias, parse_ref_id(dep["checkpoint"])
                    )

        elif num_dependencies == 1:
            # standalone dependency
            dependency = checkpoint["dependencies"][0]

            # prevent edge duplication for identical dependencies
            if is_duplicate_dependency(dependent_id, dependency):
                return

            for operand in ["left", "right"]:
                if (
                    operand not in dependency["compare"]
                    or "ref" not in dependency["compare"][operand]
                ):
                    continue

                if "ref" in dependency["compare"][operand]:
                    to_action_id = parse_ref_id(dependency["compare"][operand]["ref"])

                self._add_edge(
                    dependent_id, to_action_id, action_dependency=dependency["compare"]
                )

                action = self.actions[to_action_id]
                if "depends_on" in action:
                    self._explore_edges_recursive(
                        to_action_id, parse_ref_id(action["depends_on"])
                    )

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
        def create_supporting_info_shape(supporting_info, x, y):
            mb.create_shape(
                shape_type=shape_types["SUPPORTING_INFO"],
                content="- " + "<br/>- ".join(supporting_info),
                text_align="left",
                fill_color="#D0E78C",
                x=x + self.node_spacing * self.x_coord_factor / 5,
                y=y - self.node_height * self.y_coord_factor / 2,
            )

        shape_dict = {}

        for action_id, node in self.actions.items():
            x = self.node_coordinates[action_id][0] * self.x_coord_factor
            y = self.node_coordinates[action_id][1] * self.y_coord_factor

            shape_dict[action_id] = mb.create_shape(
                shape_type=shape_types["ACTION"],
                content=node["description"] if "description" in node else node["id"],
                fill_color=self.party_colors[parse_ref_id(node["party"])]
                if "party" in node
                else self._default_node_color,
                x=x,
                y=y,
            )

            if "supporting_info" in node:
                create_supporting_info_shape(node["supporting_info"], x, y)

        for alias, gate_type in self.gates.items():
            x = self.node_coordinates[alias][0] * self.x_coord_factor
            y = self.node_coordinates[alias][1] * self.y_coord_factor

            shape_dict[alias] = mb.create_shape(
                shape_type=shape_types["GATE"],
                content=gate_type,
                fill_color=gate_colors[gate_type],
                x=x,
                y=y,
            )

            if "supporting_info" in self.checkpoints[alias]:
                create_supporting_info_shape(
                    self.checkpoints[alias]["supporting_info"], x, y
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
                mb.create_connector(
                    shape_dict[from_id],
                    shape_dict[to_id],
                    caption=self.edge_captions[(from_id, to_id)][0]
                    if (from_id, to_id) in self.edge_captions
                    and len(self.edge_captions[(from_id, to_id)]) == 1
                    else None,
                )
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

                    caption = (
                        self.edge_captions[(from_id, to_id)][i]
                        if (from_id, to_id) in self.edge_captions
                        and len(self.edge_captions[(from_id, to_id)]) > i
                        else None
                    )

                    # Connect the gate and node through the elbow
                    # using two connector segments
                    mb.create_connector(
                        shape_dict[from_id],
                        elbow_id,
                        end_stroke_cap="none",
                        caption=caption if i % 2 == 0 else None,
                    )
                    mb.create_connector(
                        elbow_id,
                        shape_dict[to_id],
                        caption=caption if i % 2 == 1 else None,
                    )

    def _add_edge(
        self,
        from_action_id,
        to_action_id,
        action_dependency=None,
        checkpoint_dependency=None,
    ):
        if from_action_id not in self.edge_dict:
            self.edge_dict[from_action_id] = []

        self.edge_dict[from_action_id].append(to_action_id)
        edge_tuple = (from_action_id, to_action_id)
        self.edge_tuples.append(edge_tuple)

        if (
            action_dependency or checkpoint_dependency
        ) and edge_tuple not in self.edge_captions:
            self.edge_captions[edge_tuple] = []

        if (
            action_dependency
            and "left" in action_dependency
            and "right" in action_dependency
            and "operator" in action_dependency
        ):
            self.edge_captions[edge_tuple].append(
                (
                    action_dependency["left"]["field"]
                    if "field" in action_dependency["left"]
                    else action_dependency["left"]["value"]
                )
                + " "
                + _comparison_operator_map[action_dependency["operator"]]
                + " "
                + (
                    str(action_dependency["right"]["value"])
                    if "value" in action_dependency["right"]
                    else action_dependency["right"]["field"]
                )
            )
        elif checkpoint_dependency and "description" in checkpoint_dependency:
            self.edge_captions[edge_tuple].append(
                checkpoint_dependency["abbreviated_description"]
                if "abbreviated_description" in checkpoint_dependency
                else checkpoint_dependency["description"]
            )

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
_comparison_operator_map = {
    "EQUALS": "=",
    "DOES_NOT_EQUAL": "!=",
    "GREATER_THAN": ">",
    "LESS_THAN": "<",
    "GREATER_THAN_OR_EQUAL_TO": ">=",
    "LESS_THAN_OR_EQUAL_TO": "<=",
    "ONE_OF": "IN",
    "NONE_OF": "NOT IN",
    "CONTAINS": "CONTAINS",
    "DOES_NOT_CONTAIN": "DOES NOT CONTAIN",
    "CONTAINS_ANY_OF": "CONTAINS ANY OF",
    "CONTAINS_NONE_OF": "CONTAINS NONE OF",
    "IS_SUPERSET_OF": "IS SUPERSET OF",
    "IS_SUBSET_OF": "IS SUBSET OF",
}
