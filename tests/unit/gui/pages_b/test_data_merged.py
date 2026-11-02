from __future__ import annotations

from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from chatimport.commands import CommandResult
from chatimport.config import ConfigError, load_config
from chatimport.gui.pages import data_merged
from chatimport.merged_export import build_merged, merged_path

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from chatimport.gui.pages.data import DataPage
    from tests.unit.gui.conftest import FakeBridge
    from tests.unit.gui.pages_b.conftest import Clipboard, Opened, Toasts

type Settle = Callable[[Callable[[], bool]], None]


def config_file(page: DataPage) -> Path:
    return page.gui.current.paths.config_file


def built(page: DataPage, *, ago: timedelta = timedelta(minutes=5)) -> None:
    build_merged(page.env.root, now=datetime.now(UTC) - ago)
    page.merged.refresh()


def test_defaults_show_a_switched_off_card_without_a_build(data_page: DataPage) -> None:
    card = data_page.merged
    assert not card.enabled.is_checked()
    assert card.format.value == "json"
    assert not card.names.is_checked()
    assert card.state_label.text() == "Switched off"
    assert card.last_label.text() == "Not built yet"
    assert not card.copy_button.isEnabled()
    assert not card.show_button.isEnabled()
    assert card.path_label.toolTip().endswith("all_chats.json")


def test_last_build_shows_exact_moment_age_records_and_size(data_page: DataPage) -> None:
    built(data_page)
    card = data_page.merged
    assert "UTC" in card.last_label.text()
    assert "ago" in card.last_label.text()
    assert card.last_label.toolTip() in card.last_label.text()
    assert card.size_label.text().startswith("6 records")
    assert card.copy_button.isEnabled()


def test_switching_on_saves_the_config_and_reloads_the_service(
    data_page: DataPage, bridge: FakeBridge, toasts: Toasts, settle: Settle
) -> None:
    card = data_page.merged
    card.enabled.set_checked(True)
    settle(lambda: bool(toasts.items))
    assert load_config(config_file(data_page)).merged.enabled is True
    assert bridge.calls == [("reload_config", {})]
    assert toasts.last() == ("success", "Saved")
    assert card.state_label.text() == "Switched on"


def test_format_and_names_are_saved_and_the_warning_follows_names(
    data_page: DataPage, toasts: Toasts, settle: Settle
) -> None:
    card = data_page.merged
    data_page.show()
    card.format.choose(1)
    settle(lambda: len(toasts.items) == 1)
    card.names.set_checked(True)
    settle(lambda: len(toasts.items) == 2)
    merged = load_config(config_file(data_page)).merged
    assert (merged.format, merged.include_names) == ("jsonl", True)
    assert card.names_warning.isVisibleTo(data_page)
    card.names.set_checked(False)
    settle(lambda: len(toasts.items) == 3)
    assert not card.names_warning.isVisibleTo(data_page)


def test_a_service_that_cannot_reload_says_the_setting_applies_later(
    data_page: DataPage, bridge: FakeBridge, toasts: Toasts, settle: Settle
) -> None:
    bridge.replies["reload_config"] = CommandResult(False, "nope")
    data_page.merged.enabled.set_checked(True)
    settle(lambda: bool(toasts.items))
    assert toasts.last() == ("info", "Saved. It applies when the service starts.")


