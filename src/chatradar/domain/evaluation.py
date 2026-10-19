"""Labels and evaluation of the filter: the gold standard and how it is measured."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict

from chatradar.domain.models import MessageKey, Source


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MessageLabel(_Frozen):
    """A human verdict on one message; the gold standard the filter is measured against."""

    source: Source
    chat_id: str
    msg_id: str
    is_noise: bool
    reason: str | None = None  # one of the noise reasons, only when `is_noise`
    is_question: bool | None = None  # None = no opinion
    created_at: AwareDatetime
    by: str = "human"

    @property
    def key(self) -> MessageKey:
        return (self.source, self.chat_id, self.msg_id)


class TruthRow(_Frozen):
    """Ground truth for one message: from a label or from the synthetic generator."""

    key: MessageKey
    is_noise: bool
    reason: str | None = None
    is_question: bool | None = None
    lang: str | None = None  # `ru`, `es` or `en` when known


class ClassMetrics(_Frozen):
    label: str
    support: int  # truth positives
    tp: int
    fp: int
    fn: int
    precision: float  # 0.0 when nothing was predicted
    recall: float  # 0.0 when there are no truth positives
    f1: float


class EvalReport(_Frozen):
    source: str  # `truth-file` or `human-labels`
    total: int  # messages compared
    missing: int  # truth rows without a stored message
    noise: ClassMetrics  # noise vs. useful, overall
    reasons: list[ClassMetrics]  # one per truth or predicted noise reason
    question: ClassMetrics
    language_total: int
    language_accuracy: float | None  # None when no row has a language
    stage_versions: dict[str, int]
    lexicon_revision: int
