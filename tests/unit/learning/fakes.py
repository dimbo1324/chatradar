"""In-memory stand-ins for the lexicon and label repositories and the message scanner,
following the port docstrings, plus a paging scanner over `QueryRepository.list_messages`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconSnapshot,
    LexiconSummary,
    LexiconTerm,
    TermDecision,
    TermPage,
    TermSource,
    TermStatus,
    next_status,
)
from chatradar.domain.models import MediaType, MessageFilter, Source, StoredMessage
from chatradar.domain.text import content_hash

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from chatradar.domain.evaluation import MessageLabel
    from chatradar.domain.ports import QueryRepository, TermOrder

CHAT = "-100900"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def make_message(
    msg_id: int | str,
    text: str,
    *,
    author: str | None = "u1",
    chat: str = CHAT,
    days_ago: float = 1,
    media: MediaType = MediaType.NONE,
    **stored: Any,
) -> StoredMessage:
    return StoredMessage.model_validate(
        {
            "source": Source.TELEGRAM,
            "chat_id": chat,
            "msg_id": str(msg_id),
            "author_id": author,
            "date": NOW - timedelta(days=days_ago),
            "text": text,
            "text_raw": text,
            "media_type": media,
            "content_hash": content_hash(text_raw=text, media_type=media.value, reply_to=None),
            **stored,
        }
    )


class FakeScanner:
    def __init__(self, messages: Sequence[StoredMessage]) -> None:
        self.messages = list(messages)

    async def iter_all(self, batch_size: int = 2000) -> AsyncIterator[list[StoredMessage]]:
        for start in range(0, len(self.messages), batch_size):
            yield self.messages[start : start + batch_size]


class PagingScanner:
    """A `MessageScanner` over `QueryRepository.list_messages`, for corpus tests."""

    def __init__(self, queries: QueryRepository) -> None:
        self._queries = queries

    async def iter_all(self, batch_size: int = 500) -> AsyncIterator[list[StoredMessage]]:
        offset = 0
        while True:
            page = await self._queries.list_messages(MessageFilter(limit=batch_size, offset=offset))
            if not page.items:
                return
            yield page.items
            offset += batch_size


class FakeLabels:
    def __init__(self, labels: Sequence[MessageLabel] = ()) -> None:
        self.labels = {label.key: label for label in labels}

    async def save_label(self, label: MessageLabel) -> None:
        self.labels[label.key] = label

    async def list_labels(self, limit: int | None = None) -> list[MessageLabel]:
        return list(self.labels.values())[:limit]

    async def count_labels(self) -> int:
        return len(self.labels)


class FakeLexicon:
    """Mining-relevant behavior of `LexiconRepository`; the rest is minimal."""

    def __init__(self, terms: Sequence[LexiconTerm] = ()) -> None:
        self.terms: dict[tuple[LexiconKind, str, str], LexiconTerm] = {t.key: t for t in terms}
        self.revision_number = 1
        self.dormant_calls: list[tuple[datetime, list[TermSource]]] = []
        self.upsert_calls: list[list[LexiconTerm]] = []

    async def seed(self, terms: Sequence[LexiconTerm]) -> int:
        added = [t for t in terms if t.key not in self.terms]
        self.terms |= {t.key: t for t in added}
        return len(added)

    async def snapshot(self) -> LexiconSnapshot:
        return LexiconSnapshot(revision=self.revision_number)

    async def revision(self) -> int:
        return self.revision_number

    async def get_term(self, kind: LexiconKind, lang: str, term: str) -> LexiconTerm | None:
        return self.terms.get((kind, lang, term))

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
        found = [
            t
            for t in self.terms.values()
            if (kind is None or t.kind is kind)
            and (status is None or t.status is status)
            and (lang is None or t.lang == lang)
        ]
        return TermPage(
            items=found[offset : offset + limit], total=len(found), limit=limit, offset=offset
        )

    async def upsert_candidates(self, terms: Sequence[LexiconTerm]) -> tuple[int, int]:
        self.upsert_calls.append(list(terms))
        inserted = refreshed = 0
        for term in terms:
            existing = self.terms.get(term.key)
            if existing is None:
                self.terms[term.key] = term
                inserted += 1
                continue
            self.terms[term.key] = existing.model_copy(
                update={
                    "occurrences": term.occurrences,
                    "chats": term.chats,
                    "authors": term.authors,
                    "score": term.score,
                    "examples": term.examples,
                    "last_seen": term.last_seen,
                }
            )
            refreshed += 1
        return inserted, refreshed

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
        old = self.terms[(kind, lang, term)]
        new = old.model_copy(
            update={"status": next_status(decision), "decided_by": by, "note": note}
        )
        self.terms[new.key] = new
        return new

    async def add_term(self, term: LexiconTerm) -> LexiconTerm:
        return self.terms.setdefault(term.key, term)

    async def mark_dormant(
        self, *, last_seen_before: datetime, sources: Sequence[TermSource]
    ) -> int:
        self.dormant_calls.append((last_seen_before, list(sources)))
        count = 0
        for key, term in list(self.terms.items()):
            if (
                term.status is TermStatus.ACTIVE
                and term.source in sources
                and term.last_seen is not None
                and term.last_seen < last_seen_before
            ):
                self.terms[key] = term.model_copy(update={"status": TermStatus.DORMANT})
                count += 1
        return count

    async def summary(self) -> LexiconSummary:
        return LexiconSummary(
            revision=self.revision_number,
            applied={},
            pending_apply=False,
            by_status={},
            by_kind={},
            labels=0,
        )

    async def applied_revision(self, stage: str) -> int:
        return 0

    async def set_applied_revision(self, stage: str, revision: int) -> None:
        return None
