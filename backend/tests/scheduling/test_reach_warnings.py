"""
Reach warnings (ADR 0032) through `GET /posts/{id}`, its reach-warnings read, scheduling's answers
and the MCP tools: what in the Text, or in a Scheduled post's own text, may cost it reach.
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


async def _text_warnings(client, post_id: str) -> list[dict]:
    """The Text's warnings through the read "Post to…" makes as the User picks a time."""
    response = await client.get(f"{POSTS}/{post_id}/reach-warnings")
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
    pytest.param(["Repost."], [("engagement_ask", 1)], id="bare-repost"),
    pytest.param(["Retweet."], [("engagement_ask", 1)], id="bare-retweet"),
    pytest.param(["Repost!"], [("engagement_ask", 1)], id="repost-exclaimed"),
    pytest.param(["Please repost."], [("engagement_ask", 1)], id="please-repost"),
    pytest.param(["Follow."], [("engagement_ask", 1)], id="bare-follow"),
    pytest.param(["Please follow."], [("engagement_ask", 1)], id="please-follow"),
    pytest.param(["Hit follow."], [("engagement_ask", 1)], id="hit-follow"),
    pytest.param(["Follow for daily tips."], [("engagement_ask", 1)], id="follow-for-tips"),
    pytest.param(["Follow @handle for more"], [("engagement_ask", 1)], id="follow-a-handle"),
    pytest.param(["Please like."], [("engagement_ask", 1)], id="please-like"),
    pytest.param(["Like if this helped."], [("engagement_ask", 1)], id="like-if-it-helped"),
    pytest.param(["Give this a like."], [("engagement_ask", 1)], id="give-this-a-like"),
    pytest.param(["Leave a like."], [("engagement_ask", 1)], id="leave-a-like"),
    pytest.param(["Hit like."], [("engagement_ask", 1)], id="hit-like"),
    pytest.param(["Repost if useful"], [("engagement_ask", 1)], id="repost-if-useful"),
    pytest.param(["Repost so others see it."], [("engagement_ask", 1)], id="repost-so"),
    pytest.param(["Repost to help a friend."], [("engagement_ask", 1)], id="repost-to-help"),
    pytest.param(["Retweet to spread the word."], [("engagement_ask", 1)], id="retweet-to-spread"),
    pytest.param(["Share if you agree."], [("share_ask", 1)], id="share-if-you-agree"),
    pytest.param(["Pass this on to a friend."], [("share_ask", 1)], id="pass-this-on"),
    pytest.param(["♻️ Repost to help others."], [("engagement_ask", 1)], id="emoji-repost-to"),
    pytest.param(["♻️ Repost if this helped."], [("engagement_ask", 1)], id="emoji-repost-if"),
    pytest.param(["👇 Tag a friend who needs this."], [("tag_ask", 1)], id="emoji-tag"),
    pytest.param(["➡️ Share this with a friend."], [("share_ask", 1)], id="arrow-share"),
    pytest.param(["🔁 Retweet if you agree"], [("engagement_ask", 1)], id="emoji-retweet-if"),
    pytest.param(["Bookmark this and share it."], [("share_ask", 1)], id="bookmark-and-share"),
    pytest.param(["Save this and send it to a friend."], [("share_ask", 1)], id="save-and-send-it"),
    pytest.param(["Save it and tag a friend."], [("tag_ask", 1)], id="save-and-tag"),
    pytest.param(
        ["Bookmark this, then share it with your team."], [("share_ask", 1)], id="then-share"
    ),
    pytest.param(["Reply to win."], [("giveaway", 1)], id="reply-to-win"),
    pytest.param(["Reply to win a copy."], [("giveaway", 1)], id="reply-to-win-a-copy"),
    pytest.param(["Comment to enter."], [("giveaway", 1)], id="comment-to-enter"),
    pytest.param(["Comment GUIDE below."], [("reply_keyword_ask", 1)], id="bare-keyword-below"),
    pytest.param(["Reply GUIDE for the doc."], [("reply_keyword_ask", 1)], id="bare-keyword-for"),
    pytest.param(["Every reply gets followed back."], [("giveaway", 1)], id="followed-back"),
    pytest.param(["Every reply gets retweeted."], [("giveaway", 1)], id="replies-retweeted"),
    pytest.param(
        ["Every reply gets featured in next week's post."], [("giveaway", 1)], id="featured"
    ),
    pytest.param(["Follow so you don't miss part 2."], [("engagement_ask", 1)], id="follow-so"),
    pytest.param(["Smash that like button."], [("engagement_ask", 1)], id="smash-like"),
    pytest.param(
        ["Retweet the first tweet of this thread."], [("engagement_ask", 1)], id="rt-first-tweet"
    ),
    pytest.param(["RT the top tweet."], [("engagement_ask", 1)], id="rt-the-top-tweet"),
    pytest.param(
        ["Enjoyed this? Repost the first post so others can find it."],
        [("engagement_ask", 1)],
        id="repost-the-first-post",
    ),
    pytest.param(["Repost the top post ♻️"], [("engagement_ask", 1)], id="repost-the-top-post"),
    pytest.param(
        ["Comment below for the link."], [("reply_keyword_ask", 1)], id="comment-below-for"
    ),
    pytest.param(["Comment for the link."], [("reply_keyword_ask", 1)], id="comment-for-the-link"),
    pytest.param(["Reply for the template."], [("reply_keyword_ask", 1)], id="reply-for-the"),
    pytest.param(
        ["Want the template? Comment below."], [("reply_keyword_ask", 1)], id="comment-below"
    ),
    pytest.param(
        ["First 100 people to reply get free access."], [("giveaway", 1)], id="first-100-to-reply"
    ),
    pytest.param(
        ["Like. Share. Subscribe."],
        [("share_ask", 1), ("engagement_ask", 1)],
        id="like-share-subscribe",
    ),
    pytest.param(["Found it useful? Share it."], [("share_ask", 1)], id="found-it-useful-share-it"),
    pytest.param(["Read this, then share it."], [("share_ask", 1)], id="read-then-share"),
    pytest.param(
        ["Tag the friend who needs this."], [("tag_ask", 1)], id="tag-the-friend-who-needs"
    ),
    pytest.param(
        ["Tag the person who needs this."], [("tag_ask", 1)], id="tag-the-person-who-needs"
    ),
    pytest.param(
        ["Tag the founder who needs to see this."], [("tag_ask", 1)], id="tag-who-needs-to-see"
    ),
    pytest.param(
        ["Share this with a friend before they quit."], [("share_ask", 1)], id="share-before-they"
    ),
    pytest.param(
        ["Share this with a friend before it's too late."],
        [("share_ask", 1)],
        id="share-before-too-late",
    ),
    pytest.param(["Share this before you forget."], [("share_ask", 1)], id="share-before-you"),
    pytest.param(
        ["Share this with a founder after you read it."], [("share_ask", 1)], id="share-after"
    ),
    pytest.param(["Comment X for the link."], [("reply_keyword_ask", 1)], id="one-letter-keyword"),
    pytest.param(["Comment A for the guide."], [("reply_keyword_ask", 1)], id="keyword-a"),
    pytest.param(
        ["Agree? Like. Repost. Follow."], [("engagement_ask", 1)], id="question-then-asks"
    ),
    pytest.param(
        ["Like. Share. Follow. Thanks!"],
        [("share_ask", 1), ("engagement_ask", 1)],
        id="asks-then-thanks",
    ),
    pytest.param(["Thanks! Like, repost, follow."], [("engagement_ask", 1)], id="thanks-then-asks"),
    pytest.param(
        ["Found this useful? Like. Share. Repeat."],
        [("share_ask", 1), ("engagement_ask", 1)],
        id="like-share-repeat",
    ),
    pytest.param(["Repost the thread."], [("engagement_ask", 1)], id="repost-the-thread"),
    pytest.param(
        ["Like, share, subscribe."],
        [("share_ask", 1), ("engagement_ask", 1)],
        id="like-share-subscribe-commas",
    ),
    pytest.param(["Repost, then follow."], [("engagement_ask", 1)], id="repost-then-follow"),
    pytest.param(["Reply for a copy."], [("reply_keyword_ask", 1)], id="reply-for-a-copy"),
    pytest.param(
        ["Comment below for the waitlist."],
        [("reply_keyword_ask", 1)],
        id="comment-below-for-the-waitlist",
    ),
    pytest.param(
        ["Comment below for a sample."], [("reply_keyword_ask", 1)], id="comment-below-for-a-sample"
    ),
    pytest.param(
        ["Comment for a free trial."], [("reply_keyword_ask", 1)], id="comment-for-a-free-trial"
    ),
    pytest.param(
        ["Reply for a free audit."], [("reply_keyword_ask", 1)], id="reply-for-a-free-audit"
    ),
    pytest.param(["Comment for the beta."], [("reply_keyword_ask", 1)], id="comment-for-the-beta"),
    pytest.param(["Reply for the recipe."], [("reply_keyword_ask", 1)], id="reply-for-the-recipe"),
    pytest.param(
        ["Comment for the recipe."], [("reply_keyword_ask", 1)], id="comment-for-the-recipe"
    ),
    pytest.param(
        ["Comment for the full thread."],
        [("reply_keyword_ask", 1)],
        id="comment-for-the-full-thread",
    ),
    pytest.param(
        ["Reply for the full write-up."],
        [("reply_keyword_ask", 1)],
        id="reply-for-the-full-write-up",
    ),
    pytest.param(
        ["Reply for my newsletter."], [("reply_keyword_ask", 1)], id="reply-for-my-newsletter"
    ),
    pytest.param(["Comment for my notes."], [("reply_keyword_ask", 1)], id="comment-for-my-notes"),
    pytest.param(
        ["Comment for the system."], [("reply_keyword_ask", 1)], id="comment-for-the-system"
    ),
    pytest.param(
        ["Reply for the workflow."], [("reply_keyword_ask", 1)], id="reply-for-the-workflow"
    ),
    pytest.param(
        ["Comment for the case study."], [("reply_keyword_ask", 1)], id="comment-for-the-case-study"
    ),
    pytest.param(["Comment for the GPT."], [("reply_keyword_ask", 1)], id="comment-for-the-gpt"),
    pytest.param(
        ["Comment for the source."], [("reply_keyword_ask", 1)], id="comment-for-the-source"
    ),
    pytest.param(["Reply for the steps."], [("reply_keyword_ask", 1)], id="reply-for-the-steps"),
    pytest.param(
        ["Drop a comment, then share it with a friend."],
        [("share_ask", 1)],
        id="drop-a-comment-then-share-it-with-a-friend",
    ),
    pytest.param(
        ["Read the guide, then share it with a friend."],
        [("share_ask", 1)],
        id="read-the-guide-then-share-it-with-a-friend",
    ),
    pytest.param(
        ["Scroll up, then share this thread."],
        [("share_ask", 1)],
        id="scroll-up-then-share-this-thread",
    ),
    pytest.param(
        ["Follow me, then share this thread."],
        [("share_ask", 1), ("engagement_ask", 1)],
        id="follow-me-then-share-this-thread",
    ),
    pytest.param(
        ["Follow me, then share it with a friend."],
        [("share_ask", 1), ("engagement_ask", 1)],
        id="follow-me-then-share-it-with-a-friend",
    ),
    pytest.param(
        ["Finish reading, then share this with a friend."],
        [("share_ask", 1)],
        id="finish-reading-then-share-this-with-a-friend",
    ),
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
    pytest.param("I write every week and share it on my blog.", id="and-share-in-a-story"),
    pytest.param(
        "I build in public and share with my team every Friday.", id="and-share-with-my-team"
    ),
    pytest.param("I just share it with friends first.", id="i-just-share"),
    pytest.param("Like it or not, AI agents are here.", id="like-it-or-not"),
    pytest.param("And like it or not, the market moved.", id="and-like-it-or-not"),
    pytest.param("Like it or hate it, it works.", id="like-it-or-hate-it"),
    pytest.param("Like this, the cache stays warm.", id="like-this-comma"),
    pytest.param("Like if you shipped on a Friday, you know the feeling.", id="like-if-you-comma"),
    pytest.param("Follow along.", id="follow-along"),
    pytest.param("Go follow up with your leads.", id="follow-up"),
    pytest.param("Now tag your release.", id="now-tag-your-release"),
    pytest.param("Next, tag a release.", id="tag-a-release"),
    pytest.param("Fix the bugs and tag them later.", id="and-tag-them"),
    pytest.param("Every comment on that PR gets addressed.", id="every-comment-gets-addressed"),
    pytest.param(
        "Every reply that wins the argument loses the friend.", id="every-reply-that-wins"
    ),
    pytest.param(
        "Open settings, copy the link and paste it in Slack.", id="copy-the-link-and-paste"
    ),
    pytest.param("Click Copy link in the share menu.", id="click-copy-link"),
    pytest.param("My rule: reply 'no' to every meeting invite.", id="reply-no-to-every"),
    pytest.param("We hit like 10k users last month.", id="hit-like-a-number"),
    pytest.param("We now share it with every customer on day one.", id="we-now-share"),
    pytest.param("Teams now like it because builds are faster.", id="teams-now-like"),
    pytest.param("I now like this approach more than the old one.", id="i-now-like"),
    pytest.param("Users now follow us from the docs.", id="users-now-follow"),
    pytest.param("Every reply gets read.", id="every-reply-gets-read"),
    pytest.param("Every reply gets read by me personally.", id="read-by-me"),
    pytest.param("Every reply gets seen.", id="every-reply-gets-seen"),
    pytest.param("Like if you're on Next.js, this breaks.", id="like-if-youre-on"),
    pytest.param("Like if Stripe had built this.", id="like-if-stripe-had"),
    pytest.param("Tag a Docker image that you push to prod.", id="tag-a-docker-image"),
    pytest.param("Tag a stable release.", id="tag-a-stable-release"),
    pytest.param('Click "Copy link" and paste it into the form.', id="click-quoted-copy-link"),
    pytest.param("Copy the link, then paste it into the form.", id="copy-then-paste"),
    pytest.param("Copy the link to your repo", id="copy-the-link-to-your-repo"),
    pytest.param('Reply "no" to recruiters.', id="reply-no-to-recruiters"),
    pytest.param("Ship it. Share it. Learn.", id="ship-it-share-it"),
    pytest.param("Forward this to legal before you sign.", id="forward-to-legal"),
    pytest.param("Build. Share. Repeat.", id="build-share-repeat"),
    pytest.param("Learn in public. Build. Share. Repeat.", id="learn-build-share-repeat"),
    pytest.param("Learn, build, share.", id="learn-build-share"),
    pytest.param("Code, test, ship, share.", id="code-test-ship-share"),
    pytest.param("Record a Loom, then share it with your team.", id="record-then-share"),
    pytest.param("Write the code, then share it.", id="write-then-share"),
    pytest.param("I build, then share it.", id="i-build-then-share"),
    pytest.param("Write it down. Share it.", id="write-it-down-share-it"),
    pytest.param("Tag the person who owns the service.", id="tag-the-person-who"),
    pytest.param("Turn on notifications in Slack for deploys.", id="notifications-in-slack"),
    pytest.param("Every reply gets a personal response from me.", id="a-personal-response"),
    pytest.param("Share it with your team before the launch.", id="share-before-the-launch"),
    pytest.param("Send it to your users first.", id="send-it-to-your-users"),
    pytest.param(
        "Comment for the next developer, not for yourself.", id="comment-for-the-next-developer"
    ),
    pytest.param("Comment for the why, not the what.", id="comment-for-the-why"),
    pytest.param("Rule 3: comment for the reader, not the compiler.", id="comment-for-the-reader"),
    pytest.param(
        "Write tests. Comment for your teammates. Ship small PRs.", id="comment-for-teammates"
    ),
    pytest.param("Open a PR, then share it with your reviewer.", id="open-a-pr-then-share"),
    pytest.param(
        "Export the report, then share this link with your team.", id="then-share-this-link"
    ),
    pytest.param("Ship it, then share this file with your boss.", id="then-share-this-file"),
    pytest.param("Build it, then share this with your manager.", id="then-share-this-with-your"),
    pytest.param(
        "Export the CSV, then share it with a teammate.", id="then-share-it-with-a-teammate"
    ),
    pytest.param(
        "Write the doc, then share it with someone on your team.",
        id="then-share-it-with-someone-on-your-team",
    ),
    pytest.param("Write. Share. Save. Repeat.", id="write-share-save-repeat"),
    pytest.param(
        "Comment for the code reviewer, not yourself.",
        id="comment-for-the-code-reviewer-not-yourself",
    ),
    pytest.param("Comment for the code review.", id="comment-for-the-code-review"),
    pytest.param("Comment for the reader.", id="comment-for-the-reader"),
]


