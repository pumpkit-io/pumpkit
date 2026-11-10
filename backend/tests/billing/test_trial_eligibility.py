from dataclasses import replace
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event

from pumpkit.billing.gateway import SubscriptionState, get_billing_gateway
from pumpkit.billing.router import router as billing_router
from pumpkit.core.config import settings
from pumpkit.x_connection.x_publisher import X_SIGN_IN_SCOPES
from tests.billing.test_billing import CHECKOUT, CHECKOUT_MONTHLY, MONTHLY
from tests.billing.test_top_up_account_deletion import remove_user
from tests.x_connection.sign_in.conftest import sign_in_app as sign_in_app
from tests.x_connection.sign_in.test_complete import begin, complete, profile

KEYS = '{"active":"first","keys":{"first":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}}'


@pytest.fixture(autouse=True)
def trial_keys(monkeypatch):
    monkeypatch.setattr(settings, "TRIAL_IDENTITY_KEYS", SecretStr(KEYS))


BILLING_ME = "/api/v1/billing/me"


@pytest.fixture(autouse=True)
async def enforce_account_cascades(db_engine):
    if db_engine.dialect.name == "sqlite":

        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        event.listen(db_engine.sync_engine, "connect", foreign_keys)


@pytest.fixture
async def trial_app(sign_in_app, fake_billing):
    fake_billing.plans = [MONTHLY]
    sign_in_app.include_router(billing_router, prefix="/api/v1")
    sign_in_app.dependency_overrides[get_billing_gateway] = lambda: fake_billing
    return sign_in_app


@pytest.fixture
async def trial_browser(trial_app):
    async with AsyncClient(
        transport=ASGITransport(app=trial_app), base_url="http://test"
    ) as browser:
        yield browser


async def sign_in(browser, publisher, *, x_id="1001", email="ada@example.com", handle="ada"):
    publisher.exchange_scope = X_SIGN_IN_SCOPES
    publisher.account = replace(
        publisher.account, user_id=x_id, confirmed_email=email, handle=handle
    )
    signed_in = await complete(browser, await begin(browser))
    me = await profile(browser, signed_in)
    browser.headers["Authorization"] = "Bearer " + signed_in.json()["access_token"]
    return me


def ended_trial(clock):
    return SubscriptionState(
        id="sub_used_trial",
        status="canceled",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        created_at=clock() - timedelta(days=10),
        current_period_end=clock() - timedelta(days=3),
        trial_start=clock() - timedelta(days=10),
        trial_end=clock() - timedelta(days=3),
    )


