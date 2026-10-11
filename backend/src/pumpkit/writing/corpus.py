"""A Post's corpus: the author posts whose writing style both calls are handed."""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CorpusPost:
    post_id: str
    handle: str
    text: str


@dataclass(frozen=True)
class CorpusGroup:
    """One Inspiration author's posts, newest first."""

    handle: str
    texts: tuple[str, ...]


@dataclass(frozen=True)
class Corpus:
    groups: tuple[CorpusGroup, ...]
    # What the Post stores, so later Versions read the same posts whatever the authors become.
    post_ids: tuple[str, ...]


def group_corpus(posts: Sequence[CorpusPost]) -> Corpus:
    """Group posts already in corpus order (by author, newest first) into one block per author."""
    groups: list[CorpusGroup] = []
    for post in posts:
        if groups and groups[-1].handle == post.handle:
            last = groups[-1]
            groups[-1] = CorpusGroup(handle=last.handle, texts=(*last.texts, post.text))
        else:
            groups.append(CorpusGroup(handle=post.handle, texts=(post.text,)))
    return Corpus(groups=tuple(groups), post_ids=tuple(post.post_id for post in posts))
