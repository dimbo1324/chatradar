from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from chatimport import app as app_module
from chatimport import context as context_module
from chatimport import service_runtime as service_runtime_module
from chatimport.app import (
    ServiceContext,
    build_gateway,
    load_context,
    resolve_entries,
    resolve_library,
    tracked_chat,
)
from chatimport.config import ConfigError, parse_config
from chatimport.control import service_running
from chatimport.library import ChatEntry, LibraryError, parse_library
from chatimport.ports import ChatImportError, ResolvedChat, ResolveStatus, SessionRevoked
from chatimport.storage.layout import chat_folder_name, iter_chat_folders
from chatimport.storage.state import load_state
from tests.fakes import FakeClock
from tests.fakes import FakeGateway as BaseGateway
from tests.unit.service.harness import Env, library_text, make_env

A, B = -1001, -1002


def found(
    ref: str, chat_id: int, title: str | None = "T", username: str | None = None
) -> ResolvedChat:
    return ResolvedChat(ref, ResolveStatus.FOUND, chat_id=chat_id, title=title, username=username)


async def test_resolve_entries_keeps_order_and_turns_handled_errors_into_not_found() -> None:
    gateway = BaseGateway()
    gateway.refs = {"@a": found("@a", A), "@c": found("@c", -3)}
    entries = [ChatEntry("@a"), ChatEntry("@b"), ChatEntry("@c")]
    gateway.fail["resolve"] = [ChatImportError("x")]

    results = await resolve_entries(gateway, entries)

    assert [e.ref for e, _ in results] == ["@a", "@b", "@c"]
    assert results[0][1].status is ResolveStatus.NOT_FOUND
    assert results[0][1].detail == "ChatImportError"
    assert results[1][1].status is ResolveStatus.NOT_FOUND
    assert results[2][1].status is ResolveStatus.FOUND


async def test_resolve_entries_lets_a_lost_session_through() -> None:
    gateway = BaseGateway()
    gateway.fail["resolve"] = [SessionRevoked("gone")]

    with pytest.raises(SessionRevoked):
        await resolve_entries(gateway, [ChatEntry("@a")])


async def test_resolve_entries_does_not_hide_programming_errors() -> None:
    gateway = BaseGateway()
    gateway.fail["resolve"] = [KeyError("bug")]

    with pytest.raises(KeyError):
        await resolve_entries(gateway, [ChatEntry("@a")])


async def test_resolve_library_asks_only_about_enabled_entries() -> None:
    library = parse_library(library_text(("@on", None, True), ("@off", None, False)))
    gateway = BaseGateway()

    await resolve_library(gateway, library)

    assert [args for name, args in gateway.calls if name == "resolve"] == [("@on",)]


async def test_resolve_entries_with_nothing_makes_no_calls() -> None:
    gateway = BaseGateway()

    assert await resolve_entries(gateway, []) == []
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("entry", "resolved", "title", "folder"),
    [
        (ChatEntry("@a", "Mine"), found("@a", A, "Real title"), "Real title", "Mine"),
        (ChatEntry("@a"), found("@a", A, "Real title"), "Real title", "Real title"),
        (ChatEntry("@a", "Mine"), found("@a", A, None), "Mine", "Mine"),
        (ChatEntry("@a"), found("@a", A, None), str(A), str(A)),
        (ChatEntry("@a"), found("@a", A, ""), str(A), str(A)),
        (ChatEntry("@a", ""), found("@a", A, "Real"), "Real", "Real"),
    ],
)
def test_tracked_chat_picks_title_and_folder_name(
    entry: ChatEntry, resolved: ResolvedChat, title: str, folder: str
) -> None:
    chat = tracked_chat(entry, resolved)

    assert chat.chat_id == A
    assert chat.title == title
    assert chat.folder_name == chat_folder_name(folder, A)


def test_tracked_chat_keeps_the_username() -> None:
    chat = tracked_chat(ChatEntry("@a"), found("@a", A, "T", "alpha"))

    assert chat.username == "alpha"


@pytest.mark.parametrize("status", [s for s in ResolveStatus if s is not ResolveStatus.FOUND])
def test_tracked_chat_refuses_an_unresolved_entry(status: ResolveStatus) -> None:
    with pytest.raises(ChatImportError, match="not resolved"):
        tracked_chat(ChatEntry("@a"), ResolvedChat("@a", status))


