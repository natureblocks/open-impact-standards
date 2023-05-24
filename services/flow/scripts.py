from flow_py_sdk import flow_client
from flow_py_sdk import flow_client, Script, cadence
from services.flow import cadence_utils
from services.flow.config import Config

get_schema_proposals = f"""import Graph from {cadence_utils.emulator_address}
pub fun main(): Graph.SchemaProposalsStruct {{
    return Graph.getSchemaProposals()
}}"""

ctx = Config("flow.json")


async def get_schema_proposal(proposal_id):
    async with flow_client(
        host=ctx.access_node_host, port=ctx.access_node_port
    ) as client:
        code = f"""
        import Graph from {cadence_utils.emulator_address}
        import Natureblocks from {cadence_utils.emulator_address}

        pub fun main(proposalID: UInt64): Graph.SchemaProposal? {{
            return Natureblocks.getSchemaProposal(proposalID)
        }}"""

        return cadence_utils.from_cadence_recursive(
            await client.execute_script(
                script=Script(
                    code=code,
                    arguments=[cadence.UInt64(proposal_id)],
                )
            )
        )
