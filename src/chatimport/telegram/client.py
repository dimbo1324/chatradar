"""Telethon-backed `TelegramGateway`. The session file is only handed to Telethon: it is never
read, logged or copied here."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import UTC, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from telethon import TelegramClient, errors, events, utils
from telethon.tl import types
from telethon.tl.functions.messages import CheckChatInviteRequest

from chatimport.ports import (
    AccessLost,
    ChatEvent,
    ChatImportError,
    DeletedMessagesEvent,
    DialogInfo,
    EditedMessageEvent,
    EventHandler,
    FloodWait,
    NewMessageEvent,
    ResolvedChat,
    SessionRevoked,
)
from chatimport.telegram.mapper import map_message
from chatimport.telegram.resolve import EntityLookup, InviteInfo, entity_kind, resolve_ref

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Generator
    from datetime import datetime

    from chatimport.config import TelegramConfig
    from chatimport.ports import Clock
    from chatimport.records import MessageRecord

logger = logging.getLogger(__name__)

_ACCESS_ERRORS: Final = (
    errors.ChannelPrivateError,
    errors.ChannelBannedError,
    errors.UserBannedInChannelError,
    errors.ChatForbiddenError,
)
_SESSION_ERRORS: Final = (
    errors.AuthKeyUnregisteredError,
    errors.SessionRevokedError,
    errors.SessionExpiredError,
    errors.UnauthorizedError,
)
_INVALID_INVITE_ERRORS: Final = (
    errors.InviteHashExpiredError,
    errors.InviteHashInvalidError,
    errors.InviteHashEmptyError,
)
_UNKNOWN_USERNAME_ERRORS: Final = (
    errors.UsernameNotOccupiedError,
    errors.UsernameInvalidError,
)


_telethon_utils: Any = utils


def _peer_id(peer: Any) -> int:
    return int(_telethon_utils.get_peer_id(peer))


@contextmanager
def _translate_errors(chat_id: int | None = None) -> Generator[None]:
    try:
        yield
    except errors.FloodWaitError as error:
        raise FloodWait(int(error.seconds)) from error
    except _ACCESS_ERRORS as error:
        if chat_id is None:
            raise
        raise AccessLost(chat_id) from error
    except _SESSION_ERRORS as error:
        raise SessionRevoked("the Telegram session is no longer valid") from error


def _dialog_kind(entity: Any) -> str | None:
    if getattr(entity, "deactivated", False):
        return None
    return entity_kind(entity)


class _Lookup:
    def __init__(self, client: Any, remember: Callable[[Any], None]) -> None:
        self._client = client
        self._remember = remember

    async def get_entity_by_username(self, username: str) -> Any | None:
        try:
            with _translate_errors():
                entity = await self._client.get_entity(username)
        except (*_UNKNOWN_USERNAME_ERRORS, ValueError):
            return None
        self._remember(entity)
        return entity

    async def check_invite(self, invite_hash: str) -> InviteInfo | None:
        try:
            with _translate_errors():
                result = await self._client(CheckChatInviteRequest(invite_hash))
        except _INVALID_INVITE_ERRORS:
            return None
        if isinstance(result, types.ChatInviteAlready):
            self._remember(result.chat)
            return InviteInfo(
                is_member=True, title=getattr(result.chat, "title", None), entity=result.chat
            )
        return InviteInfo(is_member=False, title=getattr(result, "title", None))

    async def dialog_entities(self) -> list[Any]:
        entities: list[Any] = []
        with _translate_errors():
            async for dialog in self._client.iter_dialogs():
                entities.append(dialog.entity)
                self._remember(dialog.entity)
        return entities

    def peer_id(self, entity: Any) -> int:
        return _peer_id(entity)


class TelethonGateway:
    def __init__(
        self,
        config: TelegramConfig,
        session_path: Path,
        *,
        include_sender_names: bool,
        include_raw: bool,
        clock: Clock,
    ) -> None:
        self._include_sender_names = include_sender_names
        self._include_raw = include_raw
        self._clock = clock
        self._client: Any = TelegramClient(
            str(session_path),
            config.api_id,
            config.api_hash,
            flood_sleep_threshold=config.flood_sleep_threshold,
        )
        self._entities: dict[int, Any] = {}
        self._handlers: list[EventHandler] = []
        self._lookup: EntityLookup = _Lookup(self._client, self._remember)

    async def connect(self) -> None:
        with _translate_errors():
            await self._client.connect()
            if not await self._client.is_user_authorized():
                raise SessionRevoked("not logged in; run `chatimport login`")

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def list_dialogs(self) -> list[DialogInfo]:
        dialogs: list[DialogInfo] = []
        for entity in await self._lookup.dialog_entities():
            kind = _dialog_kind(entity)
            if kind is None:
                continue
            username = getattr(entity, "username", None) or None
            dialogs.append(
                DialogInfo(
                    chat_id=self._lookup.peer_id(entity),
                    title=str(getattr(entity, "title", "")),
                    username=username,
                    link=f"https://t.me/{username}" if username else None,
                    kind=kind,
                )
            )
        return dialogs

    async def resolve(self, ref: str) -> ResolvedChat:
        return await resolve_ref(ref, self._lookup)

    async def newest_id(self, chat_id: int) -> int:
        entity = await self._entity(chat_id)
        with _translate_errors(chat_id):
            messages = await self._client.get_messages(entity, limit=1)
        return int(messages[0].id) if messages else 0

    async def iter_history(
        self, chat_id: int, *, offset_id: int = 0, min_id: int = 0
    ) -> AsyncIterator[MessageRecord]:
        entity = await self._entity(chat_id)
        with _translate_errors(chat_id):
            async for message in self._client.iter_messages(
                entity, offset_id=offset_id, min_id=min_id
            ):
                if not isinstance(message, types.MessageEmpty):
                    yield self._record(message, chat_id)

    async def iter_since(self, chat_id: int, min_id: int) -> AsyncIterator[MessageRecord]:
        entity = await self._entity(chat_id)
        with _translate_errors(chat_id):
            async for message in self._client.iter_messages(entity, min_id=min_id, reverse=True):
                if not isinstance(message, types.MessageEmpty):
                    yield self._record(message, chat_id)

    async def iter_window(
        self, chat_id: int, since: datetime, max_id: int
    ) -> AsyncIterator[MessageRecord]:
        entity = await self._entity(chat_id)
        # Offset one second early: Telethon treats offset_date as exclusive.
        offset_date = since - timedelta(seconds=1)
        with _translate_errors(chat_id):
            async for message in self._client.iter_messages(
                entity, offset_date=offset_date, reverse=True
            ):
                if isinstance(message, types.MessageEmpty):
                    continue
                if message.id > max_id:
                    return
                dated = message.date if message.date.tzinfo else message.date.replace(tzinfo=UTC)
                if dated >= since:
                    yield self._record(message, chat_id)

    def add_event_handler(self, handler: EventHandler) -> None:
        if not self._handlers:
            self._client.add_event_handler(self._on_new_message, events.NewMessage())
            self._client.add_event_handler(self._on_edited_message, events.MessageEdited())
            self._client.add_event_handler(self._on_deleted_messages, events.MessageDeleted())
        self._handlers.append(handler)

    async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
        entity = await self._entity(chat_id)
        with _translate_errors(chat_id):
            message = await self._client.get_messages(entity, ids=msg_id)
            if message is None or isinstance(message, types.MessageEmpty) or not message.media:
                return None
            await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
            saved = await self._client.download_media(message, file=str(target_dir))
        return Path(saved) if saved else None

    def _remember(self, entity: Any) -> None:
        if entity_kind(entity) is not None:
            self._entities[_peer_id(entity)] = entity

    async def _entity(self, chat_id: int) -> Any:
        cached = self._entities.get(chat_id)
        if cached is not None:
            return cached
        try:
            with _translate_errors(chat_id):
                entity = await self._client.get_entity(chat_id)
        except ValueError:
            entity = None
        if entity is None or entity_kind(entity) is None:
            await self._lookup.dialog_entities()
            entity = self._entities.get(chat_id)
        if entity is None:
            raise AccessLost(chat_id)
        self._remember(entity)
        return entity

    def _record(self, message: Any, chat_id: int) -> MessageRecord:
        entity = self._entities.get(chat_id)
        return map_message(
            message,
            chat_id=chat_id,
            chat_username=getattr(entity, "username", None) or None,
            fetched_at=self._clock.now(),
            include_sender_names=self._include_sender_names,
            include_raw=self._include_raw,
        )

    async def _event_record(self, event: Any) -> MessageRecord | None:
        message = event.message
        chat_id = _peer_id(message.peer_id)
        if event.is_private:
            return None
        if chat_id not in self._entities:
            try:
                self._remember(await event.get_chat())
            except errors.RPCError, ValueError:
                logger.warning("cannot load chat %s for an event", chat_id)
        if self._include_sender_names:
            try:
                await message.get_sender()
            except errors.RPCError, ValueError:
                logger.warning("cannot load the sender of message %s in %s", message.id, chat_id)
        return self._record(message, chat_id)

    async def _dispatch(self, event: ChatEvent) -> None:
        for handler in list(self._handlers):
            await handler(event)

    async def _on_new_message(self, event: Any) -> None:
        record = await self._event_record(event)
        if record is not None:
            await self._dispatch(NewMessageEvent(record))

    async def _on_edited_message(self, event: Any) -> None:
        record = await self._event_record(event)
        if record is not None:
            await self._dispatch(EditedMessageEvent(record))

    async def _on_deleted_messages(self, event: Any) -> None:
        chat_id = event.chat_id
        ids = tuple(int(msg_id) for msg_id in event.deleted_ids)
        await self._dispatch(DeletedMessagesEvent(None if chat_id is None else int(chat_id), ids))


async def login(
    config: TelegramConfig,
    session_path: Path,
    *,
    prompt_phone: Callable[[], str],
    prompt_code: Callable[[], str],
    prompt_password: Callable[[], str],
) -> str:
    """Interactive login; returns `@username` or `id <n>` of the account, never a phone."""
    if not config.is_configured:
        raise ChatImportError("telegram api_id and api_hash are not set in config.toml")
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client: Any = TelegramClient(
        str(session_path),
        config.api_id,
        config.api_hash,
        flood_sleep_threshold=config.flood_sleep_threshold,
    )
    try:
        with _translate_errors():
            await client.start(
                phone=prompt_phone, code_callback=prompt_code, password=prompt_password
            )
            me = await client.get_me()
    finally:
        await client.disconnect()
    username = getattr(me, "username", None)
    return f"@{username}" if username else f"id {me.id}"
