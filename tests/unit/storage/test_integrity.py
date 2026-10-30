from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from chatimport import integrity
from chatimport.integrity import ERROR, INFO, WARNING, CheckIssue, check_root
from chatimport.records import MediaSavedRecord, record_to_line
from chatimport.storage.state import load_state
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import at, fresh_state, make_writer

if TYPE_CHECKING:
    import pytest

FOLDER_NAME = "example_-1001234567890"


def build_chat(
    root: Path, name: str = FOLDER_NAME, chat_id: int = CHAT_ID, *, max_bytes: int = 10**9
) -> Path:
    folder = root / name
    writer = make_writer(folder, max_bytes=max_bytes)
    writer.append(
        fresh_state(chat_id),
        [
            msg(1, chat_id=chat_id, date=at(2026, 10, 1)),
            msg(2, chat_id=chat_id, date=at(2026, 10, 2)),
        ],
    )
    return folder


def line(msg_id: int) -> bytes:
    return record_to_line(msg(msg_id, date=at(2026, 10, 1))).encode()


def messages(issues: list[CheckIssue], severity: str | None = None) -> list[str]:
    return [i.message for i in issues if severity is None or i.severity == severity]


def test_clean_root_has_no_issues(tmp_path: Path) -> None:
    build_chat(tmp_path)
    assert check_root(tmp_path, repair=False, now=NOW) == []
    assert check_root(tmp_path, repair=True, now=NOW) == []


def test_missing_and_empty_roots_are_clean(tmp_path: Path) -> None:
    assert check_root(tmp_path / "missing", repair=False, now=NOW) == []
    assert check_root(tmp_path, repair=True, now=NOW) == []


def test_service_entries_and_files_in_the_root_are_not_checked(tmp_path: Path) -> None:
    (tmp_path / "_status.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_service").mkdir()
    (tmp_path / "_service" / "garbage.jsonl").write_text("junk", encoding="utf-8")
    assert check_root(tmp_path, repair=False, now=NOW) == []


def test_check_without_repair_never_modifies_anything(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / "state.json").unlink()
    (folder / "2026-10_001.jsonl").write_bytes(line(1) + b"\n" + b"cut")
    (folder / ".state.json.tmp").write_bytes(b"x")
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    check_root(tmp_path, repair=False, now=NOW)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot


def test_missing_state_is_a_fixable_error_and_repair_round_trips(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / "state.json").unlink()
    issues = check_root(tmp_path, repair=False, now=NOW)
    assert [(i.severity, i.message) for i in issues] == [(ERROR, "state.json is missing")]
    assert issues[0].chat_id == CHAT_ID
    check_root(tmp_path, repair=True, now=NOW)
    assert load_state(folder) is not None
    assert check_root(tmp_path, repair=False, now=NOW) == []


def test_unparsable_state_is_reported_as_unparsable(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / "state.json").write_bytes(b"{broken")
    (issue,) = check_root(tmp_path, repair=False, now=NOW)
    assert issue.message == "state.json is unparsable"
    assert issue.severity == ERROR


def test_repair_reports_what_it_fixed_as_info_and_the_second_check_is_clean(
    tmp_path: Path,
) -> None:
    folder = build_chat(tmp_path)
    (folder / "state.json").write_bytes(b"")
    repaired = check_root(tmp_path, repair=True, now=NOW)
    assert [i.severity for i in repaired] == [INFO]
    assert repaired[0].message == "repaired: state.json is unparsable"
    assert check_root(tmp_path, repair=False, now=NOW) == []


def test_state_listing_a_missing_part_and_a_part_not_listed(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / "2026-10_001.jsonl").rename(folder / "2026-09_001.jsonl")
    found = messages(check_root(tmp_path, repair=False, now=NOW))
    assert "2026-10_001: listed in state.json but the file is missing" in found
    assert "2026-09_001: file is not listed in state.json" in found


