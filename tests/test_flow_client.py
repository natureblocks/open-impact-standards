import logging
import pytest
from flow_py_sdk import flow_client, cadence
from services.flow import flow, transactions, scripts, cadence_utils
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

            await flow.execute_transaction(
                client=client,
                code=transactions.whitelist_schema_proposal,
                arguments=cadence_utils.schema_to_cadence(json_file_path),
            )

            # Check that the schema proposal was submitted
            script_result = await flow.execute_script(
                client=client,
                code=scripts.get_schema_proposals,
            )

            contract_identifier = cadence_utils.emulator_address + "Natureblocks"
            assert contract_identifier in script_result["schemaProposals"]
            proposal_ids = script_result["schemaProposals"][contract_identifier]
            assert len(proposal_ids) >= 1

            proposal_id = int(proposal_ids[-1])

            # Retrieve the schema proposal
            proposed_schema = await flow.execute_script(
                client=client,
                code=scripts.get_schema_proposal,
                arguments=[cadence.UInt64(proposal_id)],
            )

            # Compare the retrieved schema with the submitted schema
            assert utils.objects_are_identical(
                utils.parse_schema(json_file_path), proposed_schema["schema"]["tags"]
            )

            # Whitelist the schema proposal
            await flow.execute_transaction(
                client=client,
                code=transactions.whitelist_schema_proposal,
                arguments=[
                    cadence.Address(ctx.service_account_address.bytes),
                    cadence.String("Natureblocks"),
                    cadence.UInt64(proposal_id),
                ],
            )

            # Whitelisted proposal should have been cleared
            proposal = await flow.execute_script(
                client=client,
                code=scripts.get_schema_proposal,
                arguments=[cadence.UInt64(proposal_id)],
            )
            assert proposal is None

            # Grab the next available schema id
            schema_id = await flow.execute_script(
                client=client, code=scripts.get_next_available_schema_id
            )
            assert schema_id is not None

            # Claim the subgraph distributor
            await flow.execute_transaction(
                client=client,
                code=transactions.claim_subgraph_distributor,
                arguments=[cadence.UInt64(proposal_id)],
            )

            # The schema should now be registered on the Graph contract
            registered_schema = await flow.execute_script(
                client=client,
                code=scripts.get_registered_schema,
                arguments=[cadence.UInt64(schema_id)],
            )

            # Compare the registered schema with the schema that was initially submitted
            assert utils.objects_are_identical(
                utils.parse_schema(json_file_path), registered_schema["tags"]
            )
