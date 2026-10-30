from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from chatimport.library import (
    ChatEntry,
    LibraryError,
    add_entry,
    load_library,
    parse_library,
    set_enabled,
)

if TYPE_CHECKING:
    from pathlib import Path


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "chats.toml"


@pytest.fixture
def failing_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)


def leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_add_creates_a_missing_file_and_parent(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "er" / "chats.toml"
    add_entry(target, "@alpha")
    assert load_library(target).entries == (ChatEntry("@alpha"),)
    assert read(target) == '[[chat]]\nref = "@alpha"\n'
    assert leftovers(target.parent) == ["chats.toml"]


def test_add_with_name(path: Path) -> None:
    add_entry(path, "@alpha", "Alpha chat")
    assert load_library(path).entries == (ChatEntry("@alpha", "Alpha chat"),)


def test_add_strips_ref_and_name(path: Path) -> None:
    add_entry(path, "  @alpha ", "  Alpha ")
    assert load_library(path).entries == (ChatEntry("@alpha", "Alpha"),)


def test_add_separates_blocks_with_one_blank_line(path: Path) -> None:
    add_entry(path, "a")
    add_entry(path, "b")
    assert read(path) == '[[chat]]\nref = "a"\n\n[[chat]]\nref = "b"\n'


def test_add_to_an_empty_existing_file_adds_no_leading_blank_line(path: Path) -> None:
    write(path, "")
    add_entry(path, "a")
    assert read(path) == '[[chat]]\nref = "a"\n'


def test_add_to_a_whitespace_only_file(path: Path) -> None:
    write(path, "\n\n")
    add_entry(path, "a")
    assert load_library(path).entries == (ChatEntry("a"),)


def test_add_preserves_comments_and_existing_text_byte_for_byte(path: Path) -> None:
    original = '# my chats\n[[chat]]\nref = "a"  # first\nname = "A"\n\n# trailing note\n'
    write(path, original)
    add_entry(path, "b")
    assert read(path).startswith(original)
    assert [e.ref for e in load_library(path).entries] == ["a", "b"]


def test_add_terminates_a_last_line_without_newline(path: Path) -> None:
    write(path, '[[chat]]\nref = "a"')
    add_entry(path, "b")
    assert read(path) == '[[chat]]\nref = "a"\n\n[[chat]]\nref = "b"\n'


def test_add_keeps_crlf_consistent(path: Path) -> None:
    write(path, '# c\r\n[[chat]]\r\nref = "a"\r\n')
    add_entry(path, "b", "B")
    text = read(path)
    assert text.replace("\r\n", "").count("\n") == 0
    assert [e.ref for e in load_library(path).entries] == ["a", "b"]


def test_add_to_crlf_file_without_trailing_newline_stays_crlf(path: Path) -> None:
    write(path, '[[chat]]\r\nref = "a"')
    add_entry(path, "b")
    assert read(path).replace("\r\n", "").count("\n") == 0


def test_add_to_a_file_with_bom_drops_the_bom_and_keeps_entries(path: Path) -> None:
    path.write_bytes(b'\xef\xbb\xbf[[chat]]\nref = "a"\n')
    add_entry(path, "b")
    assert [e.ref for e in load_library(path).entries] == ["a", "b"]


@pytest.mark.parametrize("ref", ["", "   ", "\t\n"])
def test_add_rejects_an_empty_ref(path: Path, ref: str) -> None:
    with pytest.raises(LibraryError, match="ref must not be empty"):
        add_entry(path, ref)
    assert not path.exists()


@pytest.mark.parametrize("name", ["", "   "])
def test_add_rejects_an_empty_name(path: Path, name: str) -> None:
    with pytest.raises(LibraryError, match="name must not be empty"):
        add_entry(path, "a", name)
    assert not path.exists()


@pytest.mark.parametrize("second", ["a", "  a "])
def test_add_rejects_a_duplicate_and_leaves_the_file_alone(path: Path, second: str) -> None:
    add_entry(path, "a")
    before = read(path)
    with pytest.raises(LibraryError, match="already in the library"):
        add_entry(path, second)
    assert read(path) == before


def test_add_to_an_invalid_existing_file_fails_and_does_not_touch_it(path: Path) -> None:
    write(path, "[[chat\nbroken")
    with pytest.raises(LibraryError):
        add_entry(path, "a")
    assert read(path) == "[[chat\nbroken"
    assert leftovers(path.parent) == ["chats.toml"]


def test_add_to_a_file_with_invalid_utf8_fails_and_does_not_touch_it(path: Path) -> None:
    path.write_bytes(b'ref = "\xff"')
    with pytest.raises(LibraryError):
        add_entry(path, "a")
    assert path.read_bytes() == b'ref = "\xff"'


NASTY_REFS = [
    'He said "hi"',
    "back\\slash",
    "C:\\path\\to\\n",
    "'single'",
    "ends with backslash\\",
    "\u0427\u0430\u0442 \u0441 \u044d\u043c\u043e\u0434\u0437\u0438 \U0001f600",
    "\u4e2d\u6587",
    "tab\tinside",
    "new\nline",
    "carriage\rreturn",
    "nul\x00char",
    "bell\x07",
    "esc\x1b",
    "del\x7fchar",
    "bom\ufeffinside",
    "[[chat]]",
    'x\n[[chat]]\nref = "evil"',
    'x"\nenabled = false\n[[chat]]\nref = "y',
    "# not a comment",
    "a = 1",
    "[table]",
    '"""',
    "'''",
    "\\u0041",
    "line\u2028sep",
    "para\u2029sep",
    "nel\x85",
    "\U0010ffff",
    "{ref = 'x'}",
]


@pytest.mark.parametrize("ref", NASTY_REFS)
def test_add_round_trips_hostile_refs_exactly(path: Path, ref: str) -> None:
    add_entry(path, "first")
    add_entry(path, ref)
    entries = load_library(path).entries
    assert [e.ref for e in entries] == ["first", ref.strip()]
    assert all(e.enabled for e in entries)
    assert all(e.name is None for e in entries)


@pytest.mark.parametrize("name", NASTY_REFS)
def test_add_round_trips_hostile_names_exactly(path: Path, name: str) -> None:
    if not name.strip():
        pytest.skip("blank names are rejected")
    add_entry(path, "ref", name)
    assert load_library(path).entries == (ChatEntry("ref", name.strip()),)


@pytest.mark.parametrize("ref", NASTY_REFS)
def test_hostile_ref_can_be_disabled_and_enabled_again(path: Path, ref: str) -> None:
    add_entry(path, "first")
    add_entry(path, ref, "N")
    add_entry(path, "last")
    set_enabled(path, "N", False)
    assert [e.enabled for e in load_library(path).entries] == [True, False, True]
    set_enabled(path, "N", True)
    entries = load_library(path).entries
    assert [e.enabled for e in entries] == [True, True, True]
    assert entries[1].ref == ref.strip()


def test_add_writes_valid_utf8_without_bom(path: Path) -> None:
    add_entry(path, "\u0427\u0430\u0442")
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8")


def test_add_atomic_failure_leaves_the_original_untouched(
    path: Path, failing_replace: None
) -> None:
    original = '[[chat]]\nref = "a"\n'
    write(path, original)
    with pytest.raises(OSError, match="disk full"):
        add_entry(path, "b")
    assert read(path) == original
    assert leftovers(path.parent) == ["chats.toml"]


def test_add_atomic_failure_on_a_new_file_leaves_nothing(path: Path, failing_replace: None) -> None:
    with pytest.raises(OSError, match="disk full"):
        add_entry(path, "b")
    assert leftovers(path.parent) == []


def test_add_write_failure_before_replace_cleans_the_temp_file(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(descriptor: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError, match="fsync failed"):
        add_entry(path, "b")
    assert leftovers(path.parent) == []


def test_add_keyboard_interrupt_during_write_still_cleans_up(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(descriptor: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "fsync", interrupt)
    with pytest.raises(KeyboardInterrupt):
        add_entry(path, "b")
    assert leftovers(path.parent) == []


THREE = (
    "# top comment\n"
    "[[chat]]\n"
    'ref = "a"\n'
    'name = "Alpha"  # keep me\n'
    "\n"
    "[[chat]]\n"
    'ref = "b"\n'
    "enabled = true  # b is on\n"
    "\n"
    "# between\n"
    "[[chat]]\n"
    'ref = "c"\n'
    'name = "Gamma"\n'
)


def test_disable_replaces_existing_value_keeping_comment(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, "b", False)
    assert read(path) == THREE.replace("enabled = true  # b is on", "enabled = false  # b is on")


def test_disable_adds_the_key_after_the_last_key_of_the_block(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, "a", False)
    expected = THREE.replace(
        'name = "Alpha"  # keep me\n', 'name = "Alpha"  # keep me\nenabled = false\n'
    )
    assert read(path) == expected


def test_disable_the_last_block_without_trailing_newline(path: Path) -> None:
    write(path, '[[chat]]\nref = "a"\nname = "A"')
    set_enabled(path, "a", False)
    assert read(path) == '[[chat]]\nref = "a"\nname = "A"\nenabled = false\n'


def test_toggle_only_touches_the_target_block(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, "c", False)
    entries = load_library(path).entries
    assert [e.enabled for e in entries] == [True, True, False]


def test_enable_after_disable_restores_semantics(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, "a", False)
    set_enabled(path, "a", True)
    assert load_library(path) == parse_library(THREE)


def test_set_same_state_twice_is_stable(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, "a", False)
    once = read(path)
    set_enabled(path, "a", False)
    assert read(path) == once


def test_find_by_name_is_case_insensitive(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, "  gAmMa ", False)
    assert [e.enabled for e in load_library(path).entries] == [True, True, False]


def test_find_by_ref_with_surrounding_whitespace(path: Path) -> None:
    write(path, THREE)
    set_enabled(path, " b ", False)
    assert [e.enabled for e in load_library(path).entries] == [True, False, True]


def test_unknown_entry_is_an_error_and_the_file_is_untouched(path: Path) -> None:
    write(path, THREE)
    with pytest.raises(LibraryError, match="no library entry matches 'zzz'"):
        set_enabled(path, " zzz ", False)
    assert read(path) == THREE


def test_missing_file_is_an_error_not_a_crash(path: Path) -> None:
    with pytest.raises(LibraryError, match="no library entry"):
        set_enabled(path, "a", False)
    assert not path.exists()


def test_invalid_existing_file_is_rejected_untouched(path: Path) -> None:
    write(path, "[[chat]\n")
    with pytest.raises(LibraryError):
        set_enabled(path, "a", False)
    assert read(path) == "[[chat]\n"


def test_crlf_file_stays_crlf_and_only_target_changes(path: Path) -> None:
    text = THREE.replace("\n", "\r\n")
    write(path, text)
    set_enabled(path, "a", False)
    result = read(path)
    assert result.replace("\r\n", "").count("\n") == 0
    assert result == text.replace(
        'name = "Alpha"  # keep me\r\n', 'name = "Alpha"  # keep me\r\nenabled = false\r\n'
    )


def test_crlf_file_with_value_replacement(path: Path) -> None:
    text = THREE.replace("\n", "\r\n")
    write(path, text)
    set_enabled(path, "b", False)
    assert read(path) == text.replace("enabled = true", "enabled = false")


def test_crlf_last_line_without_newline_gets_crlf(path: Path) -> None:
    write(path, '[[chat]]\r\nref = "a"')
    set_enabled(path, "a", False)
    assert read(path) == '[[chat]]\r\nref = "a"\r\nenabled = false\r\n'


def test_header_with_spaces_and_trailing_comment_is_found(path: Path) -> None:
    write(path, '  [[ chat ]]  # first\n  ref = "a"\n[[chat]] # second\nref = "b"\n')
    set_enabled(path, "b", False)
    assert [e.enabled for e in load_library(path).entries] == [True, False]


def test_enabled_without_spaces_is_replaced(path: Path) -> None:
    write(path, '[[chat]]\nref = "a"\nenabled=true\n')
    set_enabled(path, "a", False)
    assert read(path) == '[[chat]]\nref = "a"\nenabled=false\n'


def test_enabled_key_of_another_block_is_not_confused(path: Path) -> None:
    write(path, '[[chat]]\nref = "a"\nenabled = false\n[[chat]]\nref = "b"\n')
    set_enabled(path, "b", False)
    assert [e.enabled for e in load_library(path).entries] == [False, False]
    set_enabled(path, "a", True)
    assert [e.enabled for e in load_library(path).entries] == [True, False]


def test_inline_array_entries_cannot_be_edited_and_fail_cleanly(path: Path) -> None:
    text = 'chat = [{ref = "a"}]\n'
    write(path, text)
    with pytest.raises(LibraryError, match="cannot locate"):
        set_enabled(path, "a", False)
    assert read(path) == text


def test_multiline_string_that_looks_like_a_header_does_not_derail_the_edit(path: Path) -> None:
    text = '[[chat]]\nref = "a"\nname = """\nnote\n[[chat]]\nmore\n"""\n[[chat]]\nref = "b"\n'
    write(path, text)
    set_enabled(path, "b", False)
    entries = load_library(path).entries
    assert [e.enabled for e in entries] == [True, False]
    assert entries[0].name == "note\n[[chat]]\nmore"


def test_set_enabled_atomic_failure_leaves_the_original(path: Path, failing_replace: None) -> None:
    write(path, THREE)
    with pytest.raises(OSError, match="disk full"):
        set_enabled(path, "a", False)
    assert read(path) == THREE
    assert leftovers(path.parent) == ["chats.toml"]


def test_set_enabled_duplicate_names_edit_the_first_match_only(path: Path) -> None:
    write(path, '[[chat]]\nref = "a"\nname = "Same"\n[[chat]]\nref = "b"\nname = "same"\n')
    set_enabled(path, "SAME", False)
    assert [e.enabled for e in load_library(path).entries] == [False, True]


def test_add_then_disable_then_add_keeps_everything_parseable(path: Path) -> None:
    add_entry(path, "a", "A")
    set_enabled(path, "a", False)
    add_entry(path, "b")
    set_enabled(path, "b", False)
    set_enabled(path, "A", True)
    assert [(e.ref, e.enabled) for e in load_library(path).entries] == [("a", True), ("b", False)]


@pytest.mark.parametrize("ref", ["a\u2028b", "a\u2029b", "a\x85b", "a\u2028[x"])
def test_unicode_line_separators_in_a_ref_do_not_break_toggling_without_a_name(
    path: Path, ref: str
) -> None:
    add_entry(path, ref)
    set_enabled(path, ref, False)
    assert load_library(path).entries == (ChatEntry(ref, enabled=False),)
