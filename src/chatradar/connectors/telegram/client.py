"""The live Telegram connector: a Telethon user-account client behind the `Connector` port.

Telethon is untyped, so it stays `Any` here and everything leaving this module is a domain
type. FloodWait up to `flood_sleep_threshold` seconds is slept through by Telethon itself;
a longer one raises and stops the sync, whose progress is already saved per batch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Self

from chatradar.connectors.telegram.serialize import to_jsonable
from chatradar.domain.models import ChatInfo, ChatKind, RawKind, RawRecord, Source

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from types import TracebackType

    from chatradar.config import Settings

type ClientFactory = Callable[[Settings], Any]


class TelegramNotConfiguredError(RuntimeError):
    """`CHATRADAR_TELEGRAM__API_ID` and `__API_HASH` are not set."""


class TelegramNotLoggedInError(RuntimeError):
    """No authorized session yet: run `chatradar telegram login` first."""


def make_client(settings: Settings) -> Any:
    """A Telethon client on `<data_dir>/sessions/<session_name>`; not connected yet."""
    from telethon import TelegramClient  # heavy; imported only on the live path

    telegram = settings.telegram
    if telegram.api_id is None or telegram.api_hash is None:
        raise TelegramNotConfiguredError(
            "set CHATRADAR_TELEGRAM__API_ID and CHATRADAR_TELEGRAM__API_HASH"
        )
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(settings.sessions_dir / telegram.session_name),
        telegram.api_id,
        telegram.api_hash.get_secret_value(),
        flood_sleep_threshold=telegram.flood_sleep_threshold,
    )


class TelegramConnector:
    """`Connector` over Telethon. Use as `async with TelegramConnector(settings) as tg:`."""

    source = Source.TELEGRAM

    def __init__(self, settings: Settings, client_factory: ClientFactory = make_client) -> None:
        self._client: Any = client_factory(settings)

    async def __aenter__(self) -> Self:
        await self._client.connect()
        if not await self._client.is_user_authorized():
            await self._client.disconnect()
            raise TelegramNotLoggedInError("run `chatradar telegram login` first")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.disconnect()

    async def list_chats(self) -> list[ChatInfo]:
        """Groups, supergroups and channels the account is a member of."""
        chats: list[ChatInfo] = []
        async for dialog in self._client.iter_dialogs():
            chat = chat_info(dialog.entity)
            if chat is not None and chat.kind is not ChatKind.PRIVATE:
                chats.append(chat)
        return chats

    async def resolve(self, ref: str) -> ChatInfo:
        """A chat by `@username`, `t.me/<username>` link or marked numeric id."""
        target = ref.strip().removeprefix("https://").removeprefix("t.me/").lstrip("@")
        entity = await self._client.get_entity(int(target) if _is_int(target) else target)
        chat = chat_info(entity)
        if chat is None:
            raise ValueError(f"{ref!r} is not a chat")
        return chat

    async def fetch(self, chat: ChatInfo, since_id: str | None) -> AsyncIterator[RawRecord]:
        """Messages with id > since_id, oldest first."""
        min_id = int(since_id) if since_id else 0
        messages = self._client.iter_messages(_entity_ref(chat), min_id=min_id, reverse=True)
        async for message in messages:
            yield _record(chat, message)

    async def fetch_recent(self, chat: ChatInfo, days: int) -> AsyncIterator[RawRecord]:
        """Messages of the last `days` days, oldest first — to catch edits."""
        since = datetime.now(UTC) - timedelta(days=days)
        messages = self._client.iter_messages(_entity_ref(chat), offset_date=since, reverse=True)
        async for message in messages:
            yield _record(chat, message)


async def login(settings: Settings, client_factory: ClientFactory = make_client) -> str:
    """Interactive first login (phone, code, 2FA in the terminal); the account's handle."""
    client: Any = client_factory(settings)
    try:
        await client.start()
        me: Any = await client.get_me()
    finally:
        await client.disconnect()
    username = getattr(me, "username", None)
    if username:
        return f"@{username}"
    return str(getattr(me, "first_name", None) or getattr(me, "id", "unknown"))


def chat_info(entity: Any) -> ChatInfo | None:
    """A Telethon `Channel`, `Chat` or `User` as `ChatInfo` in the marked id form."""
    kind_name = type(entity).__name__
    if kind_name not in ("Channel", "ChannelForbidden", "Chat", "ChatForbidden", "User"):
        return None
    entity_id = int(entity.id)
    username: str | None = getattr(entity, "username", None) or None
    if kind_name in ("Channel", "ChannelForbidden"):
        kind = ChatKind.SUPERGROUP if getattr(entity, "megagroup", False) else ChatKind.CHANNEL
        chat_id = f"-100{entity_id}"
    elif kind_name in ("Chat", "ChatForbidden"):
        kind, chat_id = ChatKind.GROUP, f"-{entity_id}"
    else:
        kind, chat_id = ChatKind.PRIVATE, str(entity_id)
    title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or chat_id
    return ChatInfo(
        source=Source.TELEGRAM, chat_id=chat_id, title=str(title), username=username, kind=kind
    )


def _entity_ref(chat: ChatInfo) -> str | int:
    return chat.username or int(chat.chat_id)


def _is_int(value: str) -> bool:
    return value.removeprefix("-").isdigit()


def _record(chat: ChatInfo, message: Any) -> RawRecord:
    payload = to_jsonable(message.to_dict())
    if not isinstance(payload, dict):
        raise TypeError("Message.to_dict() did not return a mapping")
    return RawRecord(
        source=Source.TELEGRAM,
        kind=RawKind.TELETHON,
        chat_id=chat.chat_id,
        fetched_at=datetime.now(UTC),
        payload=payload,
    )
