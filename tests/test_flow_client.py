import logging
import pytest
from flow_py_sdk import flow_client, Script, cadence
from services.flow import flow, scripts, cadence_utils
from services.flow.config import Config
from validation import utils

logger = logging.getLogger("flow_client")

ctx = Config("flow.json")


class TestFlowClient:
    @pytest.mark.asyncio
    async def test_schema_proposal(self):
        async with flow_client(
            host=ctx.access_node_host, port=ctx.access_node_port
        ) as client:
            json_file_path = "schemas/test/small_example_schema.json"
            await flow.propose_schema(json_file_path)

            # Check that the schema proposal was submitted
            script_result = cadence_utils.from_cadence_recursive(
                await client.execute_script(
                    script=Script(code=scripts.get_schema_proposals)
                )
            )

            contract_identifier = cadence_utils.emulator_address + "Natureblocks"
            assert contract_identifier in script_result["schemaProposals"]
            proposal_ids = script_result["schemaProposals"][contract_identifier]
            assert len(proposal_ids) >= 1

            proposal_id = int(proposal_ids[-1])

            # Retrieve the schema proposal
            proposed_schema = await scripts.get_schema_proposal(proposal_id)

            # Compare the retrieved schema with the submitted schema
            assert utils.objects_are_identical(
                utils.parse_schema(json_file_path), proposed_schema["schema"]["tags"]
            )

            await flow.whitelist_schema_proposal(proposal_id)

            # Whitelisted proposal should have been cleared
            assert await scripts.get_schema_proposal(proposal_id) is None
