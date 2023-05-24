class DependencyChartLayout:
    def __init__(self):
        self.node_depths = {}

        self._apply_depth_offsets = False
        self.depth_origins = {}
        self.depth_offset_directives = {}
        self.depth_offsets = {}

        self.node_height = 2
        self.node_spacing = 1

        self.node_coordinates = {}

    def from_graph_data(self, node_ids, edge_dict, edge_tuples):
        """Calculates and returns a dictionary of node coordinates
        for a dependency chart layout based on the provided graph data.
        """

        # Layout is based on the depth of each node relative to the rightmost exit node
        exit_nodes = self._find_exit_nodes(node_ids, edge_tuples)
        self._calculate_node_depths(exit_nodes, edge_dict)

        # sort nodes into columns by depth
        columns = {depth: [] for depth in set(self.node_depths.values())}
        for node_id, depth in self.node_depths.items():
            columns[depth].append(node_id)

        sorted_columns = []
        column_offset = 0
        # assign coordinates to each node
        for depth, column in reversed(columns.items()):
            # reduce edge crossings
            sorted_column = self._sort_column_by_dependents(
                column, sorted_columns, edge_dict
            )

            node_count = len(column)
            column_height = (self.node_height * node_count) + (
                self.node_spacing * (node_count - 1)
            )

            # offset consecutive columns where y coordinates would exactly align,
            # unless either column only has a single node
            prev_column_count = len(sorted_columns[-1]) if sorted_columns else 0
            if (
                node_count > 1
                and prev_column_count > 1
                and node_count % 2 == prev_column_count % 2
            ):
                if column_offset == 0:
                    column_offset = self.node_spacing
                else:
                    column_offset *= -1

            # assign coordinates to nodes in column,
            # offsetting the column if necessary to avoid edge overlap
            while True:
                y = -column_height / 2 + column_offset
                for node_id in sorted_column:
                    self.node_coordinates[node_id] = (-depth, y)
                    y += self.node_height + self.node_spacing

                if self._has_definite_edge_overlap(
                    sorted_columns, sorted_column, edge_dict
                ):
                    column_offset += self.node_spacing
                else:
                    break

            sorted_columns.append(sorted_column)

        return self.node_coordinates

    def _calculate_node_depths(self, exit_nodes, edge_dict):
        self.node_depths = {}

        # If there is more than one exit node and their depths vary,
        # it may be necessary to apply depth offsets to nodes whose depths were
        # initially calculated relative to a non-rightmost exit node.
        self.depth_origins = {}  # from which origin was each depth calculated?
        self.depth_offset_directives = (
            {}
        )  # which origins directed offsets for other origins?
        self.depth_offsets = {}  # how much does each node's depth need to be adjusted?

        # calculate the depth of each node, with depth 0 being the rightmost exit node
        for exit_node in exit_nodes:
            self.node_depths[exit_node] = 0  # assume rightmost until proven otherwise
            self.depth_origins[exit_node] = exit_node

            self._calculate_node_depths_recursive(
                node_id=exit_node, edge_dict=edge_dict, depth=0, origin=exit_node
            )

        # apply depth offsets (not well tested!)
        if self._apply_depth_offsets:
            for origin, offset in self.depth_offsets.items():
                for node_id in self.node_depths.keys():
                    if self.depth_origins[node_id] == origin:
                        self.node_depths[node_id] += offset

    def _calculate_node_depths_recursive(self, node_id, edge_dict, depth, origin):
        if node_id in edge_dict:
            depth += 1
            for edge_node in edge_dict[node_id]:
                set_depth_and_recurse = False

                if edge_node not in self.node_depths:
                    # first time this node has been reached
                    set_depth_and_recurse = True
                elif self.node_depths[edge_node] < depth:
                    # longer path discovered
                    set_depth_and_recurse = True

                    if self._apply_depth_offsets:
                        # depth adjustment required for former origin
                        former_origin = self.depth_origins[edge_node]
                        if former_origin != origin:
                            # depth adjustment must cascade to all nodes with the same depth origin
                            if origin not in self.depth_offset_directives:
                                self.depth_offset_directives[origin] = []

                            self.depth_offset_directives[origin].append(former_origin)
                            adjustment = depth - self.node_depths[edge_node]
                            self.depth_offsets[former_origin] = adjustment

                            # offset directives must cascade
                            if former_origin in self.depth_offset_directives:
                                for adjustee_origin in self.depth_offset_directives[
                                    former_origin
                                ]:
                                    self.depth_offsets[adjustee_origin] += adjustment
                                    self.depth_offset_directives[origin].append(
                                        adjustee_origin
                                    )

                                self.depth_offset_directives.pop(former_origin)

                # elif self.node_depths[edge_node] > depth:
                # TODO: shorter path discovered -- depth adjustment required for current origin

                if set_depth_and_recurse:
                    self.node_depths[edge_node] = depth
                    self.depth_origins[edge_node] = origin

                    self._calculate_node_depths_recursive(
                        edge_node, edge_dict, depth, origin
                    )

    def _sort_column_by_dependents(self, column, sorted_columns, edge_dict):
        """Assign scores to pull each node up or down toward its dependents
        according to their positions in the previous column.
        """

        if len(column) < 2:
            return column

        score = {node_id: 0 for node_id in column}

        not_weighted = column.copy()
        column_idx = len(sorted_columns) - 1
        while not_weighted and column_idx >= 0:
            for dependent_id in sorted_columns[column_idx]:
                for node_id in column:
                    if (
                        node_id in not_weighted
                        and node_id in edge_dict
                        and dependent_id in edge_dict[node_id]
                    ):
                        score[node_id] += self.node_coordinates[dependent_id][1]
                        not_weighted.remove(node_id)

            # Continue searching previous columns for dependents
            # of any nodes from this column that have not yet been weighted.
            column_idx -= 1

        return sorted(column, key=lambda node_id: score[node_id])

    def _has_definite_edge_overlap(self, previous_columns, column, edge_dict):
        if len(previous_columns) < 2:
            # no spanned columns to check
            return False

        for node_id in column:
            if node_id not in edge_dict:
                continue

            for dependent_id in edge_dict[node_id]:
                # if the dependent is not in the previous column...
                if (
                    dependent_id not in previous_columns[-1]
                    and self.node_coordinates[dependent_id][1]
                    == self.node_coordinates[node_id][1]
                ):
                    # does a spanned column contain a node with the same y coordinate?
                    for col in previous_columns:
                        if dependent_id not in col:
                            for node in col:
                                if (
                                    self.node_coordinates[node][1]
                                    == self.node_coordinates[dependent_id][1]
                                ):
                                    return True

        return False

    def _find_exit_nodes(self, node_ids, edge_tuples):
        exit_nodes = []
        for node_id in node_ids:
            if node_id not in [b for (_, b) in edge_tuples]:
                exit_nodes.append(node_id)

        return exit_nodes
