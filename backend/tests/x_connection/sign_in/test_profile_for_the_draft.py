"""Sign-in keeps the X profile's bio, location and website, which the Positioning draft reads."""

from dataclasses import replace

from test_complete import begin, complete

from pumpkit.x_connection.x_publisher import X_SIGN_IN_SCOPES
from tests.positioning.positioning import DRAFT, DRAFTED


async def _draft_reads(browser, signed_in, fake_llm) -> str:
    """What the model is sent about the profile when the signed-in User asks for a draft."""
    assert signed_in.status_code == 200, signed_in.text
    fake_llm.calls.clear()
    fake_llm.replies = [{"positioning": DRAFTED}]
    drafted = await browser.post(
        DRAFT, headers={"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    )
    assert drafted.status_code == 200, drafted.text
    return fake_llm.calls[0].messages[1]["content"]


async def test_sign_in_keeps_the_bio_location_and_website_for_the_draft(
    sign_in_browser, new_browser, sells_no_plans, fake_x_publisher, fake_x_reader, fake_llm
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(
        fake_x_publisher.account,
        bio="Solo founder. Building a pricing tool in public.",
        location="Lisbon",
        website="https://ada.dev",
    )
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    fake_x_reader.posts["ada"] = []

    signed_in = await complete(sign_in_browser, await begin(sign_in_browser))

    assert await _draft_reads(new_browser(), signed_in, fake_llm) == (
        "<profile>\n"
        "Handle: @ada\n"
        "Bio: Solo founder. Building a pricing tool in public.\n"
        "Location: Lisbon\n"
        "Website: https://ada.dev\n"
        "</profile>"
    )


async def test_a_later_sign_in_replaces_what_the_profile_said(
    sign_in_browser, new_browser, sells_no_plans, fake_x_publisher, fake_x_reader, fake_llm
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(
        fake_x_publisher.account, bio="Solo founder.", location="Lisbon"
    )
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    fake_x_reader.posts["ada"] = []
    await complete(sign_in_browser, await begin(sign_in_browser))
    fake_x_publisher.account = replace(
        fake_x_publisher.account, bio="Founder of Tally.", location=None
    )

    signed_in = await complete(sign_in_browser, await begin(sign_in_browser))

    assert await _draft_reads(new_browser(), signed_in, fake_llm) == (
        "<profile>\nHandle: @ada\nBio: Founder of Tally.\n</profile>"
    )
