from services.flow import cadence_utils

get_schema_proposals = f"""import Graph from {cadence_utils.emulator_address}
pub fun main(): Graph.SchemaProposalsStruct {{
    return Graph.getSchemaProposals()
}}"""

get_schema_proposal = f"""
import Graph from {cadence_utils.emulator_address}
import Natureblocks from {cadence_utils.emulator_address}

pub fun main(proposalID: UInt64): Graph.SchemaProposal? {{
    return Natureblocks.getSchemaProposal(proposalID)
}}"""

get_next_available_schema_id = f"""
import Graph from {cadence_utils.emulator_address}

pub fun main(): UInt64 {{
    return Graph.schemaCount
}}"""

get_registered_schema = f"""
import Graph from {cadence_utils.emulator_address}

pub fun main(
    schemaID: UInt64
): Graph.GraphSchemaStruct? {{
    return Graph.getSchema(schemaID)
}}
"""