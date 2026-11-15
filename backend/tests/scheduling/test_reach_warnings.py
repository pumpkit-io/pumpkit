"""
Reach warnings (ADR 0032) on a Post read through `GET /posts/{id}` and the `get_post` tool: what
in the Text, or in its Scheduled post's own text, may lead X to show it to fewer people.
"""

import time

import pytest

from pumpkit.x_connection.x_publisher import XPostRejectedError

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"


async def _warnings(client, post_id: str) -> list[dict]:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()["reach_warnings"]


async def test_a_share_ask_warns_with_its_part_and_message(client, subscribed, post_with):
    post_id = await post_with("Ship small things. Share this with a founder who ships big.")

    assert await _warnings(client, post_id) == [
        {
            "code": "share_ask",
            "part": 1,
            "message": "This post asks readers to share it, and X hides posts that ask for "
            "shares from people who don't follow you.",
        }
    ]


# Each Text as its Parts, and the warnings it gives as (code, Part).
FINDINGS = [
    pytest.param(["Send this to a founder who ships big."], [("share_ask", 1)], id="send-this-to"),
    pytest.param(["Opening.", "Know a PM? Forward it to them."], [("share_ask", 2)], id="forward"),
    pytest.param(["Share this if it helped."], [("share_ask", 1)], id="share-this"),
    pytest.param(["Tag a friend who needs this."], [("tag_ask", 1)], id="tag-a-friend"),
    pytest.param(["Tag someone who ships on Fridays."], [("tag_ask", 1)], id="tag-someone"),
    pytest.param(["Copy the link and save it."], [("copy_link_ask", 1)], id="copy-the-link"),
    pytest.param(["Like and repost if you agree."], [("engagement_ask", 1)], id="like-and-repost"),
    pytest.param(["Follow me for more."], [("engagement_ask", 1)], id="follow-for-more"),
    pytest.param(["Turn on notifications."], [("engagement_ask", 1)], id="notifications"),
    pytest.param(["Drop a 🔥 below."], [("engagement_ask", 1)], id="drop-an-emoji"),
    pytest.param(
        ["One.", "Two.", "Reply 'RAG' for the doc."], [("reply_keyword_ask", 3)], id="reply-keyword"
    ),
    pytest.param(
        ["Comment below and I'll send you the template."],
        [("reply_keyword_ask", 1)],
        id="comment-for-template",
    ),
    pytest.param(["Giveaway: three free seats."], [("giveaway", 1)], id="giveaway"),
    pytest.param(
        ["Everyone who replies gets the checklist."], [("giveaway", 1)], id="everyone-who-replies"
    ),
    pytest.param(["Built with @alice and @bob."], [("many_mentions", 1)], id="two-mentions"),
    pytest.param(["Ship it. #buildinpublic #saas"], [("many_hashtags", 1)], id="two-hashtags"),
    pytest.param(
        ["The guide.", "Read it: https://bit.ly/3abc"],
        [("shortened_link", 2)],
        id="shortener-in-the-first-reply",
    ),
    pytest.param(["Notes at tinyurl.com/notes"], [("shortened_link", 1)], id="bare-shortener"),
    pytest.param(
        ["Share this with your team. Tag a friend."],
        [("share_ask", 1), ("tag_ask", 1)],
        id="two-findings-in-one-part",
    ),
    pytest.param(
        ["Everyone who replies by Friday wins a seat."], [("giveaway", 1)], id="reward-after-a-gap"
    ),
    pytest.param(["Repost this."], [("engagement_ask", 1)], id="repost-this"),
    pytest.param(["Follow me."], [("engagement_ask", 1)], id="follow-me"),
    pytest.param(["Like this."], [("engagement_ask", 1)], id="like-this"),
    pytest.param(["Please share."], [("share_ask", 1)], id="please-share"),
    pytest.param(
        ["Share with a friend who needs it."], [("share_ask", 1)], id="share-with-a-friend"
    ),
    pytest.param(["If it helped, share it."], [("share_ask", 1)], id="share-it-after-a-clause"),
    pytest.param(["Done.\n\nTag your cofounder."], [("tag_ask", 1)], id="tag-on-a-new-line"),
]

