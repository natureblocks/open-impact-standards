# open-impact-standards


# Schema Specification
The below psuedocode blocks describe the structure of valid json objects within an open standard schema. Open standard json schemas must conform to these specifications.

__Notes for psuedocode interpretation:__
- Capitalized value types indicate object types or enumeration types that are defined by this specification (e.g. `parties: [Party]` indicates that the `parties` array can only contain objects of type `Party`).
- Some field types indicate a specific field from another object that must exist within the schema (e.g. `node_id: StateNode.id` indicates that the `node_id` field must reference the `id` field of an existing `StateNode` object).
- `?` indicates an optional field.
- `?*` indicates that a field is optional only under certain conditions.
- `|` can be read as "or", and is used to indicate that a field, array, or json object can contain a more than one type of object or value.
- `//` indicates an inline code comment.

__Top-level json object:__
- `standard` is the name of the open standard.
- `parties` is the list of parties relevant to the open standard.
- The keys of the `node_definitions` object (denoted as `<node_tag>` below) define the node tags that the schema requires. `StateNode.tag` must reference a defined node tag.
- `state_nodes` is a list containing the `StateNode` objects that comprise the standard's dependency chart.
- If two or more `StateNode` objects specify an identical `DependencySet` object (`StateNode.depends_on`), the `DependencySet` is added to the `referenced_dependency_sets` array and referenced by those nodes. `DependencySet` objects can be referenced in `StateNode.depends_on` using a `DependencySetReference` object.
````
{
    standard: string,
    parties: [Party],
    node_definitions: {<node_tag>: NodeDefinition},
    state_nodes: [StateNode],
    referenced_dependency_sets: [DependencySet]
}
````
__NodeDefinition object type:__
- The keys of a `NodeDefinition` object (denoted as `<field_name>` below) should be the names of any fields that instances of that node type would have. There is no limit to the number of `<field_name>` keys that can be specified for a given `NodeDefinition`.
- `tag` is optional when `field_type` is set to any `FieldType` enum value. If `field_type` is set to `"EDGE"` or `"EDGE_COLLECTION"` then `tag` is required to specify the `NodeDefinition` of node instance(s) that the edge or edge collection can reference.
- `description` can be used to provide more detail regarding the purpose of the field.
````
type NodeDefinition {
    <field_name>: {
        field_type: FieldType | "EDGE" | "EDGE_COLLECTION",
        tag: string?*,
        description: string?
    }
}
````
__StateNode object type:__
- `tag` must be a key of the top-level (root) object's `node_definitions` object. A `StateNode`'s `tag` affects some aspects of `Dependency` validation within the `StateNode.depends_on` `DependencySet` (see the `Dependency` object type for more details).
- A `StateNode` may specify 0 or more `Milestone` values, but a given `Milestone` value may not appear on `StateNode` objects more than once per schema.
````
type StateNode {
    id: integer
    description: string,
    node_type: StateNodeType,
    applies_to: Party.name,
    tag: root.node_definitions.key,
    depends_on: DependencySet?,
    milestones: [Milestone]?
}
````
__StateNodeType enumeration:__
````
enum StateNodeType {
    "ACTION",
    "STATE",
    "QUESTION"
}
````
__FieldType enumeration:__
````
enum FieldType {
    "STRING",
    "NUMERIC",
    "BOOLEAN",
    "STRING_LIST",
    "NUMERIC_LIST"
}
````
__Milestone enumeration:__
````
enum Milestone {
    "REAL",
    "CLEAR_OWNERSHIP",
    "PERMANENT",
    "ADDITIONAL",
    "VERIFIABLE"
}
````
__DependencySet object type:__
- `alias` should be a human-readable name followed by a 4-digit hashtag to ensure uniqueness. E.g. "humanReadableName#0000"
- The `dependencies` array can include `Dependency` objects and/or `DependencySetReference` objects.
- `alias` and `gate_type` are not required when there are one or zero dependencies in the set.
- `description` can be used to provide more detail about the `DependencySet`.
````
type DependencySet {
    alias: string,
    gate_type: GateType,
    dependencies: [Dependency | DependencySetReference],
    description: string?
}
````
__GateType enumeration:__
- Logic gate types through which groups of dependencies (`DependencySet` objects) can be evaluated.
````
enum GateType {
    "AND",
    "OR",
    "XOR",
    "NAND",
    "NOR",
    "XNOR"
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
- Represents a dependency of the parent `StateNode` object.
- `Dependency.node_id` references a `StateNode` object from the top-level object's `state_nodes` array.
- `field_name` references a key of the `NodeDefinition` that's indicated by the referenced `StateNode`'s `tag`.
- `comparison_value_type` must match the `field_type` of the referenced `field_name`.
- A dependency is satisfied when applying the `comparison_operator` to the applicable comparison value field and the specified field on the referenced `StateNode` evaluates to `true`.
- `comparison_value_type` indicates the applicable comparison value field for the dependency. Only the indicated comparison value field is required. Values of non-applicable comparison value fields are ignored during dependency evaluation.
- `description` can be used to provide more detail about the `Dependency`.
````
type Dependency {
    node_id: StateNode.id,
    field_name: NodeDefinition.key,
    comparison_operator: ComparisonOperator,
    comparison_value_type: FieldType,

    // Comparison value fields
    string_comparison_value: string,
    numeric_comparison_value: number,
    boolean_comparison_value: boolean,
    string_list_comparison_value: [string],
    numeric_list_comparison_value: [number],

    description: string?
}
````
__ComparisonOperator enumeration:__
````
enum ComparisonOperator {
    "EQUALS",
    "DOES_NOT_EQUAL",
    "GREATER_THAN",
    "LESS_THAN",
    "GREATER_THAN_OR_EQUAL_TO",
    "LESS_THAN_OR_EQUAL_TO",
    "MATCHES_REGEX",
    "DOES_NOT_MATCH_REGEX",
    "ONE_OF",
    "NONE_OF",
    "CONTAINS",
    "DOES_NOT_CONTAIN",
    "CONTAINS_ANY_OF",
    "CONTAINS_ALL_OF",
    "CONTAINS_NONE_OF"
}
````
__Party object:__
- Defines a relevant party for the open standard.
- Example party `name`s: "Project Developer", "Carbon Auditor", "Government Representatives"
- `hex_code` sets the color of the applicable Miro shapes in state map visualizations (see the Schema Visualization) section below. If `hex_code` is not specified, the default `#ffffff` is used.
````
type Party {
    name: string,
    hex_code: string?
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
