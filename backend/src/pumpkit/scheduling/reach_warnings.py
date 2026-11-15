"""
Reach warnings (ADR 0032): what in a Scheduled post's or a Post's text may lead X to show it to
fewer people, in words for the User. They warn and never refuse; nothing here is stored.
"""

import re
from dataclasses import dataclass
from typing import Optional

from pumpkit.posts.formats import part_name


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
# Where an order starts, so "I'll share it" and "excited to share it" give none. Its whitespace
# never crosses a line: a long run of blank lines would make every search quadratic.
_START = r"(?:(?:^|(?<=[.!?:;,]))[^\S\n]*|\b(?:and|please|just|go|now|feel\s+free\s+to)\s+)"
_THIS = r"(?:this|it)(?:\s+(?:post|thread|tweet))?"

# An ask's code, what it is found by, and what it says to the User after the Part's name.
_ASKS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "share_ask",
        re.compile(
            rf"{_START}(?:share(?:\s+{_THIS}\b(?!\s+(?:week|weekend|month|year|morning|evening)\b)"
            r"|(?=\s+with\b|\s*[.!]|\s*$))"
            rf"|(?:send|forward)\s+{_THIS}\s+(?:to|along)\b)",
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
            r"|(?:a|an|your)(?:\s+[\w-]+){1,3}?(?=\s+(?:who|that|below|here)\b|\s*[.!?]|\s*$)"
            r"|the(?:\s+[\w-]+){1,3}?\s+who\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        "asks readers to tag someone, and X hides posts that ask for tags from people who "
        "don't follow you.",
    ),
    (
        "copy_link_ask",
        re.compile(
            r"\bcopy\s+(?:(?:the|this|my)\s+)?(?:post['\u2019]?s?\s+)?link\b"
            r"(?!\s+(?:from|into)\b)",
            re.IGNORECASE,
        ),
        "asks readers to copy the post's link, and X shows posts that ask for that to fewer "
        "people.",
    ),
    (
        "engagement_ask",
        re.compile(
            rf"{_START}(?:(?:like|retweet|repost|rt)\s+(?:(?:and|&|\+|or)\s+"
            r"(?:like|retweet|repost|rt|follow|share)\b|(?:this|it)\b(?!\s*:)|if\s+you\b)"
            r"|follow\s+(?:me|us)\b)"
            r"|\bfollow\s+(?:me\s+)?for\s+more\b"
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
            rf"{_START}(?:reply|comment|respond)\s+(?:with\s+)?[{_QUOTE_OPEN}][^{_QUOTE_CLOSE}]{{1,30}}"
            rf"[{_QUOTE_CLOSE}]"
            r"|\b(?:reply|comment)\b[^.\n]{0,40}\band\s+i(?:['\u2019]| wi)?ll\s+(?:send|dm|share)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "trades something for a reply or a comment, and X hides posts that do from people who "
        "don't follow you.",
    ),
    (
        "giveaway",
        re.compile(
            r"(?<!\bdead )\bgiveaway\b"
            # "Every reply I get" is the writer's; "every reply gets" is a reward.
            r"|\bevery(?:one\s+who)?\s+(?:reply|replies|comments?)\b[^.\n]{0,40}?"
            r"(?<!\bi )(?<!\bwe )(?<!\byou )(?<!\bthey )\b(?:gets?|wins?)\b",
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
