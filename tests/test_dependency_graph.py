from visualization.dependency_graph import DependencyGraph


class TestDependencyGraph:
    def test_generate_miro_board(self):
        """This test attempts to automatically generate a Miro board representation of the
        JSON schema located at the json_schema_file_path.

        The generate_miro_board method offers two ways of generating a Miro board:
            1. Generate a new Miro board by specifying a board_name (board_id must be None).
            2. Add to an existing Miro board by specifying a board_id.
                For example, if the existing board's URL is https://miro.com/app/board/abcdefg=/
                then board_id = "abcdefg="
        """

        # Specify the JSON file to use as the schema.
        json_schema_file_path = "schemas/test/small_example_schema.json"

        # Specify a board_id to add to an existing Miro board.
        # If board_id is None, a new board will be generated using the specified board_name.
        board_id = None

        # If generating a new board, specify the board_name.
        board_name = "Test Result (test_generate_miro_board)"

        # Set to False to skip JSON schema validation.
        validate_schema = True

        graph = DependencyGraph(
            json_schema_file_path=json_schema_file_path, validate_schema=validate_schema
        )

        if board_id is not None:
            graph.generate_miro_board(board_id=board_id)
        else:
            graph.generate_miro_board(
                board_name=board_name or "Test Result (test_generate_miro_board)"
            )

    def test_basic_dependency_chart_layout(self):
        graph = DependencyGraph(
            json_schema_file_path="schemas/test/basic_dependency_chart.json",
            validate_schema=False,
        )

        expected_node_depths = {
            "0": -3,
            "1": -2,
            "2": -2,
            "1 and 2": -1,
            "3": 0,
        }
        assert {
            action_id: coords[0] for action_id, coords in graph.node_coordinates.items()
        } == expected_node_depths

    def test_multi_condition_node_dependency(self):
        graph = DependencyGraph(
            json_schema_file_path="schemas/test/multi_condition_node_dependency.json"
        )
        # graph.generate_miro_board(board_name="Test Result (multi_condition_node_dependency)")

        # If a node lists more than one dependency for the same node id, a gate should be created
        assert len(graph.gates) == 1
        expected_edge_dict = {
            "1": ["a#0000"],
            "a#0000": ["0", "0"],
        }
        assert graph.edge_dict == expected_edge_dict

    def test_multi_entrance_node_layouts(self):
        expected_node_depths = {
            "schemas/test/multi_entrance_node_layout_1.json": {
                "0": -2,
                "1": -2,
                "0 and 1": -1,
                "2": 0,
            },
            "schemas/test/multi_entrance_node_layout_2.json": {
                "0": -3,
                "1": -2,
                "2": -2,
                "1 and 2": -1,
                "3": 0,
            },
            "schemas/test/multi_entrance_node_layout_3.json": {
                "10": 0,
                "8 and 9": -1,
                "9": -2,
                "8": -2,
                "6 and 7": -3,
                "4 and 5": -3,
                "7": -4,
                "6": -4,
                "5": -4,
                "4": -4,
                "1 and 2": -5,
                "3": -5,
                "2": -6,
                "1": -6,
                "0": -7,
            },
        }

        i = 1
        for path, expected_depths in expected_node_depths.items():
            graph = DependencyGraph(
                json_schema_file_path=path,
                validate_schema=False,
            )
            # graph.generate_miro_board(board_name=f"Test Result (test_multi_entrance_node_layouts, case {i})")
            i += 1

            actual_depths = {
                action_id: coords[0]
                for action_id, coords in graph.node_coordinates.items()
            }
            assert actual_depths == expected_depths

    def test_multi_exit_node_layouts(self):
        expected_node_depths = {
            "schemas/test/multi_exit_node_layout_1.json": {
                "0": -1,
                "1": 0,
                "2": 0,
            },
            "schemas/test/multi_exit_node_layout_2.json": {
                "3": 0,
                "2": 0,
                "1": -1,
                "0": -2,
            },
            "schemas/test/multi_exit_node_layout_3.json": {
                "3": 0,
                "2": 0,
                "1": -1,
                "0": -2,
            },
            "schemas/test/multi_exit_node_layout_4.json": {
                "6": 0,
                "13": 0,
                "10": 0,
                "9": 0,
                "5": -1,
                "12": -1,
                "4 and 7": -2,
                "11": -2,
                "7": -3,
                "4": -3,
                "8": -3,
                "3": -4,
                "2": -5,
                "1": -6,
                "0": -7,
            },
        }

        i = 1
        visualize_cases = []
        for path, expected_depths in expected_node_depths.items():
            graph = DependencyGraph(
                json_schema_file_path=path,
                validate_schema=False,
            )
            if i in visualize_cases:
                graph.generate_miro_board(
                    board_name=f"Test Result (test_multi_exit_node_layouts, case {i})"
                )
            i += 1

            actual_depths = {
                action_id: coords[0]
                for action_id, coords in graph.node_coordinates.items()
            }
            assert actual_depths == expected_depths

    def test_edge_overlap_prevention(self):
        possible_overlaps = {
            "schemas/test/edge_overlap_simple.json": {("1", "2", "5")},
            "schemas/test/edge_overlap_double_span.json": {("1", "2", "7")},
        }

        i = 1
        for path, tup in possible_overlaps.items():
            graph = DependencyGraph(
                json_schema_file_path=path,
                validate_schema=False,
            )
            # graph.generate_miro_board(board_name=f"Test Result (test_edge_overlap_prevention, {i})")
            i += 1

            y_coords = []
            for action_ids in tup:
                for action_id in action_ids:
                    y_coords.append(graph.node_coordinates[action_id][1])

            # the last node should be offset from the other two
            assert y_coords[0] == y_coords[1]
            assert y_coords[1] != y_coords[2]

    def test_gate_combinations(self):
        graph = DependencyGraph(
            json_schema_file_path="schemas/test/gate_combinations.json",
            validate_schema=False,
        )
        # graph.generate_miro_board(board_name="Test Result (test_gate_combinations)")

        expected_node_depths = {
            "7": 0,
            "e#0000": -1,
            "d#0000": -2,
            "c#0000": -2,
            "6": -3,
            "5": -3,
            "b#0000": -3,
            "a#0000": -3,
            "8": -3,
            "9": -3,
            "4": -4,
            "3": -4,
            "2": -4,
            "1": -4,
            "0": -4,
        }
        actual_depths = {
            action_id: coords[0] for action_id, coords in graph.node_coordinates.items()
        }
        assert actual_depths == expected_node_depths

    def test_multi_dependent_node(self):
        graph = DependencyGraph(
            json_schema_file_path="schemas/test/multi_dependent_node.json",
            validate_schema=False,
        )
        # graph.generate_miro_board(board_name="Test Result (test_multi_dependent_node)")

        expected_edge_tuples = [
            ("0", "6 or 7"),
            ("6 or 7", "6"),
            ("6 or 7", "7"),
            ("1", "0"),
            ("2", "1"),
            ("3", "1"),
            ("4", "1"),
            ("5", "3 and 4"),
            ("3 and 4", "3"),
            ("3 and 4", "4"),
        ]
        assert graph.edge_tuples == expected_edge_tuples
