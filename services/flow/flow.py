from flow_py_sdk import flow_client, ProposalKey, Tx, cadence
from services.flow.config import Config
from services.flow import cadence_utils, transactions


ctx = Config("flow.json")


async def propose_schema(json_file_path):
    async with flow_client(
        host=ctx.access_node_host, port=ctx.access_node_port
    ) as client:
        latest_block = await client.get_latest_block()
        emulator_account = await client.get_account_at_latest_block(
            address=ctx.service_account_address.bytes
        )

        tx = (
            Tx(
                code=transactions.propose_schema,
                reference_block_id=latest_block.id,
                payer=ctx.service_account_address,
                proposal_key=ProposalKey(
                    key_address=ctx.service_account_address,
                    key_id=0,
                    key_sequence_number=emulator_account.keys[0].sequence_number,
                ),
            )
            .add_arguments(*cadence_utils.schema_to_cadence(json_file_path))
            .add_authorizers(ctx.service_account_address)
            .with_envelope_signature(
                ctx.service_account_address,
                0,
                ctx.service_account_signer,
            )
        )

        tx.gas_limit = 500

        await client.send_transaction(transaction=tx.to_signed_grpc())


async def whitelist_schema_proposal(proposal_id):
    async with flow_client(
        host=ctx.access_node_host, port=ctx.access_node_port
    ) as client:
        latest_block = await client.get_latest_block()
        emulator_account = await client.get_account_at_latest_block(
            address=ctx.service_account_address.bytes
        )

        tx = (
            Tx(
                code=transactions.whitelist_schema_proposal,
                reference_block_id=latest_block.id,
                payer=ctx.service_account_address,
                proposal_key=ProposalKey(
                    key_address=ctx.service_account_address,
                    key_id=0,
                    key_sequence_number=emulator_account.keys[0].sequence_number,
                ),
            )
            .add_arguments(cadence.Address(ctx.service_account_address.bytes))
            .add_arguments(cadence.String("Natureblocks"))
            .add_arguments(cadence.UInt64(proposal_id))
            .add_authorizers(ctx.service_account_address)
            .with_envelope_signature(
                ctx.service_account_address,
                0,
                ctx.service_account_signer,
            )
        )

        tx.gas_limit = 500

        await client.send_transaction(transaction=tx.to_signed_grpc())
