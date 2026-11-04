from __future__ import annotations

import json
import logging
import shutil
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from chatimport import merged_export
from chatimport.merged_export import (
    META_NAME,
    build_merged,
    current_signature,
    last_result,
    merged_path,
    read_meta,
)
from chatimport.records import DeleteRecord, EditRecord, MediaSavedRecord
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import new_state, save_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import NOW, msg
from tests.unit.storage.helpers import at

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.records import Record


def make_chat(
    root: Path, chat_id: int, records: list[Record], title: str = "Chat", max_bytes: int = 10**9
) -> Path:
    folder = root / chat_folder_name(title, chat_id)
    writer = ChunkWriter(folder, max_bytes, clock=lambda: NOW)
    state = new_state(chat_id, title, None, NOW)
    if records:
        writer.append(state, records)
    else:
        folder.mkdir(parents=True)
        save_state(folder, state)
    return folder


def chats_logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [str(getattr(r, "chat")) for r in caplog.records if hasattr(r, "chat")]  # noqa: B009


def rows(root: Path, fmt: str = "json") -> list[dict[str, object]]:
    text = merged_path(root, fmt).read_text(encoding="utf-8")
    if fmt == "json":
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines()]


def ids(root: Path, fmt: str = "json") -> list[tuple[object, object]]:
    return [(r["chat_id"], r.get("msg_id")) for r in rows(root, fmt)]


def test_records_of_all_chats_are_sorted_by_date_chat_and_msg(tmp_path: Path) -> None:
    make_chat(
        tmp_path,
        -2,
        [msg(1, chat_id=-2, date=at(2026, 9, 1)), msg(2, chat_id=-2, date=at(2026, 9, 3))],
    )
    make_chat(
        tmp_path,
        -1,
        [msg(5, chat_id=-1, date=at(2026, 9, 2)), msg(6, chat_id=-1, date=at(2026, 9, 4))],
    )
    result = build_merged(tmp_path, now=NOW)
    assert (result.chats, result.records, result.skipped) == (2, 4, False)
    assert ids(tmp_path) == [(-2, 1), (-1, 5), (-2, 2), (-1, 6)]


def test_equal_dates_are_ordered_by_chat_id_then_msg_id(tmp_path: Path) -> None:
    same = at(2026, 9, 1)
    make_chat(tmp_path, 7, [msg(2, chat_id=7, date=same), msg(1, chat_id=7, date=same)])
    make_chat(tmp_path, 3, [msg(9, chat_id=3, date=same)])
    build_merged(tmp_path, now=NOW)
    assert ids(tmp_path) == [(3, 9), (7, 1), (7, 2)]


def test_several_parts_per_month_and_months_stay_ordered(tmp_path: Path) -> None:
    many: list[Record] = [
        msg(i, chat_id=5, date=at(2026, 8 + (i - 1) // 20, 1 + (i - 1) % 20)) for i in range(1, 41)
    ]
    make_chat(tmp_path, 5, many, max_bytes=1500)
    make_chat(tmp_path, 6, [msg(1, chat_id=6, date=at(2026, 8, 10, 5))])
    build_merged(tmp_path, now=NOW)
    got = rows(tmp_path)
    assert len(got) == 41
    dates = [str(r["date"]) for r in got]
    assert dates == sorted(dates)


def test_out_of_order_month_is_sorted_and_edit_and_delete_records_are_kept(tmp_path: Path) -> None:
    records: list[Record] = [
        msg(1, date=at(2026, 9, 1)),
        msg(2, date=at(2026, 9, 5)),
        EditRecord(1, 1, at(2026, 9, 3), NOW, "new"),
        DeleteRecord(1, (2,), at(2026, 9, 2), "recheck"),
        MediaSavedRecord(1, 2, "media/a.jpg", at(2026, 9, 6)),
    ]
    make_chat(tmp_path, 1, records)
    build_merged(tmp_path, now=NOW)
    kinds = [r["kind"] for r in rows(tmp_path)]
    assert kinds == ["message", "delete", "edit", "message", "media_saved"]


def test_every_object_names_its_chat(tmp_path: Path) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)], title="Alpha")
    build_merged(tmp_path, now=NOW)
    (row,) = rows(tmp_path)
    assert row["chat_id"] == 1
    assert row["chat_title"] == "Alpha"
    assert row["chat_folder"] == folder.name


def test_title_falls_back_to_the_folder_name_without_state(tmp_path: Path) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    (folder / "state.json").unlink()
    build_merged(tmp_path, now=NOW)
    assert rows(tmp_path)[0]["chat_title"] == folder.name


def test_title_falls_back_when_state_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)])

    def unreadable(path: Path) -> None:
        raise merged_export.StateUnreadable(path, OSError("busy"))

    monkeypatch.setattr(merged_export, "load_state", unreadable)
    build_merged(tmp_path, now=NOW)
    assert rows(tmp_path)[0]["chat_title"] == folder.name
    assert current_signature(tmp_path)[folder.name][:2] == [0, 0]


