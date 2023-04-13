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
            "schemas/test/basic_dependency_chart.json", validate_schema=False
        )

        expected_node_depths = {
            0: -3,
            1: -2,
            2: -2,
            "a#0000": -1,
            3: 0,
        }
        assert {
            node_id: coords[0] for node_id, coords in graph.node_coordinates.items()
        } == expected_node_depths
