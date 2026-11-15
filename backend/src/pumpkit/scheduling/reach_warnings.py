"""
Reach warnings (ADR 0032): what in a Scheduled post's or a Post's text may lead X to show it to
fewer people, in words for the User. They warn and never refuse; nothing here is stored.
"""

import re
from dataclasses import dataclass
from typing import Optional

from pumpkit.posts.formats import part_name
from pumpkit.posts.models import Post
from pumpkit.scheduling.models import FAILED, ScheduledPost


@dataclass(frozen=True)
class ReachWarning:
    code: str
    # The Part it was found in, from 1.
    part: Optional[int]
    message: str


def _subject(number: int, count: int, *, first_reply: bool) -> str:
    name = part_name(number, count, first_reply=first_reply)
    return name.capitalize() if name else "This post"


_QUOTE_OPEN = "\"'\u201c\u2018"
_QUOTE_CLOSE = "\"'\u201d\u2019"
# Where an order starts, so "I'll share it" and "excited to share it" give none; "and" starts none,
# as in "I write and share it". Its whitespace never crosses a line: a long run of blank lines
# would make every search quadratic.
_START = (
    r"(?:(?:^|(?<=[.!?:;,]))[^\S\n]*|\b(?:please|go|now|feel\s+free\s+to)\s+)"
    r"(?:(?:just|please)\s+)?"
)
_THIS = r"(?:this|it)(?:\s+(?:post|thread|tweet))?"
# What an order's verb may end its sentence with, on the same line.
_END = r"[^\S\n]*(?:[.!]|$)"

