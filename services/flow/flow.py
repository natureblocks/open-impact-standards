from flow_py_sdk import ProposalKey, Tx, Script, cadence
from services.flow.config import Config
from services.flow import flow, cadence_utils, scripts, transactions
from validation import utils


ctx = Config("flow.json")


async def register_schema(client, json_file_path):
    await flow.execute_transaction(
        client=client,
        code=transactions.propose_schema,
        arguments=cadence_utils.schema_to_cadence(json_file_path),
    )

    schema_proposals = await flow.execute_script(
        client=client,
        code=scripts.get_schema_proposals,
    )
    proposal_id = int(
        schema_proposals["schemaProposals"][
            cadence_utils.emulator_address + "Natureblocks"
        ][-1]
    )

    # Retrieve the schema proposal
    proposed_schema = await flow.execute_script(
        client=client,
        code=scripts.get_schema_proposal,
        arguments=[cadence.UInt64(proposal_id)],
    )

    # Compare the retrieved schema with the submitted schema
    if not utils.objects_are_identical(
        utils.parse_schema(json_file_path), proposed_schema["schema"]["tags"]
    ):
        raise Exception("Proposed schema does not match submitted schema")

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

    # Grab the next available schema id
    schema_id = await flow.execute_script(
        client=client, code=scripts.get_next_available_schema_id
    )
    if schema_id is None:
        raise Exception("Failed to retrieve next available schema id")

    # Claim the subgraph distributor
    await flow.execute_transaction(
        client=client,
        code=transactions.claim_subgraph_distributor,
        arguments=[cadence.UInt64(proposal_id)],
    )

    return schema_id


async def issue_subgraph(client, schema_id):
    await flow.execute_transaction(
        client=client,
        code=transactions.add_subgraph_ledger,
        arguments=[cadence.UInt64(schema_id)],
    )

    await flow.execute_transaction(
        client=client, code=transactions.set_up_subgraph_collection
    )

    subgraph_count = len(
        await flow.execute_script(
            client=client,
            code=scripts.get_valid_subgraph_ids,
            arguments=[cadence.UInt64(schema_id)],
        )
    )

    await flow.execute_transaction(
        client=client,
        code=transactions.issue_subgraph,
        arguments=[
            cadence.Address(ctx.service_account_address.bytes),
            cadence.UInt64(schema_id),
        ],
    )

    subgraph_ids = await flow.execute_script(
        client=client,
        code=scripts.get_valid_subgraph_ids,
        arguments=[cadence.UInt64(schema_id)],
    )

    if len(subgraph_ids) != subgraph_count + 1:
        raise Exception("Subgraph was not issued")

    subgraph_id = max(subgraph_ids)

    return subgraph_id


async def execute_transaction(client, code, arguments=[]):
    latest_block = await client.get_latest_block()
    emulator_account = await client.get_account_at_latest_block(
        address=ctx.service_account_address.bytes
    )

    tx = (
        Tx(
            code=code,
            reference_block_id=latest_block.id,
            payer=ctx.service_account_address,
            proposal_key=ProposalKey(
                key_address=ctx.service_account_address,
                key_id=0,
                key_sequence_number=emulator_account.keys[0].sequence_number,
            ),
        )
        .add_arguments(*arguments)
        .add_authorizers(ctx.service_account_address)
        .with_envelope_signature(
            ctx.service_account_address,
            0,
            ctx.service_account_signer,
        )
    )

    tx.gas_limit = 9999

    await client.send_transaction(transaction=tx.to_signed_grpc())


async def execute_script(client, code, arguments=None):
    return cadence_utils.from_cadence_recursive(
        await client.execute_script(
            script=Script(
                code=code,
                arguments=arguments,
            )
        )
    )
