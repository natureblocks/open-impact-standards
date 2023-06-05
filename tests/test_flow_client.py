import logging
import pytest
from flow_py_sdk import flow_client, cadence
from services.flow import flow, transactions, scripts, cadence_utils
from services.flow.template_converter import GraphNode, TemplateConverter
from services.flow.config import Config
from validation import utils
from validation.schema_validator import SchemaValidator

logger = logging.getLogger("flow_client")

ctx = Config("flow.json")


class TestFlowClient:
    @pytest.mark.asyncio
    async def test_state_map_schema(self):
        async with flow_client(
            host=ctx.access_node_host, port=ctx.access_node_port
        ) as client:
            state_map_schema_file_path = "schemas/state_map_schema.json"

            validator = SchemaValidator()
            assert not validator.validate(json_file_path=state_map_schema_file_path)

            state_map_schema_id = await flow.register_schema(
                client, state_map_schema_file_path
            )

            registered_versions = await flow.execute_script(
                client=client,
                code=scripts.get_state_map_schema_versions,
            )
            next_version = str(
                max([int(v) for v in registered_versions.values()]) + 1
                if registered_versions
                else 0
            )
            await flow.add_state_map_schema_version(
                client, state_map_schema_id, next_version
            )

            # Register a schema for the node_definitions
            template_file_path = "schemas/test/small_example_schema.json"
            node_definitions_schema_id = await flow.register_schema(
                client, template_file_path
            )

            template_id = await flow.execute_script(
                client=client,
                code=scripts.get_next_available_template_id,
            )

            expected_nodes = await flow.create_state_map_template(
                client,
                node_definitions_schema_id,
                template_file_path,
                state_map_schema_file_path,
            )

            actual_nodes = [
                GraphNode().from_node_dict(
                    cadence_utils.from_cadence_recursive(cadence_node)
                )
                for cadence_node in await flow.execute_script(
                    client=client,
                    code=scripts.get_template_nodes,
                    arguments=[cadence.UInt64(template_id)],
                )
            ]

            # Set the on_chain_id for the expected nodes
            edge_map = {}
            for node in actual_nodes:
                expected_nodes[node.off_chain_id].on_chain_id = node.on_chain_id
                edge_map[node.off_chain_id] = node.on_chain_id

            # Set on chain ids for edges and edge collections
            for node in expected_nodes.values():
                for k, v in node.edge_off_chain_ids.items():
                    node.edges[k] = edge_map[str(v)]

                for k, v in node.edge_collection_off_chain_ids.items():
                    node.edgeCollections[k] = [edge_map[str(i)] for i in v]

            differences = cadence_utils.compare_graph_nodes(
                sorted(expected_nodes.values(), key=lambda n: n.on_chain_id),
                sorted(actual_nodes, key=lambda n: n.on_chain_id),
                keys_to_skip=["edge_off_chain_ids", "edge_collection_off_chain_ids"],
            )
            assert not differences

    @pytest.mark.asyncio
    async def test_schema_proposal(self):
        async with flow_client(
            host=ctx.access_node_host, port=ctx.access_node_port
        ) as client:
            json_file_path = "schemas/test/small_example_schema.json"

            await flow.execute_transaction(
                client=client, code=transactions.clear_schema_proposals
            )

            contract_identifier = cadence_utils.emulator_address + "Natureblocks"
            script_result = await flow.execute_script(
                client=client,
                code=scripts.get_schema_proposals,
            )
            assert contract_identifier not in script_result["schemaProposals"]

            await flow.execute_transaction(
                client=client,
                code=transactions.propose_schema,
                arguments=TemplateConverter().schema_to_cadence(json_file_path),
            )

            # Check that the schema proposal was submitted
            script_result = await flow.execute_script(
                client=client,
                code=scripts.get_schema_proposals,
            )

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
