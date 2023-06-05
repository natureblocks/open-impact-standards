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

clear_schema_proposals = f'''
import Natureblocks from {emulator_address}
import Graph from {emulator_address}

transaction {{
    let adminRef: &Natureblocks.Administrator
    let contractID: String

    prepare(signer: AuthAccount) {{
        self.adminRef = signer.borrow<&Natureblocks.Administrator>(from: /storage/natureblocksAdministrator)
            ?? panic("Could not borrow reference to admin resource")

        self.contractID = "{emulator_address}Natureblocks"
    }}

    execute {{
        for proposalID in Graph.getSchemaProposalIDs(self.contractID) {{
            self.adminRef.retractSchemaProposal(proposalID)
        }}
    }}

    post {{
        Graph.getSchemaProposalIDs(self.contractID).length == 0:
            "Failed to clear schema proposals"
    }}
}}
'''

add_subgraph_ledger = f'''
import Natureblocks from {emulator_address}
import Graph from {emulator_address}

transaction(schemaID: UInt64) {{
    let subgraphDistributor: &Graph.SubgraphDistributor

    prepare(signer: AuthAccount) {{
        let storagePath: StoragePath = StoragePath(identifier: "subgraphDistributor".concat(schemaID.toString()))!
        self.subgraphDistributor = signer.borrow<&Graph.SubgraphDistributor>(
            from: storagePath
        )
            ?? panic("Could not borrow a reference to the owner's SubgraphDistributor")
    }}

    pre {{
        self.subgraphDistributor.schemaID == schemaID
    }}

    execute {{
        Natureblocks.addSubgraphLedger(subgraphDistributor: self.subgraphDistributor)
    }}

    post {{
        Natureblocks.getSubgraphLedgerRef(self.subgraphDistributor).schemaID == schemaID:
            "Failed to add SubgraphLedger"
    }}
}}
'''

set_up_subgraph_collection = f'''
import Graph from {emulator_address}
import Natureblocks from {emulator_address}

transaction {{
    prepare(signer: AuthAccount) {{
        if signer.borrow<&Graph.SubgraphCollection>(from: Natureblocks.SubgraphCollectionStoragePath) != nil {{
            return
        }}

        signer.save(<- Graph.createSubgraphCollection(), to: Natureblocks.SubgraphCollectionStoragePath)
        signer.link<&{{Graph.SubgraphCollectionPublic}}>(
            Natureblocks.SubgraphCollectionPublicPath,
            target: Natureblocks.SubgraphCollectionStoragePath
        )
    }}
}}
'''

issue_subgraph = f'''
import Graph from {emulator_address}
import Natureblocks from {emulator_address}

transaction(
    recipient: Address,
    schemaID: UInt64
) {{
    var subgraphDistributorRef: &{{Graph.SubgraphDistributorPrivate}}?
    let depositRef: &{{Graph.SubgraphCollectionPublic}}
    let nextSubgraphID: UInt64

    prepare(signer: AuthAccount) {{
        self.subgraphDistributorRef = signer.borrow<&{{Graph.SubgraphDistributorPrivate}}>(
            from: StoragePath(identifier: "subgraphDistributor".concat(schemaID.toString()))!
        )

        if self.subgraphDistributorRef == nil {{
            let subgraphDistributorPrivateCap = signer.borrow<&Capability<&{{Graph.SubgraphDistributorPrivate}}>>(
                from: StoragePath(identifier: "subgraphDistributorPrivateCap".concat(schemaID.toString()))!
            )

            if subgraphDistributorPrivateCap?.check() ?? false {{
                self.subgraphDistributorRef = subgraphDistributorPrivateCap!.borrow()
                    ?? panic("Could not borrow reference to SubgraphDistributorPrivate")
            }} else {{
                let subgraphDistributorCap = signer.borrow<&Capability<&Graph.SubgraphDistributor>>(
                    from: StoragePath(identifier: "subgraphDistributorCap".concat(schemaID.toString()))!
                )

                self.subgraphDistributorRef = subgraphDistributorCap?.borrow()
                    ?? panic("Could not borrow reference to SubgraphDistributor")
            }}
        }}

        assert(self.subgraphDistributorRef != nil,
            message: "Could not borrow reference to SubgraphDistributor")

        let collectionCap = getAccount(recipient)
            .getCapability<&{{Graph.SubgraphCollectionPublic}}>(Natureblocks.SubgraphCollectionPublicPath)

        assert(collectionCap.check(),
            message: "Recipient does not have a public SubgraphCollection capability")

        self.depositRef = collectionCap.borrow()
            ?? panic("Could not borrow a reference to the recipient's SubgraphCollectionPublic")

        self.nextSubgraphID = Graph.subgraphCount
    }}

    execute {{
        let subgraph <- self.subgraphDistributorRef!.issueSubgraph(
            ledger: Natureblocks.getSubgraphLedgerRef(self.subgraphDistributorRef!)
        )

        self.depositRef.deposit(<-subgraph)
    }}

    post {{
        Natureblocks.getValidSubgraphIDs(schemaID: schemaID).contains(self.nextSubgraphID):
            "Failed to add Subgraph to SubgraphLedger"

        self.depositRef.getIDs().contains(self.nextSubgraphID):
            "Failed to deposit Subgraph into recipient's collection"
    }}
}}
'''

