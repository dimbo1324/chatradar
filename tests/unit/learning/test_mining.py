from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconTerm,
    TermDecision,
    TermSource,
    TermStatus,
)
from chatradar.services.learning import mine_candidates
from tests.unit.learning.fakes import NOW, FakeLabels, FakeLexicon, FakeScanner
from tests.unit.learning.test_generators import SETTINGS, background, label, spam_messages

if TYPE_CHECKING:
    from chatradar.config import LearningSettings
    from chatradar.domain.evaluation import MessageLabel
    from chatradar.domain.lexicon import MiningReport
    from chatradar.domain.models import StoredMessage


def corpus() -> list[StoredMessage]:
    return [*background(300), *spam_messages("Earn five hundred weekly, write me in DM", 8)]


async def run(
    lexicon: FakeLexicon,
    messages: list[StoredMessage],
    labels: list[MessageLabel] | None = None,
    settings: LearningSettings = SETTINGS,
) -> MiningReport:
    return await mine_candidates(
        settings,
        scanner=FakeScanner(messages),
        lexicon=lexicon,
        labels=FakeLabels(labels or []),
        now=NOW,
    )


def active_term(term: str, *, source: TermSource, days_ago: float) -> LexiconTerm:
    return LexiconTerm(
        kind=LexiconKind.SPAM_OFFERS,
        term=term,
        status=TermStatus.ACTIVE,
        source=source,
        last_seen=NOW - timedelta(days=days_ago),
    )


async def test_mining_inserts_candidates_and_reports() -> None:
    lexicon = FakeLexicon()

    report = await run(lexicon, corpus())

    assert report.messages == 308
    assert report.new_candidates == len(lexicon.terms) > 0
    assert report.refreshed == 0
    assert report.dormant == 0
    assert report.by_kind["spam_offers"] > 0
    assert report.by_kind["spam_contacts"] > 0
    assert sum(report.by_kind.values()) == report.new_candidates
    assert all(t.status is TermStatus.CANDIDATE for t in lexicon.terms.values())
    assert all(t.source is TermSource.STATS for t in lexicon.terms.values())
    assert report.duration_ms >= 0


async def test_second_run_is_idempotent() -> None:
    lexicon = FakeLexicon()
    await run(lexicon, corpus())
    first = dict(lexicon.terms)

    report = await run(lexicon, corpus())

    assert report.new_candidates == 0
    assert report.refreshed == len(first)
    assert report.by_kind == {}
    assert lexicon.terms == first


async def test_a_rejected_twin_stays_rejected_and_is_refreshed() -> None:
    lexicon = FakeLexicon()
    await run(lexicon, corpus())
    earn = next(t for t in lexicon.terms.values() if t.term == "earn")
    await lexicon.decide(earn.kind, earn.lang, earn.term, TermDecision.REJECT, by="owner")

    report = await run(lexicon, [*corpus(), *spam_messages("earn", 3, start=9000)])

    twin = lexicon.terms[earn.key]
    assert twin.status is TermStatus.REJECTED
    assert twin.decided_by == "owner"
    assert twin.occurrences == earn.occurrences + 3
    assert "spam_offers" not in report.by_kind


async def test_mining_never_changes_the_active_set() -> None:
    seed = active_term("earn", source=TermSource.SEED, days_ago=0)
    lexicon = FakeLexicon([seed])

    await run(lexicon, corpus())

    assert lexicon.terms[seed.key].status is TermStatus.ACTIVE
    assert lexicon.revision_number == 1
    assert lexicon.terms[seed.key].occurrences > 0


async def test_dormancy_covers_only_unseen_mined_active_terms() -> None:
    stale_mined = active_term("old phrase", source=TermSource.STATS, days_ago=400)
    stale_seed = active_term("old seed", source=TermSource.SEED, days_ago=400)
    seen_mined = active_term("earn", source=TermSource.STATS, days_ago=400)
    lexicon = FakeLexicon([stale_mined, stale_seed, seen_mined])

    report = await run(lexicon, corpus())

    assert lexicon.dormant_calls == [
        (NOW - timedelta(days=SETTINGS.dormant_after_days), [TermSource.STATS])
    ]
    assert report.dormant == 1
    assert lexicon.terms[stale_mined.key].status is TermStatus.DORMANT
    assert lexicon.terms[stale_seed.key].status is TermStatus.ACTIVE
    assert lexicon.terms[seen_mined.key].status is TermStatus.ACTIVE
    assert lexicon.terms[seen_mined.key].last_seen == NOW - timedelta(days=1)


async def test_dormancy_runs_on_an_empty_corpus() -> None:
    lexicon = FakeLexicon()

    report = await run(lexicon, [])

    assert (report.messages, report.new_candidates, report.refreshed, report.dormant) == (
        0,
        0,
        0,
        0,
    )
    assert len(lexicon.dormant_calls) == 1
    assert lexicon.upsert_calls == []


async def test_human_labels_override_the_filter_verdict() -> None:
    flagged = spam_messages("course ads now", 8, start=100)
    labels = [label(m, noise=False) for m in flagged]

    without = FakeLexicon()
    await run(without, [*background(300), *flagged])
    with_labels = FakeLexicon()
    await run(with_labels, [*background(300), *flagged], labels)

    assert any(t.kind is LexiconKind.SPAM_OFFERS for t in without.terms.values())
    assert not any(t.kind is LexiconKind.SPAM_OFFERS for t in with_labels.terms.values())


async def test_a_language_specific_twin_of_a_neutral_term_is_refreshed_not_duplicated() -> None:
    neutral = LexiconTerm(
        kind=LexiconKind.SPAM_OFFERS, lang="any", term="earn", status=TermStatus.ACTIVE
    )
    lexicon = FakeLexicon([neutral])

    report = await run(lexicon, corpus())

    assert (LexiconKind.SPAM_OFFERS, "en", "earn") not in lexicon.terms
    assert lexicon.terms[neutral.key].occurrences == 8
    assert report.refreshed >= 1


async def test_a_term_seeded_under_another_language_is_refreshed_not_proposed_again() -> None:
    """Regression found on the synthetic chats: a seeded Russian "thanks" was proposed again
    as a language-neutral candidate."""
    seeded = LexiconTerm(
        kind=LexiconKind.SPAM_OFFERS, lang="ru", term="earn", status=TermStatus.ACTIVE
    )
    lexicon = FakeLexicon([seeded])

    await run(lexicon, corpus())

    assert (LexiconKind.SPAM_OFFERS, "en", "earn") not in lexicon.terms
    assert (LexiconKind.SPAM_OFFERS, "any", "earn") not in lexicon.terms
    assert lexicon.terms[seeded.key].occurrences == 8
    assert lexicon.terms[seeded.key].status is TermStatus.ACTIVE


async def test_candidates_carry_examples_as_keys_only() -> None:
    lexicon = FakeLexicon()

    await run(lexicon, corpus())

    for term in lexicon.terms.values():
        assert 0 < len(term.examples) <= SETTINGS.max_examples
        assert all(e.chat_id and e.msg_id for e in term.examples)
