# Open Impact Standard

## Schema Specification
The below psuedocode blocks describe the structure of valid json objects within an open standard schema. Open standard json schemas must conform to these specifications.

- An example json file illustrating the different object types can be found here: [schemas/example.json](https://github.com/natureblocks/open-impact-standards/blob/main/schemas/example.json)

__Notes for psuedocode interpretation:__
- Capitalized value types indicate object types or enumeration types that are defined by this specification (e.g. `parties: [Party]` indicates that the `parties` array can only contain objects of type `Party`).
- Some field types indicate a specific field from another object that must exist within the schema (e.g. `action_id: Action.id` indicates that the `action_id` field must reference the `id` field of an existing `Action` object).
- `?` at the end of an object key indicates that the key is optional.
- `?` at the end of a value type indicates that the value is nullable.
- `?*` indicates optional/nullable as above, but only under certain conditions.
- `|` can be read as "or", and is used to indicate that a field, array, or json object can contain a more than one type of object or value.
- `//` indicates an inline code comment.

__Top-level json object:__
- `standard` is the name of the open standard.
- `parties` is the list of parties relevant to the open standard.
- The keys of the `nodes` object (denoted as `<node_tag>` below) define the node tags that the schema requires. `Action.tag` must reference a defined node tag.
- `actions` and `checkpoints` are lists containing the `Action` and `Checkpoint` objects that comprise the standard's dependency chart.
````
{
    standard: string,
    term_definitions: [TermDefinition],
    parties: [Party],
    nodes: {<node_tag>: NodeDefinition},
    actions: [Action],
    checkpoints: [Checkpoint]
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
        tag?*: string,
        description?: string
    }
}
````
__Action object type:__
- `tag` must be a key of the top-level (root) object's `nodes` object.
- `operation` allows the operation type to be specified, as well as the fields that can be set when completing the action.
- `depends_on` references the `Checkpoint` that must be satisfied before the action can be taken.
- A `Action` may specify 0 or more `Milestone` values, but a given `Milestone` value may not appear on `Action` objects more than once per schema.
````
type Action {
    id: integer,
    description: string,
    steps: {
        title: string,
        description: string
    },
    party: reference(Party),
    tag: root.nodes.key,
    operation: Operation,
    depends_on?: reference(Checkpoint),
    milestones?: [Milestone],
    supporting_info?: [string]
}
````
__Operation object type:__
- `include` is for specifying the fields that can be set on the node that is to be created or editied by the parent `Action`. Specifying `null` for this field indicates that no fields are included, or in other words, that all fields are excluded.
- `exclude` is for specifying the fields that cannot be set on the node that is to be created or editied. Specifying `null` for this field indicates that no fields are excluded, or in other words, that all fields are included.
- `include` and `exclude` are mutually exclusive.
- An `Action` may specify 0 or more `Milestone` values, but a given `Milestone` value may not appear on `Action` objects more than once per schema.
- If `type` is `"CREATE"`, then `default_values` and `default_edges` can optionally be specified.
- If `type` is `"EDIT"`, then `ref` is required to indicate the `Action` whence the node to be edited came.
````
type Operation {
    type: "CREATE" | "EDIT",
    
    // Mutually exclusive:
    include: [<field_name>]?,
    exclude: [<field_name>]?,

    // If type is "CREATE":
    default_values?: {
        <field_name>: scalar
    },
    default_edges?: {
        <field_name>: reference(Action)
    },

    // If type is "EDIT":
    ref?*: reference(Action)
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
__Checkpoint object type:__
- `alias` should be a unique, human-readable name.
- The `description` should provide more information about the significance of the `Checkpoint`.
- The `dependencies` array can include `Dependency` objects and/or `CheckpointReference` objects.
- To prevent redundancies, a lone `CheckpointReference` cannot be the only item in `Checkpoint.dependencies`.
- `gate_type` should not be specified when the number of items in the `dependencies` array is 1.
````
type Checkpoint {
    id: integer,
    alias: string,
    description: string,
    gate_type?*: GateType,
    dependencies: [Dependency | CheckpointReference],
}
````
__GateType enumeration:__
- Logic gate types through which groups of dependencies (`Checkpoint` objects) can be evaluated.
- `XNOR` has been intentionally omitted as it reduces state map clarity.
````
enum GateType {
    "AND",
    "OR",
    "XOR",
    "NAND",
    "NOR"
}
````
__CheckpointReference object type:__
- The `checkpoint` field references the id or alias of a `Checkpoint` object that has been added to the top-level object's `checkpoints` array.
- `CheckpointReference`s can be used to achieve complex logic gate combinations. A basic example would be `dependency_1` AND (`dependency_2` OR `dependency_3`).
````
type CheckpointReference {
    checkpoint: reference(Checkpoint)
}
````
__Dependency object type:__
- Represents a dependency of the parent `Checkpoint` object.
- `left` and `right` are the operands to be compared using the `operator`.
- `description` can be used to provide more detail about the `Dependency`.
````
type Dependency {
    compare: {
        left: ReferencedOperand | LiteralOperand,
        right: ReferencedOperand | LiteralOperand,
        operator: ComparisonOperator,
        description?: string
    }
}
````
__ReferencedOperand object type:__
- A reference to a `field` that must exist in the `NodeDefinition` that corresponds to the `tag` of the referenced `Action` (`ref`).
- A `ReferencedOperand` evaluates to the value of the referenced field.
- The `field_type` of the referenced field is checked against the other-side operand of the parent `Dependency` and the `Dependency.compare.operator` to determine whether the comparison is valid.
````
type ReferencedOperand {
    ref: reference(Action),
    field: string
}
````
__LiteralOperand object type:__
- A literal value of any type to be used as an operand in `Dependency.compare`.
- `LiteralOperand` types are checked against the other-side operand of the parent `Dependency` and the `Dependency.compare.operator` to determine whether the comparison is valid.
````
type LiteralOperand {
    value: scalar
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
    "ONE_OF",
    "NONE_OF",
    "CONTAINS",
    "DOES_NOT_CONTAIN",
    "CONTAINS_ANY_OF",
    "IS_SUBSET_OF",
    "IS_SUPERSET_OF",
    "CONTAINS_NONE_OF"
}
````
__TermDefinition object:__
- Defines a term that is used in the schema.
- `attributes` can be used flexibly to aid in the clarity of the `description`.
````
type TermDefinition {
    name: string,
    description: string,
    attributes?: [string]
}
````
__Party object:__
- Defines a relevant party for the schema.
- Example party `name`s: "Project Developer", "Carbon Auditor", "Government Representatives"
- `hex_code` sets the color of the applicable Miro shapes in state map visualizations (see the Schema Visualization) section below. If `hex_code` is not specified, the default `#ffffff` is used.
````
type Party {
    id: integer,
    name: string,
    hex_code?: string
}
````

### Schema Validation
Running Tests:
- Validation tests can be found in [tests/test_schema_validation.py](https://github.com/natureblocks/open-impact-standards/blob/main/tests/test_schema_validation.py).
- The `test_validate_schema` test runs validation on the schema at the specified `json_file_path`. Simply run the test and check stdout for validation errors (refer to the test's docstring for more details).
- The `test_get_next_action_id` and `test_get_all_action_ids` tests are validation utilities. Check the docstring on each test for usage instructions.

General Usage:
````python
from validation.schema_validator import SchemaValidator

# Specify which JSON file to validate.
json_file_path = "path/to/my_schema_file.json"

validator = SchemaValidator()
errors = validator.validate(json_file_path=json_file_path)

if errors:
    validator.print_errors()
````

### Schema Visualization
Prerequisites:
- Must create a Miro app and generate an OAuth token. To do this from the Miro dashboard navigate to Team profile > Profile settings > Your apps > Create new app. Once the app has been created scroll down to All Plans, then select `boards:read` and `boards:write` permissions, then click "Install app and get OAuth token". 
- Must include the OAuth token in a file called `tokens.json` in the root folder of the repository, like so:
````
{
    "access_token": "4U7H021Z3_M3"
}
````

Running Tests:
- Visualization tests can be found in [tests/test_dependency_graph.py](https://github.com/natureblocks/open-impact-standards/blob/main/tests/test_dependency_graph.py).
- The `test_generate_miro_board` test attempts to generate a Miro board representation of the schema at the specified `json_schema_file_path`. See the test's docstring for usage details.

General Usage:
````python
from visualization.dependency_graph import DependencyGraph

# Specify which JSON file to visualize.
json_schema_file_path = "schemas/my_schema_file.json"

# Convert json schema to graph and calculate node coordinates.
graph = DependencyGraph(json_schema_file_path=json_schema_file_path)

# Generate a new Miro board on the connected Miro app.
graph.generate_miro_board(board_name="New Board Name")
````

__Important Note:__ The `dependency_chart` layout algorithm has not been adequately tested for dependency charts that have more than one exit node, and such schemas may yield unexpected results. Multiple entry nodes (nodes with 0 dependencies) are supported.