# Texts that ask for nothing X labels, though they come close.
CLEAN = [
    pytest.param("I'll share this week's numbers on Friday.", id="share-this-week"),
    pytest.param("Last year I'd share it with my team and wait.", id="share-it-in-a-story"),
    pytest.param("I shared it with my cofounder first.", id="shared"),
    pytest.param("Shipped this with @alice last week.", id="one-mention"),
    pytest.param("Day 3 of #buildinpublic.", id="one-hashtag"),
    pytest.param("Same mention twice: @alice and @Alice.", id="one-handle-twice"),
    pytest.param("My #1 lesson and #2 lesson.", id="numbers-are-not-hashtags"),
    pytest.param("Mail me at me@example.com or @alice.", id="an-email-is-not-a-mention"),
    pytest.param("The full guide: https://example.com/guides/shipping-small#start", id="full-url"),
    pytest.param("What would you cut first?", id="a-specific-question"),
    pytest.param("DM me 'RAG' and I'll send you the doc.", id="dm-keyword"),
    pytest.param("I like this post format more than threads.", id="i-like-this-post"),
    pytest.param("The price tag a year ago was double.", id="price-tag"),
    pytest.param("A habit.ly/x is not a shortener.", id="not-a-shortener"),
    pytest.param("Excited to share this with you all: we shipped v2.", id="excited-to-share"),
    pytest.param("Can't wait to share it next week.", id="cant-wait-to-share"),
    pytest.param("Let me share this story.", id="let-me-share"),
    pytest.param("We’re excited to share it.", id="were-excited-to-share"),
    pytest.param("He'll share it tomorrow.", id="he-will-share"),
    pytest.param("Just send it. Ship and learn.", id="just-send-it"),
    pytest.param("Share this weekend with someone you love.", id="share-this-weekend"),
    pytest.param("That was a dead giveaway.", id="dead-giveaway"),
    pytest.param("I read every reply I get, even the mean ones.", id="every-reply-i-get"),
    pytest.param("Feeds full of accounts you like or follow.", id="you-like-or-follow"),
    pytest.param("It's like if you took Notion and made it fast.", id="like-if-you-took"),
    pytest.param("You'll like this post if you hate meetings.", id="youll-like-this"),
    pytest.param("Then, tag the release and push.", id="tag-the-release"),
    pytest.param("Now tag the commit with v1.2.", id="tag-the-commit"),
    pytest.param('Her comment "you\'ll never make it" stuck with me.', id="a-quoted-comment"),
    pytest.param(
        "Copy the link from your dashboard and paste it in the config.", id="copy-another-link"
    ),
]


@pytest.mark.parametrize(("parts", "found"), FINDINGS)
async def test_each_finding_warns_in_the_part_it_lands_in(
    client, subscribed, post_with, parts, found
):
    post_id = await post_with(*parts, first_reply=len(parts) == 2)

    warnings = await _warnings(client, post_id)

    assert [(w["code"], w["part"]) for w in warnings] == found


@pytest.mark.parametrize("text", CLEAN)
async def test_close_calls_stay_clean(client, subscribed, post_with, text):
    post_id = await post_with(text)

    assert await _warnings(client, post_id) == []


@pytest.mark.parametrize(
    "text",
    [
        "copy" + " " * 30_000 + "x",
        "\n" * 30_000,
        "Done," + " " * 30_000 + "x",
        "please" + " " * 30_000 + "x",
    ],
    ids=["after-copy", "newlines", "after-a-comma", "after-please"],
)
async def test_a_long_run_of_whitespace_reads_fast(client, subscribed, post_with, text):
    post_id = await post_with(text)

    started = time.monotonic()
    assert await _warnings(client, post_id) == []
    assert time.monotonic() - started < 1


async def test_a_message_names_the_part_and_a_shortener_says_what_to_link(
    client, subscribed, post_with
):
    post_id = await post_with("Opening.", "The guide: https://bit.ly/3abc", "Closing.")

    assert await _warnings(client, post_id) == [
        {
            "code": "shortened_link",
            "part": 2,
            "message": "Part 2 uses a link shortener, and X checks every hop a link redirects "
            "through. Link the final page instead.",
        }
    ]


async def test_the_warnings_follow_a_hand_edit_of_the_text(client, subscribed, post_with):
    post_id = await post_with("Ship small things.")

    saved = await client.put(
        f"{POSTS}/{post_id}/text", json={"parts": ["Ship small things. Tag a friend who doesn't."]}
    )
    assert saved.status_code == 200, saved.text

    assert [w["code"] for w in await _warnings(client, post_id)] == ["tag_ask"]


async def test_a_scheduled_post_warns_from_its_own_text(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    post_id = await post_with("Ship small things.")
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 201, scheduled.text

    edited = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}",
        json={"parts": ["Ship small things. #shipping #small"]},
    )
    assert edited.status_code == 200, edited.text

    assert [w["code"] for w in await _warnings(client, post_id)] == ["many_hashtags"]


async def test_a_warning_stops_nothing(client, subscribed, connect_x, fixed_clock, post_with):
    await connect_x()
    post_id = await post_with("Like and repost if you agree.")

    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert scheduled.status_code == 201, scheduled.text


async def test_the_get_post_tool_gives_the_warnings(subscribed, mcp, post_with):
    post_id = await post_with("Built with @alice and @bob.")

    read = (await mcp.call_tool("get_post", post_id=post_id))["structuredContent"]

    assert [(w["code"], w["part"]) for w in read["reach_warnings"]] == [("many_mentions", 1)]


async def test_a_failed_post_warns_from_its_text_which_a_retry_copies(
    client, subscribed, connect_x, fixed_clock, fake_x_publisher, post_with
):
    await connect_x()
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    post_id = await post_with("Ship small things.")
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert failed.json()["state"] == "failed", failed.text

    saved = await client.put(
        f"{POSTS}/{post_id}/text", json={"parts": ["Ship small things. Follow me for more."]}
    )
    assert saved.status_code == 200, saved.text

    assert [w["code"] for w in await _warnings(client, post_id)] == ["engagement_ask"]
