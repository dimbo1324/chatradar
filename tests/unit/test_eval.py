from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from chatradar.domain.evaluation import MessageLabel, TruthRow
from chatradar.domain.models import ChatInfo, ChatSummary, Source
from chatradar.services.evaluation import (
    evaluate,
    evaluate_labels,
    evaluate_truth_files,
    format_report,
    load_truth,
)
from tests.unit.learning.fakes import CHAT, NOW, FakeLabels, make_message

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from chatradar.domain.models import MessageFilter, MessageKey, MessagePage, StoredMessage
    from chatradar.domain.ports import MessageRepository, QueryRepository

LONG_TEXT = "hola a todos los amigos"
VERSIONS = {"noise": 3, "enrich": 1}


def row(
    msg_id: int,
    *,
    noise: bool = False,
    reason: str | None = None,
    question: bool | None = False,
    lang: str | None = None,
) -> TruthRow:
    return TruthRow(
        key=(Source.TELEGRAM, CHAT, str(msg_id)),
        is_noise=noise,
        reason=reason,
        is_question=question,
        lang=lang,
    )


def stored(msg_id: int, text: str = "x", **columns: Any) -> StoredMessage:
    return make_message(msg_id, text, **columns)


def crafted() -> tuple[list[TruthRow], dict[MessageKey, StoredMessage]]:
    truth = [
        row(1, noise=True, reason="gratitude"),
        row(2, noise=True, reason="gratitude"),
        row(3, noise=True, reason="spam"),
        row(4),
        row(5),
        row(6),
        row(7),  # no stored message
        row(8, question=True),
        row(9, question=True),
        row(10, question=False),
        row(11, question=None),
    ]
    messages = [
        stored(1, is_noise=True, noise_reason="gratitude", is_question=False),
        stored(2, is_noise=True, noise_reason="short", is_question=False),
        stored(3, is_noise=False, is_question=False),
        stored(4, is_noise=True, noise_reason="duplicate"),
        stored(5, is_noise=None),
        stored(6, is_noise=False),
        stored(8, is_noise=False, is_question=True),
        stored(9, is_noise=False, is_question=None),
        stored(10, is_noise=False, is_question=True),
        stored(11, is_noise=False, is_question=True),
    ]
    return truth, {m.key: m for m in messages}


def test_evaluate_exact_numbers() -> None:
    truth, messages = crafted()

    report = evaluate(
        truth, messages, source="truth-file", stage_versions=VERSIONS, lexicon_revision=4
    )

    assert (report.source, report.total, report.missing) == ("truth-file", 10, 1)
    assert report.stage_versions == VERSIONS
    assert report.lexicon_revision == 4
    noise = report.noise
    assert (noise.support, noise.tp, noise.fp, noise.fn) == (3, 2, 1, 1)
    assert noise.precision == pytest.approx(2 / 3)
    assert noise.recall == pytest.approx(2 / 3)
    assert noise.f1 == pytest.approx(2 / 3)
    by_label = {m.label: m for m in report.reasons}
    assert list(by_label) == ["duplicate", "gratitude", "short", "spam"]
    gratitude = by_label["gratitude"]
    assert (gratitude.support, gratitude.tp, gratitude.fp, gratitude.fn) == (2, 1, 0, 1)
    assert (gratitude.precision, gratitude.recall) == (1.0, 0.5)
    assert gratitude.f1 == pytest.approx(2 / 3)
    spam = by_label["spam"]
    assert (spam.support, spam.tp, spam.fp, spam.fn) == (1, 0, 0, 1)
    assert (spam.precision, spam.recall, spam.f1) == (0.0, 0.0, 0.0)
    short = by_label["short"]
    assert (short.support, short.tp, short.fp, short.fn) == (0, 0, 1, 0)
    assert (short.precision, short.recall, short.f1) == (0.0, 0.0, 0.0)
    assert (by_label["duplicate"].fp, by_label["duplicate"].support) == (1, 0)


def test_question_metrics_skip_rows_without_an_opinion() -> None:
    truth, messages = crafted()

    report = evaluate(truth, messages, source="s", stage_versions={}, lexicon_revision=0)

    question = report.question
    assert (question.support, question.tp, question.fp, question.fn) == (2, 1, 1, 1)
    assert (question.precision, question.recall, question.f1) == (0.5, 0.5, 0.5)


def test_unprocessed_message_counts_as_predicted_useful() -> None:
    truth = [row(1, noise=True, reason="spam"), row(2)]
    messages = {m.key: m for m in [stored(1, is_noise=None), stored(2, is_noise=None)]}

    report = evaluate(truth, messages, source="s", stage_versions={}, lexicon_revision=0)

    assert (report.noise.tp, report.noise.fp, report.noise.fn) == (0, 0, 1)


def test_language_accuracy_counts_only_rows_with_lang_and_enough_text() -> None:
    truth = [
        row(1, lang="es"),
        row(2, lang="en"),
        row(3, lang="ru"),
        row(4, lang=None),
        row(5, lang="es"),
    ]
    messages = {
        m.key: m
        for m in [
            stored(1, LONG_TEXT, lang="es"),
            stored(2, "this text is long enough", lang="ru"),
            stored(3, "short", lang="en"),
            stored(4, "a text without a truth lang", lang="en"),
            stored(5, "  ", lang="es"),
        ]
    }

    report = evaluate(truth, messages, source="s", stage_versions={}, lexicon_revision=0)

    assert report.language_total == 2  # rows 3 (short), 4 (no truth lang), 5 (blank) are ignored
    assert report.language_accuracy == 0.5


