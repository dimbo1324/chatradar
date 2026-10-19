from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from chatradar.domain.evaluation import MessageLabel
from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconTerm,
    TermDecision,
    TermExample,
    TermSource,
    TermStatus,
)
from chatradar.domain.models import Source
from chatradar.storage.db.lexicon_repo import SqlLabelRepository, SqlLexiconRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
G = LexiconKind.GRATITUDE


def term(
    text: str,
    *,
    kind: LexiconKind = G,
    lang: str = "any",
    status: TermStatus = TermStatus.CANDIDATE,
    source: TermSource = TermSource.STATS,
    **extra: object,
) -> LexiconTerm:
    return LexiconTerm(kind=kind, lang=lang, term=text, status=status, source=source, **extra)  # type: ignore[arg-type]


@pytest.fixture
def lexicon(engine: AsyncEngine) -> SqlLexiconRepository:
    return SqlLexiconRepository(engine)


@pytest.fixture
def labels(engine: AsyncEngine) -> SqlLabelRepository:
    return SqlLabelRepository(engine)


async def test_empty_lexicon_has_revision_zero(lexicon: SqlLexiconRepository) -> None:
    assert await lexicon.revision() == 0
    snapshot = await lexicon.snapshot()
    assert snapshot.revision == 0
    assert snapshot.entries == {}


async def test_seed_is_idempotent_and_sets_revision_one(lexicon: SqlLexiconRepository) -> None:
    seeded = [term("thanks", lang="ru", status=TermStatus.ACTIVE, source=TermSource.SEED)]

    assert await lexicon.seed(seeded) == 1
    assert await lexicon.seed(seeded) == 0
    assert await lexicon.revision() == 1
    stored = await lexicon.get_term(G, "ru", "thanks")
    assert stored is not None
    assert stored.revision == 1


async def test_seed_never_touches_existing_rows(lexicon: SqlLexiconRepository) -> None:
    active = term("thanks", lang="en", status=TermStatus.ACTIVE, source=TermSource.SEED)
    await lexicon.seed([active])
    await lexicon.decide(G, "en", "thanks", TermDecision.REJECT, by="human")
    revision = await lexicon.revision()

    assert await lexicon.seed([active]) == 0

    stored = await lexicon.get_term(G, "en", "thanks")
    assert stored is not None
    assert stored.status is TermStatus.REJECTED
    assert await lexicon.revision() == revision


async def test_seeding_new_active_terms_into_a_live_lexicon_moves_the_revision(
    lexicon: SqlLexiconRepository,
) -> None:
    await lexicon.seed([term("a", status=TermStatus.ACTIVE, source=TermSource.SEED)])

    await lexicon.seed([term("b", status=TermStatus.ACTIVE, source=TermSource.SEED)])

    assert await lexicon.revision() == 2


async def test_snapshot_has_only_active_terms_sorted(lexicon: SqlLexiconRepository) -> None:
    await lexicon.seed(
        [
            term("zeta", status=TermStatus.ACTIVE),
            term("alpha", status=TermStatus.ACTIVE),
            term("alpha", lang="ru", status=TermStatus.ACTIVE),
            term("pending"),
            term("no", status=TermStatus.REJECTED),
            term("who", kind=LexiconKind.QUESTIONS, status=TermStatus.ACTIVE),
        ]
    )

    snapshot = await lexicon.snapshot()

    assert snapshot.revision == 1
    assert snapshot.entries == {"gratitude": ("alpha", "zeta"), "questions": ("who",)}


async def test_get_term_unknown_is_none(lexicon: SqlLexiconRepository) -> None:
    assert await lexicon.get_term(G, "any", "missing") is None


async def test_term_roundtrip_keeps_examples_and_utc_dates(lexicon: SqlLexiconRepository) -> None:
    example = TermExample(source=Source.TELEGRAM, chat_id="-100", msg_id="7")
    original = term(
        "good morning",
        weight=2.0,
        occurrences=5,
        chats=2,
        authors=3,
        score=4.5,
        examples=(example,),
        first_seen=NOW,
        last_seen=NOW + timedelta(days=1),
        note="n",
    )
    await lexicon.upsert_candidates([original])

    stored = await lexicon.get_term(G, "any", "good morning")

    assert stored == original
    assert stored is not None
    assert stored.first_seen is not None
    assert stored.first_seen.tzinfo is not None
    assert stored.first_seen.utcoffset() == timedelta(0)


