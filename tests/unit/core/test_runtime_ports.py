from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import chatimport
from chatimport.ports import (
    AccessLost,
    ChatImportError,
    FloodWait,
    ResolvedChat,
    ResolveStatus,
    SessionRevoked,
)
from chatimport.runtime import (
    ChatRegistry,
    Level,
    LogNotifier,
    SystemClock,
    SystemDiskUsage,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class StubController:
    def __init__(self, chat_id: int) -> None:
        self._chat_id = chat_id
        self._lock = asyncio.Lock()

    @property
    def chat_id(self) -> int:
        return self._chat_id

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock


def recorder(asked: list[Path], free: int) -> Callable[[Path], Any]:
    def disk_usage(path: Path) -> Any:
        asked.append(Path(path))
        return SimpleNamespace(free=free)

    return disk_usage


def never_exists(self: Path) -> bool:
    return False


def registry_with(*ids: int) -> tuple[ChatRegistry, dict[int, StubController]]:
    registry = ChatRegistry()
    controllers = {i: StubController(i) for i in ids}
    for controller in controllers.values():
        registry.add(controller)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    return registry, controllers


def test_flood_wait_carries_seconds_and_message() -> None:
    error = FloodWait(754)
    assert error.seconds == 754
    assert "754" in str(error)
    assert isinstance(error, ChatImportError)


def test_access_lost_carries_chat_id_and_message() -> None:
    error = AccessLost(-1001)
    assert error.chat_id == -1001
    assert "-1001" in str(error)
    assert isinstance(error, ChatImportError)


def test_session_revoked_is_a_handled_error() -> None:
    assert issubclass(SessionRevoked, ChatImportError)
    assert not issubclass(SessionRevoked, FloodWait)
    assert not issubclass(AccessLost, FloodWait)


def test_ports_errors_are_distinguishable_by_except_clauses() -> None:
    caught: list[str] = []
    for error in (FloodWait(1), AccessLost(1), SessionRevoked("x")):
        try:
            raise error
        except FloodWait:
            caught.append("flood")
        except AccessLost:
            caught.append("access")
        except SessionRevoked:
            caught.append("session")
    assert caught == ["flood", "access", "session"]


def test_resolved_chat_defaults() -> None:
    resolved = ResolvedChat("ref", ResolveStatus.NOT_FOUND)
    assert resolved.chat_id is None
    assert resolved.title is None
    assert resolved.username is None
    assert resolved.detail == ""


def test_resolve_status_values_are_stable_strings() -> None:
    assert {s.name: s.value for s in ResolveStatus} == {
        "FOUND": "found",
        "NEED_TO_JOIN": "need_to_join",
        "NOT_FOUND": "not_found",
        "AMBIGUOUS": "ambiguous",
        "NOT_A_CHAT": "not_a_chat",
    }


def test_registry_starts_empty() -> None:
    registry = ChatRegistry()
    assert len(registry) == 0
    assert registry.all() == []
    assert list(registry) == []
    assert registry.get(1) is None


def test_registry_instances_do_not_share_storage() -> None:
    first = ChatRegistry()
    second = ChatRegistry()
    first.add(StubController(1))  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    assert len(second) == 0


def test_registry_add_get_len_and_order() -> None:
    registry, controllers = registry_with(5, -3, 9)
    assert len(registry) == 3
    assert registry.get(-3) is controllers[-3]
    assert [c.chat_id for c in registry] == [5, -3, 9]
    assert [c.chat_id for c in registry.all()] == [5, -3, 9]


def test_registry_add_with_same_id_replaces_in_place() -> None:
    registry, controllers = registry_with(1, 2, 3)
    replacement = StubController(2)
    registry.add(replacement)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    assert len(registry) == 3
    assert registry.get(2) is replacement
    assert registry.get(2) is not controllers[2]
    assert [c.chat_id for c in registry] == [1, 2, 3]


def test_registry_remove_returns_controller_and_forgets_it() -> None:
    registry, controllers = registry_with(1, 2)
    assert registry.remove(1) is controllers[1]
    assert registry.get(1) is None
    assert len(registry) == 1


def test_registry_remove_unknown_returns_none_and_is_harmless() -> None:
    registry, _ = registry_with(1)
    assert registry.remove(99) is None
    assert registry.remove(1) is not None
    assert registry.remove(1) is None
    assert len(registry) == 0


def test_registry_iteration_is_a_snapshot_safe_against_removal() -> None:
    registry, _ = registry_with(1, 2, 3)
    seen: list[int] = []
    for controller in registry:
        seen.append(controller.chat_id)
        registry.remove(controller.chat_id)
    assert seen == [1, 2, 3]
    assert len(registry) == 0


def test_registry_all_returns_a_copy() -> None:
    registry, _ = registry_with(1)
    registry.all().clear()
    assert len(registry) == 1


def test_registry_distinguishes_huge_and_negative_ids() -> None:
    registry, controllers = registry_with(-(2**63), 2**63, 0)
    assert registry.get(-(2**63)) is controllers[-(2**63)]
    assert registry.get(2**63) is controllers[2**63]
    assert registry.get(0) is controllers[0]


def test_disk_usage_reports_free_bytes_of_existing_path(tmp_path: Path) -> None:
    expected = shutil.disk_usage(tmp_path).free
    reported = SystemDiskUsage().free_bytes(tmp_path)
    assert reported > 0
    assert abs(reported - expected) < 50 * 1024 * 1024


def test_disk_usage_walks_up_from_a_missing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Path] = []

    def fake(path: Path) -> Any:
        asked.append(Path(path))
        return SimpleNamespace(free=123)

    monkeypatch.setattr("chatimport.runtime.shutil.disk_usage", fake)
    missing = tmp_path / "a" / "b" / "c" / "d"
    assert SystemDiskUsage().free_bytes(missing) == 123
    assert asked == [tmp_path]


