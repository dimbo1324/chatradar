"""Service behaviour added with the app split: run --once resilience (C20), cancellation
during thread work (C12), backfill slots and unreadable state."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from chatimport import commands as commands_module
from chatimport import service_runtime as service_runtime_module
from chatimport.config import load_config
from chatimport.paths import normalize_root
from chatimport.ports import ChatImportError, SessionRevoked
from chatimport.storage.state import StateUnreadable
from chatimport.worker import ChatWorker
from tests.fakes import FakeClock
from tests.unit.service.harness import Env, library_text, make_env
from tests.unit.service.helpers import StubController

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from chatimport.runtime import BackfillSlots

A, B = -1001, -1002


@pytest_asyncio.fixture
async def live(tmp_path: Path) -> AsyncIterator[Env]:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
        messages={A: 4, B: 3},
    )
    task = env.start()
    await env.wait_live(A, B)
    yield env
    if not task.done():
        await env.stop()


async def test_run_once_continues_after_a_failing_chat(tmp_path: Path) -> None:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)),
        chats={"@a": (A, "Alpha"), "@b": (B, "Beta")},
    )
    env.app._clock = FakeClock()  # pyright: ignore[reportPrivateUsage]
    env.gateway.fail["newest_id"] = [RuntimeError("boom")]

    with pytest.raises(ChatImportError, match=f"sync failed for chats {A}$"):
        await env.app.run_once()

    synced = {folder.name for folder in env.root.iterdir() if (folder / "state.json").is_file()}
    assert any(name.endswith(str(B)) for name in synced)
    assert not env.gateway.connected


def blocking(started: threading.Event, release: threading.Event) -> Any:
    def wait(*_args: Any, **_kwargs: Any) -> list[Any]:
        started.set()
        release.wait(10)
        return []

    return wait


def rename_into_place(old: Path, new: Path) -> None:
    new.rmdir()
    old.replace(new)


async def test_cancel_set_root_during_move_does_not_restart_old_root(
    live: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()
    new_root = normalize_root(str(tmp_path / "moved"))

    async def slow_move(old: Path, new: Path, *, move: bool) -> None:
        await asyncio.to_thread(blocking(started, release))
        await asyncio.to_thread(rename_into_place, old, new)

    monkeypatch.setattr("chatimport.app.move_root", slow_move)
    task = asyncio.create_task(live.app.execute("set_root", {"path": str(new_root), "move": True}))
    await asyncio.to_thread(started.wait, 5)

    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    with pytest.raises(ChatImportError, match="not running"):
        live.app.runtime()
    assert not live.root.exists()
    assert new_root.is_dir()
    assert load_config(live.ctx.paths.config_file).output.root_dir == str(new_root)
    assert live.app.ctx.root == new_root


async def test_cancel_set_root_whose_move_fails_keeps_the_config(
    live: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()

    async def failing_move(old: Path, new: Path, *, move: bool) -> None:
        await asyncio.to_thread(blocking(started, release))
        raise OSError("disk unplugged")

    monkeypatch.setattr("chatimport.app.move_root", failing_move)
    task = asyncio.create_task(
        live.app.execute("set_root", {"path": str(tmp_path / "x"), "move": True})
    )
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert live.app.ctx.root == live.root
    assert not live.ctx.paths.config_file.exists()


async def test_config_write_failure_after_a_cancelled_move_is_logged(
    live: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    started, release = threading.Event(), threading.Event()

    async def slow_move(old: Path, new: Path, *, move: bool) -> None:
        await asyncio.to_thread(blocking(started, release))

    def read_only(path: Path, root: Path) -> None:
        raise OSError("read-only config")

    monkeypatch.setattr("chatimport.app.move_root", slow_move)
    monkeypatch.setattr("chatimport.app.set_output_root", read_only)
    task = asyncio.create_task(
        live.app.execute("set_root", {"path": str(tmp_path / "y"), "move": True})
    )
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert "config.toml was not updated" in caplog.text


async def test_cancelled_check_repair_keeps_the_lock_until_the_thread_ends(
    live: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(commands_module, "check_folder", blocking(started, release))
    alpha = live.app.runtime().registry.get(A)
    assert alpha is not None

    task = asyncio.create_task(live.app.execute("check", {"repair": True}))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.02)
    assert alpha.lock.locked()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not alpha.lock.locked()


async def test_every_worker_shares_the_runtime_backfill_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[BackfillSlots | None] = []

    class Recording(ChatWorker):
        def __init__(self, *args: Any, slots: BackfillSlots | None = None, **kwargs: Any) -> None:
            seen.append(slots)
            super().__init__(*args, slots=slots, **kwargs)

    monkeypatch.setattr(service_runtime_module, "ChatWorker", Recording)
    env = make_env(
        tmp_path,
        config={"backfill": {"max_parallel_chats": 2}},
        library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)),
        chats={"@a": (A, "Alpha"), "@b": (B, "Beta")},
    )
    env.start()
    await env.wait_live(A, B)
    slots = env.app.runtime().slots
    await env.stop()

    assert slots.limit == 2
    assert seen == [slots, slots]


def unreadable(folder: Path) -> None:
    raise StateUnreadable(folder, PermissionError("locked"))


def test_unreadable_state_means_an_unknown_recheck_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_runtime_module, "load_state", unreadable)

    controller = StubController(A, tmp_path)

    assert service_runtime_module._last_recheck_at(controller) is None  # pyright: ignore[reportPrivateUsage]


async def test_unreadable_state_launches_the_worker_staggered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "Alpha")},
    )
    calls = 0
    real = service_runtime_module.load_state

    def flaky(folder: Path) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            unreadable(folder)
        return real(folder)

    monkeypatch.setattr(service_runtime_module, "load_state", flaky)
    env.start()
    await env.wait_live(A)
    await env.stop()

    assert calls >= 1


async def test_deeper_keeps_the_floor_of_a_chat_whose_state_is_unreadable(
    live: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(folder: Path, now: object) -> bool:
        raise StateUnreadable(folder, PermissionError("locked"))

    monkeypatch.setattr(commands_module, "lower_floor_state", refuse)

    result = await live.run_command("deeper", chat=A)

    assert result.ok
    assert result.data == {"chats": 0}


async def test_run_once_lets_a_lost_session_through_a_chat_sync(tmp_path: Path) -> None:
    env = make_env(tmp_path, library=library_text(("@a", "Alpha", True)), chats={"@a": (A, "A")})
    env.app._clock = FakeClock()  # pyright: ignore[reportPrivateUsage]
    env.gateway.fail["newest_id"] = [SessionRevoked("gone")]

    with pytest.raises(SessionRevoked):
        await env.app.run_once()


async def test_session_lost_while_resolving_a_library_change_ends_the_run(
    tmp_path: Path,
) -> None:
    env = make_env(
        tmp_path,
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "Alpha"), "@b": (B, "Beta")},
    )
    task = env.start()
    await env.wait_live(A)
    env.gateway.fail["resolve"] = [SessionRevoked("gone")]
    env.write_library(library_text(("@a", "Alpha", True), ("@b", "Beta", True)))

    async def finished() -> bool:
        return task.done()

    await env.until_async(finished)

    assert task.exception() is None
    assert not env.gateway.connected


def make_foreign_folder(root: Path) -> None:
    (root / "Old chat_-555").mkdir()


async def test_check_reads_untracked_folders_without_a_lock(live: Env) -> None:
    await asyncio.to_thread(make_foreign_folder, live.root)

    result = await live.run_command("check")

    assert result.ok
    assert any(issue["folder"] == "Old chat_-555" for issue in result.data["issues"])


async def test_removing_a_chat_that_is_not_running_is_a_no_op(live: Env) -> None:
    await live.app.runtime().remove(-999)

    assert set(await live.chats()) == {A, B}


async def test_set_root_needs_a_running_service(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    result = await env.app.execute("set_root", {"path": str(tmp_path / "elsewhere")})

    assert result.ok is False
    assert "not running" in result.message