async def test_list_terms_filters_orders_and_pages(lexicon: SqlLexiconRepository) -> None:
    await lexicon.upsert_candidates(
        [
            term("a", score=1.0, occurrences=30, last_seen=NOW),
            term("b", score=3.0, occurrences=10, last_seen=NOW + timedelta(days=2)),
            term("c", score=2.0, occurrences=20),
            term("d", lang="ru", score=9.0, occurrences=1, last_seen=NOW + timedelta(days=1)),
            term("e", kind=LexiconKind.QUESTIONS, score=5.0),
        ]
    )
    await lexicon.decide(G, "any", "a", TermDecision.ACCEPT, by="human")

    def names(page_items: list[LexiconTerm]) -> list[str]:
        return [t.term for t in page_items]

    by_score = await lexicon.list_terms(kind=G)
    assert names(by_score.items) == ["d", "b", "c", "a"]
    assert by_score.total == 4

    by_occurrences = await lexicon.list_terms(kind=G, order="occurrences")
    assert names(by_occurrences.items) == ["a", "c", "b", "d"]

    recent = await lexicon.list_terms(kind=G, order="recent")
    assert names(recent.items) == ["b", "d", "a", "c"]

    assert names((await lexicon.list_terms(status=TermStatus.ACTIVE)).items) == ["a"]
    assert names((await lexicon.list_terms(lang="ru")).items) == ["d"]

    page = await lexicon.list_terms(kind=G, limit=2, offset=1)
    assert names(page.items) == ["b", "c"]
    assert (page.total, page.limit, page.offset) == (4, 2, 1)


async def test_upsert_candidates_inserts_new_and_refreshes_only_statistics(
    lexicon: SqlLexiconRepository,
) -> None:
    await lexicon.seed([term("kept", status=TermStatus.ACTIVE, source=TermSource.SEED)])
    await lexicon.decide(G, "any", "kept", TermDecision.REJECT, by="human", note="no")
    revision = await lexicon.revision()
    example = TermExample(source=Source.TELEGRAM, chat_id="-1", msg_id="1")

    inserted, refreshed = await lexicon.upsert_candidates(
        [
            term("kept", occurrences=9, chats=4, authors=5, score=7.0, examples=(example,)),
            term("fresh", occurrences=3),
        ]
    )

    assert (inserted, refreshed) == (1, 1)
    kept = await lexicon.get_term(G, "any", "kept")
    assert kept is not None
    assert (kept.occurrences, kept.chats, kept.authors, kept.score) == (9, 4, 5, 7.0)
    assert kept.examples == (example,)
    assert kept.status is TermStatus.REJECTED
    assert kept.source is TermSource.SEED
    assert kept.note == "no"
    assert kept.decided_by == "human"
    assert await lexicon.revision() == revision
    assert await lexicon.upsert_candidates([term("fresh", occurrences=4)]) == (0, 1)


async def test_decide_moves_the_revision_only_when_the_active_set_changes(
    lexicon: SqlLexiconRepository,
) -> None:
    await lexicon.seed([term("seed", status=TermStatus.ACTIVE, source=TermSource.SEED)])
    await lexicon.upsert_candidates([term("cand"), term("other")])
    assert await lexicon.revision() == 1

    rejected = await lexicon.decide(G, "any", "cand", TermDecision.REJECT, by="human")
    assert await lexicon.revision() == 1
    assert rejected.status is TermStatus.REJECTED

    accepted = await lexicon.decide(G, "any", "cand", TermDecision.ACCEPT, by="human", note="ok")
    assert await lexicon.revision() == 2
    assert accepted.status is TermStatus.ACTIVE
    assert accepted.revision == 2
    assert accepted.note == "ok"
    assert accepted.decided_by == "human"
    assert accepted.decided_at is not None
    assert accepted.decided_at.utcoffset() == timedelta(0)

    again = await lexicon.decide(G, "any", "cand", TermDecision.ACCEPT, by="human")
    assert await lexicon.revision() == 2
    assert again.status is TermStatus.ACTIVE

    await lexicon.decide(G, "any", "cand", TermDecision.RESET, by="human")
    assert await lexicon.revision() == 3
    assert (await lexicon.snapshot()).entries == {"gratitude": ("seed",)}


async def test_decide_unknown_term_raises_key_error(lexicon: SqlLexiconRepository) -> None:
    with pytest.raises(KeyError):
        await lexicon.decide(G, "any", "nope", TermDecision.ACCEPT, by="human")


async def test_add_term_active_moves_revision_and_existing_is_returned_unchanged(
    lexicon: SqlLexiconRepository,
) -> None:
    await lexicon.seed([term("seed", status=TermStatus.ACTIVE, source=TermSource.SEED)])

    added = await lexicon.add_term(term("mine", status=TermStatus.ACTIVE, source=TermSource.HUMAN))
    assert added.revision == 2
    assert await lexicon.revision() == 2

    candidate = await lexicon.add_term(term("maybe", source=TermSource.AI))
    assert candidate.status is TermStatus.CANDIDATE
    assert await lexicon.revision() == 2

    clash = await lexicon.add_term(term("mine", status=TermStatus.REJECTED))
    assert clash.status is TermStatus.ACTIVE
    assert await lexicon.revision() == 2


