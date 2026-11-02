from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QUrl

from chatimport.gui.pages import settings_support as support
from chatimport.gui.pages.settings_support import SettingsHooks
from chatimport.telegram import client, session_probe
from chatimport.telegram.session_probe import SessionInfo

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from chatimport.context import ServiceContext
    from chatimport.gui.context import GuiContext
    from tests.unit.gui.conftest import FakeBridge
    from tests.unit.gui.pages_c.conftest import FakeControl


def test_control_prefers_the_hook(gui: GuiContext, control: FakeControl) -> None:
    assert support.control_of(gui, SettingsHooks(control=control)) is control


def test_control_falls_back_to_the_bridge(control_gui: GuiContext, control: FakeControl) -> None:
    assert support.control_of(control_gui, SettingsHooks()) is control


def test_plain_bridge_is_no_control(gui: GuiContext, bridge: FakeBridge) -> None:
    assert support.control_of(gui, SettingsHooks()) is None


def test_context_comes_from_control_or_gui(
    gui: GuiContext, control: FakeControl, service_context: ServiceContext
) -> None:
    assert support.context_of(gui, SettingsHooks()) is service_context
    assert support.context_of(gui, SettingsHooks(control=control)) is control.context


def test_open_path_opens_a_folder_and_a_files_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[QUrl] = []
    monkeypatch.setattr(support.QDesktopServices, "openUrl", opened.append)
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")
    support.open_path(tmp_path)
    support.open_path(file)
    assert opened == [QUrl.fromLocalFile(str(tmp_path))] * 2


def test_open_link(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[QUrl] = []
    monkeypatch.setattr(support.QDesktopServices, "openUrl", opened.append)
    support.open_link("https://example.org/x")
    assert opened == [QUrl("https://example.org/x")]


def test_default_probe_runs_the_async_probe(
    monkeypatch: pytest.MonkeyPatch, service_context: ServiceContext
) -> None:
    seen: list[Any] = []

    async def fake_probe(config: Any, session_file: Any) -> SessionInfo:
        seen.append((config, session_file))
        return SessionInfo("@someone")

    monkeypatch.setattr(session_probe, "probe_session", fake_probe)
    info = support.probe_session_blocking(service_context)
    assert info == SessionInfo("@someone")
    assert seen == [(service_context.config.telegram, service_context.paths.session_file)]


async def test_default_login_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_login(*args: Any, **kwargs: Any) -> str:
        return f"{args}-{sorted(kwargs)}"

    monkeypatch.setattr(client, "login", fake_login)
    assert await support.telegram_login(1, key=2) == "(1,)-['key']"
