from services.flow.cadence_utils import emulator_address

get_schema_proposals = f'''import Graph from {emulator_address}
pub fun main(): Graph.SchemaProposalsStruct {{
    return Graph.getSchemaProposals()
}}'''

get_schema_proposal = f'''
import Graph from {emulator_address}
import Natureblocks from {emulator_address}

pub fun main(proposalID: UInt64): Graph.SchemaProposal? {{
    return Natureblocks.getSchemaProposal(proposalID)
}}'''