async def test_mark_dormant_only_old_active_terms_of_the_given_sources(
    lexicon: SqlLexiconRepository,
) -> None:
    cutoff = NOW
    old = NOW - timedelta(days=100)
    await lexicon.seed(
        [
            term("old mined", status=TermStatus.ACTIVE, last_seen=old),
            term("fresh mined", status=TermStatus.ACTIVE, last_seen=NOW + timedelta(days=1)),
            term("never seen", status=TermStatus.ACTIVE),
            term("old human", status=TermStatus.ACTIVE, source=TermSource.HUMAN, last_seen=old),
            term("old candidate", last_seen=old),
        ]
    )
    revision = await lexicon.revision()

    count = await lexicon.mark_dormant(last_seen_before=cutoff, sources=[TermSource.STATS])

    assert count == 1
    dormant = await lexicon.get_term(G, "any", "old mined")
    assert dormant is not None
    assert dormant.status is TermStatus.DORMANT
    assert await lexicon.revision() == revision + 1
    assert (await lexicon.snapshot()).entries == {
        "gratitude": ("fresh mined", "never seen", "old human")
    }
    assert await lexicon.mark_dormant(last_seen_before=cutoff, sources=[TermSource.STATS]) == 0
    assert await lexicon.revision() == revision + 1


async def test_summary_counts_and_pending_apply(
    lexicon: SqlLexiconRepository, labels: SqlLabelRepository
) -> None:
    await lexicon.seed(
        [
            term("t", status=TermStatus.ACTIVE, source=TermSource.SEED),
            term("q", kind=LexiconKind.QUESTIONS, status=TermStatus.ACTIVE),
            term("c"),
        ]
    )

    summary = await lexicon.summary()

    assert summary.revision == 1
    assert summary.applied == {"noise": 0, "enrich": 0}
    assert summary.pending_apply is True
    assert summary.by_status == {"candidate": 1, "active": 2, "rejected": 0, "dormant": 0}
    assert summary.by_kind["gratitude"] == {
        "candidate": 1,
        "active": 1,
        "rejected": 0,
        "dormant": 0,
    }
    assert summary.by_kind["spam_offers"]["active"] == 0
    assert summary.labels == 0

    await lexicon.set_applied_revision("noise", 1)
    assert (await lexicon.summary()).pending_apply is True
    await lexicon.set_applied_revision("enrich", 1)
    done = await lexicon.summary()
    assert done.pending_apply is False
    assert done.applied == {"noise": 1, "enrich": 1}

    await labels.save_label(_label("1"))
    assert (await lexicon.summary()).labels == 1


async def test_applied_revision_defaults_to_zero_and_can_be_overwritten(
    lexicon: SqlLexiconRepository,
) -> None:
    assert await lexicon.applied_revision("noise") == 0

    await lexicon.set_applied_revision("noise", 3)
    await lexicon.set_applied_revision("noise", 5)

    assert await lexicon.applied_revision("noise") == 5
    assert await lexicon.applied_revision("enrich") == 0


def _label(msg_id: str, *, minutes: int = 0, is_noise: bool = True) -> MessageLabel:
    return MessageLabel(
        source=Source.TELEGRAM,
        chat_id="-100",
        msg_id=msg_id,
        is_noise=is_noise,
        reason="gratitude" if is_noise else None,
        created_at=NOW + timedelta(minutes=minutes),
    )


async def test_labels_upsert_by_key_and_list_newest_first(labels: SqlLabelRepository) -> None:
    await labels.save_label(_label("1", minutes=0))
    await labels.save_label(_label("2", minutes=5))
    await labels.save_label(_label("3", minutes=3))

    assert [lab.msg_id for lab in await labels.list_labels()] == ["2", "3", "1"]
    assert [lab.msg_id for lab in await labels.list_labels(limit=2)] == ["2", "3"]
    assert await labels.count_labels() == 3

    await labels.save_label(_label("1", minutes=10, is_noise=False))

    listed = await labels.list_labels()
    assert [lab.msg_id for lab in listed] == ["1", "2", "3"]
    assert listed[0].is_noise is False
    assert listed[0].reason is None
    assert listed[0].created_at == NOW + timedelta(minutes=10)
    assert listed[0].created_at.utcoffset() == timedelta(0)
    assert await labels.count_labels() == 3


async def test_empty_labels(labels: SqlLabelRepository) -> None:
    assert await labels.list_labels() == []
    assert await labels.count_labels() == 0
