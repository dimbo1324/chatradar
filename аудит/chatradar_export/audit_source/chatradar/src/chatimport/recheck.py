"""Daily recheck of the last N days (spec §8.7): what to compare, and when to ask for it."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING

from chatimport import worker_store
from chatimport.records import (
    DETECTED_RECHECK,
    DeleteRecord,
    EditRecord,
    MediaInfo,
    MessageRecord,
    Record,
    record_sort_id,
)
from chatimport.storage.layout import list_parts, month_key, parse_part_name
from chatimport.storage.reader import iter_records

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import tzinfo
    from pathlib import Path

    from chatimport.config import RecheckConfig
    from chatimport.ports import Clock, TelegramGateway
    from chatimport.runtime import ChatController, ChatRegistry
    from chatimport.storage.state import ChatState

log = logging.getLogger(__name__)

STARTUP_STALE_AFTER = timedelta(hours=24)


@dataclass(slots=True)
class _Known:
    text: str
    media: MediaInfo | None
    edit_date: datetime | None
    deleted: bool = False


def _comparable(media: MediaInfo | None) -> MediaInfo | None:
    return replace(media, file=None) if media else None


def window_parts(folder: Path, since: datetime) -> list[Path]:
    """Parts that can hold a record dated at or after `since`: every record lives in the
    month of its own date (message date, edit date, detection time), so older months
    cannot."""
    first = month_key(since)
    return [
        path
        for path in list_parts(folder)
        if (parsed := parse_part_name(path.name)) is not None and parsed[0] >= first
    ]


def _read_known(folder: Path, state: ChatState, since: datetime) -> dict[int, _Known]:
    """Current version of every window message, in one streaming pass over the window's
    parts."""
    floor, ceiling = state.floor_id, state.last_id
    messages: dict[int, _Known] = {}
    edits: dict[int, EditRecord] = {}
    deleted: set[int] = set()
    for record in iter_records(folder, window_parts(folder, since)):
        match record:
            case MessageRecord():
                if floor <= record.msg_id <= ceiling and record.date >= since:
                    messages[record.msg_id] = _Known(record.text, record.media, record.edit_date)
            case EditRecord():
                if floor <= record.msg_id <= ceiling and record.edit_date >= since:
                    current = edits.get(record.msg_id)
                    if current is None or record.edit_date >= current.edit_date:
                        edits[record.msg_id] = record
            case DeleteRecord():
                if record.fetched_at >= since:
                    deleted.update(i for i in record.msg_ids if floor <= i <= ceiling)
            case _:
                pass
    for msg_id, edit in edits.items():
        known = messages.get(msg_id)
        if known is not None and (known.edit_date is None or edit.edit_date >= known.edit_date):
            known.text, known.media, known.edit_date = edit.text, edit.media, edit.edit_date
    for msg_id in deleted:
        known = messages.get(msg_id)
        if known is not None:
            known.deleted = True
    return messages


def _differs(known: _Known, message: MessageRecord) -> bool:
    if message.edit_date is not None and (
        known.edit_date is None or message.edit_date > known.edit_date
    ):
        return True
    return known.text != message.text or _comparable(known.media) != _comparable(message.media)


async def compute_recheck(
    gateway: TelegramGateway,
    folder: Path,
    state: ChatState,
    *,
    now: datetime,
    days: int,
    track_edits: bool,
    track_deletes: bool,
) -> list[Record]:
    """Records that bring the files in line with Telegram for the last `days` days.

    Never writes. After the result is appended, calling it again returns nothing.
    """
    if state.last_id <= state.floor_id:
        return []
    since = now - timedelta(days=days)
    known = await worker_store.run_blocking(partial(_read_known, folder, state, since))

    result: list[Record] = []
    seen: set[int] = set()
    async for message in gateway.iter_window(state.chat_id, since, state.last_id):
        if message.msg_id < state.floor_id:
            continue
        seen.add(message.msg_id)
        current = known.get(message.msg_id)
        if current is None:
            if message.msg_id > state.floor_id:
                result.append(message)
        elif track_edits and not current.deleted and _differs(current, message):
            result.append(
                EditRecord(
                    chat_id=state.chat_id,
                    msg_id=message.msg_id,
                    edit_date=message.edit_date or now,
                    fetched_at=now,
                    text=message.text,
                    media=message.media,
                    detected_by=DETECTED_RECHECK,
                )
            )

    if track_deletes and known and not seen:
        log.warning(
            "recheck: Telegram returned an empty window, deletions not recorded",
            extra={"chat_id": state.chat_id, "window_messages": len(known)},
        )
    elif track_deletes:
        missing = sorted(i for i, k in known.items() if not k.deleted and i not in seen)
        if missing:
            result.append(
                DeleteRecord(
                    chat_id=state.chat_id,
                    msg_ids=tuple(missing),
                    fetched_at=now,
                    detected_by=DETECTED_RECHECK,
                )
            )

    result.sort(key=record_sort_id)
    log.info(
        "recheck computed",
        extra={
            "chat_id": state.chat_id,
            "window_messages": len(known),
            "records": len(result),
        },
    )
    return result


def seconds_until_next(daily_at: str, now: datetime, tz: tzinfo | None = None) -> float:
    """Seconds from `now` to the next local `HH:MM` in `tz`; always positive.

    Without `tz` the system zone is used with the offset in force on the target day (a
    naive wall time is converted by the operating system's rules), so a DST change between
    now and the target does not shift the result by an hour.
    """
    hour, minute = (int(part) for part in daily_at.split(":", 1))
    wall = time(hour, minute)
    local_day = now.astimezone(tz).date()
    instant = now.astimezone(UTC)
    target = datetime.combine(local_day, wall, tzinfo=tz).astimezone(UTC)
    if target <= instant:
        target = datetime.combine(local_day + timedelta(days=1), wall, tzinfo=tz).astimezone(UTC)
    return (target - instant).total_seconds()


class RecheckScheduler:
    """Asks chats to recheck on start (if stale) and daily; one chat at a time with pauses."""

    def __init__(
        self,
        registry: ChatRegistry,
        config: RecheckConfig,
        clock: Clock,
        last_recheck_at: Callable[[ChatController], datetime | None],
        local_tz: tzinfo | None = None,
    ) -> None:
        """`local_tz=None` follows the system zone, re-read for every daily wait."""
        self._registry = registry
        self._config = config
        self._clock = clock
        self._last_recheck_at = last_recheck_at
        self._tz = local_tz

    async def run(self) -> None:
        if not self._config.enabled:
            log.info("recheck disabled")
            return
        now = self._clock.now()
        stale = [
            c
            for c in self._registry.all()
            if (last := self._last_recheck_at(c)) is None or now - last > STARTUP_STALE_AFTER
        ]
        await self._pass(stale, self._config.days)
        while True:
            await self._clock.sleep(
                seconds_until_next(self._config.daily_at, self._clock.now(), self._tz)
            )
            await self._pass(self._registry.all(), self._config.days)

    async def trigger_now(self, days: int | None = None, chat_id: int | None = None) -> int:
        """Request a recheck now, ignoring `enabled`; returns how many chats were asked."""
        if chat_id is None:
            targets = self._registry.all()
        else:
            controller = self._registry.get(chat_id)
            targets = [controller] if controller is not None else []
        return await self._pass(targets, days if days is not None else self._config.days)

    async def _pass(self, controllers: list[ChatController], days: int) -> int:
        for index, controller in enumerate(controllers):
            if index:
                await self._clock.sleep(self._config.pause_between_chats_sec)
            controller.request_recheck(days)
            log.info("recheck requested", extra={"chat_id": controller.chat_id, "days": days})
        return len(controllers)
