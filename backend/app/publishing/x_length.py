"""
A text's length the way X counts it: twitter-text 3.1.0's v3 weighting, hand-ported because
its Python port is archived. `frontend/src/lib/xLength.ts` is the same port; both are tested
against one set of strings, so the composer's counter agrees with the backend.

After NFC normalization, a URL counts 23, an emoji sequence 2, a code point in the ranges
below 1, and any other code point 2. URL matching follows twitter-text's extractUrl regex and
TLD list (Copyright 2018 Twitter, Inc., Apache License 2.0). Three simplifications: emoji
sequences are matched by code point ranges rather than twemoji's list, a URL's length check
skips punycode encoding, and a domain has at most 127 labels, which keeps matching fast.
"""

import re
import unicodedata
from pathlib import Path

# TODO(#66): raise the limit for X Premium accounts once the long-post spike (#67) settles it.
X_POST_MAX_CHARS = 280

URL_LENGTH = 23
_SCALE = 100
_DEFAULT_WEIGHT = 200
_LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_MAX_URL_LENGTH = 4096
_MAX_TCO_SLUG_LENGTH = 40


def _tlds() -> str:
    lines = (Path(__file__).parent / "x_tlds.txt").read_text(encoding="utf-8").splitlines()
    tlds = [line for line in lines if line and not line.startswith("#")]
    return _trie_pattern(tlds) + "(?=[^0-9a-zA-Z@+\\-]|$)"


def _trie_pattern(words: list[str]) -> str:
    """
    An alternation of `words` as a prefix trie. Python's re tries a flat alternation's
    branches one by one, which made a text like "a.a.a." take minutes.
    """
    trie: dict = {}
    for word in words:
        node = trie
        for char in word:
            node = node.setdefault(char, {})
        node[""] = {}

    def pattern(node: dict) -> str:
        ends_here = "" in node
        branches = [re.escape(char) + pattern(child) for char, child in node.items() if char]
        if not branches:
            return ""
        body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
        if ends_here:
            # Greedy: the longer TLD is tried first, and the lookahead backtracks to the shorter.
            return "(?:" + body + ")?"
        return body

    return "(?:" + pattern(trie) + ")"


_TLD = _tlds()
_PUNYCODE = r"(?:xn--[\-0-9a-z]+)"
_LATIN_ACCENTS = "\xc0-\xd6\xd8-\xf6\xf8-\xffĀ-ɏɓɔɖɗəɛɣɨɯɲʉʋʻ̀-ͯḀ-ỿ"
_DIRECTIONAL = "‪-‮؜‎‏⁦-⁩"
_INVALID = "￾﻿￿"
_SPACES = "\t-\r \x85\xa0 ᠎ -     　"
_PUNCT = r"!'#%&()*+,\\\-./:;<=>?@\[\]^_{|}~$"
_DOMAIN_CHAR = f"[^{_PUNCT}{_SPACES}{_INVALID}{_DIRECTIONAL}]"
_SUBDOMAIN = f"(?:(?:{_DOMAIN_CHAR}(?:[_-]|{_DOMAIN_CHAR})*)?{_DOMAIN_CHAR}\\.)"
_DOMAIN_NAME = f"(?:(?:{_DOMAIN_CHAR}(?:-|{_DOMAIN_CHAR})*)?{_DOMAIN_CHAR}\\.)"
_DOMAIN = f"(?:{_SUBDOMAIN}{{0,126}}{_DOMAIN_NAME}(?:{_TLD}|{_PUNYCODE}))"
_PATH_CHAR = f"[a-zЀ-ӿ0-9!*';:=+,.$/%#\\[\\]\\-–_~@|&{_LATIN_ACCENTS}]"
_BALANCED_PARENS = f"\\((?:{_PATH_CHAR}+|(?:{_PATH_CHAR}*\\({_PATH_CHAR}+\\){_PATH_CHAR}*))\\)"
_PATH_END = f"(?:[+\\-a-zЀ-ӿ0-9=_#/{_LATIN_ACCENTS}]|(?:{_BALANCED_PARENS}))"
_PATH = f"(?:(?:{_PATH_CHAR}*(?:{_BALANCED_PARENS}{_PATH_CHAR}*)*{_PATH_END})|(?:@{_PATH_CHAR}+/))"
_QUERY_CHAR = r"[a-z0-9!?*'@();:&=+$/%#\[\]\-_.,~|]"
_QUERY_END = r"[a-z0-9\-_&=#/]"
_PRECEDING = f"(?:[^A-Za-z0-9@＠$#＃{_INVALID}]|[{_DIRECTIONAL}]|^)"