# An ask's code, what it is found by, and what it says to the User after the Part's name.
_ASKS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "share_ask",
        re.compile(
            rf"{_START}(?:share(?:\s+{_THIS}\b(?!\s+(?:week|weekend|month|year|morning|evening)\b)"
            rf"|(?=\s+(?:with|if)\b|{_END}))"
            rf"|(?:send|forward)\s+{_THIS}\s+(?:to|along)\b"
            rf"|pass\s+{_THIS}\s+(?:on|along)\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        "asks readers to share it, and X hides posts that ask for shares from people who don't "
        "follow you.",
    ),
    (
        "tag_ask",
        re.compile(
            # "Tag the release" names a thing; "the" counts only for a person, before "who".
            rf"{_START}tag\s+(?:someone|somebody|them|\d+\b"
            r"|(?:a|an|your)(?!\s+(?:new\s+)?(?:release|version|commit|build|branch|image|issue|pr)s?\b)"
            r"(?:\s+[\w-]+){1,3}?(?=\s+(?:who|that|below|here)\b|\s*[.!?]|\s*$)"
            r"|the(?:\s+[\w-]+){1,3}?\s+who\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        "asks readers to tag someone, and X hides posts that ask for tags from people who "
        "don't follow you.",
    ),
    (
        "copy_link_ask",
        re.compile(
            # "Click Copy link" names a button, and "copy the link and paste it" is a how-to.
            r"(?<!\bclick )(?<!\btap )\bcopy\s+(?:(?:the|this|my)\s+)?(?:post['’]?s?\s+)?link\b"
            r"(?!\s+(?:from|into|and\s+paste)\b)",
            re.IGNORECASE,
        ),
        "asks readers to copy the post's link, and X shows posts that ask for that to fewer "
        "people.",
    ),
    (
        "engagement_ask",
        re.compile(
            rf"{_START}(?:(?:like|retweet|repost|rt)\s+(?:and|&|\+|or)\s+"
            r"(?:like|retweet|repost|rt|follow|share)\b"
            # "Like it or not" and "Like this, the cache stays warm" are idioms.
            r"|(?:like|retweet|repost|rt)\s+(?:this|it)\b(?!\s*[:,]|\s+or\b)"
            rf"|(?:retweet|repost|rt)(?:\s+(?:if|so|to|for)\b|{_END})"
            # "Like if you shipped on a Friday, you know" goes on past a comma; an ask ends there.
            rf"|like(?:\s+if\b[^,.!?\n]{{0,60}}(?:[.!?]|$)|{_END})"
            rf"|follow(?:\s+(?:me|us|@\w+|for)\b|{_END})"
            r"|hit\s+(?:(?:the|that)\s+)?(?:like|follow|repost|retweet)\b(?!\s+\d))"
            r"|\bfollow\s+(?:me\s+)?for\s+more\b"
            r"|\b(?:give|leave)\s+(?:(?:this|it|us|me)\s+)?an?\s+(?:like|follow|repost|retweet)\b"
            r"|\bturn\s+on\s+(?:post\s+)?notifications\b"
            r"|\bdrop\s+an?\s+\S+\s+(?:below|in\s+the\s+(?:replies|comments))\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "asks outright for likes, reposts, follows or notifications, and X hides posts that do "
        "from people who don't follow you.",
    ),
    (
        "reply_keyword_ask",
        re.compile(
            # "Reply 'no' to every meeting invite" is a rule for the writer, not a trade.
            rf"{_START}(?:reply|comment|respond)\s+(?:with\s+)?[{_QUOTE_OPEN}][^{_QUOTE_CLOSE}]{{1,30}}"
            rf"[{_QUOTE_CLOSE}](?!\s+to\s+(?:every|all|any)\b)"
            r"|\b(?:reply|comment)\b[^.\n]{0,40}\band\s+i(?:['’]| wi)?ll\s+(?:send|dm|share)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "trades something for a reply or a comment, and X hides posts that do from people who "
        "don't follow you.",
    ),
    (
        "giveaway",
        re.compile(
            r"(?<!\bdead )\bgiveaway\b"
            # "Every reply I get" is the writer's and "every reply that wins" the reply's own;
            # "every reply gets" is a reward, unless it "gets addressed".
            r"|\bevery(?:one\s+who)?\s+(?:reply|replies|comments?)\b[^.\n]{0,40}?"
            r"(?<!\bi )(?<!\bwe )(?<!\byou )(?<!\bthey )(?<!\bthat )(?<!\bwhich )"
            r"\b(?:gets?|wins?)\b(?!\s+\w+ed\b)",
            re.IGNORECASE,
        ),
        "promises a reward for engaging, and X hides posts that do from people who don't follow "
        "you.",
    ),
]

_MENTION = re.compile(r"(?<![\w@])@(\w{1,15})\b")
# A hashtag on X holds at least one letter, so "#1" isn't one; nor is a URL's "/#section".
_HASHTAG = re.compile(r"(?<![\w#&/])#[\d_]*[^\W\d_]\w*")
# X wraps every link in its own t.co, so a pasted t.co link adds no hop worth a warning.
_SHORTENERS = re.compile(
    r"(?<![\w.-])(?:bit\.ly|tinyurl\.com|t\.ly|ow\.ly|buff\.ly|cutt\.ly|rebrand\.ly|"
    r"shorturl\.at|is\.gd|rb\.gy|lnkd\.in|tiny\.cc|s\.id|goo\.gl|dlvr\.it|trib\.al)/",
    re.IGNORECASE,
)


def post_warnings(post: Post, scheduled_post: Optional[ScheduledPost]) -> list[ReachWarning]:
    """
    The warnings for what goes out on X: the Scheduled post's own text, else the Text, which is
    also what a Failed post's retry copies.
    """
    if scheduled_post is not None and scheduled_post.state != FAILED:
        parts = [part.text for part in scheduled_post.parts]
        return text_warnings(parts, first_reply=scheduled_post.first_reply)
    return text_warnings(list(post.text_parts or []), first_reply=post.text_first_reply)


def text_warnings(parts: list[str], *, first_reply: bool) -> list[ReachWarning]:
    """One warning per finding, in Part order."""
    warnings: list[ReachWarning] = []
    for number, text in enumerate(parts, start=1):
        subject = _subject(number, len(parts), first_reply=first_reply)

        def warn(code: str, finding: str) -> None:
            warnings.append(ReachWarning(code, number, f"{subject} {finding}"))

        for code, pattern, finding in _ASKS:
            if pattern.search(text):
                warn(code, finding)
        if len({handle.lower() for handle in _MENTION.findall(text)}) >= 2:
            warn(
                "many_mentions",
                "mentions two or more accounts, which sends it through X's real-time spam check.",
            )
        if len(_HASHTAG.findall(text)) >= 2:
            warn(
                "many_hashtags",
                "has two or more hashtags, and X may treat that as hashtag abuse and show it "
                "to fewer people.",
            )
        if _SHORTENERS.search(text):
            warn(
                "shortened_link",
                "uses a link shortener, and X checks every hop a link redirects through. "
                "Link the final page instead.",
            )
    return warnings
