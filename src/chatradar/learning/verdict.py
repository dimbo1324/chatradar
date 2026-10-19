"""The class of a message for mining: a human label if there is one, else the filter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from chatradar.domain.evaluation import MessageLabel
    from chatradar.domain.models import MessageKey, StoredMessage

SPAM_REASON = "spam"


@dataclass(frozen=True)
class Verdict:
    is_spam: bool
    is_question: bool
    human_useful: bool  # a human said the message is not noise


def verdict_of(msg: StoredMessage, labels: Mapping[MessageKey, MessageLabel]) -> Verdict:
    label = labels.get(msg.key)
    if label is None:
        return Verdict(
            is_spam=msg.is_noise is True and msg.noise_reason == SPAM_REASON,
            is_question="?" in msg.text,
            human_useful=False,
        )
    return Verdict(
        is_spam=label.is_noise and label.reason == SPAM_REASON,
        is_question="?" in msg.text if label.is_question is None else label.is_question,
        human_useful=not label.is_noise,
    )
