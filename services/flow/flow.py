from flow_py_sdk import ProposalKey, Tx, Script
from services.flow.config import Config
from services.flow import cadence_utils


ctx = Config("flow.json")


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
