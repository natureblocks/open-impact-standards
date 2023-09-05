# Open Impact Standard

## Schema Specification
The below psuedocode blocks describe the structure of valid json objects within an open standard schema. Open standard json schemas must conform to these specifications.

- An example json file illustrating the different object types can be found here: [schemas/example.json](https://github.com/natureblocks/open-impact-standards/blob/main/schemas/example.json)

__Notes for psuedocode interpretation:__
- Capitalized value types indicate object types or enumeration types that are defined by this specification (e.g. `parties: [Party]` indicates that the `parties` array can only contain objects of type `Party`).
- `?` at the end of an object key indicates that the key is optional.
- `?` at the end of a value type indicates that the value is nullable.
- `?*` indicates optional/nullable as above, but only under certain conditions.
- `|` can be read as "or", and is used to indicate that an attribute, array, or json object can contain a more than one type of object or value.
- `//` indicates an inline code comment.
- The `reference()` syntax indicates that the attribute must be a global reference to an entity of the object type specified within the brackets. An example of a global reference to an `ObjectPromise` entity (denoted as `reference(ObjectPromise)`) is `"object_promise:2"`, where `object_promise` is the reference type (snake case) and `2` is the `id` of the referenced `ObjectPromise`. The referenceable unique identifiers for each object type can be found at the end of each object type description below.
- The `reference_path()` syntax is the same as the `reference()` syntax, except it indicates that a dot-separated path from the referenced object can be specified as part of the reference. For example, `"object_promise:2.my_attribute"` would reference the value of `my_attribute` on the promised object instance, provided that the `ObjectType` that is referenced by the `ObjectPromise` defines an attribute called `my_attribute`.

__Root json object:__
- Henceforth denoted as `root`.
- `standard` is the name of the open standard.
- `parties` is the list of parties relevant to the open standard.
- The keys of the `object_types` object (denoted as `<object_tag>` below) define the object type names that the schema requires.
- `actions` and `checkpoints` are lists containing the `Action` and `Checkpoint` objects that comprise the standard's dependency chart.
````
{
    standard: string,
    terms: [Term],
    parties: [Party],
    object_types: {<object_tag>: ObjectType},
    object_promises: [ObjectPromise],
    actions: [Action],
    checkpoints: [Checkpoint],
    thread_groups?: [ThreadGroup],
    pipelines: [Pipeline]
}
````
__ObjectType:__
- The keys of an `ObjectType` object (denoted as `<attribute>` below) should be the names of any attributes that instances of that object would have. There is no limit to the number of `<attribute>` keys that can be specified for a given `ObjectType`.
- `tag` is optional when `field_type` is set to any `FieldType` enum value. If `field_type` is set to `"EDGE"` or `"EDGE_COLLECTION"` then `tag` is required to specify the `ObjectType` of object instance(s) that the edge or edge collection can reference.
- `description` can be used to provide more detail regarding the purpose of the attribute.
````
type ObjectType {
    <attribute>: {
        field_type: FieldType | "EDGE" | "EDGE_COLLECTION",
        tag?*: string,
        description?: string
    }
}
````
__Action:__
- `id` must be unique within `root.actions`.
- `operation` allows specifying which attributes can be set when completing the action.
- `object_promise` specifies the promised object instance on which the `operation` will act.
- `context` determines whether the `Action` is to be completed as part of a thread within a `ThreadGroup`.
- `depends_on` references the `Checkpoint` that must be satisfied before the action can be taken.
- An `Action` may specify 0 or more `Milestone` values, but a given `Milestone` value may not appear on `Action` objects more than once per schema.
- Referenceable: `id`
````
type Action {
    id: integer,
    description: string,
    steps?: {
        title: string,
        description: string
    },
    party: reference(Party),
    object_promise: reference(ObjectPromise),
    operation: Operation,
    context?: reference(ThreadGroup),
    depends_on?: reference(Checkpoint),
    milestones?: [Milestone],
    supporting_info?: [string]
}
````
__Operation:__
- `include` is for specifying the fields that can be set on the object instance that is promised by the parent `Action`'s `object_promise`. Specifying `null` for this attribute indicates that no fields are included, or in other words, that all fields are excluded.
- `exclude` is for specifying the fields that cannot be set on the promised object instance. Specifying `null` for this attribute indicates that no fields are excluded, or in other words, that all fields are included.
- `include` and `exclude` are mutually exclusive.
- An `Action` may specify 0 or more `Milestone` values, but a given `Milestone` value may not appear on `Action` objects more than once per schema.
- If the parent `Action` fulfills the object promise (is the first action in the state map to reference that specific `ObjectPromise`, and will therefore trigger the creation of the object instance), then `default_values` and `default_edges` can optionally be specified. Defaults are not supported for edge collections.
- If the parent `Action` fulfills the object promise and is never referenced by a checkpoint dependency, `appends_objects_to` can be used to reference an edge collection to which new instances of the object promise will be automatically appended. This mechanism is useful for manually spawning threads within a `ThreadGroup` that is set to spawn a new thread for each item in the referenced edge collection.
- If the parent `Action` DOES NOT fulfill the object promise (an ancestor `Action` within the state map fulfills the promise), its `operation` is inferred to be editing an already-instantiated object. In that case, `default_fields` and `default_edges` shall not be specified by the `operation`.
````
type Operation {
    // Mutually exclusive:
    include: [<attribute>]?,
    exclude: [<attribute>]?,

    default_values?: {
        <attribute>: scalar
    },
    default_edges?: {
        <attribute>: reference(Action)
    },
    appends_objects_to?*: reference_path(ObjectPromise)
}
````
__Checkpoint:__
- `id` must be unique within `root.checkpoints`
- `alias` should a human-readable name, and must also be unique within `root.checkpoints`.
- The `description` should provide more information about the significance of the `Checkpoint`.
- The `dependencies` array can include `Dependency` objects and/or `CheckpointReference` objects.
- To prevent redundancies, a lone `CheckpointReference` cannot be the only item in the `dependencies` array.
- `gate_type` shall not be specified when the number of items in the `dependencies` array is 1.
- `context` determines the `ThreadGroup` context in which the `Checkpoint` is allowed to be referenced.
- Referenceable: `id`, `alias`
````
type Checkpoint {
    id: integer,
    alias: string,
    description: string,
    abbreviated_description?: string,
    supporting_info?: [string],
    gate_type?*: GateType,
    dependencies: [Dependency | CheckpointReference],
    context?: reference(ThreadGroup)
}
````
__CheckpointReference:__
- The `checkpoint` attribute references a `Checkpoint` object from the `root` object's `checkpoints` array.
- `CheckpointReference`s can be used to achieve complex logic gate combinations. A basic example would be `dependency_1` AND (`dependency_2` OR `dependency_3`).
````
type CheckpointReference {
    checkpoint: reference(Checkpoint)
}
````
__Dependency:__
- Represents a dependency of the parent `Checkpoint` object.
- `left` and `right` are the operands to be compared using the `operator`. At least one of the operands must be a `ReferencedOperand`.
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
__ReferencedOperand:__
- A reference to an attribute on the applicable `ObjectType`, or a reference to a path that begins with a `thread_variable`.
- If `ref` is a `reference_path(Action)`, the applicable `ObjectType` is inferred from the `Action` that is referenced by the first segment of the `ReferencedOperand`'s `ref` path. That `Action`'s `object_promise` attribute points to an `ObjectPromise`, which in turn has an `object_type` attribute that points to the applicable `ObjectType`.
- A `ReferencedOperand` evaluates to the value of the referenced attribute or `thread_variable`.
- The `field_type` of the reference is evaluated and checked against the other-side operand of the parent `Dependency` and the `Dependency.compare.operator` to determine whether the comparison is valid.
````
type ReferencedOperand {
    ref: reference_path(Action) | thread_variable_path
}
````
__LiteralOperand:__
- A literal value of any type to be used as an operand in `Dependency.compare`.
- `LiteralOperand` types are checked against the other-side operand of the parent `Dependency` and the `Dependency.compare.operator` to determine whether the comparison is valid.
````
type LiteralOperand {
    value: scalar
}
````
__ThreadGroup:__
- Some sequences of `Action`s and `Checkpoint`s need to be completed for each member of a party, for each item in a list, or for each object in an edge collection. `ThreadGroups` accomplish this by enabling the `context` attribute of an `Action` or `Checkpoint` to indicate that it is part of a threaded sequence and will be executed in parallel with the other threads in the `ThreadGroup`.
- `id` must be unique within `root.thread_groups`.
- `spawn` defines the source `from` which to spawn threads `foreach` item in a collection. It also defines the name of the variable (`as`) to which the value of the item will be assigned for a given thread in the thread group.
- If `context` is specified, the `ThreadGroup` is nested within another `ThreadGroup`. Nested `ThreadGroup`s can be spawned using `reference_path`s as normal, or from paths from existing `thread_variable`s that are available in the `ThreadGroup.context`.
- A `thread_variable_path` can either be the name of a `thread_variable` or a path that begins with a `thread_variable`.
- `Pipeline`s are a mechanism for specifying how data should be aggregated during the execution of a state map instance.
- Referenceable: `id`
````
type ThreadGroup {
    id: integer,
    description?: string,
    context?: reference(ThreadGroup),
    depends_on?: reference(Checkpoint),
    spawn: {
        from: reference_path(ObjectPromise) | thread_variable_path,
        foreach: string,
        as: string
    }
}
````
__Term:__
- Defines a term that is used in the schema.
- `attributes` can be used flexibly to aid in the clarity of the `description`.
- Referenceable: `name`
````
type Term {
    name: string,
    description: string,
    attributes?: [string]
}
````
__Party:__
- Defines a relevant party for the schema.
- Example party `name`s: "Project Developer", "Carbon Auditor", "Government Representatives"
- `id` and `name` must be unique within `root.parties`.
- `hex_code` sets the color of the applicable Miro shapes in state map visualizations (see the Schema Visualization) section below. If `hex_code` is not specified, the default `#ffffff` is used.
- Referenceable: `id`, `name`
````
type Party {
    id: integer,
    name: string,
    hex_code?: string
}
````

### Pipelines
- A pipeline's `object_promise` references the promised object instance to which the `Pipeline.output`s will write. The pipeline inherits its threaded (or non-threaded) context from the referenced `ObjectPromise`. When a pipeline inherits a threaded context, in-scope `thread_variable`s can be referenced within the pipeline where indicated by this specification.
- The runtime execution order of a pipeline is as follows: initialize `variables`, then `traverse`, then `apply`, then `output`. The execution order is the same within `PipelineTraversal`s (minus `output` which is not part of traversals). Nested traversals are always executed before the `apply` step.
__Pipeline:__
````
type Pipeline {
    object_promise: reference(ObjectPromise),
    variables: [PipelineVariable],
    traverse?: [PipelineTraversal],
    apply?: [PipelineApplication],
    output: [PipelineOutput]
}
````
__PipelineVariable__:
- Declaration of a variable to be used within a pipeline. This specification indicates the `pipeline_variable` value type wherever a `PipelineVariable.name` can be referenced. `reference_path(pipeline_variable)` indicates that the value can be a path beginning with a `PipelineVariable.name`, provided that the `PipelineVariable.type` is `"OBJECT"` (or in some special cases, `"OBJECT_LIST"`).
- An `initial` value must be provided for a `PipelineVariable`, and it must match the specified `type`. List types cannot be initialized to `null`, but an empty array (`[]`) is valid.
````
type PipelineVariable {
    name: string,
    type: FieldType | "OBJECT" | "OBJECT_LIST",
    initial: scalar? | [scalar]
}
````
__PipelineTraversal__:
- A `PipelineTraversal` loops over the value of the `ref` and executes the specified pipeline operations `foreach` item in the referenced list (`ref` must evaluate to a list type).
- A traversal loop variable is declared by `PipelineTraversal.foreach.as`. This variable can be referenced within the traversal and any nested traversals.
- `PipelineApplications` within `PipelineTraversal`s can apply `to` `pipeline_variable`s that were defined in parent scopes.
````
type PipelineTraversal {
    ref: reference_path(ObjectPromise | pipeline_variable | thread_variable),
    foreach: {
        as: string,
        variables: [PipelineVariable],
        traverse: [Pipelinetraversal],
        apply: [PipelineApplication]
    }
}
````
__PipelineApplication__:
- The `from` value can be aggregated using one of `aggregate`, `filter`, `sort`, or `select`, and the resulting value is applied `to` the referenced `pipeline_variable`. The `from` value must evaluate to a list type if `aggregate`, `filter`, or `sort` are specified. Note that a `PipelineApplication` could omit the aforementioned 4 properties altogether and simply apply `from` a reference `to` a variable.
- It must be valid to use the `method` to apply the aggregated value to the `to` type.
- `PipelineTraversal` loop variables (defined by `PipelineTraversal.foreach.as`) cannot be referenced by `PipelineApplication.to`.
````
type PipelineApplication {
    from: reference_path(ObjectPromise | pipeline_variable | thread_variable),
    
    // Begin mutually exclusive properties
    aggregate?: {
        field: string,
        operator: AggregationOperator
    },
    filter?: {
        where: [FilterComparison | NestedFilter],
        gate_type?*: GateType
    },
    sort?: [
        {
            field: string,
            order: "ASC" | "DESC"
        }
    ],
    select?: string,
    // End mutually exclusive properties

    method: ApplicationMethod,
    to: pipeline_variable
}
````
__FilterComparison__:
- Since a `PipelineApplication.filter` is applied to each item in a list, `filter_variable` refers to the individual item being compared. The `filter_variable` source is `PipelineApplication.from`.
- Either `left`, `right`, or both must be `filter_variable` references.
````
type FilterComparison {
    left: reference_path(filter_variable | ObjectPromise | pipeline_variable | thread_variable) | scalar,
    operator: ComparisonOperator,
    right: reference_path(filter_variable | ObjectPromise | pipeline_variable | thread_variable) | scalar
}
````
__NestedFilter__:
- Facilitates complex logic gate combinations within `PipelineApplication.filter`s.
````
type NestedFilter {
    where: [FilterComparison | NestedFilter],
    gate_type?*: GateType
}
````
__PipelineOutput__:
- Output values must come `from` a `pipeline_variable` defined by the same `Pipeline`.
- Pipelines output values `to` attributes on the referenced `Pipeline.object_promise`.
````
type PipelineOutput {
    from: pipeline_variable,
    to: string
}
````

### Enumeration Types

__FieldType enumeration:__
````
enum FieldType {
    "STRING",
    "NUMERIC",
    "BOOLEAN",
    "STRING_LIST",
    "NUMERIC_LIST",
    "BOOLEAN_LIST
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
    "CONTAINS_NONE_OF"
    "IS_SUBSET_OF",
    "IS_SUPERSET_OF"
}
````

__ApplicationMethod enumeration:__
````
enum ApplicationMethod {
    "ADD",
    "SUBTRACT",
    "MULTIPLY",
    "DIVIDE",
    "APPEND",
    "PREPEND",
    "CONCAT",
    "SELECT",
    "SET"
}
````

__AggregationOperator enumeration:__
````
enum AggregationOperator {
    "AVERAGE",
    "COUNT",
    "MAX",
    "MIN",
    "SUM",
    "FIRST",
    "LAST",
    "AND",
    "OR"
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