def test_nothing_to_compare_gives_zeros_and_no_accuracy() -> None:
    report = evaluate([], {}, source="s", stage_versions={}, lexicon_revision=0)

    assert report.language_accuracy is None
    assert report.language_total == 0
    assert report.total == report.missing == 0
    assert report.noise.precision == report.noise.recall == report.noise.f1 == 0.0
    assert report.reasons == []


def write_truth(path: Path, chat_id: str, rows: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({"chat_id": chat_id, "rows": rows}), encoding="utf-8")
    return path


def test_load_truth_reads_the_generator_format(tmp_path: Path) -> None:
    path = write_truth(
        tmp_path / "truth.json",
        "-100500",
        [
            {
                "msg_id": "12",
                "is_noise": True,
                "reason": "gratitude",
                "is_question": False,
                "lang": "ru",
            },
            {"msg_id": "13", "is_noise": False, "reason": None, "is_question": True, "lang": None},
        ],
    )

    rows = load_truth(path)

    assert [(r.key, r.is_noise, r.reason, r.is_question, r.lang) for r in rows] == [
        ((Source.TELEGRAM, "-100500", "12"), True, "gratitude", False, "ru"),
        ((Source.TELEGRAM, "-100500", "13"), False, None, True, None),
    ]


def test_format_report_is_an_aligned_table() -> None:
    truth, messages = crafted()
    report = evaluate(
        truth, messages, source="truth-file", stage_versions=VERSIONS, lexicon_revision=4
    )

    lines = format_report(report).splitlines()

    assert lines[0] == "source: truth-file; compared 10, missing 1"
    assert lines[1] == "stages: noise=3, enrich=1; lexicon revision 4"
    header = next(line for line in lines if line.startswith("class"))
    noise_line = next(line for line in lines if line.startswith("noise"))
    assert len(header) == len(noise_line)
    assert "0.667" in noise_line
    labels = [line.split()[0] for line in lines[5:-2]]
    assert labels == ["noise", "duplicate", "gratitude", "short", "spam", "question"]
    assert lines[-1] == "language accuracy: n/a over 0 messages"


class FakeMessages:
    def __init__(self, messages: Sequence[StoredMessage]) -> None:
        self.by_key = {m.key: m for m in messages}
        self.batches: list[int] = []

    async def get_many(self, keys: Sequence[MessageKey]) -> dict[MessageKey, StoredMessage]:
        self.batches.append(len(keys))
        return {k: self.by_key[k] for k in keys if k in self.by_key}


class FakeQueries:
    def __init__(self, chat_ids: list[str]) -> None:
        self.chat_ids = chat_ids

    async def chat_summaries(self) -> list[ChatSummary]:
        return [
            ChatSummary(
                chat=ChatInfo(source=Source.TELEGRAM, chat_id=chat_id, title="t"),
                message_count=1,
                thread_count=0,
            )
            for chat_id in self.chat_ids
        ]

    async def list_messages(self, filters: MessageFilter) -> MessagePage:
        raise NotImplementedError


def as_ports(
    messages: FakeMessages, chat_ids: list[str]
) -> tuple[MessageRepository, QueryRepository]:
    return cast("MessageRepository", messages), cast("QueryRepository", FakeQueries(chat_ids))


async def test_evaluate_truth_files_skips_chats_not_in_the_database(tmp_path: Path) -> None:
    spam = [{"msg_id": "1", "is_noise": True, "reason": "spam"}]
    present = write_truth(tmp_path / "a.json", CHAT, spam)
    absent = write_truth(tmp_path / "b.json", "-100999", spam)
    repo, queries = as_ports(FakeMessages([stored(1, is_noise=True, noise_reason="spam")]), [CHAT])

    report = await evaluate_truth_files(
        [present, absent],
        queries=queries,
        messages=repo,
        stage_versions=VERSIONS,
        lexicon_revision=2,
    )

    assert report.source == "truth-file"
    assert (report.total, report.missing) == (1, 0)
    assert report.noise.tp == 1


async def test_evaluate_truth_files_looks_messages_up_in_batches(tmp_path: Path) -> None:
    rows = [{"msg_id": str(i), "is_noise": False} for i in range(1, 1201)]
    path = write_truth(tmp_path / "big.json", CHAT, rows)
    fake = FakeMessages([])
    repo, queries = as_ports(fake, [CHAT])

    report = await evaluate_truth_files(
        [path], queries=queries, messages=repo, stage_versions={}, lexicon_revision=0
    )

    assert fake.batches == [500, 500, 200]
    assert report.missing == 1200


async def test_evaluate_labels_uses_human_labels_as_truth() -> None:
    def label(msg_id: str, **fields: Any) -> MessageLabel:
        return MessageLabel(
            source=Source.TELEGRAM, chat_id=CHAT, msg_id=msg_id, created_at=NOW, **fields
        )

    labels = FakeLabels(
        [
            label("1", is_noise=True, reason="spam", is_question=False),
            label("2", is_noise=False, reason="short", is_question=True),
            label("3", is_noise=True),
        ]
    )
    fake = FakeMessages(
        [
            stored(1, is_noise=True, noise_reason="spam", is_question=False),
            stored(2, is_noise=False, is_question=True),
        ]
    )
    repo, _ = as_ports(fake, [])

    report = await evaluate_labels(labels, repo, stage_versions=VERSIONS, lexicon_revision=7)

    assert report.source == "human-labels"
    assert (report.total, report.missing) == (2, 1)
    assert (report.noise.tp, report.noise.fp, report.noise.fn) == (1, 0, 0)
    assert [m.label for m in report.reasons] == ["spam"]
    assert (report.question.tp, report.question.fp, report.question.fn) == (1, 0, 0)
    assert report.lexicon_revision == 7
