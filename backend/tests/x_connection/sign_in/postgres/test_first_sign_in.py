import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from pumpkit.x_connection.x_publisher import X_SIGN_IN_SCOPES
from tests.billing.postgres.test_coupon_contention import blocked_requests
from tests.x_connection.sign_in.test_complete import begin, complete, profile
from tests.x_connection.test_x_identity_migration import (
    test_stable_x_identity_and_shared_contact_email_can_be_migrated_and_reversed as test_stable_x_identity_and_shared_contact_email_can_be_migrated_and_reversed,
)

pytestmark = pytest.mark.postgres


async def test_parallel_first_sign_ins_open_one_stable_x_account(
    sign_in_app, fake_x_publisher, db_engine
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    async with (
        AsyncClient(transport=ASGITransport(app=sign_in_app), base_url="http://test") as first,
        AsyncClient(transport=ASGITransport(app=sign_in_app), base_url="http://test") as second,
    ):
        first_state = await begin(first)
        second_state = await begin(second)
        async with db_engine.connect() as control:
            await control.execute(text("LOCK TABLE users IN SHARE MODE"))
            tasks = [
                asyncio.create_task(complete(browser, state))
                for browser, state in [(first, first_state), (second, second_state)]
            ]
            responses = await blocked_requests(db_engine, control, tasks, 2)
        accounts = await asyncio.gather(profile(first, responses[0]), profile(second, responses[1]))
        assert accounts[0]["id"] == accounts[1]["id"]
        assert accounts[0]["email"] == "ada@example.com"
