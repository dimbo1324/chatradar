from __future__ import annotations

import json
import os
import shutil
from typing import TYPE_CHECKING

import pytest

from chatimport.export import export_chat_json
from chatimport.records import DeleteRecord, EditRecord, MediaSavedRecord, MessageRecord
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import (
    EMOJI,
    LINE_SEP,
    RU_LOWER,
    ZH,
    at,
    fresh_state,
    make_writer,
)

if TYPE_CHECKING:
    from pathlib import Path


def build(
    folder: Path, count: int, *, max_bytes: int = 10**9, text: str | None = None
) -> list[MessageRecord]:
    writer = make_writer(folder, max_bytes=max_bytes)
    records = [
        msg(i, date=at(2026, 8 + (i % 3), 1 + i % 27, i % 24), text=text)
        for i in range(1, count + 1)
    ]
    if records:
        writer.append(fresh_state(), records)
    return records


def test_export_of_a_folder_without_records_is_an_empty_json_array(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    folder.mkdir()
    out = export_chat_json(folder)
    assert json.loads(out.read_text(encoding="utf-8")) == []


def test_export_of_one_record(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    (record,) = build(folder, 1)
    out = export_chat_json(folder)
    assert json.loads(out.read_text(encoding="utf-8")) == [record.to_dict()]


def test_export_of_many_records_is_one_valid_array_in_part_order(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 120, max_bytes=2000)
    data = json.loads(export_chat_json(folder).read_text(encoding="utf-8"))
    assert len(data) == 120
    months = [d["date"][:7] for d in data]
    assert months == sorted(months)


def test_export_includes_every_record_kind(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    writer = make_writer(folder)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    writer.append(
        state,
        [
            EditRecord(CHAT_ID, 1, at(2026, 10, 2), NOW, "new"),
            DeleteRecord(CHAT_ID, (1,), NOW),
            MediaSavedRecord(CHAT_ID, 1, "media/1.jpg", NOW),
        ],
    )
    data = json.loads(export_chat_json(folder).read_text(encoding="utf-8"))
    assert [d["kind"] for d in data] == ["message", "edit", "delete", "media_saved"]


def test_export_streams_a_large_set(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 5000, max_bytes=200_000)
    out = export_chat_json(folder)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len([d for d in data if d["kind"] == "message"]) == 5000


def test_export_preserves_unicode_and_awkward_text(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    text = f'{RU_LOWER} {EMOJI} {ZH}\nsecond{LINE_SEP}line "q" \\'
    build(folder, 1, text=text)
    out = export_chat_json(folder)
    assert json.loads(out.read_text(encoding="utf-8"))[0]["text"] == text
    assert RU_LOWER.encode() in out.read_bytes()


def test_export_default_path_is_in_the_exports_service_folder_outside_the_chat(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 1)
    target = tmp_path / "_exports" / "chat_-1.json"
    assert export_chat_json(folder) == target
    assert target.is_file()
    assert not (folder / "chat_-1.json").exists()


def test_exporting_twice_overwrites_and_ignores_its_own_previous_output(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 3)
    first = export_chat_json(folder).read_bytes()
    second = export_chat_json(folder).read_bytes()
    assert first == second
    assert len(json.loads(second)) == 3


def test_export_to_an_explicit_path_creates_missing_parents(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 2)
    target = tmp_path / "deep" / "er" / "out.json"
    assert export_chat_json(folder, target) == target
    assert len(json.loads(target.read_text(encoding="utf-8"))) == 2
    assert not (folder / "chat_-1.json").exists()


def test_export_overwrites_an_existing_target(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 2)
    target = tmp_path / "out.json"
    target.write_text("old content", encoding="utf-8")
    export_chat_json(folder, target)
    assert len(json.loads(target.read_text(encoding="utf-8"))) == 2


def test_export_uses_lf_line_endings_and_ends_with_a_newline(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 3)
    raw = export_chat_json(folder).read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"]\n")
    assert raw.startswith(b"[\n")


def test_empty_export_is_exactly_brackets(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    folder.mkdir()
    assert export_chat_json(folder).read_bytes() == b"[]\n"


def test_failure_leaves_no_partial_target_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 5)
    target = tmp_path / "out.json"

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="replace failed"):
        export_chat_json(folder, target)
    monkeypatch.undo()
    assert not target.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_failure_keeps_a_previous_export_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 5)
    target = tmp_path / "out.json"
    target.write_text("previous export", encoding="utf-8")

    def broken(_fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(OSError, match="fsync failed"):
        export_chat_json(folder, target)
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == "previous export"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_failure_while_reading_a_record_leaves_no_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chatimport import export as export_module

    folder = tmp_path / "chat_-1"
    build(folder, 5)

    def exploding(_folder: Path) -> object:
        yield msg(1)
        raise OSError("read error")

    monkeypatch.setattr(export_module, "iter_records", exploding)
    target = tmp_path / "out.json"
    with pytest.raises(OSError, match="read error"):
        export_chat_json(folder, target)
    assert not target.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_export_leaves_the_folder_deletable(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 3)
    export_chat_json(folder)
    shutil.rmtree(folder)
    assert not folder.exists()


def test_export_skips_unparsable_lines(tmp_path: Path) -> None:
    folder = tmp_path / "chat_-1"
    build(folder, 2)
    part = next(folder.glob("*.jsonl"))
    part.write_bytes(part.read_bytes() + b"garbage\n")
    assert len(json.loads(export_chat_json(folder).read_text(encoding="utf-8"))) == 2
