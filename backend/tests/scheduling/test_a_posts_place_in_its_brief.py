"""
Where a Post comes among its Brief's Posts, in `GET /posts/{id}`, `GET /posts` and `get_post`:
every Post of the Brief counts, written, being written or not written, in the order of its Ideas
(ADR 0025). Ideas never written are not Posts and don't count.
"""

import pytest

from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import LLMCall, LLMError
from pumpkit.main import app
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import HUMANIZED_POST, POST_IDEAS, ideas, planned_post

BRIEFS = "/api/v1/briefs"
POSTS = "/api/v1/posts"
CORE_IDEAS = [
    "Make sure the pain is real before you build.",
    "Charge at least 20 euros a month.",
    "Don't make OAuth integrations your core value.",
]
WHOLE = "Three lessons from a failed SaaS."
ALONE = {"position": 1, "post_count": 1, "previous_post_id": None, "next_post_id": None}


@pytest.fixture
async def ready(client, subscribed, writing_session_maker):
    await save_positioning(client)
    app.dependency_overrides[get_session_maker] = lambda: writing_session_maker


def _humanizer(fails: tuple[str, ...] = ()):
    def reply(call: LLMCall):
        text = "\n".join(str(message["content"]) for message in call.messages)
        for core_idea in [*CORE_IDEAS, WHOLE]:
            if core_idea in text:
                if core_idea in fails:
                    return LLMError("provider down")
                return {"post": f"Post on: {core_idea}", "first_reply": None}
        raise AssertionError("The humanizer was sent no known core idea")

    return reply


@pytest.fixture
def split(fake_llm):
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(WHOLE), [planned_post(core_idea) for core_idea in CORE_IDEAS]
    )
    fake_llm.standing[HUMANIZED_POST] = _humanizer()


async def _plan(client) -> dict:
    response = await client.post(BRIEFS, json={"brief": "Three things I learned from my SaaS."})
    assert response.status_code == 201, response.text
    return response.json()


async def _write(client, brief: dict, ideas: list[dict]) -> dict[str, str]:
    """Writes `ideas` and answers with their Posts' ids by core idea."""
    response = await client.post(
        f"{BRIEFS}/{brief['id']}/posts", json={"idea_ids": [idea["id"] for idea in ideas]}
    )
    assert response.status_code == 202, response.text
    return {
        idea["plan"]["core_idea"]: idea["post"]["id"]
        for idea in response.json()["ideas"]
        if idea["post"]
    }


def _split(brief: dict) -> list[dict]:
    return [idea for idea in brief["ideas"] if not idea["whole_brief"]]


def _whole(brief: dict) -> dict:
    [idea] = [idea for idea in brief["ideas"] if idea["whole_brief"]]
    return idea


async def _read(client, post_id: str) -> dict:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_post_from_a_brief_with_one_idea_is_alone_in_its_brief(client, ready, fake_llm):
    fake_llm.standing[HUMANIZED_POST] = {"post": "Ship small things.", "first_reply": None}
    planned = await _plan(client)

    post = await _read(client, _whole(planned)["post"]["id"])

    assert post["brief_id"] == planned["id"]
    assert post["place_in_brief"] == ALONE


async def test_posts_count_in_posting_order_and_ideas_not_written_do_not(client, ready, split):
    planned = await _plan(client)
    first, _, third = _split(planned)
    ids = await _write(client, planned, [first, third])
    one, two = ids[CORE_IDEAS[0]], ids[CORE_IDEAS[2]]

    assert (await _read(client, one))["place_in_brief"] == {
        "position": 1,
        "post_count": 2,
        "previous_post_id": None,
        "next_post_id": two,
    }
    second = await _read(client, two)
    assert second["brief_id"] == planned["id"]
    assert second["place_in_brief"] == {
        "position": 2,
        "post_count": 2,
        "previous_post_id": one,
        "next_post_id": None,
    }


async def test_a_post_not_written_counts_and_its_neighbours_lead_to_it(
    client, ready, fake_llm, split
):
    fake_llm.standing[HUMANIZED_POST] = _humanizer(fails=(CORE_IDEAS[1],))
    planned = await _plan(client)
    ids = await _write(client, planned, _split(planned))

    failed = await _read(client, ids[CORE_IDEAS[1]])

    assert failed["writing_state"] == "not_written"
    assert failed["place_in_brief"] == {
        "position": 2,
        "post_count": 3,
        "previous_post_id": ids[CORE_IDEAS[0]],
        "next_post_id": ids[CORE_IDEAS[2]],
    }
    first = await _read(client, ids[CORE_IDEAS[0]])
    assert first["place_in_brief"]["next_post_id"] == ids[CORE_IDEAS[1]]


async def test_draft_rows_carry_their_brief_and_place(client, ready, fake_llm, split):
    planned = await _plan(client)
    ids = await _write(client, planned, _split(planned)[:2])
    fake_llm.standing[POST_IDEAS] = ideas(planned_post(WHOLE))
    alone = await _plan(client)

    response = await client.get(POSTS, params={"status": "draft"})

    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["data"]}
    assert rows[ids[CORE_IDEAS[0]]]["brief_id"] == planned["id"]
    assert rows[ids[CORE_IDEAS[0]]]["place_in_brief"] == {
        "position": 1,
        "post_count": 2,
        "previous_post_id": None,
        "next_post_id": ids[CORE_IDEAS[1]],
    }
    assert rows[ids[CORE_IDEAS[1]]]["place_in_brief"]["position"] == 2
    alone_row = rows[_whole(alone)["post"]["id"]]
    assert alone_row["brief_id"] == alone["id"]
    assert alone_row["place_in_brief"] == ALONE


async def test_the_get_post_tool_reads_the_place_in_its_brief(client, ready, split, mcp):
    planned = await _plan(client)
    ids = await _write(client, planned, _split(planned)[:2])

    read = (await mcp.call_tool("get_post", post_id=ids[CORE_IDEAS[1]]))["structuredContent"]

    assert read["brief_id"] == planned["id"]
    assert read["place_in_brief"]["position"] == 2
    assert read["place_in_brief"]["post_count"] == 2
