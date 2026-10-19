from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from chatradar.domain.models import ChatInfo, MediaType, Message, Source, StageResult, Thread
from chatradar.domain.text import content_hash, message_link, thread_id_for

if TYPE_CHECKING:
    from chatradar.domain.models import ResultValue
    from chatradar.storage.db.repositories import SqlRepository

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CHAT = ChatInfo(source=Source.TELEGRAM, chat_id="-100500", title="Synthetic", username="demo")
OTHER = ChatInfo(source=Source.TELEGRAM, chat_id="-100600", title="Other chat")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "storage"


def texts() -> dict[str, str]:
    raw = json.loads((FIXTURES / "texts.json").read_text(encoding="utf-8"))
    return cast("dict[str, str]", raw)


def make_message(
    msg_id: int,
    text: str = "",
    *,
    chat: ChatInfo = CHAT,
    minutes: int | None = None,
    reply_to: int | None = None,
    media_type: MediaType = MediaType.NONE,
) -> Message:
    body = text or f"synthetic message {msg_id}"
    reply = str(reply_to) if reply_to is not None else None
    return Message(
        source=chat.source,
        chat_id=chat.chat_id,
        msg_id=str(msg_id),
        author_id=f"user{msg_id % 3}",
        date=T0 + timedelta(minutes=msg_id if minutes is None else minutes),
        text=body,
        text_raw=body,
        reply_to=reply,
        media_type=media_type,
        link=message_link(chat.chat_id, str(msg_id), chat.username),
        content_hash=content_hash(text_raw=body, media_type=media_type.value, reply_to=reply),
    )


def result(message: Message, **values: ResultValue) -> StageResult:
    return StageResult(key=message.key, values=values)


def make_thread(root: Message, members: list[Message], *, has_question: bool = False) -> Thread:
    return Thread(
        thread_id=thread_id_for(root.chat_id, root.msg_id),
        source=root.source,
        chat_id=root.chat_id,
        root_msg_id=root.msg_id,
        started_at=min(m.date for m in members),
        ended_at=max(m.date for m in members),
        msg_count=len(members),
        has_question=has_question,
    )


async def run_pipeline(
    repo: SqlRepository,
    messages: list[Message],
    *,
    noise: dict[str, str] | None = None,
    threads: list[list[Message]] | None = None,
) -> list[Thread]:
    """Store messages and fake every stage: `noise` maps msg_id to a reason; each list in
    `threads` is one thread, its first message the root."""
    noise = noise or {}
    await repo.upsert_many(messages, 1)
    await repo.mark(
        "noise",
        1,
        [result(m, is_noise=m.msg_id in noise, noise_reason=noise.get(m.msg_id)) for m in messages],
    )
    await repo.mark(
        "enrich",
        1,
        [
            result(m, lang="ru", is_question="?" in m.text, urls=[], has_mention=False)
            for m in messages
        ],
    )
    built: list[Thread] = []
    marks: list[StageResult] = []
    for members in threads or []:
        thread = make_thread(members[0], members)
        built.append(thread)
        marks.extend(result(m, thread_id=thread.thread_id) for m in members)
    by_chat: dict[tuple[Source, str], list[Thread]] = {}
    for thread in built:
        by_chat.setdefault((thread.source, thread.chat_id), []).append(thread)
    for (source, chat_id), chat_threads in by_chat.items():
        await repo.save_threads(source, chat_id, T0 - timedelta(days=1), chat_threads)
    await repo.mark("threads", 1, marks)
    return built
