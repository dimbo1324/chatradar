from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from telethon import errors

from chatimport.config import TelegramConfig
from chatimport.ports import ChatImportError
from chatimport.telegram import session_probe
from chatimport.telegram.session_probe import SessionInfo, probe_session

if TYPE_CHECKING:
    from pathlib import Path


class FakeClient:
    def __init__(
        self,
        *,
        authorized: bool = True,
        me: Any = None,
        connect_error: BaseException | None = None,
        authorized_error: BaseException | None = None,
        me_error: BaseException | None = None,
    ) -> None:
        self.authorized = authorized
        self.me = me if me is not None else SimpleNamespace(username="owner", id=42)
        self.connect_error = connect_error
        self.authorized_error = authorized_error
        self.me_error = me_error
        self.calls: list[str] = []

    async def connect(self) -> None:
        self.calls.append("connect")
        if self.connect_error:
            raise self.connect_error

    async def is_user_authorized(self) -> bool:
        self.calls.append("is_user_authorized")
        if self.authorized_error:
            raise self.authorized_error
        return self.authorized

    async def get_me(self) -> Any:
        self.calls.append("get_me")
        if self.me_error:
            raise self.me_error
        return self.me

    async def disconnect(self) -> None:
        self.calls.append("disconnect")


class Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.session = tmp_path / "chatimport.session"
        self.session.write_bytes(b"x")
        self.client = FakeClient()
        self.protected: list[Path] = []
        self.made: list[Path] = []
        monkeypatch.setattr(session_probe, "_make_client", self._make)
        monkeypatch.setattr(session_probe, "protect_session", self.protected.append)

    def _make(self, config: TelegramConfig, path: Path) -> FakeClient:
        self.made.append(path)
        return self.client


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Rig:
    return Rig(monkeypatch, tmp_path)


CONFIGURED = TelegramConfig(api_id=12345, api_hash="abcdef")


async def test_signed_in_session_reports_the_username(rig: Rig) -> None:
    info = await probe_session(CONFIGURED, rig.session)

    assert info == SessionInfo("@owner")
    assert rig.client.calls == ["connect", "is_user_authorized", "get_me", "disconnect"]
    assert rig.protected == [rig.session]
    assert rig.made == [rig.session]


async def test_account_without_username_reports_its_id(rig: Rig) -> None:
    rig.client.me = SimpleNamespace(username=None, id=42)
    assert await probe_session(CONFIGURED, rig.session) == SessionInfo("id 42")


async def test_missing_credentials_never_touch_the_client(rig: Rig) -> None:
    assert await probe_session(TelegramConfig(), rig.session) is None
    assert rig.made == []


async def test_missing_session_file_never_touches_the_client(rig: Rig, tmp_path: Path) -> None:
    assert await probe_session(CONFIGURED, tmp_path / "absent.session") is None
    assert rig.made == []


async def test_unauthorised_session_gives_none_and_disconnects(rig: Rig) -> None:
    rig.client.authorized = False
    assert await probe_session(CONFIGURED, rig.session) is None
    assert rig.client.calls == ["connect", "is_user_authorized", "disconnect"]


@pytest.mark.parametrize(
    "error",
    [
        errors.AuthKeyError(request=None, message="x"),
        errors.UnauthorizedError(request=None, message="x"),
    ],
)
async def test_revoked_session_gives_none(rig: Rig, error: BaseException) -> None:
    rig.client.authorized_error = error
    assert await probe_session(CONFIGURED, rig.session) is None
    assert rig.client.calls[-1] == "disconnect"


@pytest.mark.parametrize(
    "error", [errors.RPCError(None, "x", 500), OSError("down"), TimeoutError("slow")]
)
async def test_other_failures_become_a_chat_import_error(rig: Rig, error: BaseException) -> None:
    rig.client.me_error = error
    with pytest.raises(ChatImportError, match=type(error).__name__):
        await probe_session(CONFIGURED, rig.session)
    assert rig.client.calls[-1] == "disconnect"


async def test_connect_failure_is_reported_and_disconnects(rig: Rig) -> None:
    rig.client.connect_error = OSError("no route")
    with pytest.raises(ChatImportError, match="OSError"):
        await probe_session(CONFIGURED, rig.session)
    assert rig.client.calls == ["connect", "disconnect"]