@pytest.mark.parametrize(("parts", "found"), FINDINGS)
async def test_each_finding_warns_in_the_part_it_lands_in(
    client, subscribed, post_with, parts, found
):
    post_id = await post_with(*parts, first_reply=len(parts) == 2)

    warnings = await _text_warnings(client, post_id)

    assert [(w["code"], w["part"]) for w in warnings] == found


@pytest.mark.parametrize("text", CLEAN)
async def test_close_calls_stay_clean(client, subscribed, post_with, text):
    post_id = await post_with(text)

    assert await _text_warnings(client, post_id) == []


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        pytest.param("copy" + " " * 30_000 + "x", [], id="after-copy"),
        pytest.param("\n" * 30_000, [], id="newlines"),
        pytest.param("Done," + " " * 30_000 + "x", [], id="after-a-comma"),
        pytest.param("please" + " " * 30_000 + "x", [], id="after-please"),
        pytest.param("." * 30_000 + "x", [], id="dots-ending-no-sentence"),
        pytest.param("like" + " & " * 20_000, ["engagement_ask"], id="ampersands-after-like"),
        pytest.param("like" + " + " * 20_000, ["engagement_ask"], id="pluses-after-like"),
        pytest.param("rt" + " & " * 20_000, ["engagement_ask"], id="ampersands-after-rt"),
        pytest.param("share it" + " & " * 20_000, ["share_ask"], id="ampersands-after-share-it"),
    ],
)
async def test_long_runs_of_stops_and_joints_read_fast(client, subscribed, post_with, text, codes):
    # Four Parts so a quadratic search, seconds on each, overruns a bound slow CI still meets.
    post_id = await post_with(text, text, text, text)

    started = time.monotonic()
    warnings = await _text_warnings(client, post_id)
    assert time.monotonic() - started < 5

    assert [w["code"] for w in warnings] == codes * 4


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


