from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from chatimport.export import export_chat_json
from chatimport.integrity import ERROR, INFO, check_root
from chatimport.records import EditRecord, record_to_bytes
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import save_state
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import at, fresh_state, make_writer

if TYPE_CHECKING:
    import pytest

DEEP = b'{"a":' + b"[" * 100_000 + b"]" * 100_000 + b"}"


def build(folder: Path) -> None:
    writer = make_writer(folder)
    named = msg(
        1,
        date=at(2026, 10, 1),
        text=f"x{chr(0x2028)}y",
        sender_name="Someone",
        sender_username="someone",
        raw={"fwd_from": {"from_name": "Hidden"}},
    )
    writer.append(fresh_state(), [named, EditRecord(CHAT_ID, 1, at(2026, 10, 2), NOW, "e")])


def test_export_no_names_strips_sender_fields(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder)
    out = export_chat_json(folder, include_names=False)
    text = out.read_text(encoding="utf-8")
    assert "Someone" not in text
    assert "Hidden" not in text
    message, edit = json.loads(text)
    assert (message["sender_name"], message["sender_username"]) == (None, None)
    assert "raw" not in message
    assert edit["text"] == "e"


def test_export_escapes_unicode_line_breaks(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder)
    text = export_chat_json(folder).read_text(encoding="utf-8")
    assert chr(0x2028) not in text
    assert json.loads(text)[0]["text"] == f"x{chr(0x2028)}y"
    assert json.loads(text)[0]["sender_name"] == "Someone"


def test_recover_does_not_touch_foreign_tmp_outside_the_chat(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder)
    exports = tmp_path / "_exports"
    exports.mkdir()
    (exports / ".chat_-1.json.abc.tmp").write_bytes(b"in progress")
    recover_chat(folder, now=NOW)
    assert (exports / ".chat_-1.json.abc.tmp").exists()


def test_check_reports_a_deeply_nested_line_without_raising(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    make_writer(folder).append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    part = folder / "2026-10_001.jsonl"
    part.write_bytes(DEEP + b"\n" + part.read_bytes())
    issues = check_root(tmp_path, repair=False, now=NOW)
    assert any(i.severity == ERROR and "unparsable line" in i.message for i in issues)


def test_check_reports_an_unreadable_state_and_repair_does_not_rebuild_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "chat_-1"
    make_writer(folder).append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    (folder / "2026-10_002.jsonl").write_bytes(record_to_bytes(msg(2, date=at(2026, 10, 2))))
    before = (folder / "state.json").read_bytes()
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "state.json":
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    issues = check_root(tmp_path, repair=True, now=NOW)
    monkeypatch.undo()
    assert any("cannot be read now" in i.message for i in issues)
    assert (folder / "state.json").read_bytes() == before


def test_check_repair_reports_a_state_that_becomes_unreadable_mid_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport import integrity
    from chatimport.storage.state import StateUnreadable

    folder = tmp_path / "chat_-1"
    folder.mkdir()
    (folder / "2026-10_001.jsonl").write_bytes(record_to_bytes(msg(1, date=at(2026, 10, 1))))

    def unreadable(path: Path, **_: object) -> None:
        raise StateUnreadable(path, PermissionError("busy"))

    monkeypatch.setattr(integrity, "recover_chat", unreadable)
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert any(i.severity == ERROR and i.message.startswith("repair failed") for i in issues)


def test_leftovers_are_only_touched_in_real_chat_folders(tmp_path: Path) -> None:
    chat = tmp_path / "chat_-1"
    save_state(chat, fresh_state())
    (chat / ".x.tmp").write_bytes(b"x")
    other = tmp_path / "control"
    other.mkdir()
    (other / ".cmd.json.123.tmp").write_bytes(b"in flight")
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert not (chat / ".x.tmp").exists()
    assert (other / ".cmd.json.123.tmp").exists()
    assert any(i.severity == INFO and "leftover deleted" in i.message for i in issues)
    assert not any(".cmd.json" in i.message for i in issues)
