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

whitelist_schema_proposal = f'''
import Graph from {emulator_address}

transaction(
    contractAddress: Address,
    contractName: String,
    proposalID: UInt64
) {{
    let adminRef: &Graph.Administrator

    prepare(signer: AuthAccount) {{
        self.adminRef = signer.borrow<&Graph.Administrator>(from: /storage/graphAdministrator)
            ?? panic("Could not borrow reference to Administrator resource")
    }}

    execute {{
        self.adminRef.whitelistSchemaProposal(
            contractID: contractAddress.toString().concat(contractName),
            proposalID: proposalID
        )
    }}
}}
'''

claim_subgraph_distributor = f'''
import Natureblocks from {emulator_address}
import Graph from {emulator_address}

transaction(proposalID: UInt64) {{
    prepare(signer: AuthAccount) {{
        let adminRef = signer.borrow<&Natureblocks.Administrator>(from: /storage/natureblocksAdministrator)
            ?? panic("Could not borrow reference to the admin")

        let subgraphDistributor <- adminRef.claimSubgraphDistributor(proposalID)
        let storagePath = StoragePath(identifier: "subgraphDistributor".concat(subgraphDistributor.schemaID.toString()))!

        signer.save(<- subgraphDistributor, to: storagePath)

        assert(signer.borrow<&Graph.SubgraphDistributor>(from: storagePath) != nil,
            message: "Failed to save SubgraphDistributor")
    }}
}}
'''