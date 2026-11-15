"""Opening a paid signup through the API, for tests in several areas."""

from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation

SIGNUPS = "/api/v1/billing/paid-signups"


async def redeem_coupon(client, coupons):
    created = await coupons("--months", "1")
    free = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(free))).status_code == 200
    return free


async def accept_paid_signup(client, plan_key="pumpkit_pro_monthly"):
    preview = await client.post(SIGNUPS + "/preview", json={"plan_key": plan_key})
    assert preview.status_code == 200, preview.text
    paid = preview.json()
    request = {
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "revision": paid["revision"],
        "terms_version": paid["terms_version"],
        "accepted_terms": True,
        "requested_immediate_start": True,
        "approved_specific_clauses": True,
        "language": "en",
    }
    result = await client.post(SIGNUPS, json=request)
    assert result.status_code == 200, result.text
    return request, result.json()


async def open_paid_signup(client, coupons, plan_key="pumpkit_pro_monthly"):
    free = await redeem_coupon(client, coupons)
    request, opened = await accept_paid_signup(client, plan_key)
    return free, request, opened