def write_config(base: Path, text: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.toml").write_text(text, encoding="utf-8")


def test_load_context_creates_the_application_folders(tmp_path: Path) -> None:
    ctx = load_context(base=tmp_path / "base")

    assert ctx.paths.control_dir.is_dir()
    assert ctx.paths.log_dir.is_dir()
    assert ctx.paths.session_file.parent.is_dir()
    assert ctx.library_file == tmp_path / "base" / "chats.toml"
    assert ctx.config == parse_config({})


def test_load_context_root_priority_cli_then_env_then_config_then_desktop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    write_config(base, f'[output]\nroot_dir = "{(tmp_path / "from_config").as_posix()}"\n')
    monkeypatch.setattr("chatimport.paths.user_desktop_dir", lambda: str(tmp_path / "desk"))
    monkeypatch.setenv("CHATIMPORT_ROOT", str(tmp_path / "from_env"))

    cli = load_context(str(tmp_path / "from_cli"), base)
    env = load_context(None, base)
    monkeypatch.delenv("CHATIMPORT_ROOT")
    config = load_context(None, base)
    write_config(base, "")
    desktop = load_context(None, base)

    assert cli.root == tmp_path / "from_cli" / "ChatImport"
    assert env.root == tmp_path / "from_env" / "ChatImport"
    assert config.root == tmp_path / "from_config" / "ChatImport"
    assert desktop.root == tmp_path / "desk" / "ChatImport"


def test_load_context_honours_a_custom_library_file(tmp_path: Path) -> None:
    custom = tmp_path / "lib" / "mine.toml"
    write_config(tmp_path / "base", f'[library]\nfile = "{custom.as_posix()}"\n')

    assert load_context(base=tmp_path / "base").library_file == custom


def test_load_context_reports_an_invalid_config(tmp_path: Path) -> None:
    write_config(tmp_path / "base", "[output\n")

    with pytest.raises(ConfigError):
        load_context(base=tmp_path / "base")


def test_build_gateway_requires_credentials(tmp_path: Path) -> None:
    ctx = make_env(tmp_path).ctx

    with pytest.raises(ChatImportError, match="api_id"):
        build_gateway(ctx, FakeClock())


def test_build_gateway_passes_configuration_to_the_telethon_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class Recorder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(context_module, "TelethonGateway", Recorder)
    base_ctx = make_env(tmp_path).ctx
    config = parse_config(
        {
            "telegram": {"api_id": 7, "api_hash": "hash"},
            "output": {"include_sender_names": False, "include_raw": True},
        }
    )
    ctx = replace(base_ctx, config=config)
    clock = FakeClock()

    build_gateway(ctx, clock)

    assert captured["args"] == (config.telegram, ctx.paths.session_file)
    assert captured["kwargs"] == {
        "include_sender_names": False,
        "include_raw": True,
        "clock": clock,
    }


def one_shot(tmp_path: Path, *, library: str | None = None, **kwargs: Any) -> tuple[Env, FakeClock]:
    env = make_env(
        tmp_path,
        config={"backfill": {"pause_between_chats_sec": 5}},
        library=library
        if library is not None
        else library_text(("@a", "Alpha", True), ("@b", "Beta", True), ("@off", None, False)),
        chats={"@a": (A, "Alpha chat"), "@b": (B, "Beta chat")},
        messages={A: 5, B: 3},
        **kwargs,
    )
    clock = FakeClock()
    env.app._clock = clock  # pyright: ignore[reportPrivateUsage]
    return env, clock


def stored(env: Env, chat_id: int) -> list[int]:
    state_folder = [
        f for f in iter_chat_folders(env.root) if (s := load_state(f)) and s.chat_id == chat_id
    ]
    if not state_folder:
        return []
    state = load_state(state_folder[0])
    assert state is not None
    return sorted(
        {
            int(line.split('"msg_id":')[1].split(",")[0])
            for part in state_folder[0].glob("*.jsonl")
            for line in part.read_text("utf-8").splitlines()
            if '"kind":"message"' in line
        }
    )


async def test_run_once_for_every_enabled_chat_syncs_full_history_and_cleans_up(
    tmp_path: Path,
) -> None:
    env, clock = one_shot(tmp_path)

    await env.app.run_once()

    assert stored(env, A) == [1, 2, 3, 4, 5]
    assert stored(env, B) == [1, 2, 3]
    assert ("resolve", ("@off",)) not in env.gateway.calls
    assert env.gateway.handlers == []
    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)
    assert clock.sleeps.count(5) == 1


