from visualization.dependency_graph import DependencyGraph


class TestDependencyGraph:
    def test_generate_miro_board(self):
        graph = DependencyGraph(json_schema_file_path="schemas/test/small_example_schema.json")
        graph.json_schema_to_graph()

        graph.generate_miro_board(board_name="Test Result (test_generate_miro_board)")

    def test_basic_dependency_chart_layout(self):
        graph = DependencyGraph(
            "schemas/test/basic_dependency_chart.json", validate_schema=False
        )
        graph.json_schema_to_graph()

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