_URL = re.compile(
    f"(?P<before>{_PRECEDING})"
    f"(?P<url>(?P<protocol>https?://)?(?P<domain>{_DOMAIN})(?::[0-9]+)?"
    f"(?P<path>/{_PATH}*)?(?:\\?{_QUERY_CHAR}*{_QUERY_END})?)",
    re.IGNORECASE,
)
_ASCII_DOMAIN = re.compile(
    f"(?:(?:[\\-a-z0-9{_LATIN_ACCENTS}]+)\\.)+(?:{_TLD}|{_PUNYCODE})", re.IGNORECASE
)
_INVALID_BEFORE_BARE_DOMAIN = re.compile(r"[-_./]$")
_TCO_URL = re.compile(f"^https?://t\\.co/([a-z0-9]+)(?:\\?{_QUERY_CHAR}*{_QUERY_END})?")

_EMOJI_BASE = "[©®‼⁉™ℹ↔-⇿⌀-⏿Ⓜ■-➿⤀-⥿⬀-⯿〰〽㊗㊙\U0001f000-\U0001faff]"
_EMOJI_MODIFIER = "[️\U0001f3fb-\U0001f3ff]"
_EMOJI = re.compile(
    "[\U0001f1e6-\U0001f1ff]{2}"
    "|[0-9#*]️?⃣"
    "|\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f"
    f"|{_EMOJI_BASE}{_EMOJI_MODIFIER}*(?:‍{_EMOJI_BASE}{_EMOJI_MODIFIER}*)*"
)


def x_weighted_length(text: str) -> int:
    """The length X gives `text` when it checks the post limit."""
    normalized = unicodedata.normalize("NFC", text)
    url_ends = _url_spans(normalized)
    # A single code point weighs the same as an emoji or not, so only sequences need a span.
    emoji_ends = {
        m.start(): m.end() for m in _EMOJI.finditer(normalized) if m.end() - m.start() > 1
    }

    units = 0
    index = 0
    while index < len(normalized):
        if index in url_ends:
            units += URL_LENGTH * _SCALE
            index = url_ends[index]
        elif index in emoji_ends:
            units += _DEFAULT_WEIGHT
            index = emoji_ends[index]
        else:
            units += _weight(ord(normalized[index]))
            index += 1
    return units // _SCALE


def _weight(code_point: int) -> int:
    for start, end in _LIGHT_RANGES:
        if start <= code_point <= end:
            return _SCALE
    return _DEFAULT_WEIGHT


def _url_spans(text: str) -> dict[int, int]:
    """Each URL X would shorten, as start index to end index."""
    if "." not in text:
        return {}
    spans: dict[int, int] = {}
    for match in _URL.finditer(text):
        url, protocol, domain = match.group("url"), match.group("protocol"), match.group("domain")
        start, end = match.start("url"), match.end("url")
        if len(protocol or "https://") + len(url) > _MAX_URL_LENGTH:
            continue
        if protocol:
            tco = _TCO_URL.match(url)
            if tco:
                if len(tco.group(1)) > _MAX_TCO_SLUG_LENGTH:
                    continue
                end = start + len(tco.group(0))
            spans[start] = end
            continue
        # Without a protocol, only ASCII domains count, and not right after "-", "_", "." or "/".
        if _INVALID_BEFORE_BARE_DOMAIN.search(match.group("before")):
            continue
        domain_start = match.start("domain")
        last_start = None
        for ascii_domain in _ASCII_DOMAIN.finditer(domain):
            last_start = domain_start + ascii_domain.start()
            spans[last_start] = domain_start + ascii_domain.end()
        if last_start is not None and match.group("path"):
            spans[last_start] = end
    return spans
