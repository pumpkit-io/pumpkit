"""
The fixed numbers and models of writing a Post. They live in code, not settings: the
prompts were tuned against them, so changing one is a code change.
"""

# X's default post limit. A longer Final is flagged, not refused: a premium account's limit is
# larger. The draft prompt interpolates it, which is why it sits apart from the prompts.
POST_MAX_CHARS = 3000

# How many of each Inspiration author's newest stored posts make a Post's corpus.
CORPUS_POSTS_PER_AUTHOR = 20

# Three constants, not aliases, so each call can be re-pointed on its own.
WRITING_MODEL = "openai/gpt-5.6-luna"
HUMANIZING_MODEL = "openai/gpt-5.6-luna"
REVISING_MODEL = "openai/gpt-5.6-luna"

# Sent as max_tokens on every call, as in pumpkit-v6.
MAX_TOKENS = 20000

# Guards against abuse, not product limits.
BRIEF_MAX_CHARS = 200_000
