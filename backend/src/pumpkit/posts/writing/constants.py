"""
The fixed numbers of writing a Post. They live in code, not settings: the prompts were tuned
against them, so changing one is a code change. The models are settings (`LLM_*_MODEL`).
"""

from pumpkit.posts.writing.post_replies import HookType

# How many Parts a written Thread may have. The Thread prompts state it and a reply outside it
# fails the attempt, so writing costs and the risk of a Thread stopping partway stay bounded.
THREAD_MIN_PARTS = 2
THREAD_MAX_PARTS = 10

# Sent as max_tokens on every call, as in pumpkit-v6.
MAX_TOKENS = 20000

# How long the provider keeps each system prompt cached. A one-hour write costs twice the
# normal rate and a hit about a tenth, so it pays off from the third call within the hour.
CACHE_TTL = "1h"

# Guards against abuse, not product limits.
BRIEF_MAX_CHARS = 200_000
FEEDBACK_MAX_CHARS = 100_000

# The most split Ideas kept from one Brief. The plan prompt states it.
MAX_SPLIT_IDEAS = 5

# How many sketches a single post's first Version is merged from.
SKETCHES_PER_POST = 5

# The hook type each sketch is asked to try first, in order, so the merge has distinct hooks to pick from.
HOOK_TYPE_ROTATION: tuple[HookType, ...] = (
    "proof",
    "curiosity_gap",
    "contrarian",
    "clear_outcome",
    "story",
    "bold_claim",
    "number_list",
    "callout",
)
