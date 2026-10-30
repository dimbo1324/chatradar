from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from chatimport import app as app_module
from chatimport.control import CommandResult, acquire_instance_lock
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import CHAT_ID, NOW, msg

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from filelock import FileLock

    from chatimport.app import ServiceContext

CREDENTIALS = '[telegram]\napi_id = 12345\napi_hash = "abcdef"\n'


@dataclass
class Env:
    ctx: ServiceContext
    runner: CliRunner
    home: Path

    def write_library(self, text: str) -> None:
        self.ctx.library_file.write_text(text, encoding="utf-8")

    def make_chat(
        self, chat_id: int = CHAT_ID, title: str = "Example group", ids: range = range(1, 6)
    ) -> Path:
        folder = self.ctx.root / chat_folder_name(title, chat_id)
        writer = ChunkWriter(folder, 10**6)
        state = new_state(chat_id, title, None, NOW)
        state = writer.append(state, [msg(i, chat_id=chat_id) for i in ids])
        return folder

    def lock_is_free(self) -> bool:
        lock = acquire_instance_lock(self.ctx.paths.lock_file)
        lock.release()
        return True


@pytest.fixture
def env(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Env:
    home = tmp_path_factory.mktemp("h")
    monkeypatch.setenv("CHATIMPORT_ROOT", str(home / "ChatImport"))
    base = home / "app"
    base.mkdir()
    (base / "config.toml").write_text(CREDENTIALS, encoding="utf-8")
    monkeypatch.setattr(app_module, "load_context", partial(app_module.load_context, base=base))
    ctx = app_module.load_context(None)
    return Env(ctx=ctx, runner=CliRunner(), home=home)


@pytest.fixture
def running_service(env: Env) -> Iterator[FileLock]:
    lock = acquire_instance_lock(env.ctx.paths.lock_file)
    try:
        yield lock
    finally:
        lock.release()


class SentCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.result = CommandResult(True, "")
        self.raises: BaseException | None = None

    def __call__(
        self, control_dir: Path, command: str, args: dict[str, Any] | None = None
    ) -> CommandResult:
        self.calls.append((command, args))
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> SentCommands:
    from chatimport import cli

    fake = SentCommands()
    monkeypatch.setattr(cli, "send_command", fake)
    return fake


@pytest.fixture(autouse=True)
def no_leaked_threads() -> Iterator[None]:
    before = set(threading.enumerate())
    yield
    for thread in set(threading.enumerate()) - before:
        thread.join(5)
        assert not thread.is_alive(), f"leaked thread {thread.name}"
