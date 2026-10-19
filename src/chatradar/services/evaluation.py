"""Measuring the filter against ground truth: a synthetic truth file or human labels.

`evaluate` is pure: it compares truth rows with what the pipeline stored. The async helper
and the file loader prepare its input.

Definitions (a "positive" is the class named in the row's label):

- *noise*: positive = the message is noise. Predicted positive = the stored `is_noise` is
  true; a message the filter has not processed (`is_noise is None`) counts as predicted useful.
- *reason r*: positive = a noise row whose truth reason is `r`; predicted positive = a noise
  verdict whose stored reason is `r`. One entry per reason seen in the truth or the prediction.
- *question*: positive = the truth says the message is a question (rows with `is_question is
  None` are skipped); predicted positive = the stored `is_question` is true (None = no).
- *language*: accuracy over rows that have a truth `lang` and at least `LANGUAGE_MIN_CHARS`
  characters of stored text; shorter texts are too ambiguous to detect.

precision = tp / (tp + fp), recall = tp / (tp + fn), f1 = 2pr / (p + r). Every ratio with a
zero denominator is 0.0 (precision when nothing was predicted, recall when there are no truth
positives, f1 when both are zero); `support` = tp + fn. A truth row whose message is not
stored counts in `missing` and nowhere else.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from chatradar.domain.evaluation import ClassMetrics, EvalReport, TruthRow
from chatradar.domain.models import Source

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from chatradar.domain.models import MessageKey, StoredMessage
    from chatradar.domain.ports import LabelRepository, MessageRepository, QueryRepository

LANGUAGE_MIN_CHARS = 20
SOURCE_TRUTH_FILE = "truth-file"
SOURCE_HUMAN_LABELS = "human-labels"
_LOOKUP_BATCH = 500


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _metrics(label: str, tp: int, fp: int, fn: int) -> ClassMetrics:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return ClassMetrics(
        label=label,
        support=tp + fn,
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0,
    )


def _confusion(label: str, pairs: Iterable[tuple[bool, bool]]) -> ClassMetrics:
    """(truth positive, predicted positive) pairs → metrics."""
    tp = fp = fn = 0
    for truth, predicted in pairs:
        tp += truth and predicted
        fp += predicted and not truth
        fn += truth and not predicted
    return _metrics(label, tp, fp, fn)


def evaluate(
    truth: Sequence[TruthRow],
    stored: Mapping[MessageKey, StoredMessage],
    *,
    source: str,
    stage_versions: Mapping[str, int],
    lexicon_revision: int,
) -> EvalReport:
    """Precision, recall and F1 of: noise vs. useful (overall and per reason), question
    detection, and language accuracy (see the module docstring for the definitions)."""
    pairs = [(row, msg) for row in truth if (msg := stored.get(row.key)) is not None]
    predicted_noise = [(row, msg.is_noise is True, msg.noise_reason) for row, msg in pairs]

    noise = _confusion("noise", ((row.is_noise, flagged) for row, flagged, _ in predicted_noise))
    reasons = sorted(
        {row.reason for row, _, _ in predicted_noise if row.is_noise and row.reason}
        | {reason for _, flagged, reason in predicted_noise if flagged and reason}
    )
    reason_metrics = [
        _confusion(
            reason,
            (
                (row.is_noise and row.reason == reason, flagged and stored_reason == reason)
                for row, flagged, stored_reason in predicted_noise
            ),
        )
        for reason in reasons
    ]
    question = _confusion(
        "question",
        (
            (row.is_question, msg.is_question is True)
            for row, msg in pairs
            if row.is_question is not None
        ),
    )
    language_rows = [
        (row.lang, msg.lang)
        for row, msg in pairs
        if row.lang is not None and len(msg.text.strip()) >= LANGUAGE_MIN_CHARS
    ]
    correct = sum(expected == actual for expected, actual in language_rows)
    return EvalReport(
        source=source,
        total=len(pairs),
        missing=len(truth) - len(pairs),
        noise=noise,
        reasons=reason_metrics,
        question=question,
        language_total=len(language_rows),
        language_accuracy=_ratio(correct, len(language_rows)) if language_rows else None,
        stage_versions=dict(stage_versions),
        lexicon_revision=lexicon_revision,
    )


async def evaluate_labels(
    labels: LabelRepository,
    messages: MessageRepository,
    *,
    stage_versions: Mapping[str, int],
    lexicon_revision: int,
) -> EvalReport:
    """`evaluate` over every human label stored in the database (`source="human-labels"`)."""
    rows = [
        TruthRow(
            key=label.key,
            is_noise=label.is_noise,
            reason=label.reason if label.is_noise else None,
            is_question=label.is_question,
        )
        for label in await labels.list_labels()
    ]
    stored = await _lookup(messages, [row.key for row in rows])
    return evaluate(
        rows,
        stored,
        source=SOURCE_HUMAN_LABELS,
        stage_versions=stage_versions,
        lexicon_revision=lexicon_revision,
    )


async def evaluate_truth_files(
    paths: Sequence[Path],
    *,
    queries: QueryRepository,
    messages: MessageRepository,
    stage_versions: Mapping[str, int],
    lexicon_revision: int,
) -> EvalReport:
    """`evaluate` over the truth files whose chats are in the database; files of other
    chats are skipped (their rows would only inflate `missing`)."""
    present = {
        (summary.chat.source, summary.chat.chat_id) for summary in await queries.chat_summaries()
    }
    rows = [
        row for path in paths for row in load_truth(path) if (row.key[0], row.key[1]) in present
    ]
    stored = await _lookup(messages, [row.key for row in rows])
    return evaluate(
        rows,
        stored,
        source=SOURCE_TRUTH_FILE,
        stage_versions=stage_versions,
        lexicon_revision=lexicon_revision,
    )


async def _lookup(
    messages: MessageRepository, keys: Sequence[MessageKey]
) -> dict[MessageKey, StoredMessage]:
    stored: dict[MessageKey, StoredMessage] = {}
    for start in range(0, len(keys), _LOOKUP_BATCH):
        stored |= await messages.get_many(keys[start : start + _LOOKUP_BATCH])
    return stored


def load_truth(path: Path, *, source: Source = Source.TELEGRAM) -> list[TruthRow]:
    """Read a truth file written by `scripts/generate_synthetic.py`:
    `{"chat_id": "...", "rows": [{"msg_id", "is_noise", "reason", "is_question", "lang"}]}`."""
    data = cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
    chat_id = str(data["chat_id"])
    return [
        TruthRow(
            key=(source, chat_id, str(row["msg_id"])),
            is_noise=bool(row["is_noise"]),
            reason=row.get("reason"),
            is_question=row.get("is_question"),
            lang=row.get("lang"),
        )
        for row in cast("list[dict[str, Any]]", data["rows"])
    ]


def format_report(report: EvalReport) -> str:
    """An aligned plain-text table of the report."""
    rows = [report.noise, *report.reasons, report.question]
    width = max(len(m.label) for m in rows)
    header = _row(width, "class", "support", "tp", "fp", "fn", "prec", "rec", "f1")
    lines = [
        f"source: {report.source}; compared {report.total}, missing {report.missing}",
        f"stages: {_versions(report.stage_versions)}; lexicon revision {report.lexicon_revision}",
        "",
        header,
        "-" * len(header),
    ]
    lines += [
        _row(
            width,
            m.label,
            str(m.support),
            str(m.tp),
            str(m.fp),
            str(m.fn),
            f"{m.precision:.3f}",
            f"{m.recall:.3f}",
            f"{m.f1:.3f}",
        )
        for m in rows
    ]
    accuracy = "n/a" if report.language_accuracy is None else f"{report.language_accuracy:.3f}"
    lines += ["", f"language accuracy: {accuracy} over {report.language_total} messages"]
    return "\n".join(lines)


def _row(width: int, label: str, *values: str) -> str:
    sizes = (7, 5, 5, 5, 6, 6, 6)
    return f"{label:<{width}}  " + "  ".join(v.rjust(n) for v, n in zip(values, sizes, strict=True))


def _versions(versions: Mapping[str, int]) -> str:
    return ", ".join(f"{name}={version}" for name, version in versions.items()) or "-"