async def test_run_once_pauses_only_between_chats_not_before_the_first(tmp_path: Path) -> None:
    env, clock = one_shot(tmp_path, library=library_text(("@a", None, True)))

    await env.app.run_once()

    assert 5 not in clock.sleeps


@pytest.mark.parametrize("selector", ["@a", "Alpha", "alpha", "  @a  "])
async def test_run_once_for_one_chat_by_ref_or_name(tmp_path: Path, selector: str) -> None:
    env, _ = one_shot(tmp_path)

    await env.app.run_once(selector)

    assert stored(env, A) == [1, 2, 3, 4, 5]
    assert stored(env, B) == []
    assert not env.gateway.connected


@pytest.mark.parametrize("selector", [str(A), "  -1001 ", "ALPHA"])
async def test_run_once_for_one_chat_by_id_or_username(tmp_path: Path, selector: str) -> None:
    env, _ = one_shot(tmp_path, library=library_text(("@a", "Alpha", True), ("@b", "Beta", True)))

    await env.app.run_once(selector)

    assert stored(env, A) == [1, 2, 3, 4, 5]
    assert stored(env, B) == []


async def test_run_once_for_an_unknown_chat_fails_and_releases_everything(
    tmp_path: Path,
) -> None:
    env, _ = one_shot(tmp_path)

    with pytest.raises(ChatImportError, match="no library chat matches"):
        await env.app.run_once("@nobody")

    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)
    assert stored(env, A) == []


async def test_run_once_skips_unresolved_entries_and_continues(tmp_path: Path) -> None:
    env, _ = one_shot(
        tmp_path, library=library_text(("@missing", None, True), ("@a", "Alpha", True))
    )

    await env.app.run_once()

    assert stored(env, A) == [1, 2, 3, 4, 5]


async def test_run_once_with_a_broken_library_raises_and_releases_everything(
    tmp_path: Path,
) -> None:
    env, _ = one_shot(tmp_path, library="[[chat]\n")

    with pytest.raises(LibraryError):
        await env.app.run_once()

    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)


async def test_run_once_refuses_when_the_service_runs_and_does_not_connect(
    tmp_path: Path,
) -> None:
    env, _ = one_shot(tmp_path)
    from chatimport.control import AlreadyRunning, acquire_instance_lock

    lock = acquire_instance_lock(env.ctx.paths.lock_file)
    try:
        with pytest.raises(AlreadyRunning):
            await env.app.run_once()
    finally:
        lock.release()

    assert env.gateway.calls == []


async def test_run_once_is_idempotent(tmp_path: Path) -> None:
    env, _ = one_shot(tmp_path)

    await env.app.run_once()
    await env.app.run_once()

    assert stored(env, A) == [1, 2, 3, 4, 5]


async def test_run_once_session_loss_propagates_and_disconnects(tmp_path: Path) -> None:
    env, _ = one_shot(tmp_path)
    env.gateway.fail["resolve"] = [SessionRevoked("gone")]

    with pytest.raises(SessionRevoked):
        await env.app.run_once()

    assert not env.gateway.connected
    assert not service_running(env.ctx.paths.lock_file)


async def test_run_once_without_credentials_does_not_leave_the_lock_behind(
    tmp_path: Path,
) -> None:
    env, _ = one_shot(tmp_path)
    app = app_module.ChatImportApp(env.ctx, notifier=env.notifier, clock=FakeClock(), disk=env.disk)

    try:
        await app.run_once()
    except ChatImportError:
        held = service_running(env.ctx.paths.lock_file)
    else:
        pytest.fail("expected ChatImportError")

    assert held is False


async def test_run_without_credentials_does_not_leave_the_lock_behind(tmp_path: Path) -> None:
    env, _ = one_shot(tmp_path)
    app = app_module.ChatImportApp(env.ctx, notifier=env.notifier, clock=FakeClock(), disk=env.disk)

    try:
        await app.run()
    except ChatImportError:
        held = service_running(env.ctx.paths.lock_file)
    else:
        pytest.fail("expected ChatImportError")

    assert held is False


