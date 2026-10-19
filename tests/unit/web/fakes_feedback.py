"""In-memory lexicon, label and message repositories for the feedback API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from chatradar.domain.evaluation import ClassMetrics, EvalReport
from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconSummary,
    LexiconTerm,
    TermDecision,
    TermPage,
    TermStatus,
)
from chatradar.services.feedback import FeedbackServices
from chatradar.services.queries import ReadServices
from tests.unit.web.fakes import STAGES, FakeQueries, FakeSearch, sample_data

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chatradar.domain.evaluation import MessageLabel
    from chatradar.domain.models import MessageKey, StoredMessage
    from chatradar.domain.ports import (
        LabelRepository,
        LexiconRepository,
        MessageRepository,
        TermOrder,
    )

DECIDED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
STATUS_AFTER = {
    TermDecision.ACCEPT: TermStatus.ACTIVE,
    TermDecision.REJECT: TermStatus.REJECTED,
    TermDecision.RESET: TermStatus.CANDIDATE,
}


class FakeLexicon:
    def __init__(self, terms: Sequence[LexiconTerm]) -> None:
        self.terms = {term.key: term for term in terms}
        self.list_calls: list[dict[str, Any]] = []
        self.decide_calls: list[tuple[Any, ...]] = []

    async def list_terms(
        self,
        *,
        kind: LexiconKind | None = None,
        status: TermStatus | None = None,
        lang: str | None = None,
        order: TermOrder = "score",
        limit: int = 100,
        offset: int = 0,
    ) -> TermPage:
        self.list_calls.append(
            {
                "kind": kind,
                "status": status,
                "lang": lang,
                "order": order,
                "limit": limit,
                "offset": offset,
            }
        )
        items = [
            term
            for term in self.terms.values()
            if (kind is None or term.kind == kind)
            and (status is None or term.status == status)
            and (lang is None or term.lang == lang)
        ]
        return TermPage(
            items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
        )

    async def decide(
        self,
        kind: LexiconKind,
        lang: str,
        term: str,
        decision: TermDecision,
        *,
        by: str,
        note: str | None = None,
    ) -> LexiconTerm:
        self.decide_calls.append((kind, lang, term, decision, by, note))
        current = self.terms[(kind, lang, term)]
        decided = current.model_copy(
            update={
                "status": STATUS_AFTER[decision],
                "decided_by": by,
                "decided_at": DECIDED_AT,
                "note": note,
            }
        )
        self.terms[decided.key] = decided
        return decided

    async def summary(self) -> LexiconSummary:
        counts: dict[str, int] = {}
        for term in self.terms.values():
            counts[term.status.value] = counts.get(term.status.value, 0) + 1
        return LexiconSummary(
            revision=3,
            applied={"noise": 2},
            pending_apply=True,
            by_status=counts,
            by_kind={},
            labels=0,
        )


class FakeLabels:
    def __init__(self) -> None:
        self.saved: list[MessageLabel] = []
        self.list_limits: list[int | None] = []

    async def save_label(self, label: MessageLabel) -> None:
        self.saved.append(label)

    async def list_labels(self, limit: int | None = None) -> list[MessageLabel]:
        self.list_limits.append(limit)
        return list(reversed(self.saved))[:limit]

    async def count_labels(self) -> int:
        return len(self.saved)


class FakeMessages:
    def __init__(self, messages: Sequence[StoredMessage]) -> None:
        self.by_key = {(m.source, m.chat_id, m.msg_id): m for m in messages}

    async def get_many(self, keys: Sequence[MessageKey]) -> dict[MessageKey, StoredMessage]:
        return {key: self.by_key[key] for key in keys if key in self.by_key}


def make_term(
    term: str, *, kind: LexiconKind = LexiconKind.GRATITUDE, lang: str = "ru"
) -> LexiconTerm:
    return LexiconTerm(kind=kind, lang=lang, term=term, occurrences=5, chats=2, score=2.5)


def empty_report() -> EvalReport:
    metrics = ClassMetrics(
        label="noise", support=0, tp=0, fp=0, fn=0, precision=0.0, recall=0.0, f1=0.0
    )
    return EvalReport(
        source="human-labels",
        total=0,
        missing=0,
        noise=metrics,
        reasons=[],
        question=metrics.model_copy(update={"label": "question"}),
        language_total=0,
        language_accuracy=None,
        stage_versions={"noise": 1},
        lexicon_revision=3,
    )


def build_read(
    messages: Sequence[StoredMessage], lexicon: FakeLexicon, labels: FakeLabels, report: EvalReport
) -> tuple[ReadServices, FeedbackServices]:
    chats, _, threads = sample_data()
    queries = FakeQueries(chats, messages, threads)
    store = FakeMessages(messages)

    async def quality() -> EvalReport:
        return report

    read = ReadServices(
        queries=queries,
        search_index=FakeSearch(queries),
        stage_versions=STAGES,
        lexicon=cast("LexiconRepository", lexicon),
        labels=cast("LabelRepository", labels),
        message_store=cast("MessageRepository", store),
        quality_report=quality,
    )
    return read, FeedbackServices(
        lexicon=cast("LexiconRepository", lexicon),
        labels=cast("LabelRepository", labels),
        messages=cast("MessageRepository", store),
    )


class FeedbackKit:
    def __init__(self, messages: Sequence[StoredMessage] | None = None) -> None:
        self.lexicon = FakeLexicon([make_term("thanks"), make_term("gracias", lang="es")])
        self.labels = FakeLabels()
        self.read, self.feedback = build_read(
            sample_data()[1] if messages is None else messages,
            self.lexicon,
            self.labels,
            empty_report(),
        )


def bare_read() -> ReadServices:
    """`ReadServices` without the optional lexicon, label, message and quality services."""
    queries = FakeQueries(*sample_data())
    return ReadServices(queries=queries, search_index=FakeSearch(queries), stage_versions=STAGES)