async def test_the_reach_warnings_read_gives_the_texts_warnings_at_a_time(
    client, subscribed, post_with
):
    post_id = await post_with("Ship small things. Tag a friend who doesn't.")

    at_a_time = await client.get(f"{POSTS}/{post_id}/reach-warnings", params={"publish_at": LATER})
    now = await client.get(f"{POSTS}/{post_id}/reach-warnings")

    assert at_a_time.status_code == 200, at_a_time.text
    assert [(w["code"], w["part"]) for w in at_a_time.json()["reach_warnings"]] == [("tag_ask", 1)]
    assert now.json() == at_a_time.json()


async def test_the_reach_warnings_read_is_the_users_own(
    client, subscribed, post_with, sign_in_as_another_subscribed_user
):
    post_id = await post_with("Tag a friend.")
    await sign_in_as_another_subscribed_user()

    read = await client.get(f"{POSTS}/{post_id}/reach-warnings")

    assert read.status_code == 404


def _found(answer: dict) -> list[tuple[str, int]]:
    return [(w["code"], w["part"]) for w in answer["reach_warnings"]]


async def test_scheduling_answers_with_the_scheduled_posts_warnings(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    post_id = await post_with("Ship small things. Tag a friend who doesn't.")

    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert scheduled.status_code == 201, scheduled.text
    assert _found(scheduled.json()) == [("tag_ask", 1)]


async def test_post_now_answers_with_the_warnings_of_what_went_out(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    post_id = await post_with("Like and repost if you agree.")

    posted = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert posted.status_code == 201, posted.text
    assert posted.json()["state"] == "published"
    assert _found(posted.json()) == [("engagement_ask", 1)]


async def test_an_edit_answers_with_the_warnings_of_the_edited_text(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    post_id = await post_with("Ship small things. Tag a friend who doesn't.")
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    edited = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}",
        json={"parts": ["Ship small things. #shipping #small"]},
    )

    assert edited.status_code == 200, edited.text
    assert _found(edited.json()) == [("many_hashtags", 1)]


async def test_a_link_placeholder_is_still_refused_beside_a_warning(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    post_id = await post_with("Share this with a founder.", "Read it: [link]", first_reply=True)

    refused = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "LINK_PLACEHOLDER"


async def test_the_scheduling_tools_give_the_warnings(
    subscribed, connect_x, fixed_clock, mcp, post_with
):
    await connect_x()
    scheduled = await mcp.call_tool(
        "schedule_post", post_id=await post_with("Tag a friend who ships."), publish_at=LATER
    )
    edited = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["structuredContent"]["id"],
        parts=["Built with @alice and @bob."],
    )
    posted = await mcp.call_tool("post_now", post_id=await post_with("Follow me for more."))

    assert _found(scheduled["structuredContent"]) == [("tag_ask", 1)]
    assert _found(edited["structuredContent"]) == [("many_mentions", 1)]
    assert _found(posted["structuredContent"]) == [("engagement_ask", 1)]
