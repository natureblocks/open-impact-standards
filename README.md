# open-impact-standard


# Schema Specification
- Requirements for open standard json schemas: [schema_specification.txt](https://github.com/natureblocks/open-impact-standards/blob/main/schema_specification.txt)
- Basic example of a schema that conforms to the specification: [schemas/demo_schema.json](https://github.com/natureblocks/open-impact-standards/blob/main/schemas/demo_schema.json)

## Schema Visualization
Usage:
````python
from visualization.dependency_graph import DependencyGraph

# Convert json schema to graph and calculate node coordinates
graph = DependencyGraph("schemas/demo_schema.json")
graph.json_schema_to_graph()
````
Generate a new Miro Board:
````python
graph.generate_miro_board(board_id="New Board Name")
````
Or add to an existing Miro Board:
````python
existing_board_id = "" # grab this from the end of the board's url on miro.com
graph.generate_miro_board(board_id=existing_board_id)
````
