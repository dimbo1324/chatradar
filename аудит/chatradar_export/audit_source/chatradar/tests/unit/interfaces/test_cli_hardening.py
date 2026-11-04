from __future__ import annotations

import io
import json
import sys
from typing import TYPE_CHECKING, Any

import pytest
from rich.cells import cell_len

from chatimport import app as app_module
from chatimport import cli, cli_chats, cli_support
from chatimport.ports import ResolvedChat, ResolveStatus
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import StateUnreadable, new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import CHAT_ID, NOW, msg

if TYPE_CHECKING:
    from pathlib import Path

    from typer.testing import Result

    from tests.unit.interfaces.conftest import Env

FIRE = "\U0001f525"
NEWS = "\u041d\u043e\u0432\u043e\u0441\u0442\u0438"


def invoke(env: Env, *args: str) -> Result:
    return env.runner.invoke(cli.app, list(args))


@pytest.fixture
def cloud_root(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OneDrive", str(env.home))


@pytest.fixture
def local_root(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------ console encoding


@pytest.fixture
def invoked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(cli, "app", lambda: calls.append("app"))
    return calls


def test_run_respects_pythonioencoding(monkeypatch: pytest.MonkeyPatch, invoked: list[str]) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp866")
    monkeypatch.setenv("PYTHONIOENCODING", "cp866")
    monkeypatch.setattr(sys, "stdout", out)

    cli.run()

    assert out.encoding == "cp866"
    assert invoked == ["app"]
    monkeypatch.undo()
    out.detach()


def test_run_replaces_what_utf8_cannot_encode_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, invoked: list[str]
) -> None:
    sink = io.BytesIO()
    out = io.TextIOWrapper(sink, encoding="cp1252")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(sys, "stdout", out)

    cli.run()
    out.write("a\udc80b")
    out.flush()

    assert sink.getvalue() == b"a?b"
    monkeypatch.undo()
    out.detach()


# ------------------------------------------------------------------ table width


def test_table_aligns_wide_titles(capsys: pytest.CaptureFixture[str]) -> None:
    cli_support.table(
        [
            ("TITLE", "LINK"),
            (f"{FIRE} {NEWS}", "a"),
            ("Cafe\u0301", "b"),
            ("Plain", "c"),
        ]
    )

    lines = capsys.readouterr().out.splitlines()
    offsets = {cell_len(line[: line.rindex(" ") + 1]) for line in lines}
    assert len(offsets) == 1


# ------------------------------------------------------------------ logging and cloud warning


def test_run_logs_to_the_console_and_the_log_folder(
    env: Env, monkeypatch: pytest.MonkeyPatch, logging_setups: list[tuple[Path | None, bool]]
) -> None:
    class Service:
        def __init__(self, ctx: Any, *, notifier: Any) -> None:
            pass

        async def run(self) -> None:
            return None

    monkeypatch.setattr(app_module, "ChatImportApp", Service)

    assert invoke(env, "run").exit_code == 0
    assert logging_setups == [(env.ctx.paths.log_dir, True)]


def test_run_warns_when_the_data_root_is_cloud_synced(
    env: Env, monkeypatch: pytest.MonkeyPatch, cloud_root: None
) -> None:
    class Service:
        def __init__(self, ctx: Any, *, notifier: Any) -> None:
            pass

        async def run(self) -> None:
            return None

    monkeypatch.setattr(app_module, "ChatImportApp", Service)

    result = invoke(env, "run")

    assert result.exit_code == 0
    assert "synced to the cloud" in result.output


def test_status_warns_when_the_data_root_is_cloud_synced(env: Env, cloud_root: None) -> None:
    result = invoke(env, "status")

    assert "synced to the cloud" in result.output


def test_status_of_a_local_root_has_no_cloud_warning(env: Env, local_root: None) -> None:
    result = invoke(env, "status")

    assert "synced to the cloud" not in result.output


# ------------------------------------------------------------------ export-json names


def chat_with_names(env: Env) -> Path:
    folder = env.ctx.root / chat_folder_name("Named", CHAT_ID)
    state = new_state(CHAT_ID, "Named", None, NOW)
    ChunkWriter(folder, 10**6).append(
        state, [msg(1, sender_name="Ann Example", sender_username="ann_example")]
    )
    return folder


def exported(env: Env, *flags: str) -> str:
    out = env.home / "out.json"
    result = invoke(env, "export-json", "--chat", str(CHAT_ID), "--out", str(out), *flags)
    assert result.exit_code == 0, result.output
    return out.read_text(encoding="utf-8")


def test_export_json_leaves_sender_names_out_by_default(env: Env) -> None:
    chat_with_names(env)

    text = exported(env)

    assert "Ann Example" not in text
    assert "ann_example" not in text
    assert json.loads(text)[0]["msg_id"] == 1


def test_export_json_keeps_sender_names_on_request(env: Env) -> None:
    chat_with_names(env)

    assert "Ann Example" in exported(env, "--names")


# ------------------------------------------------------------------ set-root


def test_set_root_refuses_a_folder_inside_the_application_folder(env: Env) -> None:
    target = env.ctx.paths.base / "data"

    result = invoke(env, "set-root", str(target), "--move")

    assert result.exit_code == 1
    assert "application folder" in result.output
    assert "root_dir" not in env.ctx.paths.config_file.read_text(encoding="utf-8")


def test_set_root_without_move_refuses_a_foreign_non_empty_folder(env: Env) -> None:
    target = env.home / "busy" / "ChatImport"
    target.mkdir(parents=True)
    (target / "notes.txt").write_text("mine", encoding="utf-8")

    result = invoke(env, "set-root", str(target), "--yes")

    assert result.exit_code == 1
    assert "holds no ChatImport data" in result.output


# ------------------------------------------------------------------ chats list rows


def test_records_on_disk_of_an_unreadable_state_is_unknown(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = env.make_chat()

    def locked(path: Path) -> None:
        raise StateUnreadable(path, PermissionError("locked"))

    monkeypatch.setattr(cli_chats, "load_state", locked)

    assert cli_chats.records_on_disk(env.ctx.root, CHAT_ID) is None
    assert folder.is_dir()


def test_records_on_disk_counts_the_stored_records(env: Env) -> None:
    env.make_chat(ids=range(1, 4))

    assert cli_chats.records_on_disk(env.ctx.root, CHAT_ID) == 3
    assert cli_chats.records_on_disk(env.ctx.root, -999) is None


def test_library_rows_merge_resolution_and_disabled_entries() -> None:
    from chatimport.library import ChatEntry, Library

    found = ChatEntry("@a", "Alpha")
    missing = ChatEntry("@b")
    disabled = ChatEntry("@c", enabled=False)
    library = Library((found, missing, disabled))
    resolved = [
        (found, ResolvedChat("@a", ResolveStatus.FOUND, chat_id=-5, title="A")),
        (missing, ResolvedChat("@b", ResolveStatus.NOT_FOUND)),
    ]

    rows = cli_chats.library_rows(library, resolved, lambda chat_id: {-5: 7}.get(chat_id))

    assert rows == [
        ("Alpha", "@a", "found", "-5", "A", "7"),
        ("@b", "@b", "not_found", "", "", ""),
        ("@c", "@c", "disabled", "", "", ""),
    ]