@pytest.mark.parametrize("names", [False, True])
def test_names_and_raw_are_stripped_unless_asked(tmp_path: Path, names: bool) -> None:
    make_chat(
        tmp_path,
        1,
        [msg(1, chat_id=1, sender_name="Ann", sender_username="ann", raw={"x": 1})],
    )
    build_merged(tmp_path, now=NOW, include_names=names)
    (row,) = rows(tmp_path)
    if names:
        assert (row["sender_name"], row["sender_username"], row["raw"]) == ("Ann", "ann", {"x": 1})
    else:
        assert row["sender_name"] is None
        assert row["sender_username"] is None
        assert "raw" not in row


def test_jsonl_is_one_object_per_line(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1, text="a" + chr(0x2028) + "b"), msg(2, chat_id=1)])
    result = build_merged(tmp_path, now=NOW, fmt="jsonl")
    text = result.path.read_text(encoding="utf-8")
    assert result.path.name == "all_chats.jsonl"
    assert text.endswith("\n")
    assert len(text.split("\n")) == 3
    assert [r["msg_id"] for r in rows(tmp_path, "jsonl")] == [1, 2]
    assert result.bytes == len(text.encode("utf-8"))


def test_json_layout_matches_export_json_and_counts_bytes(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1), msg(2, chat_id=1)])
    result = build_merged(tmp_path, now=NOW)
    text = result.path.read_text(encoding="utf-8")
    assert text.startswith("[\n{")
    assert text.endswith("}\n]\n")
    assert "},\n{" in text
    assert result.bytes == len(text.encode("utf-8"))


def test_empty_archive_gives_an_empty_array_and_empty_jsonl(tmp_path: Path) -> None:
    build_merged(tmp_path, now=NOW)
    assert merged_path(tmp_path, "json").read_text(encoding="utf-8") == "[]\n"
    result = build_merged(tmp_path, now=NOW, fmt="jsonl")
    assert result.records == 0
    assert result.path.read_text(encoding="utf-8") == ""


def test_an_empty_chat_adds_nothing(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [])
    make_chat(tmp_path, 2, [msg(1, chat_id=2)])
    result = build_merged(tmp_path, now=NOW)
    assert (result.chats, result.records) == (2, 1)


def test_unknown_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="format must be one of"):
        build_merged(tmp_path, now=NOW, fmt="xml")


def test_unchanged_archive_skips_the_rebuild(tmp_path: Path) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    first = build_merged(tmp_path, now=NOW)
    target = first.path
    stamp = target.stat().st_mtime_ns
    second = build_merged(tmp_path, now=NOW + timedelta(minutes=5))
    assert second.skipped is True
    assert second.built_at == first.built_at
    assert second.records == first.records
    assert target.stat().st_mtime_ns == stamp
    writer = ChunkWriter(folder, 10**9, clock=lambda: NOW)
    state = new_state(1, "Chat", None, NOW)
    writer.append(
        merged_export.load_state(folder) or state,
        [msg(2, chat_id=1, date=NOW + timedelta(hours=1))],
    )
    third = build_merged(tmp_path, now=NOW + timedelta(minutes=10))
    assert (third.skipped, third.records) == (False, 2)


@pytest.mark.parametrize(
    "change",
    [{"fmt": "jsonl"}, {"include_names": True}],
)
def test_a_changed_option_forces_a_rebuild(tmp_path: Path, change: dict[str, object]) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    build_merged(tmp_path, now=NOW)
    assert build_merged(tmp_path, now=NOW, **change).skipped is False  # type: ignore[arg-type]  # a keyword subset