class StubDownloader:
    instances: list[StubDownloader] = []  # noqa: RUF012

    def __init__(self, registry: object, gateway: object, config: Any, **kwargs: Any) -> None:
        self.gateway = gateway
        self.config = config
        self.kwargs = kwargs
        self.calls: list[str] = []
        StubDownloader.instances.append(self)

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    async def run(self) -> None:
        await asyncio.Event().wait()


@pytest.fixture
def stub_downloader(monkeypatch: pytest.MonkeyPatch) -> type[StubDownloader]:
    StubDownloader.instances = []
    monkeypatch.setattr(service_runtime_module, "MediaDownloader", StubDownloader)
    return StubDownloader


async def test_media_downloader_is_not_built_when_media_is_disabled(
    tmp_path: Path, stub_downloader: type[StubDownloader]
) -> None:
    env = make_env(tmp_path, library=library_text(("@a", "Alpha", True)), chats={"@a": (A, "A")})
    env.start()
    await env.wait_live(A)
    await env.stop()

    assert stub_downloader.instances == []


async def test_media_downloader_is_wired_with_gateway_config_and_chunk_size(
    tmp_path: Path, stub_downloader: type[StubDownloader]
) -> None:
    env = make_env(
        tmp_path,
        config={"media": {"enabled": True, "types": ["photo"]}, "output": {"max_chunk_mb": 3}},
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "A")},
    )
    env.start()
    await env.wait_live(A)
    await env.stop()

    (downloader,) = stub_downloader.instances
    assert downloader.gateway is env.gateway
    assert downloader.config.types == ("photo",)
    assert downloader.kwargs["max_chunk_bytes"] == 3 * 1024 * 1024
    assert downloader.kwargs["clock"] is env.clock


@pytest.mark.parametrize(
    ("free_gib", "expected"),
    [
        (14.9, ["pause"]),
        (0, ["pause"]),
        (15, []),
        (16, []),
        (16.99, []),
        (17, ["resume"]),
        (500, ["resume"]),
    ],
)
async def test_media_guard_pauses_below_low_and_resumes_at_high_watermark(
    tmp_path: Path,
    stub_downloader: type[StubDownloader],
    free_gib: float,
    expected: list[str],
) -> None:
    env = make_env(
        tmp_path,
        config={"media": {"enabled": True, "types": ["photo"]}},
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "A")},
        free_bytes=int(free_gib * 1024**3),
    )
    env.start()
    await env.wait_live(A)
    (downloader,) = stub_downloader.instances

    await env.clock.advance(1)
    await env.stop()

    assert downloader.calls[:1] == expected


async def test_media_guard_follows_the_disk_over_time(
    tmp_path: Path, stub_downloader: type[StubDownloader]
) -> None:
    gib = 1024**3
    env = make_env(
        tmp_path,
        config={"media": {"enabled": True, "types": ["photo"]}},
        library=library_text(("@a", "Alpha", True)),
        chats={"@a": (A, "A")},
        free_bytes=10 * gib,
    )
    env.start()
    await env.wait_live(A)
    (downloader,) = stub_downloader.instances
    assert downloader.calls[:1] == ["pause"]
    assert "resume" not in downloader.calls

    env.disk.values = [16 * gib]
    await env.clock.advance(300)
    assert "resume" not in downloader.calls

    env.disk.values = [20 * gib]
    await env.clock.advance(300)
    await env.stop()

    assert downloader.calls[-1] == "resume"


async def test_a_crashing_worker_is_restarted_and_reported(tmp_path: Path) -> None:
    env = make_env(
        tmp_path, library=library_text(("@a", "Alpha", True)), chats={"@a": (A, "Alpha")}
    )
    env.gateway.fail["newest_id"] = [RuntimeError("boom")]
    env.start()

    async def reported() -> bool:
        data = await env.status()
        return data is not None and any(e["source"] == f"worker-{A}" for e in data["errors"])

    await env.until_async(reported, step=0.01)
    await env.wait_live(A)
    await env.stop()

    assert stored(env, A) == [1, 2, 3]


def test_service_context_is_immutable(tmp_path: Path) -> None:
    ctx: ServiceContext = make_env(tmp_path).ctx

    with pytest.raises(AttributeError):
        ctx.root = Path("x")  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]
