# open-impact-standard


# Schema Specification
The below psuedocode blocks describe the structure of valid json objects within an open standard schema. Open standard json schemas must conform to these specifications.

__Notes for psuedocode interpretation:__
- Capitalized value types indicate object types or enumeration types that are defined by this specification (e.g. `parties: [Party]` indicates that the `parties` array can only contain objects of type `Party`).
- Some field types indicate a specific field from another object that must exist within the schema (e.g. `node_id: Node.meta.id` indicates that the `node_id` field must reference the `id` field of an existing `Node` object).
- `?` indicates an optional field.
- `|` can be read as "or", and is used to indicate that a field, array, or json object can contain a more than one type of object.
- `//` indicates an inline code comment.

__Top-level json object:__
- `standard` is the name of the open standard.
- `parties` is the list of parties relevant to the open standard.
- `nodes` is a list containing the `Node` objects that comprise the standard's dependency chart.
- If two or more `Node` objects specify an identical `DependencySet` object (`Node.depends_on`), the `DependencySet` is added to the `referenced_dependency_sets` array and referenced by those nodes. `DependencySet` objects can be referenced in `Node.depends_on` using a `DependencySetReference` object.
````
{
    standard: string,
    parties: [Party],
    nodes: [Node],
    referenced_dependency_sets: [DependencySet]
}
````
__Node object type:__
- The keys of the `Node.data` object (denoted as `<field_name>` below) should be the names of any fields that instances of that node would have. There is no limit to the number of `<field_name>` keys that can be specified for a given node.
````
type Node {
    meta: {
        id: integer
        description: string,
        node_type: NodeType,
        applies_to: Party.name
    },
    data: {
        <field_name>: {
            field_type: FieldType,
            description: string?
        }
    },
    depends_on: DependencySet?
}
````
__NodeType enumeration:__
````
enum NodeType {
    ACTION,
    STATE,
    QUESTION
}
````
__FieldType enumeration:__
````
enum FieldType {
    STRING,
    NUMERIC,
    BOOLEAN
}
````
__DependencySet object type:__
- `alias` should be a human-readable name followed by a 4-digit hashtag to ensure uniqueness. E.g. "humanReadableName#0000"
- The `dependencies` array can include `Dependency` objects and/or `DependencySetReference` objects.
- `alias` and `gate_type` are not required when there are one or zero dependencies in the set.
````
type DependencySet {
    alias: string,
    gate_type: GateType,

    dependencies: [Dependency | DependencySetReference]
}
````
__Gate type enumeration:__
- Logic gate types through which groups of dependencies (`DependencySet` objects) can be evaluated.
````
enum GateType {
    AND,
    OR,
    XOR,
    NAND,
    NOR,
    XNOR
}
````
__DependencySetReference object type:__
- The `alias` field references the alias (unique identifier) of a recurring `DependencySet` object that has been added to the top-level object's `referenced_dependency_sets` array.
````
type DependencySetReference {
    alias: DependencySet.alias
}
````
__Dependency object type:__
- Represents a dependency of the parent `Node` object.
- `Dependency.node_id` references a `Node` object from the top-level object's `nodes` array.
- `field_name` must be a key that exists in the referenced `Node`'s `data` object.
- Exactly one comparison field must be present.
- A dependency is satisfied when applying the comparison field to the specified property on the referenced `Node` evaluates to `true`.
````
type Dependency {
    node_id: Node.meta.id,
    field_name: Node.data.key,

    // Comparison fields:
    equals: scalar?,
    does_not_equal: scalar?,
    greater_than: scalar?,
    less_than: scalar?,
    regex: string?,
    any_of: [scalar]?,
    one_of: [scalar]?,
    none_of: [scalar]?
}
````
__Party object:__
- Defines a relevant party for the open standard. E.g. "Project Developer", "Carbon Auditor", "Government Representatives"
````
type Party {
    name: string
    // Additional properties TBD...
}
````
- Basic example of a schema that conforms to the specification: [schemas/demo_schema.json](https://github.com/natureblocks/open-impact-standards/blob/main/schemas/demo_schema.json)

## Schema Visualization
Usage:
````python
from visualization.dependency_graph import DependencyGraph

# Convert json schema to graph and calculate node coordinates
graph = DependencyGraph(json_schema_file_path="schemas/demo_schema.json")
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

__Important Note:__ The `dependency_chart` layout algorithm has not been adequately tested for dependency charts that have more than one exit node, and such schemas may yield unexpected results. Multiple entry nodes (nodes with 0 dependencies) are supported.
