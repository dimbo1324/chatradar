"""Learning-lexicon, label, quality and single-message endpoints (`docs/api.md`).

The only writes the panel makes (ADR-0004); everything delegates to `FeedbackServices`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from chatradar.domain.evaluation import EvalReport, MessageLabel  # noqa: TC001 - FastAPI evaluates annotations
from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconSummary,
    LexiconTerm,
    TermDecision,
    TermPage,
    TermStatus,
)
from chatradar.domain.models import Source, StoredMessage
from chatradar.domain.ports import TermOrder  # noqa: TC001 - FastAPI evaluates annotations
from chatradar.pipeline.noise import NOISE_REASONS
from chatradar.services.feedback import (
    FeedbackServices,
    InvalidLabelError,
    UnknownMessageError,
    UnknownTermError,
)
from chatradar.web.api import Read  # noqa: TC001 - FastAPI evaluates annotations

if TYPE_CHECKING:
    from collections.abc import Generator

router = APIRouter(prefix="/api", tags=["learning"])


def get_feedback_services(request: Request) -> FeedbackServices:
    feedback = cast("FeedbackServices | None", getattr(request.app.state, "feedback", None))
    if feedback is None:
        raise HTTPException(status_code=503, detail="Feedback services are not available")
    return feedback


Feedback = Annotated[FeedbackServices, Depends(get_feedback_services)]


@contextmanager
def _available() -> Generator[None]:
    try:
        yield
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionBody(_Body):
    kind: LexiconKind
    lang: str = Field(min_length=1, max_length=20)
    term: str = Field(min_length=1, max_length=200)
    decision: TermDecision
    note: str | None = Field(default=None, max_length=500)


class LabelBody(_Body):
    source: Source
    chat_id: str = Field(min_length=1, max_length=200)
    msg_id: str = Field(min_length=1, max_length=200)
    is_noise: bool
    reason: str | None = Field(default=None, max_length=100)
    is_question: bool | None = None


@router.get("/lexicon/summary")
async def lexicon_summary(read: Read) -> LexiconSummary:
    with _available():
        return await read.lexicon_summary()


@router.get("/lexicon/terms")
async def lexicon_terms(
    read: Read,
    kind: LexiconKind | None = None,
    status: TermStatus | None = None,
    lang: str | None = None,
    order: Annotated[TermOrder, Query()] = "score",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TermPage:
    with _available():
        return await read.lexicon_terms(
            kind=kind, status=status, lang=lang, order=order, limit=limit, offset=offset
        )


@router.post("/lexicon/decision")
async def lexicon_decision(body: DecisionBody, feedback: Feedback) -> LexiconTerm:
    try:
        return await feedback.decide_term(body.kind, body.lang, body.term, body.decision, body.note)
    except UnknownTermError as error:
        raise HTTPException(status_code=404, detail="Term not found") from error


@router.get("/labels")
async def labels(
    read: Read, limit: Annotated[int, Query(ge=1, le=5000)] = 5000
) -> list[MessageLabel]:
    with _available():
        return await read.label_list(limit)


@router.post("/labels")
async def save_label(body: LabelBody, feedback: Feedback) -> MessageLabel:
    try:
        return await feedback.label_message(
            (body.source, body.chat_id, body.msg_id),
            is_noise=body.is_noise,
            reason=body.reason,
            is_question=body.is_question,
        )
    except UnknownMessageError as error:
        raise HTTPException(status_code=404, detail="Message not found") from error
    except InvalidLabelError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/quality")
async def quality(read: Read) -> EvalReport:
    with _available():
        return await read.quality()


@router.get("/noise-reason-list")
async def noise_reason_list() -> list[str]:
    return sorted(NOISE_REASONS)


@router.get("/messages/{source}/{chat_id}/{msg_id}")
async def single_message(read: Read, source: Source, chat_id: str, msg_id: str) -> StoredMessage:
    with _available():
        found = await read.message(source, chat_id, msg_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return found
