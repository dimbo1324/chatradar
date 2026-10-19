"""The learning lexicon: terms the rule stages use, candidates mined around them, and the
pure rules for moving between statuses.

A term is a phrase for one purpose (`LexiconKind`). The built-in lists seed it; statistics
propose candidates; a human accepts or rejects them; AI can later be one more proposer.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from chatradar.domain.models import Source


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LexiconKind(StrEnum):
    """What a term is for. Values equal the seed file names in `resources/lexicons/`."""

    GRATITUDE = "gratitude"  # a whole message that only thanks or agrees (noise)
    SPAM_OFFERS = "spam_offers"  # easy-money offers, matched inside text
    SPAM_CONTACTS = "spam_contacts"  # "write me privately" phrases, matched inside text
    QUESTIONS = "questions"  # question words
    QUESTION_PHRASES = "question_phrases"  # "does anyone know" style openers


class TermStatus(StrEnum):
    CANDIDATE = "candidate"  # proposed (by statistics or AI), waiting for a decision
    ACTIVE = "active"  # used by the pipeline
    REJECTED = "rejected"  # a human said no; never proposed again
    DORMANT = "dormant"  # was active, not seen for a long time; not used until it returns


class TermSource(StrEnum):
    SEED = "seed"  # the built-in lists
    STATS = "stats"  # mined from the corpus
    AI = "ai"  # proposed by a model (later)
    HUMAN = "human"  # added by hand


class TermDecision(StrEnum):
    ACCEPT = "accept"  # any status → active
    REJECT = "reject"  # any status → rejected
    RESET = "reset"  # any status → candidate (back to the queue)


type TermKey = tuple[LexiconKind, str, str]
"""(kind, lang, term) — the identity of a term. `lang` is `any` when not language-specific."""


class TermExample(_Frozen):
    """Where a term was seen, so a human can read it in context. Never the text itself."""

    source: Source
    chat_id: str
    msg_id: str


class LexiconTerm(_Frozen):
    kind: LexiconKind
    lang: str = "any"
    term: str = Field(min_length=1, max_length=200)  # folded phrase, or as written for symbols
    status: TermStatus = TermStatus.CANDIDATE
    source: TermSource = TermSource.STATS
    weight: float = Field(default=1.0, ge=0)
    occurrences: int = Field(default=0, ge=0)
    chats: int = Field(default=0, ge=0)  # distinct chats it was seen in
    authors: int = Field(default=0, ge=0)  # distinct authors (a count, never ids)
    score: float = 0.0  # log-odds z-score against the background (see `learning/`)
    examples: tuple[TermExample, ...] = ()
    first_seen: AwareDatetime | None = None
    last_seen: AwareDatetime | None = None
    decided_at: AwareDatetime | None = None
    decided_by: str | None = None
    note: str | None = None
    revision: int = 0  # lexicon revision at which the status last changed

    @property
    def key(self) -> TermKey:
        return (self.kind, self.lang, self.term)


class TermPage(_Frozen):
    items: list[LexiconTerm]
    total: int
    limit: int
    offset: int


class LexiconSnapshot(_Frozen):
    """The ACTIVE terms at one revision: an immutable input for the rule stages."""

    revision: int
    entries: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # kind value → terms

    def terms(self, kind: LexiconKind) -> tuple[str, ...]:
        return self.entries.get(kind.value, ())


class LexiconSummary(_Frozen):
    revision: int
    applied: dict[str, int]  # stage → revision the stage last processed with
    pending_apply: bool  # some stage still runs on an older revision
    by_status: dict[str, int]
    by_kind: dict[str, dict[str, int]]  # kind → status → count
    labels: int  # human labels collected so far


class MiningReport(_Frozen):
    messages: int  # messages scanned
    new_candidates: int
    refreshed: int  # existing terms whose statistics were updated
    dormant: int  # active mined terms put to sleep
    by_kind: dict[str, int]  # new candidates per kind
    duration_ms: int


NOISE_LEXICON_KINDS: tuple[LexiconKind, ...] = (
    LexiconKind.GRATITUDE,
    LexiconKind.SPAM_OFFERS,
    LexiconKind.SPAM_CONTACTS,
)
QUESTION_LEXICON_KINDS: tuple[LexiconKind, ...] = (
    LexiconKind.QUESTIONS,
    LexiconKind.QUESTION_PHRASES,
)
STAGE_LEXICON_KINDS: dict[str, tuple[LexiconKind, ...]] = {
    "noise": NOISE_LEXICON_KINDS,
    "enrich": QUESTION_LEXICON_KINDS,
}
"""Stages that read the lexicon. A revision change makes them reprocess (see `process`)."""

_TARGET: dict[TermDecision, TermStatus] = {
    TermDecision.ACCEPT: TermStatus.ACTIVE,
    TermDecision.REJECT: TermStatus.REJECTED,
    TermDecision.RESET: TermStatus.CANDIDATE,
}


def next_status(decision: TermDecision) -> TermStatus:
    """The status a decision leads to, whatever the current one is (every move is allowed)."""
    return _TARGET[decision]


def changes_active_set(old: TermStatus, new: TermStatus) -> bool:
    """Whether the pipeline's view of the lexicon changes, i.e. the revision must move."""
    return (old is TermStatus.ACTIVE) != (new is TermStatus.ACTIVE)
