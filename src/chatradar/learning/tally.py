"""Counting terms of a target class against a background class, with thresholds."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from chatradar.domain.lexicon import LexiconKind, LexiconTerm, TermExample, TermSource, TermStatus
from chatradar.learning.scoring import log_odds_z

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from chatradar.config import LearningSettings
    from chatradar.domain.models import StoredMessage

DOMINANT_LANG_SHARE = 0.8
_REAL_LANGS = frozenset({"ru", "es", "en"})


@dataclass
class TermTally:
    occurrences: int = 0  # messages containing the term
    authors: set[str] = field(default_factory=set[str])
    chats: set[str] = field(default_factory=set[str])
    examples: list[TermExample] = field(default_factory=list[TermExample])
    langs: Counter[str] = field(default_factory=Counter[str])
    first_seen: datetime | None = None
    last_seen: datetime | None = None


@dataclass(frozen=True)
class Scored:
    term: str
    tally: TermTally
    score: float


class Tally:
    """Target-class terms with their evidence, background-class terms as plain counts.

    Callers pass the distinct terms of one message at a time. `bucket` groups terms whose
    counts are comparable (n-grams of one order); class sizes are counted per bucket.
    """

    def __init__(self, max_examples: int) -> None:
        self._max_examples = max_examples
        self._target: dict[str, TermTally] = {}
        self._bucket_of: dict[str, int] = {}
        self._background: Counter[str] = Counter()
        self._target_total: Counter[int] = Counter()
        self._background_total: Counter[int] = Counter()

    def add_target(self, terms: Iterable[str], msg: StoredMessage, bucket: int = 0) -> None:
        """Evidence for each term, and the class grows by one item per term."""
        for term in terms:
            self.note_target(term, msg, bucket)
            self._target_total[bucket] += 1

    def add_background(self, terms: Iterable[str], bucket: int = 0) -> None:
        for term in terms:
            self.note_background(term)
            self._background_total[bucket] += 1

    def count_target(self, bucket: int = 0) -> None:
        """One more item in the target class, without evidence for any term."""
        self._target_total[bucket] += 1

    def count_background(self, bucket: int = 0) -> None:
        self._background_total[bucket] += 1

    def note_background(self, term: str) -> None:
        """Evidence only: the class size is counted separately (`count_background`)."""
        self._background[term] += 1

    def note_target(self, term: str, msg: StoredMessage, bucket: int = 0) -> None:
        """Evidence only: the class size is counted separately (`count_target`)."""
        tally = self._target.setdefault(term, TermTally())
        self._bucket_of[term] = bucket
        tally.occurrences += 1
        if msg.author_id is not None:
            tally.authors.add(f"{msg.source}:{msg.author_id}")
        tally.chats.add(f"{msg.source}:{msg.chat_id}")
        if len(tally.examples) < self._max_examples:
            tally.examples.append(
                TermExample(source=msg.source, chat_id=msg.chat_id, msg_id=msg.msg_id)
            )
        if msg.lang in _REAL_LANGS:
            tally.langs[str(msg.lang)] += 1
        if tally.first_seen is None or msg.date < tally.first_seen:
            tally.first_seen = msg.date
        if tally.last_seen is None or msg.date > tally.last_seen:
            tally.last_seen = msg.date

    @property
    def has_background(self) -> bool:
        return any(self._background_total.values())

    def passing(self, settings: LearningSettings) -> list[Scored]:
        """Terms over every threshold, best score first (ties: more occurrences, then text)."""
        found: list[Scored] = []
        for term, tally in self._target.items():
            if (
                tally.occurrences < settings.min_occurrences
                or len(tally.authors) < settings.min_authors
                or len(tally.chats) < settings.min_chats
            ):
                continue
            bucket = self._bucket_of[term]
            score = log_odds_z(
                tally.occurrences,
                self._background[term],
                self._target_total[bucket],
                self._background_total[bucket],
            )
            if score >= settings.min_score:
                found.append(Scored(term, tally, score))
        found.sort(key=lambda s: (-s.score, -s.tally.occurrences, s.term))
        return found


def dominant_lang(langs: Counter[str]) -> str:
    """The language most of a term's messages are in, or `any` when it is mixed or unknown."""
    total = sum(langs.values())
    if total == 0:
        return "any"
    lang, count = langs.most_common(1)[0]
    return lang if count / total >= DOMINANT_LANG_SHARE else "any"


def to_candidate(kind: LexiconKind, scored: Scored) -> LexiconTerm:
    tally = scored.tally
    return LexiconTerm(
        kind=kind,
        lang=dominant_lang(tally.langs),
        term=scored.term,
        status=TermStatus.CANDIDATE,
        source=TermSource.STATS,
        occurrences=tally.occurrences,
        chats=len(tally.chats),
        authors=len(tally.authors),
        score=round(scored.score, 3),
        examples=tuple(tally.examples),
        first_seen=tally.first_seen,
        last_seen=tally.last_seen,
    )
