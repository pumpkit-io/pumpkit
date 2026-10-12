"""
The fixed numbers of writing a Post. They live in code, not settings: the prompts were tuned
against them, so changing one is a code change. The models are settings (`LLM_*_MODEL`).
"""

# X's default post limit. A longer Final is flagged, not refused: a premium account's limit is
# larger. The draft prompt interpolates it, which is why it sits apart from the prompts.
POST_MAX_CHARS = 3000

# How many of each Inspiration author's newest stored posts make a Post's corpus.
CORPUS_POSTS_PER_AUTHOR = 20

# Sent as max_tokens on every call, as in pumpkit-v6.
MAX_TOKENS = 20000

# How long the provider keeps each system prompt cached. A one-hour write costs twice the
# normal rate and a hit about a tenth, so it pays off from the third call within the hour.
CACHE_TTL = "1h"

# Guards against abuse, not product limits.
BRIEF_MAX_CHARS = 200_000
FEEDBACK_MAX_CHARS = 100_000