def test_record_and_byte_mismatches_are_reported_separately(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    path = folder / "2026-10_001.jsonl"
    path.write_bytes(path.read_bytes() + line(3) + b"\n")
    found = messages(check_root(tmp_path, repair=False, now=NOW))
    assert any("state.json has 2 records, the file has 3" in m for m in found)
    assert any("bytes, the file has" in m for m in found)
    assert any(m.startswith("last_id 2 is below the highest id 3") for m in found)


def test_byte_mismatch_without_a_record_mismatch(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    path = folder / "2026-10_001.jsonl"
    path.write_bytes(path.read_bytes() + b"\n\n")
    found = messages(check_root(tmp_path, repair=False, now=NOW))
    assert len(found) == 1
    assert "bytes" in found[0]


def test_repair_of_a_stale_state_round_trips_to_clean(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    path = folder / "2026-10_001.jsonl"
    path.write_bytes(path.read_bytes() + line(3) + b"\n")
    (folder / "2026-11_001.jsonl").write_bytes(line(9) + b"\n")
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert issues
    assert all(i.severity == INFO for i in issues)
    assert check_root(tmp_path, repair=False, now=NOW) == []
    state = load_state(folder)
    assert state is not None
    assert state.last_id == 9


def test_cut_last_line_is_fixable_and_repair_truncates_it(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    path = folder / "2026-10_001.jsonl"
    path.write_bytes(path.read_bytes() + b'{"v":1,"kind":"mess')
    (issue, *_) = check_root(tmp_path, repair=False, now=NOW)
    assert issue.severity == ERROR
    assert "1 unparsable line(s)" in issue.message
    assert "fix by hand" not in issue.message
    check_root(tmp_path, repair=True, now=NOW)
    assert check_root(tmp_path, repair=False, now=NOW) == []


def test_garbage_in_the_middle_is_reported_as_manual_and_repair_cannot_fix_it(
    tmp_path: Path,
) -> None:
    folder = build_chat(tmp_path)
    path = folder / "2026-10_001.jsonl"
    path.write_bytes(line(1) + b"\ngarbage\n" + line(2) + b"\n")
    issues = check_root(tmp_path, repair=True, now=NOW)
    bad = [i for i in issues if "unparsable" in i.message]
    assert len(bad) == 1
    assert bad[0].severity == ERROR
    assert "more than the last line; fix by hand" in bad[0].message
    assert path.read_bytes() == line(1) + b"\ngarbage\n" + line(2) + b"\n"


def test_two_bad_lines_are_not_auto_fixable(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    path = folder / "2026-10_001.jsonl"
    path.write_bytes(line(1) + b"\ngarbage\n" + b"more garbage\n")
    (issue, *_) = check_root(tmp_path, repair=False, now=NOW)
    assert "2 unparsable line(s) (more than the last line; fix by hand)" in issue.message


def test_stray_jsonl_names_are_warned_about(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / "notes.jsonl").write_bytes(b"")
    (folder / "2026-10_1000.jsonl").write_bytes(b"")
    found = messages(check_root(tmp_path, repair=False, now=NOW), WARNING)
    assert "notes.jsonl: name does not match YYYY-MM_NNN.jsonl" in found
    assert "2026-10_1000.jsonl: name does not match YYYY-MM_NNN.jsonl" in found


def test_out_of_order_messages_are_a_warning(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / "2026-10_001.jsonl").write_bytes(line(5) + b"\n" + line(3) + b"\n" + line(7) + b"\n")
    found = messages(check_root(tmp_path, repair=False, now=NOW), WARNING)
    assert "2026-10_001.jsonl: 1 message(s) out of msg_id order" in found


def test_edits_appended_after_higher_ids_are_not_flagged_as_out_of_order(tmp_path: Path) -> None:
    folder = tmp_path / FOLDER_NAME
    writer = make_writer(folder)
    from chatimport.records import EditRecord

    state = writer.append(fresh_state(), [msg(10, date=at(2026, 10, 1))])
    writer.append(state, [EditRecord(CHAT_ID, 2, at(2026, 10, 2), NOW, "t")])
    assert check_root(tmp_path, repair=False, now=NOW) == []


def test_duplicate_ids_are_counted_across_parts(tmp_path: Path) -> None:
    folder = build_chat(tmp_path, max_bytes=1)
    writer = make_writer(folder, max_bytes=1)
    state = load_state(folder)
    assert state is not None
    writer.append(state, [msg(1, date=at(2026, 10, 3)), msg(2, date=at(2026, 10, 3))])
    found = messages(check_root(tmp_path, repair=False, now=NOW), WARNING)
    assert "2 duplicate message record(s)" in found


def test_a_part_that_starts_below_the_previous_parts_last_id_is_warned_within_a_month(
    tmp_path: Path,
) -> None:
    folder = build_chat(tmp_path, max_bytes=1)
    writer = make_writer(folder, max_bytes=1)
    state = load_state(folder)
    assert state is not None
    writer.append(state, [msg(1, date=at(2026, 10, 3))])
    found = messages(check_root(tmp_path, repair=False, now=NOW), WARNING)
    assert any("first id 1 is below the previous part's last id" in m for m in found)


def test_ids_restarting_in_a_new_month_are_not_a_cross_part_warning(tmp_path: Path) -> None:
    folder = tmp_path / FOLDER_NAME
    writer = make_writer(folder)
    state = writer.append(fresh_state(), [msg(100, date=at(2026, 9, 1))])
    writer.append(state, [msg(5, date=at(2026, 10, 1))])
    found = messages(check_root(tmp_path, repair=False, now=NOW), WARNING)
    assert not any("previous part" in m for m in found)


def test_missing_saved_media_is_a_warning_and_present_media_is_not(tmp_path: Path) -> None:
    folder = tmp_path / FOLDER_NAME
    writer = make_writer(folder)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    present = MediaSavedRecord(CHAT_ID, 1, "media/1.jpg", NOW)
    absent = MediaSavedRecord(CHAT_ID, 1, "media/gone.jpg", NOW)
    (folder / "media").mkdir()
    (folder / "media" / "1.jpg").write_bytes(b"jpg")
    writer.append(state, [present, absent])
    found = messages(check_root(tmp_path, repair=False, now=NOW))
    assert found == ["1 saved media file(s) are missing"]


def test_leftover_temp_files_are_info_and_repair_deletes_them(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (folder / ".state.json.tmp").write_bytes(b"x")
    (folder / ".2026-10_002.jsonl.tmp").write_bytes(b"y")
    issues = check_root(tmp_path, repair=False, now=NOW)
    assert {i.severity for i in issues} == {INFO}
    assert messages(issues) == [
        ".2026-10_002.jsonl.tmp: leftover temp file",
        ".state.json.tmp: leftover temp file",
    ]
    assert (folder / ".state.json.tmp").exists()
    repaired = check_root(tmp_path, repair=True, now=NOW)
    assert messages(repaired) == [
        ".2026-10_002.jsonl.tmp: leftover deleted",
        ".state.json.tmp: leftover deleted",
    ]
    assert not list(folder.glob(".*.tmp"))
    assert check_root(tmp_path, repair=False, now=NOW) == []


def test_undeletable_leftover_is_a_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = build_chat(tmp_path)
    (folder / ".state.json.tmp").write_bytes(b"x")

    def locked(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", locked)
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert [(i.severity, i.message) for i in issues] == [
        (WARNING, ".state.json.tmp: cannot delete")
    ]


def test_issues_carry_the_chat_id_from_state_records_or_folder_name(tmp_path: Path) -> None:
    with_state = build_chat(tmp_path, "a_-1", -1)
    (with_state / "notes.jsonl").write_bytes(b"")

    no_state = build_chat(tmp_path, "b_-2", -2)
    (no_state / "state.json").unlink()

    empty = tmp_path / "c_-3"
    empty.mkdir()
    (empty / ".x.tmp").write_bytes(b"")

    issues = check_root(tmp_path, repair=False, now=NOW)
    by_folder = {i.folder: i.chat_id for i in issues}
    assert by_folder == {"a_-1": -1, "b_-2": -2, "c_-3": None}


def test_issues_are_sorted_by_folder_then_severity(tmp_path: Path) -> None:
    b = build_chat(tmp_path, "b_-2", -2)
    a = build_chat(tmp_path, "a_-1", -1)
    for folder in (a, b):
        (folder / "state.json").unlink()
        (folder / "notes.jsonl").write_bytes(b"")
        (folder / ".s.tmp").write_bytes(b"")
    issues = check_root(tmp_path, repair=False, now=NOW)
    assert [(i.folder, i.severity) for i in issues] == [
        ("a_-1", ERROR),
        ("a_-1", WARNING),
        ("a_-1", INFO),
        ("b_-2", ERROR),
        ("b_-2", WARNING),
        ("b_-2", INFO),
    ]


def test_repair_failure_inside_recover_is_reported_as_an_error(tmp_path: Path) -> None:
    folder = tmp_path / "weird"
    folder.mkdir()
    (folder / "2026-10_001.jsonl").write_bytes(b"")
    issues = check_root(tmp_path, repair=True, now=NOW)
    failed = [i for i in issues if i.message.startswith("repair failed")]
    assert len(failed) == 1
    assert failed[0].severity == ERROR
    assert "cannot recover weird" in failed[0].message
    assert any(i.message == "state.json is missing" for i in issues)


def test_repair_uses_the_folder_name_id_when_nothing_else_knows_it(tmp_path: Path) -> None:
    folder = tmp_path / "named_-4242"
    folder.mkdir()
    (folder / "2026-10_001.jsonl").write_bytes(b"")
    check_root(tmp_path, repair=True, now=NOW)
    state = load_state(folder)
    assert state is not None
    assert state.chat_id == -4242


def test_os_error_in_recover_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = build_chat(tmp_path)
    (folder / "state.json").unlink()

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(integrity, "recover_chat", broken)
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert any(i.severity == ERROR and "repair failed: disk gone" in i.message for i in issues)
    assert not (folder / "state.json").exists()


def test_repair_leaves_a_healthy_folder_untouched(tmp_path: Path) -> None:
    folder = build_chat(tmp_path)
    (tmp_path / "other_-5").mkdir()
    (tmp_path / "other_-5" / "notes.jsonl").write_bytes(b"")
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    check_root(tmp_path, repair=True, now=NOW)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot


def test_non_fixable_issue_alongside_a_fixable_one_repairs_only_the_fixable(
    tmp_path: Path,
) -> None:
    folder = build_chat(tmp_path)
    (folder / "state.json").unlink()
    (folder / "2026-10_001.jsonl").write_bytes(line(2) + b"\n" + line(1) + b"\n")
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert "repaired: state.json is missing" in messages(issues, INFO)
    assert "2026-10_001.jsonl: 1 message(s) out of msg_id order" in messages(issues, WARNING)


def test_each_folder_is_handled_independently(tmp_path: Path) -> None:
    good = build_chat(tmp_path, "good_-1", -1)
    bad = build_chat(tmp_path, "bad_-2", -2)
    (bad / "state.json").unlink()
    issues = check_root(tmp_path, repair=True, now=NOW)
    assert {i.folder for i in issues} == {"bad_-2"}
    assert load_state(good) is not None
    assert load_state(bad) is not None