def test_force_rebuilds_even_when_nothing_changed(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    build_merged(tmp_path, now=NOW)
    assert build_merged(tmp_path, now=NOW, force=True).skipped is False


def test_a_missing_output_file_forces_a_rebuild(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    first = build_merged(tmp_path, now=NOW)
    first.path.unlink()
    assert build_merged(tmp_path, now=NOW).skipped is False
    assert first.path.is_file()


def test_unreadable_meta_forces_a_rebuild(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    build_merged(tmp_path, now=NOW)
    (tmp_path / "_exports" / META_NAME).write_text("{", encoding="utf-8")
    assert build_merged(tmp_path, now=NOW).skipped is False


def test_a_meta_that_cannot_be_turned_into_a_result_forces_a_rebuild(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    build_merged(tmp_path, now=NOW)
    meta = read_meta(tmp_path)
    assert meta is not None
    meta["records"] = "many"
    (tmp_path / "_exports" / META_NAME).write_text(json.dumps(meta), encoding="utf-8")
    assert last_result(tmp_path) is None
    assert build_merged(tmp_path, now=NOW).skipped is False


@pytest.mark.parametrize("text", ["[1]", '{"v": 99}'])
def test_meta_of_the_wrong_shape_is_ignored(tmp_path: Path, text: str) -> None:
    (tmp_path / "_exports").mkdir()
    (tmp_path / "_exports" / META_NAME).write_text(text, encoding="utf-8")
    assert read_meta(tmp_path) is None
    assert last_result(tmp_path) is None


def test_last_result_reads_the_meta(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    built = build_merged(tmp_path, now=NOW)
    assert last_result(tmp_path) == built


def test_the_other_format_is_removed_after_a_build(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    build_merged(tmp_path, now=NOW)
    build_merged(tmp_path, now=NOW, fmt="jsonl")
    assert not merged_path(tmp_path, "json").exists()
    assert merged_path(tmp_path, "jsonl").exists()


def test_a_failed_build_keeps_the_old_file_and_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    first = build_merged(tmp_path, now=NOW)
    before = first.path.read_bytes()
    meta_before = (tmp_path / "_exports" / META_NAME).read_bytes()
    writer = ChunkWriter(folder, 10**9, clock=lambda: NOW)
    state = merged_export.load_state(folder)
    assert state is not None
    writer.append(state, [msg(2, chat_id=1, date=NOW + timedelta(hours=1))])

    def broken(*_a: object, **_k: object) -> object:
        raise RuntimeError("disk full")

    monkeypatch.setattr(merged_export, "export_dict", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        build_merged(tmp_path, now=NOW + timedelta(minutes=1))
    assert first.path.read_bytes() == before
    assert (tmp_path / "_exports" / META_NAME).read_bytes() == meta_before
    assert [p.name for p in (tmp_path / "_exports").iterdir() if p.name.endswith(".tmp")] == []


def test_a_chat_that_vanishes_is_skipped_with_a_warning_of_its_id(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1, text="secret text")])
    gone = make_chat(tmp_path, 2, [msg(1, chat_id=2)], title="Secret title")
    original = merged_export.iter_chat_folders

    calls: list[int] = []

    def listing(root: Path) -> object:
        found = list(original(root))
        calls.append(1)
        if len(calls) == 2:
            shutil.rmtree(gone)
        return iter(found)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(merged_export, "iter_chat_folders", listing)
        with caplog.at_level(logging.WARNING):
            result = build_merged(tmp_path, now=NOW)
    assert result.records == 1
    assert chats_logged(caplog) == ["2"]
    assert "secret" not in caplog.text.lower()


def test_a_part_that_vanishes_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    folder = make_chat(tmp_path, 1, [msg(i, chat_id=1) for i in range(1, 4)])
    make_chat(tmp_path, 2, [msg(1, chat_id=2)])
    original = merged_export.iter_part_records

    def reading(path: Path) -> object:
        if path.parent == folder:
            raise FileNotFoundError(path)
        return original(path)

    monkeypatch.setattr(merged_export, "iter_part_records", reading)
    with caplog.at_level(logging.WARNING):
        result = build_merged(tmp_path, now=NOW)
    assert result.records == 1
    assert "1" in chats_logged(caplog)


def test_a_folder_that_cannot_be_listed_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])

    def broken(folder: Path) -> list[Path]:
        raise PermissionError(folder)

    monkeypatch.setattr(merged_export, "list_parts", broken)
    assert build_merged(tmp_path, now=NOW).records == 0


def test_unknown_folder_name_logs_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "2026-09_001.jsonl").write_text("{}\n", encoding="utf-8")

    def broken(path: Path) -> object:
        raise OSError(path)

    monkeypatch.setattr(merged_export, "iter_part_records", broken)
    with caplog.at_level(logging.WARNING):
        build_merged(tmp_path, now=NOW)
    assert chats_logged(caplog)[0] == "unknown"


def test_signature_uses_part_sizes_when_state_is_missing(tmp_path: Path) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    (folder / "state.json").unlink()
    (last,) = current_signature(tmp_path).values()
    assert last[:2] == [0, 0]
    assert last[2] > 0


def test_signature_survives_a_part_that_vanishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    (folder / "state.json").unlink()
    ghost = folder / "2026-09_009.jsonl"
    monkeypatch.setattr(merged_export, "list_parts", lambda _f: [ghost])  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    assert current_signature(tmp_path) == {folder.name: [0, 0, 0]}


def test_result_serialises_for_the_control_reply(tmp_path: Path) -> None:
    make_chat(tmp_path, 1, [msg(1, chat_id=1)])
    data = build_merged(tmp_path, now=NOW).to_dict()
    assert data["records"] == 1
    assert data["built_at"] == "2026-10-29T12:00:00Z"
    assert data["skipped"] is False
    assert data["path"].endswith("all_chats.json")
