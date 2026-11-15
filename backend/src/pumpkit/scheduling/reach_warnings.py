"""
Reach warnings (ADR 0032): what in a Scheduled post's or a Post's text may lead X to show it to
fewer people, in words for the User. They warn and never refuse; nothing here is stored.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Optional

from pumpkit.posts.formats import part_name
from pumpkit.posts.models import Post
from pumpkit.scheduling.models import FAILED, ScheduledPost

ReachWarningCode = Literal[
    "share_ask",
    "tag_ask",
    "copy_link_ask",
    "engagement_ask",
    "reply_keyword_ask",
    "giveaway",
    "many_mentions",
    "many_hashtags",
    "shortened_link",
]


@dataclass(frozen=True)
class ReachWarning:
    code: ReachWarningCode
    # The Part it was found in, from 1.
    part: Optional[int]
    message: str


def _subject(number: int, count: int, *, first_reply: bool) -> str:
    name = part_name(number, count, first_reply=first_reply)
    return name.capitalize() if name else "This post"


# An ask is an order, so its verb starts a clause: "We now share it" and "I write and share it"
# state, they don't ask. A Part is split into sentences, each into clauses at "," and ":".
# A run of stops is taken whole from its start, so a long one not ending a sentence reads once.
_SENTENCE_END = re.compile(r"(?<![.!?\u2026])[.!?\u2026]++(?=[\s\"'\u201d\u2019)]|$)|[;\n]")
_CLAUSE_BREAK = re.compile(r"[,:]")
# Emoji, arrows and bullets before an order, and the words that soften it.
_LEAD = re.compile(
    r"[^\w,:]*(?:(?:please|pls|plz|just|go|then|now|so|and|also)\b[^\w,:]*){0,3}", re.IGNORECASE
)
# An order that "and" or "then" chains a second order onto, as in "Bookmark this and share it".
_CHAIN = re.compile(
    r"(?:bookmark|save|like|repost|retweet|rt|follow|share|send|forward|tag|copy|grab|read|check"
    r"|try|comment|reply|subscribe|join|open|click|tap|hit|give|leave|drop|turn|pass|scroll)\b",
    re.IGNORECASE,
)
_AND = re.compile(r"\s(?:and|&|\+|then)\s", re.IGNORECASE)
# Two short steps such as "Ship it. Share it." are a list, not an ask for shares.
_STEP = re.compile(r"[^\W\d_]+\s+it(?:\s+[^\W\d_]+)?", re.IGNORECASE)
# Three one-word steps such as "Build. Share. Repeat." are a list too, unless all ask or two
# ask for what X labels.
_WORD = re.compile(r"[^\W\d_]+")
_ASK_WORD = re.compile(
    r"like|share|repost|retweet|rt|follow|subscribe|comment|reply|bookmark|save|tag",
    re.IGNORECASE,
)
_LABELED_WORD = re.compile(r"like|share|repost|retweet|rt|follow|subscribe", re.IGNORECASE)
# "Record a Loom, then share it" goes on with the writer's own steps; only an order on this
# post or an "if" before it makes the "then" clause an ask, else only a share aimed at this
# post or at someone.
_THEN_CLAUSE = re.compile(r"\s*then\b", re.IGNORECASE)
_ON_THIS = re.compile(r"\s+(?:this|it|the\s+(?:post|thread|tweet))\b|\W*$", re.IGNORECASE)
_IF = re.compile(r"if\b", re.IGNORECASE)

_QUOTE_OPEN = "\"'\u201c\u2018"
_QUOTE_CLOSE = "\"'\u201d\u2019"
_THIS = r"(?:this|it)(?:\s+(?:post|thread|tweet))?"
# "Share this weekend" names a time, not the post.
_NOT_A_TIME = r"(?!\s+(?:week|weekend|month|year|morning|evening)\b)"
# Where an order ends its clause: trailing emoji or punctuation, then the sentence's end.
_END = r"[^\w,:]*$"
# What may follow "like this" or "repost it" in an order, unlike "Like it or not".
_THEN = rf"(?={_END}|\s+(?:and|&|\+|if|so|to|for|too|now|please)\b)"
# A share aimed at this post or at a person, which asks even before "before" or "after".
_AIMED_SHARE_PATTERN = (
    rf"share\s+this(?:\s+(?:post|thread|tweet))?\b{_NOT_A_TIME}"
    r"|share\s+it\s+with\s+(?:a|an|someone|somebody)\b"
)
# After the writer's own steps, "then share this file" is one more step: only a share naming
# the post, ending its clause or going to someone asks.
_AIMED_SHARE = re.compile(
    r"share\s+(?:this\s+(?:post|thread|tweet)\b|this(?=[^\w,:]*(?:$|[,:]))"
    r"|(?:this|it)\s+with\s+(?:a|an|someone|somebody)\b)",
    re.IGNORECASE,
)
_PERSON = (
    r"(?:friends?|someone|co-?founders?|founders?|devs?|developers?|engineers?|colleagues?"
    r"|co-?workers?|teammates?|team|boss|manager|mates?|buddy|buddies|pals?|partner|designers?"
    r"|pms?|marketers?|people|person|bestie|bff|mom|dad)"
)
# What a reply or a comment is traded for, unlike "comment for the reader".
_RESOURCE = (
    r"(?:(?:the|my|a|an|this|our|your|free)\s+)?(?:[\w-]+\s+){0,2}?"
    r"(?:links?|guides?|templates?|docs?|prompts?|playbooks?|checklists?|list|files?|pdfs?"
    r"|access|code(?!\s+review)|cheat\s*sheets?|sheets?|swipe\s+file|course|e-?books?|deck"
    r"|slides|scripts?|repo|invites?|discount|framework|spreadsheet|(?:tool)?kit|notion|copy"
    r"|video|recording|breakdown|resources?|details|dm)\b"
)
# Advice such as "comment for the reader" and idioms such as "reply for the record" trade nothing.
_NOT_TRADED = (
    r"(?!\s+(?:record|win|sake)\b|\s+(?:(?:next|future|code)\s+)?(?:why|what|how|readers?"
    r"|compiler|reviewers?|review|developers?|devs?|teammates?|team|maintainers?)"
    r"(?=[^\w,:]*$|\s*,|\s+not\b))"
)
_NEUTRAL = (
    r"(?:read|seen|answered|addressed|ignored|reviewed|considered|noticed|heard|replied|logged"
    r"|counted|shown|deleted|moderated|hidden|looked\s+at|an?\s+(?:\w+\s+)?(?:response|reply|answer)"
    r"|my\s+attention|its\s+own)"
)


def _ignoring_case(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


@dataclass(frozen=True)
class _Ask:
    code: ReachWarningCode
    # Said to the User after the Part's name.
    finding: str
    # Matched where a clause starts.
    order: Optional[re.Pattern[str]] = None
    # Searched anywhere in the Part.
    anywhere: Optional[re.Pattern[str]] = None


_SHARE_ASK = _Ask(
    "share_ask",
    "asks readers to share it, and X hides posts that ask for shares from people who don't "
    "follow you.",
    order=_ignoring_case(
        _AIMED_SHARE_PATTERN
        # "Share it with your team before the launch" is a step in the writer's how-to.
        + rf"|share(?:\s+{_THIS}\b{_NOT_A_TIME}|(?=\s+(?:with|if)\b)|{_END})"
        r"(?![^,.]{0,80}\b(?:before|after|during|until)\b)"
        rf"|(?:send|forward)\s+{_THIS}\s+(?:along\b|to\s+(?:the\s+)?[\w-]+\s+who\b"
        r"|to\s+(?:a|an|your|them|him|her|someone|somebody|anyone|everyone|every|those)\b"
        r"(?!\s+(?:users?|customers?|clients?)\b))"
        rf"|pass\s+{_THIS}\s+(?:on|along)\b"
    ),
)

_ASKS = [
    _SHARE_ASK,
    _Ask(
        "tag_ask",
        "asks readers to tag someone, and X hides posts that ask for tags from people who "
        "don't follow you.",
        # Anything tagged "who" is a person; else only a person counts, not "a stable release".
        order=_ignoring_case(
            rf"tag\s+(?:someone|somebody|anyone|them(?={_END})"
            r"|(?:a|an|your|\d+)(?:\s+[\w'-]+){1,3}?\s+who\b"
            rf"|(?:a|an|your|\d+)(?:\s+[\w'-]+){{0,2}}?\s+{_PERSON}\b"
            r"|the(?:\s+[\w'-]+){1,3}?\s+who\s+(?:needs?|would\s+love|should\s+see|must\s+see)\b)"
        ),
    ),
    _Ask(
        "copy_link_ask",
        "asks readers to copy the post's link, and X shows posts that ask for that to fewer "
        "people.",
        # "Copy the link and paste it" is a how-to, and "copy the link to your repo" another link.
        order=_ignoring_case(
            r"copy\s+(?:(?:the|this|my)\s+)?(?:post['\u2019]?s?\s+)?link\b"
            r"(?!\s+(?:from|into|in|of)\b|\s+to\s+(?!(?:this|the|my)\s+(?:post|tweet|thread)\b)"
            r"|,?\s+(?:(?:and|then)\s+)+paste\b|,\s*paste\b)"
        ),
    ),
    _Ask(
        "engagement_ask",
        "asks outright for likes, reposts, follows or notifications, and X hides posts that do "
        "from people who don't follow you.",
        order=_ignoring_case(
            r"(?:like|retweet|repost|rt)(?:\s*[&+/]\s*|\s+(?:and|or)\s+)"
            r"(?:like|retweet|repost|rt|follow|share)\b"
            rf"|(?:like|retweet|repost|rt)\s+{_THIS}\b{_THEN}"
            r"|(?:retweet|repost|rt)\s+(?:the|my|our)\s+(?:first|1st|top|pinned|original|last)\s+"
            r"(?:tweet|post|part)\b"
            rf"|(?:retweet|repost|rt)(?:\s+(?:if|so|to|for)\b|{_END})"
            rf"|(?:retweet|repost|rt)\s+(?:the|my|this)\s+(?:thread|post|tweet)\b{_THEN}"
            # "Like if Stripe had built this" wonders, and an ask ends at its comma.
            rf"|like(?:\s+if\s+(?:you|this|it|u)\b[^,]{{0,120}}?)?{_END}"
            rf"|follow(?:\s+(?:me|us|@\w+)\b(?!\s+on\b)|\s+(?:for|so)\b|{_END})"
            r"|(?:hit|smash|tap|click)\s+(?:(?:the|that)\s+)?"
            r"(?:like|follow|repost|retweet|rt|subscribe|bell)\b(?!\s+\d)"
            r"|(?:give|leave|drop)\s+(?:(?:this|it|us|me)\s+)?an?\s+"
            r"(?:like|follow|repost|retweet|heart)\b"
            r"|turn\s+on\s+(?:(?:post|the|your)\s+)?notifications\b(?!\s+(?:in|on)\b)"
            r"|drop\s+an?\s+\S+\s+(?:below|in\s+the\s+(?:replies|comments))\b"
        ),
    ),
    _Ask(
        "reply_keyword_ask",
        "trades something for a reply or a comment, and X hides posts that do from people who "
        "don't follow you.",
        # "Reply 'no' to recruiters" is a rule for the writer, not a trade.
        order=_ignoring_case(
            rf"(?:reply|comment|respond)\s+(?:with\s+)?(?:[{_QUOTE_OPEN}][^{_QUOTE_CLOSE}]{{1,30}}"
            rf"[{_QUOTE_CLOSE}]|(?-i:[A-Z][A-Z0-9]+)\b(?=\s+(?:below|for|and|to|in|if)\b|{_END})"
            rf"|(?-i:[A-Z])(?=\s+(?:below\b|for\s+{_RESOURCE})))"
            r"(?!\s+to\b(?!\s+(?:get|receive|grab|claim|unlock)\b))"
            rf"|(?:reply|comment)\s+for\s+(?:{_RESOURCE}"
            rf"|(?:the|my|a|an|this|our|your|free)\b{_NOT_TRADED})"
            r"|(?:reply|comment)\s+below\s+for\b"
            rf"|(?:reply|comment)\s+below{_END}"
        ),
        anywhere=_ignoring_case(
            r"\b(?:reply|comment)\b[^.\n]{0,40}\band\s+i(?:['\u2019]| wi)?ll\s+(?:send|dm|share)\b"
        ),
    ),
    _Ask(
        "giveaway",
        "promises a reward for engaging, and X hides posts that do from people who don't follow "
        "you.",
        order=_ignoring_case(r"(?:reply|comment|respond)\s+(?:below\s+)?to\s+(?:win|enter)\b"),
        # "Every reply I get" is the writer's, and "every reply gets read" no reward.
        anywhere=_ignoring_case(
            r"(?<!\bdead )\bgiveaway\b"
            r"|\bevery(?:one\s+who)?\s+(?:reply|replies|comments?)\b[^.\n]{0,40}?"
            r"(?<!\bi )(?<!\bwe )(?<!\byou )(?<!\bthey )(?<!\bthat )(?<!\bwhich )"
            rf"\b(?:gets?|wins?)\b(?!\s+{_NEUTRAL}\b)"
            r"|\bfirst\s+\d+(?:\s+(?:people|folks|followers|of\s+you))?\s+(?:to|who)\s+"
            r"(?:reply|replies|comment|comments|repost|reposts|retweet|retweets|rt)\b[^.\n]{0,40}?"
            rf"\b(?:get|gets|win|wins|receive|receives)\b(?!\s+{_NEUTRAL}\b)"
        ),
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

        def warn(code: ReachWarningCode, finding: str) -> None:
            warnings.append(ReachWarning(code, number, f"{subject} {finding}"))

        found = _asks_in(text)
        for ask in _ASKS:
            if ask.code in found:
                warn(ask.code, ask.finding)
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


def _asks_in(text: str) -> set[ReachWarningCode]:
    found: set[ReachWarningCode] = {
        ask.code for ask in _ASKS if ask.anywhere and ask.anywhere.search(text)
    }
    sentences = [(sentence, stop) for sentence, stop in _sentences(text) if sentence]
    clauses = [_clauses(sentence) for sentence, _ in sentences]
    listed, alone = _listed(sentences, clauses)
    for words in alone:
        for word in words:
            found.update(ask.code for ask in _ASKS if ask.order and ask.order.match(word))
    previous, previous_stop = "", ""
    for index, (sentence, stop) in enumerate(sentences):
        if not (
            _STEP.fullmatch(sentence) and _STEP.fullmatch(previous) and "?" not in previous_stop
        ):
            for start, aimed_only in _clause_starts(sentence, clauses[index], listed[index]):
                if aimed_only:
                    if _AIMED_SHARE.match(sentence, start):
                        found.add(_SHARE_ASK.code)
                    continue
                found.update(
                    ask.code for ask in _ASKS if ask.order and ask.order.match(sentence, start)
                )
        previous, previous_stop = sentence, stop
    return found


def _sentences(text: str) -> Iterator[tuple[str, str]]:
    """Each sentence, stripped, with the stops that end it."""
    begin = 0
    for stop in _SENTENCE_END.finditer(text):
        yield text[begin : stop.start()].strip(), stop.group()
        begin = stop.end()
    yield text[begin:].strip(), ""


def _clauses(sentence: str) -> list[tuple[int, int]]:
    breaks = [0, *(m.end() for m in _CLAUSE_BREAK.finditer(sentence))]
    return list(zip(breaks, [*breaks[1:], len(sentence)]))


def _listed(
    sentences: list[tuple[str, str]], clauses: list[list[tuple[int, int]]]
) -> tuple[list[set[int]], list[list[str]]]:
    """
    For each sentence, its clauses that are a step in a run of one-word steps; and each run of
    one-word asks, whose words such as "Like, share, subscribe" ask on their own.
    """
    listed: list[set[int]] = [set() for _ in sentences]
    alone: list[list[str]] = []
    run: list[tuple[int, int, str]] = []

    def close() -> None:
        asks = sum(1 for _, _, word in run if _ASK_WORD.fullmatch(word))
        labeled = sum(1 for _, _, word in run if _LABELED_WORD.fullmatch(word))
        if labeled >= 2 or (len(run) >= 2 and asks == len(run)):
            alone.append([word for _, _, word in run])
        elif len(run) >= 3:
            for index, clause, _ in run:
                listed[index].add(clause)
        run.clear()

    for index, (sentence, stop) in enumerate(sentences):
        # A question such as "Agree?" is no step, so it ends a run.
        if "?" in stop:
            close()
            continue
        for clause, (begin, end) in enumerate(clauses[index]):
            word = sentence[begin:end].rstrip(",:").strip()
            if _WORD.fullmatch(word):
                run.append((index, clause, word))
            else:
                close()
    close()
    return listed, alone


def _clause_starts(
    sentence: str, clauses: list[tuple[int, int]], listed: set[int]
) -> Iterator[tuple[int, bool]]:
    """Where each order may start, and whether only a share aimed at this post or a person counts."""
    ordered = False
    for clause, (begin, end) in enumerate(clauses):
        start = _after_lead(sentence, begin)
        chain = _CHAIN.match(sentence, start)
        chained = chain is not None
        goes_on = begin > 0 and _THEN_CLAUSE.match(sentence, begin) is not None and not ordered
        ordered = (
            chain is not None and _ON_THIS.match(sentence, chain.end(), end) is not None
        ) or (_IF.match(sentence, start) is not None)
        if clause in listed:
            continue
        yield start, goes_on
        if goes_on:
            continue
        if chained:
            # A lead runs to the next word, so a joint inside one already read adds nothing.
            reached = start
            for joint in _AND.finditer(sentence, start, end):
                if joint.end() < reached:
                    continue
                reached = _after_lead(sentence, joint.end())
                yield reached, False


def _after_lead(sentence: str, position: int) -> int:
    lead = _LEAD.match(sentence, position)
    return lead.end() if lead else position
