"""The JSON API from `docs/api.md`: parameter parsing and delegation to `ReadServices`."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime  # noqa: TC002 - FastAPI evaluates route annotations

from chatradar.domain.models import (
    ChatSummary,
    MessageFilter,
    MessagePage,
    PipelineStats,
    SearchFilters,
    Source,
    StoredMessage,
    ThreadDetail,
    ThreadHit,
)
from chatradar.services.queries import ReadServices

router = APIRouter(prefix="/api", tags=["api"])


def get_read_services(request: Request) -> ReadServices:
    return cast("ReadServices", request.app.state.read)


Read = Annotated[ReadServices, Depends(get_read_services)]


@router.get("/chats")
async def chats(read: Read) -> list[ChatSummary]:
    return await read.chats()


@router.get("/pipeline")
async def pipeline(read: Read) -> PipelineStats:
    return await read.pipeline()


@router.get("/messages")
async def messages(read: Read, filters: Annotated[MessageFilter, Query()]) -> MessagePage:
    return await read.messages(filters)


@router.get("/threads/{thread_id}")
async def thread(read: Read, thread_id: str) -> ThreadDetail:
    detail = await read.thread(thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return detail


def search_filters(
    source: Source | None = None,
    chat_id: str | None = None,
    date_from: AwareDatetime | None = None,
    date_to: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchFilters:
    return SearchFilters(
        source=source, chat_id=chat_id, date_from=date_from, date_to=date_to, limit=limit
    )


@router.get("/search")
async def search(
    read: Read,
    q: Annotated[str, Query()],
    filters: Annotated[SearchFilters, Depends(search_filters)],
) -> list[ThreadHit]:
    return await read.search(q, filters)


@router.get("/review")
async def review(
    read: Read,
    noise: Annotated[bool, Query()],
    n: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[StoredMessage]:
    return await read.review(is_noise=noise, n=n)


@router.get("/noise-reasons")
async def noise_reasons(read: Read) -> dict[str, int]:
    return await read.noise_reasons()
