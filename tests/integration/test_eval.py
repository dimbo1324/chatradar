"""The regression gate for the filter: the four synthetic chats, processed by the CURRENT
stages, measured against the generator's truth files.

The thresholds sit below the measured values with a safety margin (measured on 2026-10-19:
noise precision 0.611 / recall 0.975, gratitude 0.862 / 1.000, short 0.920 / 0.885, spam
1.000 / 0.609, duplicate recall 1.000, question precision 1.000 / recall 0.840, language
accuracy 0.811). A rule change that drops one of them is a regression; a rule change that
raises one lets the threshold be raised in the same commit.

Known, understood misses: the phrase bank repeats whole answers, so the filter's `duplicate`
rule flags ~100 messages the generator did not mean as reposts (noise precision, duplicate
precision); spam written without a link or a contact phrase is not recognised (spam recall).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatradar.config import LearningSettings, Settings
from chatradar.domain.lexicon import LexiconKind
from chatradar.domain.models import MessageFilter
from chatradar.pipeline.registry import stage_versions
from chatradar.services.container import open_runtime
from chatradar.services.evaluation import evaluate_truth_files
from chatradar.services.ingest import import_tg_export
from chatradar.services.learning import mine_candidates
from chatradar.services.process import process
from scripts import generate_synthetic as gen
from tests.unit.learning.fakes import NOW, FakeLabels, FakeLexicon, PagingScanner

if TYPE_CHECKING:
    from pathlib import Path

    from chatradar.domain.evaluation import ClassMetrics, EvalReport
    from chatradar.services.container import Runtime

pytestmark = pytest.mark.integration

TRUTH_FILES = [gen.FIXTURES / gen.TRUTH_DIR / spec.file for spec in gen.CHATS]


def _reason(report: EvalReport, label: str) -> ClassMetrics:
    return next(m for m in report.reasons if m.label == label)


async def _load(rt: Runtime) -> None:
    for spec in gen.CHATS:
        await import_tg_export(
            gen.FIXTURES / spec.file,
            username=None,
            raw=rt.raw,
            chats=rt.repo,
            messages=rt.repo,
            catalog=rt.raw,
        )
    await process(rt.stage_deps)


async def _measure(tmp_path: Path, files: list[Path]) -> EvalReport:
    async with open_runtime(Settings(data_dir=tmp_path / "data")) as rt:
        await _load(rt)
        assert (await rt.repo.list_messages(MessageFilter(limit=1))).total > 1500
        return await evaluate_truth_files(
            files,
            queries=rt.repo,
            messages=rt.repo,
            stage_versions=dict(stage_versions()),
            lexicon_revision=0,
        )


async def test_filter_quality_on_synthetic_chats(tmp_path: Path) -> None:
    report = await _measure(tmp_path, TRUTH_FILES)

    assert report.missing == 0
    assert report.total > 1500
    assert report.noise.recall >= 0.93
    assert report.noise.precision >= 0.55
    assert _reason(report, "gratitude").recall >= 0.95
    assert _reason(report, "gratitude").precision >= 0.80
    assert _reason(report, "short").f1 >= 0.80
    assert _reason(report, "spam").precision >= 0.90
    assert _reason(report, "spam").recall >= 0.50
    assert _reason(report, "duplicate").recall >= 0.90
    for label in ("emoji_only", "sticker", "service"):
        assert _reason(report, label).recall >= 0.95
        assert _reason(report, label).precision >= 0.95
    assert report.question.precision >= 0.95
    assert report.question.recall >= 0.78
    assert report.language_accuracy is not None
    assert report.language_accuracy >= 0.75
    assert report.stage_versions["noise"] >= 3


async def test_chats_without_stored_messages_are_skipped(tmp_path: Path) -> None:
    async with open_runtime(Settings(data_dir=tmp_path / "data")) as rt:
        report = await evaluate_truth_files(
            TRUTH_FILES,
            queries=rt.repo,
            messages=rt.repo,
            stage_versions={},
            lexicon_revision=0,
        )

    assert report.total == 0
    assert report.missing == 0


async def test_mining_the_synthetic_corpus_proposes_safe_candidates(tmp_path: Path) -> None:
    lexicon = FakeLexicon()
    async with open_runtime(Settings(data_dir=tmp_path / "data")) as rt:
        await _load(rt)
        scanner = PagingScanner(rt.repo)
        settings = LearningSettings()

        first = await mine_candidates(
            settings, scanner=scanner, lexicon=lexicon, labels=FakeLabels(), now=NOW
        )
        second = await mine_candidates(
            settings, scanner=scanner, lexicon=lexicon, labels=FakeLabels(), now=NOW
        )

    assert first.messages > 1500
    assert first.new_candidates == len(lexicon.terms)
    assert {"gratitude", "spam_offers", "spam_contacts", "question_phrases"} <= set(first.by_kind)
    assert (second.new_candidates, second.refreshed) == (0, first.new_candidates)
    for term in lexicon.terms.values():
        assert "@" not in term.term
        assert "http" not in term.term
        assert term.authors >= settings.min_authors
        assert term.occurrences >= settings.min_occurrences
        assert term.score >= settings.min_score
        assert term.examples
    assert all(
        t.kind is not LexiconKind.GRATITUDE or len(t.term.split()) <= 6
        for t in lexicon.terms.values()
    )