async def test_trial_history_survives_changed_contact_and_account_recreation(
    trial_browser, fake_x_publisher, fake_billing, fixed_clock, db_session_maker, file_storage
):
    original = await sign_in(trial_browser, fake_x_publisher)
    assert (await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    checkout = fake_billing.checkouts[-1]
    assert checkout.trial_period_days == 7
    fake_billing.set_subscription(checkout.customer_id, ended_trial(fixed_clock))
    await fake_billing.expire_open_checkouts(customer_id=checkout.customer_id)
    changed = await sign_in(
        trial_browser, fake_x_publisher, email="changed@example.org", handle="renamed"
    )
    assert changed["id"] == original["id"]
    status, error = await remove_user(db_session_maker, fake_billing, file_storage, original["id"])
    assert status == 0, error

    recreated = await sign_in(trial_browser, fake_x_publisher, email="third@example.org")

    assert recreated["id"] != original["id"]
    offer = await trial_browser.get(BILLING_ME)
    assert offer.status_code == 200
    assert offer.json()["may_subscribe"] is True
    assert offer.json()["trial_days"] is None


async def used_trial_then_delete(browser, publisher, billing, clock, sessions, storage):
    original = await sign_in(browser, publisher)
    assert (await browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    customer = billing.checkouts[-1].customer_id
    billing.set_subscription(customer, ended_trial(clock))
    await billing.expire_open_checkouts(customer_id=customer)
    status, error = await remove_user(sessions, billing, storage, original["id"])
    assert status == 0, error
    return original


async def test_distinct_x_accounts_sharing_contact_email_keep_separate_trial_history(
    trial_browser, fake_x_publisher, fake_billing, fixed_clock, db_session_maker, file_storage
):
    await used_trial_then_delete(
        trial_browser, fake_x_publisher, fake_billing, fixed_clock, db_session_maker, file_storage
    )

    await sign_in(trial_browser, fake_x_publisher, x_id="2002")
    response = await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert fake_billing.checkouts[-1].trial_period_days == 7


@pytest.mark.parametrize("failed", [True, False])
async def test_failed_or_abandoned_checkout_does_not_use_trial_eligibility(
    trial_browser, fake_x_publisher, fake_billing, db_session_maker, file_storage, failed
):
    original = await sign_in(trial_browser, fake_x_publisher)
    if failed:
        fake_billing.fail_on.add("create_subscription_checkout")
    response = await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)
    assert response.status_code == (502 if failed else 200)
    fake_billing.fail_on.clear()
    if not failed:
        await fake_billing.expire_open_checkouts(customer_id=fake_billing.checkouts[-1].customer_id)
    status, error = await remove_user(db_session_maker, fake_billing, file_storage, original["id"])
    assert status == 0, error

    await sign_in(trial_browser, fake_x_publisher, email="other@example.com")
    offer = await trial_browser.get(BILLING_ME)

    assert offer.status_code == 200
    assert offer.json()["trial_days"] == 7


async def test_key_rotation_matches_retained_trial_without_restoring_eligibility(
    trial_browser,
    fake_x_publisher,
    fake_billing,
    fixed_clock,
    db_session_maker,
    file_storage,
    monkeypatch,
):
    await used_trial_then_delete(
        trial_browser, fake_x_publisher, fake_billing, fixed_clock, db_session_maker, file_storage
    )
    monkeypatch.setattr(
        settings,
        "TRIAL_IDENTITY_KEYS",
        SecretStr(
            '{"active":"second","keys":{"first":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",'
            '"second":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="}}'
        ),
    )

    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    offer = await trial_browser.get(BILLING_ME)

    assert offer.status_code == 200
    assert offer.json()["trial_days"] is None


async def test_missing_historical_key_cannot_restore_a_trial(
    trial_browser,
    fake_x_publisher,
    fake_billing,
    fixed_clock,
    db_session_maker,
    file_storage,
    monkeypatch,
):
    await used_trial_then_delete(
        trial_browser, fake_x_publisher, fake_billing, fixed_clock, db_session_maker, file_storage
    )
    monkeypatch.setattr(
        settings,
        "TRIAL_IDENTITY_KEYS",
        SecretStr(
            '{"active":"second","keys":{"second":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="}}'
        ),
    )

    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    offer = await trial_browser.get(BILLING_ME)
    checkout = await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert offer.status_code == 503
    assert checkout.status_code == 503
    assert len(fake_billing.checkouts) == 1


async def test_lost_historical_key_does_not_block_settled_deletion_or_restore_trial(
    trial_browser,
    fake_x_publisher,
    fake_billing,
    fixed_clock,
    db_session_maker,
    file_storage,
    monkeypatch,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    assert (await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    customer = fake_billing.checkouts[-1].customer_id
    fake_billing.set_subscription(customer, ended_trial(fixed_clock))
    await fake_billing.expire_open_checkouts(customer_id=customer)
    assert (await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    assert fake_billing.checkouts[-1].trial_period_days is None
    await fake_billing.expire_open_checkouts(customer_id=customer)
    monkeypatch.setattr(
        settings,
        "TRIAL_IDENTITY_KEYS",
        SecretStr(
            '{"active":"second","keys":{"second":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="}}'
        ),
    )

    status, error = await remove_user(db_session_maker, fake_billing, file_storage, original["id"])

    assert status == 0, error
    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    offer = await trial_browser.get(BILLING_ME)
    assert offer.status_code == 200
    assert offer.json()["trial_days"] is None
