"""Ingestion's last step: raw records → messages (through the mappers) → upsert."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.domain.models import ChatInfo, ChatKind, RawKind, RawRecord, Source, UpsertResult
from chatradar.logs import get_logger
from chatradar.pipeline.base import NORMALIZE_VERSION

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from chatradar.domain.models import Message
    from chatradar.domain.ports import ChatRepository, Mapper, MessageRepository

log = get_logger(__name__)

BATCH = 500


async def normalize_records(
    records: Sequence[RawRecord],
    *,
    mappers: Mapping[RawKind, Mapper],
    chats: ChatRepository,
    messages: MessageRepository,
) -> UpsertResult:
    """Map every record with the mapper of its kind and upsert the results in batches.

    Records whose chat is unknown are mapped against a placeholder chat (no username, so
    no public link); importers register chats before calling this.
    """
    known: dict[tuple[Source, str], ChatInfo] = {}
    mapped: list[Message] = []
    skipped = 0
    for record in records:
        chat_key = (record.source, record.chat_id)
        if chat_key not in known:
            chat = await chats.get_chat(record.source, record.chat_id)
            known[chat_key] = chat or ChatInfo(
                source=record.source,
                chat_id=record.chat_id,
                title=record.chat_id,
                kind=ChatKind.SUPERGROUP,
            )
        message = mappers[record.kind](record, known[chat_key])
        if message is None:
            skipped += 1
        else:
            mapped.append(message)

    total = UpsertResult()
    for start in range(0, len(mapped), BATCH):
        total += await messages.upsert_many(mapped[start : start + BATCH], NORMALIZE_VERSION)
    log.info(
        "normalize.done",
        stage="normalize",
        count=len(records),
        skipped=skipped,
        inserted=total.inserted,
        updated=total.updated,
        unchanged=total.unchanged,
    )
    return total
