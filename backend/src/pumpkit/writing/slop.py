"""
Find the machine-written tells in a Final, ported from pumpkit-v6.

A smoke alarm, not a judge: it reports what it saw so the User can decide whether to ask for a
change. Every pattern was found in real output from the v6 pipeline.
"""

import re

# (name, compiled pattern, what it looks like) - the third element is what gets
# printed, so it has to name the shape rather than restate the regex.
PATTERNS = (
    (
        "em_dash",
        re.compile(r"—"),
        "em dash",
    ),
    (
        "curly_quote",
        re.compile(r"[‘’“”]"),
        "curly quote",
    ),
    (
        "correction_pivot",
        re.compile(
            r"\b(?:it'?s|its|that'?s)\s+not\s+\w[\w\s]{0,30}?,\s*it'?s\b"
            r"|\bnot\s+(?:just|only)\s+\w[\w\s]{0,30}?,\s*(?:it'?s|but)\b"
            r"|\bthe\s+(?:interesting|real|important)\s+(?:part|thing|story)\s+"
            r"(?:isn'?t|is not)\b"
            r"|\bisn'?t\s+(?:even\s+)?the\s+(?:most\s+)?"
            r"(?:interesting|important|real)\b",
            re.IGNORECASE,
        ),
        "correction pivot (\"it's not X, it's Y\" and its disguises)",
    ),
    (
        "named_lesson",
        re.compile(
            r"\b(?:the\s+(?:real\s+)?lesson|the\s+takeaway|what\s+this\s+shows|"
            r"the\s+pattern\s+here|the\s+insight\s+here)\b",
            re.IGNORECASE,
        ),
        "announcing the lesson instead of stating it",
    ),
    (
        "invented_stance",
        re.compile(
            r"\b(?:i\s+keep\s+saying|i'?ve\s+been\s+saying|i\s+keep\s+coming\s+back\s+to|"
            r"i\s+always\s+say)\b",
            re.IGNORECASE,
        ),
        "invented recurring opinion",
    ),
    (
        "startup_cliche",
        re.compile(
            r"\b(?:unfair\s+advantage|moat|flywheel|secret\s+sauce|the\s+playbook|"
            r"productiz(?:e|ed|ing)|leverage|at\s+scale|10x|north\s+star)\b",
            re.IGNORECASE,
        ),
        "startup-commentary cliche",
    ),
    (
        "hedge_stack",
        re.compile(
            r"\b(?:it'?s\s+worth\s+noting|it\s+is\s+important\s+to\s+note|"
            r"generally\s+speaking|in\s+many\s+cases|that\s+said,)\b",
            re.IGNORECASE,
        ),
        "hedge stack",
    ),
)

# "a, b and c" / "a, b, and c" where each item is one to three words. Loose on
# purpose: a triple is a rhythm, and the rhythm is what reads as generated.
TRIPLE = re.compile(
    r"\b(\w+(?:\s+\w+){0,2}),\s+(\w+(?:\s+\w+){0,2}),?\s+and\s+(\w+(?:\s+\w+){0,2})\b"
)


def find(text: str) -> list[tuple[str, str]]:
    """Every tell in one post, as a list of (name, description) pairs.

    Order follows PATTERNS so two replies with the same tells report them the
    same way, which is what makes the counts comparable between runs.
    """
    hits = [(name, description) for name, pattern, description in PATTERNS if pattern.search(text)]
    if TRIPLE.search(text):
        hits.append(("list_of_three", "balanced list of three"))
    return hits
