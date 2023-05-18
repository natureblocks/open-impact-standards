from services.flow.cadence_utils import emulator_address

propose_schema = f'''
import Graph from {emulator_address}
import Natureblocks from {emulator_address}

transaction(
    nodeTags: [String],
    booleanFields: {{String: [String]}},
    numericFields: {{String: [String]}},
    stringFields: {{String: [String]}},
    numericListFields: {{String: [String]}},
    stringListFields: {{String: [String]}},
    edges: {{String: {{String: String}}}},
    edgeCollections: {{String: {{String: String}}}},
    deletable: {{String: Bool}},
    notifyEmailAddress: String?
) {{
    let adminRef: &Natureblocks.Administrator
    let tags: {{String: Graph.NodeSchemaStruct}}

    prepare(signer: AuthAccount) {{
        self.adminRef = signer.borrow<&Natureblocks.Administrator>(from: /storage/natureblocksAdministrator)
            ?? panic("Could not borrow reference to Administrator resource")

        self.tags = {{}}
        for tag in nodeTags {{
            self.tags[tag] = Graph.NodeSchemaStruct(
                booleanFields: booleanFields[tag] ?? [],
                numericFields: numericFields[tag] ?? [],
                stringFields: stringFields[tag] ?? [],
                numericListFields: numericListFields[tag] ?? [],
                stringListFields: stringListFields[tag] ?? [],
                edges: edges[tag] ?? {{}},
                edgeCollections: edgeCollections[tag] ?? {{}},
                isDeletable: deletable[tag] ?? true
            )
        }}
    }}

    execute {{
        self.adminRef.proposeSchema(
            schema: Graph.GraphSchemaStruct(self.tags),
            notifyEmailAddress: notifyEmailAddress
        )
    }}
}}
'''