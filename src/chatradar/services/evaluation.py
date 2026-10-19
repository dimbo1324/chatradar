"""Measuring the filter against ground truth: a synthetic truth file or human labels.

Contract written by the lead; package B replaces the bodies. The pure `evaluate` compares
truth rows with what the pipeline stored; the two async helpers load the inputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from chatradar.domain.evaluation import EvalReport, TruthRow
    from chatradar.domain.models import MessageKey, StoredMessage
    from chatradar.domain.ports import LabelRepository, MessageRepository


def evaluate(
    truth: Sequence[TruthRow],
    stored: Mapping[MessageKey, StoredMessage],
    *,
    source: str,
    stage_versions: Mapping[str, int],
    lexicon_revision: int,
) -> EvalReport:
    """Precision, recall and F1 of: noise vs. useful (overall and per reason), question
    detection, and language accuracy. A truth row without a stored message counts in
    `missing`, not as an error of the filter. A message the filter has not processed yet
    (`is_noise is None`) counts as predicted useful."""
    raise NotImplementedError


async def evaluate_labels(
    labels: LabelRepository,
    messages: MessageRepository,
    *,
    stage_versions: Mapping[str, int],
    lexicon_revision: int,
) -> EvalReport:
    """`evaluate` over every human label stored in the database (`source="human-labels"`)."""
    raise NotImplementedError