def test_disk_usage_of_a_file_path_uses_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    asked: list[Path] = []
    monkeypatch.setattr("chatimport.runtime.shutil.disk_usage", recorder(asked, 1))
    assert SystemDiskUsage().free_bytes(target) == 1
    assert asked == [target]


def test_disk_usage_terminates_when_nothing_on_the_way_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "exists", never_exists)
    asked: list[Path] = []
    monkeypatch.setattr("chatimport.runtime.shutil.disk_usage", recorder(asked, 7))
    start = Path("nowhere") / "deeper"
    assert SystemDiskUsage().free_bytes(start) == 7
    assert asked == [Path()]


def test_system_clock_now_is_aware_utc_and_current() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)
    assert now.utcoffset() == timedelta(0)
    assert before <= now <= after


async def test_system_clock_sleep_really_awaits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr("chatimport.runtime.asyncio.sleep", fake_sleep)
    await SystemClock().sleep(12.5)
    assert calls == [12.5]


@pytest.mark.parametrize(
    ("level", "numeric"),
    [(Level.INFO, logging.INFO), (Level.WARNING, logging.WARNING), (Level.ERROR, logging.ERROR)],
)
def test_log_notifier_maps_levels(
    caplog: pytest.LogCaptureFixture, level: Level, numeric: int
) -> None:
    with caplog.at_level(logging.DEBUG, logger="chatimport.notify"):
        LogNotifier().notify(level, "Title", "body text")
    assert [(r.levelno, r.name, r.getMessage()) for r in caplog.records] == [
        (numeric, "chatimport.notify", "Title: body text")
    ]


def test_log_notifier_does_not_interpret_percent_signs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="chatimport.notify"):
        LogNotifier().notify(Level.INFO, "100%", "%s %d {x}")
    assert caplog.records[0].getMessage() == "100%: %s %d {x}"


def test_level_values() -> None:
    assert [level.value for level in Level] == ["info", "warning", "error"]


def test_version_falls_back_when_package_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    original = chatimport.__version__
    monkeypatch.setattr(importlib.metadata, "version", missing)
    try:
        importlib.reload(chatimport)
        assert chatimport.__version__ == "0.0.0"
    finally:
        monkeypatch.undo()
        importlib.reload(chatimport)
    assert chatimport.__version__ == original


def test_version_comes_from_the_installed_metadata() -> None:
    assert chatimport.__version__ == importlib.metadata.version("chatimport")