add_state_map_schema_version = f'''
import Graph from {emulator_address}
import Natureblocks from {emulator_address}

transaction(
    schemaID: UInt64,
    version: String
) {{
    let adminRef: &Natureblocks.Administrator

    prepare(signer: AuthAccount) {{
        self.adminRef = signer.borrow<&Natureblocks.Administrator>(from: /storage/natureblocksAdministrator)
            ?? panic("Could not borrow reference to admin resource")
    }}

    execute {{
        self.adminRef.addStateMapSchemaVersion(schemaID, version)
    }}

    post {{
        Natureblocks.getStateMapSchemaVersion(schemaID: schemaID) == version:
            "Failed to add state map schema version"
    }}
}}
'''

create_state_map_template = f'''
import Graph from {emulator_address}
import Natureblocks from {emulator_address}

transaction(
    nodeDefinitionsSchemaID: UInt64,
    tags: [String],
    offChainIDs: [String],
    booleanFields: [{{String: Bool}}],
    numericFields: [{{String: Fix64?}}],
    stringFields: [{{String: String?}}],
    numericListFields: [{{String: [Fix64?]?}}],
    stringListFields: [{{String: [String?]?}}],
    edgeOffChainIDs: [{{String: String}}],
    edgeCollectionOffChainIDs: [{{String: [String]}}],
    offChainDependenciesInverse: {{String: [String]}}
) {{
    let stateMapSchemaID: UInt64
    let subgraphDistributorRef: &{{Graph.SubgraphDistributorPrivate}}
    let nextSubgraphID: UInt64
    let adminRef: &Natureblocks.Administrator

    prepare(signer: AuthAccount) {{
        let stateMapSchemaversions = Natureblocks.getStateMapSchemaVersions()
        var latestStateMapSchemaID: UInt64? = nil
        for schemaID in stateMapSchemaversions.keys {{
            if latestStateMapSchemaID == nil || schemaID > latestStateMapSchemaID! {{
                latestStateMapSchemaID = schemaID
            }}
        }}
        assert(latestStateMapSchemaID != nil, message: "Could not get latest state map schema version: no state map schemas exist")
        self.stateMapSchemaID = latestStateMapSchemaID!

        self.subgraphDistributorRef = signer.borrow<&{{Graph.SubgraphDistributorPrivate}}>(
            from: StoragePath(identifier: "subgraphDistributor".concat(self.stateMapSchemaID.toString()))!
        ) ?? panic("Could not borrow reference to SubgraphDistributor")

        self.nextSubgraphID = Graph.subgraphCount

        self.adminRef = signer.borrow<&Natureblocks.Administrator>(from: /storage/natureblocksAdministrator)
            ?? panic("Could not borrow reference to Administrator resource")
    }}

    pre {{
        Graph.schemaIsValid(nodeDefinitionsSchemaID):
            "Invalid nodeDefinitionsSchemaID"

        tags.length == offChainIDs.length:
            "tags and offChainIDs must be the same length"

        offChainIDs.length == booleanFields.length:
            "offChainIDs and booleanFields must be the same length"

        booleanFields.length == numericFields.length:
            "booleanFields and numericFields must be the same length"

        numericFields.length == stringFields.length:
            "numericFields and stringFields must be the same length"

        stringFields.length == numericListFields.length:
            "stringFields and numericListFields must be the same length"

        numericListFields.length == stringListFields.length:
            "numericListFields and stringListFields must be the same length"

        stringListFields.length == edgeOffChainIDs.length:
            "stringListFields and edgeOffChainIDs must be the same length"

        edgeOffChainIDs.length == edgeCollectionOffChainIDs.length:
            "edgeOffChainIDs and edgeCollectionOffChainIDs must be the same length"
    }}

    execute {{
        let subgraph <- self.subgraphDistributorRef!.issueSubgraph(
            ledger: Natureblocks.getSubgraphLedgerRef(self.subgraphDistributorRef!)
        )

        let creations: [Graph.OffChainNodeStruct] = []
        var idx = 0;
        while idx < tags.length {{
            creations.append(Graph.OffChainNodeStruct(
                offChainID: offChainIDs[idx]!,
                offChainEdges: edgeOffChainIDs[idx]!,
                offChainEdgeCollections: edgeCollectionOffChainIDs[idx]!,
                tag: tags[idx]!,
                data: Graph.NodeDataStruct(
                    booleanFields: booleanFields[idx]!,
                    numericFields: numericFields[idx]!,
                    stringFields: stringFields[idx]!,
                    numericListFields: numericListFields[idx]!,
                    stringListFields: stringListFields[idx]!,
                    edges: {{}},
                    edgeCollections: {{}}
                )
            ))

            idx = idx + 1
        }}

        self.adminRef.createStateMapTemplate(
            subgraph: <- subgraph,
            creations: creations,
            nodeDefinitionsSchemaID: nodeDefinitionsSchemaID,
            offChainDependenciesInverse: offChainDependenciesInverse
        )
    }}

    post {{
        Natureblocks.getValidSubgraphIDs(schemaID: self.stateMapSchemaID).contains(self.nextSubgraphID):
            "Failed to add Subgraph to SubgraphLedger"
    }}
}}
'''