def test_a_failing_bridge_future_counts_as_not_reloaded(
    data_page: DataPage, bridge: FakeBridge, toasts: Toasts, settle: Settle
) -> None:
    def broken(command: str, args: object = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    bridge.execute = broken  # type: ignore[method-assign]  # a stand-in
    data_page.merged.enabled.set_checked(True)
    settle(lambda: bool(toasts.items))
    assert toasts.tones() == ["info"]


@pytest.mark.parametrize("error", [ConfigError("bad"), OSError("locked")])
def test_a_config_that_cannot_be_written_reverts_the_controls(
    data_page: DataPage,
    toasts: Toasts,
    bridge: FakeBridge,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise error

    monkeypatch.setattr(data_merged, "update_config", refuse)
    data_page.merged.enabled.set_checked(True)
    assert toasts.last() == ("danger", "The setting could not be saved.")
    assert not data_page.merged.enabled.is_checked()
    assert bridge.calls == []


def test_an_invalid_config_file_shows_defaults(data_page: DataPage) -> None:
    config_file(data_page).write_text("[merged]\nformat = 'xml'\n", encoding="utf-8")
    data_page.merged.refresh()
    assert data_page.merged.format.value == "json"


def test_build_now_calls_the_service_and_toasts(
    data_page: DataPage, bridge: FakeBridge, toasts: Toasts, settle: Settle
) -> None:
    card = data_page.merged
    build_merged(data_page.env.root, now=datetime.now(UTC))
    bridge.replies["export_all"] = CommandResult(True, data={"records": 6})
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    card.build()
    assert bridge.calls == []
    card._busy = False  # pyright: ignore[reportPrivateUsage]
    card.build()
    settle(lambda: bool(toasts.items))
    assert bridge.calls == [("export_all", {"format": "json", "names": False})]
    assert toasts.last() == ("success", "Combined file is ready: 6 records")
    assert card.build_button.isEnabled()
    assert card.build_button.text() == "Build now"
    assert card.size_label.text().startswith("6 records")


def test_build_now_failures_toast(
    data_page: DataPage, bridge: FakeBridge, toasts: Toasts, settle: Settle
) -> None:
    bridge.replies["export_all"] = CommandResult(False, "boom")
    data_page.merged.build()
    settle(lambda: bool(toasts.items))
    assert toasts.last() == ("danger", "The combined file was not built.")


def test_build_now_without_a_service_says_so(
    data_page: DataPage, bridge: FakeBridge, toasts: Toasts, settle: Settle
) -> None:
    def broken(command: str, args: object = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    bridge.execute = broken  # type: ignore[method-assign]  # a stand-in
    data_page.merged.build()
    settle(lambda: bool(toasts.items))
    assert toasts.tones() == ["warning"]


def test_copy_and_show_in_folder(
    data_page: DataPage, clipboard: Clipboard, opened: Opened, toasts: Toasts
) -> None:
    card = data_page.merged
    card._copy()  # pyright: ignore[reportPrivateUsage]
    card._show()  # pyright: ignore[reportPrivateUsage]
    assert clipboard.text == ""
    assert opened.urls == []
    built(data_page)
    card.copy_button.click()
    card.show_button.click()
    assert clipboard.text == str(merged_path(data_page.env.root, "json"))
    assert opened.urls == [str(data_page.env.root / "_exports")]
    assert toasts.tones() == ["info"]


def test_the_busy_card_shows_the_working_texts(data_page: DataPage) -> None:
    card = data_page.merged
    card._set_busy(True)  # pyright: ignore[reportPrivateUsage]
    assert card.build_button.text() == "Building..."
    assert not card.build_button.isEnabled()
    card._set_busy(False)  # pyright: ignore[reportPrivateUsage]
    assert card.build_button.text() == "Build now"


def test_snapshots_track_the_building_flag_and_new_builds(
    data_page: DataPage, bridge: FakeBridge
) -> None:
    card = data_page.merged
    bridge.snapshot.emit({"merged": {"building": True, "last_built_at": None}})
    assert card.state_label.text() == "Building now..."
    built_at = datetime.now(UTC).replace(microsecond=0)
    build_merged(data_page.env.root, now=built_at)
    stamp = built_at.isoformat().replace("+00:00", "Z")
    bridge.snapshot.emit({"merged": {"building": False, "last_built_at": stamp}})
    assert card.state_label.text() == "Switched off"
    assert card.size_label.text().startswith("6 records")
    bridge.snapshot.emit({"merged": {"building": False, "last_built_at": stamp}})
    bridge.snapshot.emit({})


def test_a_snapshot_during_a_local_build_does_not_replace_the_result(
    data_page: DataPage, bridge: FakeBridge
) -> None:
    card = data_page.merged
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    build_merged(data_page.env.root, now=datetime.now(UTC))
    bridge.snapshot.emit({"merged": {"building": False, "last_built_at": "2026-01-01T00:00:00Z"}})
    assert card._result is None  # pyright: ignore[reportPrivateUsage]


def test_changing_the_root_rereads_the_last_build(data_page: DataPage, tmp_path: Path) -> None:
    built(data_page)
    other = tmp_path / "elsewhere"
    other.mkdir()
    data_page.env.set_root(other)
    assert data_page.merged.last_label.text() == "Not built yet"
    assert str(other) in data_page.merged.path_label.toolTip()


def test_language_switch_retranslates(data_page: DataPage) -> None:
    built(data_page)
    card = data_page.merged
    english = card.build_button.text()
    data_page.gui.language.set_language("ru")
    assert card.build_button.text() != english
    assert card.size_label.text().startswith("6 ")
    assert card.size_label.text() != "6 records"
