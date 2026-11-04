from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from telethon import errors, events
from telethon.tl import types as tl
from telethon.tl.functions.messages import CheckChatInviteRequest

from chatimport.config import TelegramConfig
from chatimport.ports import (
    AccessLost,
    ChatEvent,
    ChatImportError,
    DeletedMessagesEvent,
    EditedMessageEvent,
    FloodWait,
    NewMessageEvent,
    ResolveStatus,
    SessionRevoked,
)
from chatimport.telegram import client as client_mod
from chatimport.telegram.client import TelethonGateway, login
from tests.fakes import NOW, FakeClock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

CHANNEL_ID = 1234567890
CHAT_ID = -1001234567890
CONFIG = TelegramConfig(api_id=12345, api_hash="hash", flood_sleep_threshold=77)


class FakeTelegramClient:
    """Scripted stand-in for `telethon.TelegramClient`; nothing leaves the process."""

    created: list[FakeTelegramClient] = []  # noqa: RUF012
    default_start_error: BaseException | None = None
    default_me: Any = SimpleNamespace(id=777, username="owner", phone="+598000111222")

    def __init__(self, session: str, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.kwargs = kwargs
        self.authorized = True
        self.connect_error: BaseException | None = None
        self.authorized_error: BaseException | None = None
        self.entities: dict[Any, Any] = {}
        self.entity_errors: dict[Any, BaseException] = {}
        self.dialogs: list[Any] = []
        self.dialog_error: BaseException | None = None
        self.history: list[Any] = []
        self.history_error: BaseException | None = None
        self.history_error_after = 0
        self.by_id: dict[int, Any] = {}
        self.latest: list[Any] = []
        self.latest_error: BaseException | None = None
        self.request_results: dict[str, Any] = {}
        self.downloaded: str | None = None
        self.start_error = FakeTelegramClient.default_start_error
        self.me = FakeTelegramClient.default_me
        self.calls: list[tuple[str, Any]] = []
        self.handlers: list[tuple[Callable[..., Any], Any]] = []
        self.disconnects = 0
        FakeTelegramClient.created.append(self)

    async def connect(self) -> None:
        self.calls.append(("connect", None))
        if self.connect_error:
            raise self.connect_error

    async def is_user_authorized(self) -> bool:
        if self.authorized_error:
            raise self.authorized_error
        return self.authorized

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def get_entity(self, key: Any) -> Any:
        self.calls.append(("get_entity", key))
        if key in self.entity_errors:
            raise self.entity_errors[key]
        if key not in self.entities:
            raise ValueError("Could not find the input entity")
        return self.entities[key]

    async def get_messages(
        self, entity: Any, limit: int | None = None, ids: int | None = None
    ) -> Any:
        self.calls.append(("get_messages", {"limit": limit, "ids": ids}))
        if self.latest_error:
            raise self.latest_error
        if ids is not None:
            return self.by_id.get(ids)
        return self.latest

    async def iter_messages(self, entity: Any, **kwargs: Any) -> AsyncIterator[Any]:
        self.calls.append(("iter_messages", kwargs))
        for index, message in enumerate(self.history):
            if self.history_error and index == self.history_error_after:
                raise self.history_error
            yield message
        if self.history_error and self.history_error_after >= len(self.history):
            raise self.history_error

    async def iter_dialogs(self) -> AsyncIterator[Any]:
        self.calls.append(("iter_dialogs", None))
        for entity in self.dialogs:
            yield SimpleNamespace(entity=entity)
        if self.dialog_error:
            raise self.dialog_error

    async def __call__(self, request: Any) -> Any:
        name = type(request).__name__
        self.calls.append(("request", request))
        result = self.request_results[name]
        if isinstance(result, BaseException):
            raise result
        return result

    def add_event_handler(self, callback: Callable[..., Any], event: Any) -> None:
        self.handlers.append((callback, event))

    async def download_media(self, message: Any, file: str) -> str | None:
        self.calls.append(("download_media", {"message": message, "file": file}))
        return self.downloaded

    async def start(self, **kwargs: Any) -> None:
        self.calls.append(("start", kwargs))
        for key in ("phone", "code_callback", "password"):
            kwargs[key]()
        if self.start_error:
            raise self.start_error

    async def get_me(self) -> Any:
        return self.me

    def names(self, kind: str) -> list[Any]:
        return [payload for name, payload in self.calls if name == kind]


@pytest.fixture(autouse=True)
def fake_telethon_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTelegramClient.created = []
    monkeypatch.setattr(client_mod, "TelegramClient", FakeTelegramClient)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_gateway(
    clock: FakeClock, *, names: bool = True, raw: bool = False
) -> tuple[TelethonGateway, FakeTelegramClient]:
    gateway = TelethonGateway(
        CONFIG,
        Path("session") / "chatimport.session",
        include_sender_names=names,
        include_raw=raw,
        clock=clock,
    )
    return gateway, FakeTelegramClient.created[-1]


def channel(
    channel_id: int = CHANNEL_ID,
    title: str = "Example",
    *,
    megagroup: bool = True,
    username: str | None = None,
) -> tl.Channel:
    return tl.Channel(
        id=channel_id,
        title=title,
        photo=tl.ChatPhotoEmpty(),
        date=NOW,
        megagroup=megagroup,
        broadcast=not megagroup,
        username=username,
    )


def basic_group(group_id: int = 5, title: str = "Basic", *, deactivated: bool = False) -> tl.Chat:
    return tl.Chat(
        id=group_id,
        title=title,
        photo=tl.ChatPhotoEmpty(),
        participants_count=3,
        date=NOW,
        version=1,
        deactivated=deactivated,
    )


def tg_message(msg_id: int, date: datetime | None = None, **kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": msg_id,
        "date": date or NOW - timedelta(hours=10 - msg_id),
        "message": f"text {msg_id}",
        "to_dict": lambda: {"id": msg_id},
    }
    base.update(kw)
    return SimpleNamespace(**base)


def empty(msg_id: int) -> tl.MessageEmpty:
    return tl.MessageEmpty(id=msg_id, peer_id=None)


async def collect[T](items: AsyncIterator[T]) -> list[T]:
    return [item async for item in items]


async def ready(clock: FakeClock) -> tuple[TelethonGateway, FakeTelegramClient]:
    gateway, fake = make_gateway(clock)
    fake.entities[CHAT_ID] = channel(username="pub")
    return gateway, fake


def test_gateway_hands_credentials_and_session_to_telethon(clock: FakeClock) -> None:
    _, fake = make_gateway(clock)
    assert fake.session == str(Path("session") / "chatimport.session")
    assert (fake.api_id, fake.api_hash) == (12345, "hash")
    assert fake.kwargs == {"flood_sleep_threshold": 77}
    assert len(FakeTelegramClient.created) == 1


class TestConnect:
    async def test_connect_succeeds_when_authorised(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        await gateway.connect()
        assert fake.names("connect") == [None]

    async def test_unauthorised_session_is_revoked(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.authorized = False
        with pytest.raises(SessionRevoked, match="login"):
            await gateway.connect()

    async def test_auth_key_error_while_checking_is_a_revoked_session(
        self, clock: FakeClock
    ) -> None:
        gateway, fake = make_gateway(clock)
        fake.authorized_error = errors.AuthKeyUnregisteredError(request=None)
        with pytest.raises(SessionRevoked):
            await gateway.connect()

    async def test_flood_wait_on_connect_is_translated(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.connect_error = errors.FloodWaitError(request=None, capture=900)
        with pytest.raises(FloodWait) as info:
            await gateway.connect()
        assert info.value.seconds == 900

    async def test_network_errors_are_not_swallowed(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.connect_error = ConnectionError("no route")
        with pytest.raises(ConnectionError):
            await gateway.connect()

    async def test_disconnect_reaches_the_client(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        await gateway.disconnect()
        assert fake.disconnects == 1


class TestTranslateErrors:
    def test_flood_wait_keeps_seconds_and_cause(self) -> None:
        original = errors.FloodWaitError(request=None, capture=45)
        with pytest.raises(FloodWait) as info, client_mod._translate_errors(5):  # pyright: ignore[reportPrivateUsage]
            raise original
        assert info.value.seconds == 45
        assert info.value.__cause__ is original

    @pytest.mark.parametrize(
        "error_type",
        [
            errors.ChannelPrivateError,
            errors.ChannelBannedError,
            errors.UserBannedInChannelError,
            errors.ChatForbiddenError,
        ],
    )
    def test_access_errors_become_access_lost_for_a_chat(self, error_type: type[Any]) -> None:
        with pytest.raises(AccessLost) as info, client_mod._translate_errors(CHAT_ID):  # pyright: ignore[reportPrivateUsage]
            raise error_type(request=None)
        assert info.value.chat_id == CHAT_ID

    def test_access_errors_without_a_chat_are_re_raised_as_they_are(self) -> None:
        with pytest.raises(errors.ChannelPrivateError), client_mod._translate_errors():  # pyright: ignore[reportPrivateUsage]
            raise errors.ChannelPrivateError(request=None)

    @pytest.mark.parametrize("chat_id", [None, CHAT_ID])
    @pytest.mark.parametrize(
        "error",
        [
            errors.AuthKeyUnregisteredError(request=None),
            errors.SessionRevokedError(request=None),
            errors.SessionExpiredError(request=None),
            errors.UnauthorizedError(request=None, message="x"),
        ],
    )
    def test_session_errors_become_session_revoked(
        self, error: BaseException, chat_id: int | None
    ) -> None:
        with pytest.raises(SessionRevoked), client_mod._translate_errors(chat_id):  # pyright: ignore[reportPrivateUsage]
            raise error

    @pytest.mark.parametrize("error", [ValueError("x"), OSError("x"), errors.RPCError(None, "x")])
    def test_other_errors_pass_through(self, error: BaseException) -> None:
        with pytest.raises(type(error)), client_mod._translate_errors(CHAT_ID):  # pyright: ignore[reportPrivateUsage]
            raise error

    def test_clean_block_is_untouched(self) -> None:
        with client_mod._translate_errors(CHAT_ID):  # pyright: ignore[reportPrivateUsage]
            value = 1
        assert value == 1


class TestListDialogs:
    async def test_only_live_groups_and_channels_are_listed(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [
            channel(1, "Super", megagroup=True, username="super_g"),
            channel(2, "Broadcast", megagroup=False),
            basic_group(5, "Basic"),
            basic_group(6, "Migrated", deactivated=True),
            tl.User(id=9, first_name="Person"),
            tl.User(id=10, first_name="Bot", bot=True),
            tl.ChannelForbidden(id=11, access_hash=1, title="Gone"),
        ]
        dialogs = await gateway.list_dialogs()
        assert [(d.chat_id, d.title, d.username, d.link, d.kind) for d in dialogs] == [
            (-1000000000001, "Super", "super_g", "https://t.me/super_g", "supergroup"),
            (-1000000000002, "Broadcast", None, None, "channel"),
            (-5, "Basic", None, None, "group"),
        ]

    async def test_empty_username_gives_no_link(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [channel(1, "T", username="")]
        (dialog,) = await gateway.list_dialogs()
        assert (dialog.username, dialog.link) == (None, None)

    async def test_no_dialogs(self, clock: FakeClock) -> None:
        gateway, _ = make_gateway(clock)
        assert await gateway.list_dialogs() == []

    async def test_flood_wait_while_listing(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialog_error = errors.FloodWaitError(request=None, capture=10)
        with pytest.raises(FloodWait):
            await gateway.list_dialogs()

    async def test_listed_dialogs_are_cached_for_later_calls(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [channel()]
        fake.latest = [tg_message(41)]
        await gateway.list_dialogs()
        assert await gateway.newest_id(CHAT_ID) == 41
        assert fake.names("get_entity") == []


class TestResolveThroughTelethon:
    async def test_public_username_is_looked_up_and_cached(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entities["pub"] = channel(username="pub")
        result = await gateway.resolve("https://t.me/pub")
        assert (result.status, result.chat_id, result.username) == (
            ResolveStatus.FOUND,
            CHAT_ID,
            "pub",
        )
        fake.latest = [tg_message(3)]
        assert await gateway.newest_id(CHAT_ID) == 3
        assert fake.names("get_entity") == ["pub"]

    @pytest.mark.parametrize(
        "error",
        [
            errors.UsernameNotOccupiedError(request=None),
            errors.UsernameInvalidError(request=None),
            ValueError("x"),
        ],
    )
    async def test_unknown_username_is_not_found(
        self, clock: FakeClock, error: BaseException
    ) -> None:
        gateway, fake = make_gateway(clock)
        fake.entity_errors["ghost"] = error
        assert (await gateway.resolve("@ghost")).status is ResolveStatus.NOT_FOUND

    async def test_person_username_is_not_a_chat_and_not_cached(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entities["someone"] = tl.User(id=9, first_name="P")
        assert (await gateway.resolve("@someone")).status is ResolveStatus.NOT_A_CHAT

    async def test_flood_wait_during_username_lookup(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entity_errors["pub"] = errors.FloodWaitError(request=None, capture=33)
        with pytest.raises(FloodWait) as info:
            await gateway.resolve("@pub")
        assert info.value.seconds == 33

    async def test_invite_for_a_chat_the_account_is_in(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.request_results["CheckChatInviteRequest"] = tl.ChatInviteAlready(
            chat=channel(title="Mine")
        )
        result = await gateway.resolve("https://t.me/+secret")
        assert (result.status, result.chat_id, result.title) == (
            ResolveStatus.FOUND,
            CHAT_ID,
            "Mine",
        )
        (request,) = fake.names("request")
        assert isinstance(request, CheckChatInviteRequest)
        assert request.hash == "secret"

    async def test_invite_for_a_chat_the_account_is_not_in_never_joins(
        self, clock: FakeClock
    ) -> None:
        gateway, fake = make_gateway(clock)
        fake.request_results["CheckChatInviteRequest"] = SimpleNamespace(title="Club")
        result = await gateway.resolve("https://t.me/joinchat/xyz")
        assert (result.status, result.title) == (ResolveStatus.NEED_TO_JOIN, "Club")
        assert [type(r).__name__ for r in fake.names("request")] == ["CheckChatInviteRequest"]
        assert {name for name, _ in fake.calls} <= {"request", "get_entity", "iter_dialogs"}

    @pytest.mark.parametrize(
        "error",
        [
            errors.InviteHashExpiredError(request=None),
            errors.InviteHashInvalidError(request=None),
            errors.InviteHashEmptyError(request=None),
        ],
    )
    async def test_invalid_invite_is_not_found(
        self, clock: FakeClock, error: BaseException
    ) -> None:
        gateway, fake = make_gateway(clock)
        fake.request_results["CheckChatInviteRequest"] = error
        assert (await gateway.resolve("t.me/+bad")).status is ResolveStatus.NOT_FOUND

    async def test_flood_wait_on_invite_check(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.request_results["CheckChatInviteRequest"] = errors.FloodWaitError(
            request=None, capture=5
        )
        with pytest.raises(FloodWait):
            await gateway.resolve("t.me/+x")

    async def test_title_and_number_use_the_dialogs(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [channel(title="Montevideo"), basic_group(5, "Basic")]
        assert (await gateway.resolve("Montevideo")).chat_id == CHAT_ID
        assert (await gateway.resolve("-100" + str(CHANNEL_ID))).chat_id == CHAT_ID
        assert (await gateway.resolve("5")).chat_id == -5


class TestNewestId:
    async def test_empty_chat_gives_zero(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.latest = []
        assert await gateway.newest_id(CHAT_ID) == 0
        assert fake.names("get_messages") == [{"limit": 1, "ids": None}]

    async def test_newest_message_id(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.latest = [tg_message(4512)]
        assert await gateway.newest_id(CHAT_ID) == 4512

    async def test_access_lost_is_translated(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.latest_error = errors.ChannelPrivateError(request=None)
        with pytest.raises(AccessLost) as info:
            await gateway.newest_id(CHAT_ID)
        assert info.value.chat_id == CHAT_ID

    async def test_flood_wait_is_translated(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.latest_error = errors.FloodWaitError(request=None, capture=61)
        with pytest.raises(FloodWait):
            await gateway.newest_id(CHAT_ID)


class TestEntityCache:
    async def test_entity_is_fetched_once(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.latest = []
        await gateway.newest_id(CHAT_ID)
        await gateway.newest_id(CHAT_ID)
        assert fake.names("get_entity") == [CHAT_ID]

    async def test_dialog_scan_is_the_fallback_for_an_unknown_entity(
        self, clock: FakeClock
    ) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [channel()]
        fake.latest = [tg_message(8)]
        assert await gateway.newest_id(CHAT_ID) == 8
        assert fake.names("get_entity") == [CHAT_ID]
        assert fake.names("iter_dialogs") == [None]
        await gateway.newest_id(CHAT_ID)
        assert fake.names("iter_dialogs") == [None]

    async def test_entity_of_the_wrong_kind_triggers_the_dialog_scan(
        self, clock: FakeClock
    ) -> None:
        gateway, fake = make_gateway(clock)
        fake.entities[CHAT_ID] = tl.User(id=9, first_name="P")
        fake.dialogs = [channel()]
        fake.latest = [tg_message(2)]
        assert await gateway.newest_id(CHAT_ID) == 2
        assert fake.names("iter_dialogs") == [None]

    async def test_unknown_chat_is_access_lost(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [channel(999)]
        with pytest.raises(AccessLost) as info:
            await gateway.newest_id(CHAT_ID)
        assert info.value.chat_id == CHAT_ID

    async def test_private_channel_error_while_fetching_the_entity(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entity_errors[CHAT_ID] = errors.ChannelPrivateError(request=None)
        with pytest.raises(AccessLost):
            await gateway.newest_id(CHAT_ID)
        assert fake.names("iter_dialogs") == []

    async def test_flood_wait_while_fetching_the_entity(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entity_errors[CHAT_ID] = errors.FloodWaitError(request=None, capture=12)
        with pytest.raises(FloodWait):
            await gateway.newest_id(CHAT_ID)

    async def test_revoked_session_while_fetching_the_entity(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entity_errors[CHAT_ID] = errors.AuthKeyUnregisteredError(request=None)
        with pytest.raises(SessionRevoked):
            await gateway.newest_id(CHAT_ID)

    async def test_basic_group_entity_is_cached_too(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entities[-5] = basic_group(5)
        fake.latest = [tg_message(1)]
        await gateway.newest_id(-5)
        await gateway.newest_id(-5)
        assert fake.names("get_entity") == [-5]


class TestIterHistory:
    async def test_defaults_and_arguments_reach_telethon(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [tg_message(9), tg_message(8)]
        records = await collect(gateway.iter_history(CHAT_ID))
        assert [r.msg_id for r in records] == [9, 8]
        assert fake.names("iter_messages") == [{"offset_id": 0, "min_id": 0}]
        await collect(gateway.iter_history(CHAT_ID, offset_id=50, min_id=10))
        assert fake.names("iter_messages")[-1] == {"offset_id": 50, "min_id": 10}

    async def test_empty_messages_are_skipped(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [tg_message(9), empty(8), empty(7), tg_message(6)]
        assert [r.msg_id for r in await collect(gateway.iter_history(CHAT_ID))] == [9, 6]

    async def test_records_carry_clock_username_and_flags(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock, names=False, raw=True)
        fake.entities[CHAT_ID] = channel(username="pub")
        sender = SimpleNamespace(first_name="Ann", last_name=None, username="ann")
        fake.history = [tg_message(9, sender=sender, sender_id=4)]
        clock.advance(hours=5)
        (record,) = await collect(gateway.iter_history(CHAT_ID))
        assert record.fetched_at == NOW + timedelta(hours=5)
        assert record.link == "https://t.me/pub/9"
        assert record.chat_id == CHAT_ID
        assert (record.sender_id, record.sender_name, record.sender_username) == (4, None, None)
        assert record.raw == {"id": 9}

    async def test_private_chat_link_without_username(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.entities[CHAT_ID] = channel()
        fake.history = [tg_message(9)]
        (record,) = await collect(gateway.iter_history(CHAT_ID))
        assert record.link == "https://t.me/c/1234567890/9"

    async def test_empty_history(self, clock: FakeClock) -> None:
        gateway, _ = await ready(clock)
        assert await collect(gateway.iter_history(CHAT_ID)) == []

    async def test_access_lost_mid_stream_keeps_earlier_records(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [tg_message(9), tg_message(8), tg_message(7)]
        fake.history_error = errors.ChannelPrivateError(request=None)
        fake.history_error_after = 2
        seen: list[int] = []

        async def drain() -> None:
            async for record in gateway.iter_history(CHAT_ID):
                seen.append(record.msg_id)

        with pytest.raises(AccessLost):
            await drain()
        assert seen == [9, 8]

    async def test_flood_wait_mid_stream(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [tg_message(9)]
        fake.history_error = errors.FloodWaitError(request=None, capture=300)
        fake.history_error_after = 1
        with pytest.raises(FloodWait) as info:
            await collect(gateway.iter_history(CHAT_ID))
        assert info.value.seconds == 300

    async def test_unknown_chat_raises_on_first_item(self, clock: FakeClock) -> None:
        gateway, _ = make_gateway(clock)
        with pytest.raises(AccessLost):
            await collect(gateway.iter_history(CHAT_ID))

    async def test_closing_the_stream_early_is_clean(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [tg_message(9), tg_message(8)]
        stream: Any = gateway.iter_history(CHAT_ID)
        first = await anext(stream)
        assert first.msg_id == 9
        await stream.aclose()


class TestIterSince:
    async def test_arguments_and_order(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [tg_message(11), empty(12), tg_message(13)]
        records = await collect(gateway.iter_since(CHAT_ID, 10))
        assert [r.msg_id for r in records] == [11, 13]
        assert fake.names("iter_messages") == [{"min_id": 10, "reverse": True}]

    async def test_access_lost(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = []
        fake.history_error = errors.ChatForbiddenError(request=None)
        with pytest.raises(AccessLost):
            await collect(gateway.iter_since(CHAT_ID, 0))


class TestIterWindow:
    SINCE = datetime(2026, 10, 25, 0, 0, 0, tzinfo=UTC)

    def window_history(self) -> list[Any]:
        return [
            tg_message(1, self.SINCE - timedelta(seconds=1)),
            tg_message(2, self.SINCE),
            tg_message(3, self.SINCE + timedelta(seconds=1)),
            tg_message(4, self.SINCE + timedelta(hours=1)),
            tg_message(5, self.SINCE + timedelta(hours=2)),
        ]

    async def test_offset_is_one_second_early_and_reversed(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        await collect(gateway.iter_window(CHAT_ID, self.SINCE, 10))
        assert fake.names("iter_messages") == [
            {"offset_date": self.SINCE - timedelta(seconds=1), "reverse": True}
        ]

    async def test_messages_before_since_are_cut_and_since_itself_is_kept(
        self, clock: FakeClock
    ) -> None:
        gateway, fake = await ready(clock)
        fake.history = self.window_history()
        records = await collect(gateway.iter_window(CHAT_ID, self.SINCE, 99))
        assert [r.msg_id for r in records] == [2, 3, 4, 5]

    async def test_stops_after_max_id_inclusive(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = self.window_history()
        records = await collect(gateway.iter_window(CHAT_ID, self.SINCE, 4))
        assert [r.msg_id for r in records] == [2, 3, 4]

    async def test_max_id_below_everything_yields_nothing(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = self.window_history()
        assert await collect(gateway.iter_window(CHAT_ID, self.SINCE, 0)) == []

    async def test_empty_messages_are_skipped_even_beyond_max_id(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [empty(1), tg_message(2, self.SINCE), empty(50), tg_message(3, self.SINCE)]
        records = await collect(gateway.iter_window(CHAT_ID, self.SINCE, 10))
        assert [r.msg_id for r in records] == [2, 3]

    async def test_non_utc_since_is_compared_as_an_instant(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = self.window_history()
        since = self.SINCE.astimezone(timezone_plus(3))
        records = await collect(gateway.iter_window(CHAT_ID, since, 99))
        assert [r.msg_id for r in records] == [2, 3, 4, 5]

    async def test_naive_telegram_dates_are_treated_as_utc(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history = [
            tg_message(1, datetime(2026, 10, 25, 0, 0, 1)),  # noqa: DTZ001 naive on purpose
            tg_message(2, datetime(2026, 10, 24, 23, 0, 0)),  # noqa: DTZ001 naive on purpose
        ]
        records = await collect(gateway.iter_window(CHAT_ID, self.SINCE, 99))
        assert [r.msg_id for r in records] == [1]

    async def test_access_lost(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        fake.history_error = errors.ChannelPrivateError(request=None)
        with pytest.raises(AccessLost):
            await collect(gateway.iter_window(CHAT_ID, self.SINCE, 99))


def timezone_plus(hours: int) -> timezone:
    return timezone(timedelta(hours=hours))


class TestEvents:
    def message_event(
        self,
        *,
        peer: Any | None = None,
        private: bool = False,
        chat: Any = None,
        sender_error: BaseException | None = None,
        chat_error: BaseException | None = None,
    ) -> SimpleNamespace:
        sender_calls: list[int] = []

        async def get_sender() -> Any:
            sender_calls.append(1)
            if sender_error:
                raise sender_error
            return None

        async def get_chat() -> Any:
            if chat_error:
                raise chat_error
            return chat

        message = tg_message(9, peer_id=peer or tl.PeerChannel(CHANNEL_ID), get_sender=get_sender)
        event = SimpleNamespace(
            message=message, is_private=private, get_chat=get_chat, sender_calls=sender_calls
        )
        return event

    def callbacks(self, fake: FakeTelegramClient) -> dict[str, Callable[..., Any]]:
        return {type(event).__name__: callback for callback, event in fake.handlers}

    async def recorder(
        self, gateway: TelethonGateway, fake: FakeTelegramClient
    ) -> tuple[list[ChatEvent], dict[str, Callable[..., Any]]]:
        seen: list[ChatEvent] = []

        async def handler(event: ChatEvent) -> None:
            seen.append(event)

        gateway.add_event_handler(handler)
        return seen, self.callbacks(fake)

    async def test_telethon_handlers_are_registered_once(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)

        async def handler(event: ChatEvent) -> None:
            return None

        gateway.add_event_handler(handler)
        gateway.add_event_handler(handler)
        gateway.add_event_handler(handler)
        kinds: list[Any] = [type(event) for _, event in fake.handlers]
        assert kinds == [events.NewMessage, events.MessageEdited, events.MessageDeleted]

    async def test_no_registration_without_handlers(self, clock: FakeClock) -> None:
        _, fake = make_gateway(clock)
        assert fake.handlers == []

    async def test_new_message_reaches_every_handler_in_order(self, clock: FakeClock) -> None:
        gateway, fake = await ready(clock)
        order: list[str] = []

        async def first(event: ChatEvent) -> None:
            order.append(f"first:{type(event).__name__}")

        async def second(event: ChatEvent) -> None:
            order.append("second")

        gateway.add_event_handler(first)
        gateway.add_event_handler(second)
        await self.callbacks(fake)["NewMessage"](self.message_event(chat=channel(username="pub")))
        assert order == ["first:NewMessageEvent", "second"]

    async def test_new_message_is_mapped_with_chat_username(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        await callbacks["NewMessage"](self.message_event(chat=channel(username="pub")))
        (event,) = seen
        assert isinstance(event, NewMessageEvent)
        assert (event.record.chat_id, event.record.msg_id) == (CHAT_ID, 9)
        assert event.record.link == "https://t.me/pub/9"
        assert event.record.fetched_at == NOW

    async def test_known_chat_is_not_fetched_again(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        fake.dialogs = [channel(username="pub")]
        await gateway.list_dialogs()
        seen, callbacks = await self.recorder(gateway, fake)

        def forbidden() -> Any:
            raise AssertionError("get_chat must not be called for a cached chat")

        event = self.message_event()
        event.get_chat = forbidden
        await callbacks["NewMessage"](event)
        assert len(seen) == 1

    async def test_edited_message_event(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        event = self.message_event(chat=channel())
        event.message.edit_date = NOW
        await callbacks["MessageEdited"](event)
        (edited,) = seen
        assert isinstance(edited, EditedMessageEvent)
        assert edited.record.edit_date == NOW

    async def test_private_chats_are_dropped(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        event = self.message_event(peer=tl.PeerUser(5), private=True)
        await callbacks["NewMessage"](event)
        await callbacks["MessageEdited"](event)
        assert seen == []
        assert event.sender_calls == []

    async def test_chat_lookup_failures_are_logged_not_raised(
        self, clock: FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        for error in (errors.ChannelPrivateError(request=None), ValueError("gone")):
            await callbacks["NewMessage"](self.message_event(chat_error=error))
        assert len(seen) == 2
        assert all(isinstance(e, NewMessageEvent) and e.record.link for e in seen)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert str(CHAT_ID) in warnings[0].getMessage()
        assert "text 9" not in caplog.text

    async def test_sender_lookup_failure_is_logged_not_raised(
        self, clock: FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        event = self.message_event(
            chat=channel(), sender_error=errors.FloodWaitError(request=None, capture=1)
        )
        await callbacks["NewMessage"](event)
        assert len(seen) == 1
        assert any("sender" in r.getMessage() for r in caplog.records)
        assert "text 9" not in caplog.text

    async def test_sender_is_not_loaded_when_names_are_off(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock, names=False)
        seen, callbacks = await self.recorder(gateway, fake)
        event = self.message_event(chat=channel())
        await callbacks["NewMessage"](event)
        assert len(seen) == 1
        assert event.sender_calls == []

    async def test_sender_is_loaded_when_names_are_on(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        _, callbacks = await self.recorder(gateway, fake)
        event = self.message_event(chat=channel())
        await callbacks["NewMessage"](event)
        assert event.sender_calls == [1]

    @pytest.mark.parametrize(
        ("chat_id", "ids", "expected_chat"),
        [(None, [4, 2, 3], None), (CHAT_ID, [1], CHAT_ID), (-5, [], -5)],
    )
    async def test_deleted_messages_event(
        self, clock: FakeClock, chat_id: int | None, ids: list[int], expected_chat: int | None
    ) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        await callbacks["MessageDeleted"](SimpleNamespace(chat_id=chat_id, deleted_ids=ids))
        assert seen == [DeletedMessagesEvent(expected_chat, tuple(ids))]

    async def test_deleted_ids_may_be_any_integer_like(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        seen, callbacks = await self.recorder(gateway, fake)
        await callbacks["MessageDeleted"](SimpleNamespace(chat_id="-5", deleted_ids=("7", 2**40)))
        assert seen == [DeletedMessagesEvent(-5, (7, 2**40))]

    async def test_handler_added_during_dispatch_does_not_break_it(self, clock: FakeClock) -> None:
        gateway, fake = make_gateway(clock)
        calls: list[str] = []

        async def late(event: ChatEvent) -> None:
            calls.append("late")

        async def early(event: ChatEvent) -> None:
            calls.append("early")
            gateway.add_event_handler(late)

        gateway.add_event_handler(early)
        callbacks = self.callbacks(fake)
        await callbacks["MessageDeleted"](SimpleNamespace(chat_id=None, deleted_ids=[1]))
        assert calls == ["early"]
        await callbacks["MessageDeleted"](SimpleNamespace(chat_id=None, deleted_ids=[1]))
        assert calls == ["early", "early", "late"]


class TestDownloadMedia:
    async def test_downloads_into_a_created_directory(
        self, clock: FakeClock, tmp_path: Path
    ) -> None:
        gateway, fake = await ready(clock)
        fake.by_id[7] = tg_message(7, media=object())
        target = tmp_path / "nested" / "media" / "2026-10"
        fake.downloaded = str(target / "7.jpg")
        result = await gateway.download_media(CHAT_ID, 7, target)
        assert result == target / "7.jpg"
        assert isinstance(result, Path)
        assert target.is_dir()
        assert fake.names("download_media")[0]["file"] == str(target)
        assert fake.names("get_messages") == [{"limit": None, "ids": 7}]

    @pytest.mark.parametrize(
        "message",
        [None, tl.MessageEmpty(id=7, peer_id=None), SimpleNamespace(id=7, media=None)],
    )
    async def test_nothing_to_download_gives_none(
        self, clock: FakeClock, tmp_path: Path, message: Any
    ) -> None:
        gateway, fake = await ready(clock)
        fake.by_id[7] = message
        assert await gateway.download_media(CHAT_ID, 7, tmp_path / "m") is None
        assert fake.names("download_media") == []
        assert not (tmp_path / "m").exists()

    async def test_download_that_saves_nothing_gives_none(
        self, clock: FakeClock, tmp_path: Path
    ) -> None:
        gateway, fake = await ready(clock)
        fake.by_id[7] = tg_message(7, media=object())
        fake.downloaded = None
        assert await gateway.download_media(CHAT_ID, 7, tmp_path / "m") is None

    async def test_access_lost_and_flood_wait(self, clock: FakeClock, tmp_path: Path) -> None:
        gateway, fake = await ready(clock)
        fake.latest_error = errors.ChannelPrivateError(request=None)
        with pytest.raises(AccessLost):
            await gateway.download_media(CHAT_ID, 7, tmp_path / "m")
        fake.latest_error = errors.FloodWaitError(request=None, capture=20)
        with pytest.raises(FloodWait):
            await gateway.download_media(CHAT_ID, 7, tmp_path / "m")


class TestLogin:
    def prompts(self, log: list[str]) -> dict[str, Callable[[], str]]:
        def remember(label: str, value: str) -> Callable[[], str]:
            def prompt() -> str:
                log.append(label)
                return value

            return prompt

        return {
            "prompt_phone": remember("phone", "+598000111222"),
            "prompt_code": remember("code", "13579"),
            "prompt_password": remember("password", "hunter2"),
        }

    @pytest.mark.parametrize(
        "config",
        [
            TelegramConfig(),
            TelegramConfig(api_id=1),
            TelegramConfig(api_hash="h"),
            TelegramConfig(api_id=0, api_hash="h"),
        ],
    )
    async def test_missing_credentials(self, config: TelegramConfig, tmp_path: Path) -> None:
        with pytest.raises(ChatImportError, match="api_id"):
            await login(config, tmp_path / "s" / "x.session", **self.prompts([]))
        assert FakeTelegramClient.created == []
        assert not (tmp_path / "s").exists()

    async def test_returns_username_and_never_the_phone(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        log: list[str] = []
        session = tmp_path / "deep" / "session" / "chatimport.session"
        with caplog.at_level(logging.DEBUG):
            who = await login(CONFIG, session, **self.prompts(log))
        assert who == "@owner"
        assert "+598" not in who
        assert "+598" not in caplog.text
        assert session.parent.is_dir()
        (client,) = FakeTelegramClient.created
        assert client.session == str(session)
        assert client.kwargs == {"flood_sleep_threshold": 77}
        assert client.disconnects == 1
        assert log == ["phone", "code", "password"]

    async def test_account_without_username_is_shown_by_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        me = SimpleNamespace(id=4242, username=None, phone="+598000111222")
        monkeypatch.setattr(FakeTelegramClient, "default_me", me)
        assert await login(CONFIG, tmp_path / "s.session", **self.prompts([])) == "id 4242"

    async def test_passes_the_callables_to_telethon(self, tmp_path: Path) -> None:
        log: list[str] = []
        prompts = self.prompts(log)
        await login(CONFIG, tmp_path / "s.session", **prompts)
        (client,) = FakeTelegramClient.created
        (kwargs,) = client.names("start")
        assert kwargs["phone"] is prompts["prompt_phone"]
        assert kwargs["code_callback"] is prompts["prompt_code"]
        assert kwargs["password"] is prompts["prompt_password"]

    async def test_client_is_disconnected_when_login_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(FakeTelegramClient, "default_start_error", RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await login(CONFIG, tmp_path / "s.session", **self.prompts([]))
        assert FakeTelegramClient.created[-1].disconnects == 1

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (errors.FloodWaitError(request=None, capture=99), FloodWait),
            (errors.AuthKeyUnregisteredError(request=None), SessionRevoked),
        ],
    )
    async def test_telegram_errors_are_translated_and_the_client_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        error: BaseException,
        expected: type[Exception],
    ) -> None:
        monkeypatch.setattr(FakeTelegramClient, "default_start_error", error)
        with pytest.raises(expected):
            await login(CONFIG, tmp_path / "s.session", **self.prompts([]))
        assert FakeTelegramClient.created[-1].disconnects == 1
