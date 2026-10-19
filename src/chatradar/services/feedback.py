"""The only writes the web panel may make (ADR-0004): term decisions and message labels.

Everything else — messages, threads, the index — stays with the worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from chatradar.domain.evaluation import MessageLabel
from chatradar.logs import get_logger
from chatradar.pipeline.noise import NOISE_REASONS

if TYPE_CHECKING:
    from chatradar.domain.lexicon import LexiconKind, LexiconTerm, TermDecision
    from chatradar.domain.models import MessageKey
    from chatradar.domain.ports import LabelRepository, LexiconRepository, MessageRepository

log = get_logger(__name__)

HUMAN = "human"


class UnknownTermError(LookupError):
    """The (kind, lang, term) is not in the lexicon."""


class UnknownMessageError(LookupError):
    """The message to label does not exist."""


class InvalidLabelError(ValueError):
    """The label contradicts itself (a reason without noise, an unknown reason)."""


@dataclass(frozen=True)
class FeedbackServices:
    lexicon: LexiconRepository
    labels: LabelRepository
    messages: MessageRepository

    async def decide_term(
        self,
        kind: LexiconKind,
        lang: str,
        term: str,
        decision: TermDecision,
        note: str | None = None,
    ) -> LexiconTerm:
        try:
            decided = await self.lexicon.decide(kind, lang, term, decision, by=HUMAN, note=note)
        except KeyError as error:
            raise UnknownTermError(f"{kind.value}/{lang}/{term}") from error
        log.info(
            "lexicon.decision", kind=kind.value, decision=decision.value, status=decided.status
        )
        return decided

    async def label_message(
        self,
        key: MessageKey,
        *,
        is_noise: bool,
        reason: str | None = None,
        is_question: bool | None = None,
    ) -> MessageLabel:
        if reason is not None and not is_noise:
            raise InvalidLabelError("a reason needs is_noise=true")
        if reason is not None and reason not in NOISE_REASONS:
            raise InvalidLabelError(f"unknown noise reason {reason!r}")
        if key not in await self.messages.get_many([key]):
            raise UnknownMessageError("/".join((key[0].value, key[1], key[2])))
        label = MessageLabel(
            source=key[0],
            chat_id=key[1],
            msg_id=key[2],
            is_noise=is_noise,
            reason=reason,
            is_question=is_question,
            created_at=datetime.now(UTC),
            by=HUMAN,
        )
        await self.labels.save_label(label)
        log.info("label.saved", is_noise=is_noise, reason=reason)
        return label
