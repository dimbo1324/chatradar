from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from chatimport.library import (
    ChatEntry,
    Library,
    LibraryChange,
    LibraryError,
    LibraryWatcher,
    diff_libraries,
    load_library,
    parse_library,
)

REPO = Path(__file__).resolve().parents[3]


def lib(*entries: ChatEntry) -> Library:
    return Library(entries=tuple(entries))


def bump_mtime(path: Path, seconds: int = 5) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 1_000_000_000))


def test_empty_text_is_an_empty_library() -> None:
    assert parse_library("") == Library()


def test_comments_only_is_an_empty_library() -> None:
    assert parse_library("# only a comment\n") == Library()


def test_example_template_parses() -> None:
    parse_library((REPO / "chats.example.toml").read_text(encoding="utf-8"))


def test_entries_keep_file_order_and_defaults() -> None:
    library = parse_library(
        '[[chat]]\nref = "b"\n[[chat]]\nref = "a"\nname = "N"\nenabled = false\n'
    )
    assert library.entries == (ChatEntry("b"), ChatEntry("a", "N", False))


def test_ref_and_name_are_stripped() -> None:
    library = parse_library('[[chat]]\nref = "  @x  "\nname = "  My name \\t"\n')
    assert library.entries == (ChatEntry("@x", "My name"),)


def test_inline_array_of_tables_is_accepted() -> None:
    library = parse_library('chat = [{ref = "a"}, {ref = "b", enabled = false}]\n')
    assert [e.ref for e in library.entries] == ["a", "b"]


def test_unicode_ref_and_name() -> None:
    library = parse_library(
        '[[chat]]\nref = "\u0427\u0430\u0442 \U0001f600"\nname = "\u540d\u524d"\n'
    )
    assert library.entries[0].ref == "\u0427\u0430\u0442 \U0001f600"
    assert library.entries[0].name == "\u540d\u524d"


@pytest.mark.parametrize(
    "text",
    [
        "[[chat]\nref = 'a'\n",
        'ref = "unterminated\n',
        "[[chat]]\nref = a\n",
        '[[chat]]\nref = "a"\nref = "b"\n',
        "\x00",
    ],
)
def test_invalid_toml_is_a_library_error(text: str) -> None:
    with pytest.raises(LibraryError, match="invalid TOML"):
        parse_library(text)


@pytest.mark.parametrize(
    "text", ['title = "x"\n', "chats = []\n", "[other]\na = 1\n", "Chat = []\n"]
)
def test_unknown_top_level_keys_are_rejected(text: str) -> None:
    with pytest.raises(LibraryError, match="unknown top-level"):
        parse_library(text)


@pytest.mark.parametrize(
    "text", ["chat = 1\n", 'chat = "x"\n', "[chat]\nref = 'a'\n", "chat = true\n"]
)
def test_chat_must_be_an_array_of_tables(text: str) -> None:
    with pytest.raises(LibraryError, match="array of tables"):
        parse_library(text)


@pytest.mark.parametrize("text", ["chat = [1]\n", 'chat = ["a"]\n', "chat = [[1]]\n"])
def test_entries_must_be_tables(text: str) -> None:
    with pytest.raises(LibraryError, match="expected a table"):
        parse_library(text)


def test_unknown_entry_keys_are_listed_with_the_entry_label() -> None:
    with pytest.raises(LibraryError, match=r"chat entry #1 \(a\): unknown key\(s\) colour, size"):
        parse_library('[[chat]]\nref = "a"\nsize = 1\ncolour = 2\n')


@pytest.mark.parametrize(
    "block",
    [
        "name = 'x'\n",
        'ref = ""\n',
        'ref = "   "\n',
        'ref = "\\n"\n',
        "ref = 5\n",
        "ref = true\n",
        'ref = ["a"]\n',
    ],
)
def test_ref_must_be_a_non_empty_string(block: str) -> None:
    with pytest.raises(LibraryError, match="'ref' must be a non-empty string"):
        parse_library("[[chat]]\n" + block)


@pytest.mark.parametrize("name", ['""', '"  "', "5", "true", '["x"]'])
def test_name_must_be_a_non_empty_string_when_present(name: str) -> None:
    with pytest.raises(LibraryError, match="'name' must be a non-empty string"):
        parse_library(f'[[chat]]\nref = "a"\nname = {name}\n')


@pytest.mark.parametrize("value", ['"true"', '"yes"', "1", "0", "[]"])
def test_enabled_must_be_a_real_boolean(value: str) -> None:
    with pytest.raises(LibraryError, match="'enabled' must be true or false"):
        parse_library(f'[[chat]]\nref = "a"\nenabled = {value}\n')


def test_error_names_the_position_of_the_second_entry() -> None:
    with pytest.raises(LibraryError, match="chat entry #2"):
        parse_library('[[chat]]\nref = "a"\n[[chat]]\nref = ""\n')


@pytest.mark.parametrize("second", ["a", " a", "a ", "  a  "])
def test_duplicate_refs_are_rejected_ignoring_surrounding_whitespace(second: str) -> None:
    text = f'[[chat]]\nref = "a"\n[[chat]]\nref = "{second}"\n'
    with pytest.raises(LibraryError, match="duplicate ref"):
        parse_library(text)


def test_same_ref_even_if_one_copy_is_disabled_is_a_duplicate() -> None:
    with pytest.raises(LibraryError, match="duplicate ref"):
        parse_library('[[chat]]\nref = "a"\n[[chat]]\nref = "a"\nenabled = false\n')


@pytest.mark.parametrize(("first", "second"), [("@Name", "@name"), ("t.me/Name", "t.me/name")])
def test_refs_that_name_the_same_public_chat_in_another_case_are_duplicates(
    first: str, second: str
) -> None:
    text = f'[[chat]]\nref = "{first}"\n[[chat]]\nref = "{second}"\n'
    with pytest.raises(LibraryError, match="duplicate ref"):
        parse_library(text)


def test_enabled_entries_filters_disabled_ones_in_order() -> None:
    library = lib(ChatEntry("a"), ChatEntry("b", enabled=False), ChatEntry("c"))
    assert [e.ref for e in library.enabled_entries()] == ["a", "c"]


def test_find_by_ref_strips_and_matches_the_same_chat_in_any_case() -> None:
    library = lib(ChatEntry("@Name", "Alpha"), ChatEntry("other"))
    assert library.find("  @Name ") is library.entries[0]
    assert library.find("@name") is library.entries[0]
    assert library.find("https://t.me/NAME") is library.entries[0]
    assert library.find("@other") is None
    assert library.find("") is None


def test_find_by_name_is_case_insensitive_and_unicode_aware() -> None:
    library = lib(ChatEntry("r1", "Stra\u00dfe"), ChatEntry("r2", "\u0427\u0430\u0442"))
    assert library.find("STRASSE") is library.entries[0]
    assert library.find("\u0447\u0430\u0442") is library.entries[1]


def test_find_prefers_ref_match_over_name_match() -> None:
    library = lib(ChatEntry("r1", "x"), ChatEntry("x", "other"))
    assert library.find("x") is library.entries[1]


def test_find_returns_first_of_equal_names() -> None:
    library = lib(ChatEntry("r1", "Same"), ChatEntry("r2", "same"))
    assert library.find("SAME") is library.entries[0]


def test_find_does_not_match_entries_without_a_name_by_none() -> None:
    assert lib(ChatEntry("r1")).find("none") is None


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_library(tmp_path / "absent.toml") == Library()


def test_load_empty_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    path.write_bytes(b"")
    assert load_library(path) == Library()


def test_load_file_with_bom_and_crlf(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    path.write_bytes(b'\xef\xbb\xbf[[chat]]\r\nref = "a"\r\nname = "N"\r\n')
    assert load_library(path).entries == (ChatEntry("a", "N"),)


def test_load_invalid_utf8_is_a_library_error(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    path.write_bytes(b'[[chat]]\nref = "\xff\xfe"\n')
    with pytest.raises(LibraryError, match="not valid UTF-8"):
        load_library(path)


def test_load_directory_is_a_library_error(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    path.mkdir()
    with pytest.raises(LibraryError, match="cannot read"):
        load_library(path)


def test_diff_of_identical_libraries_is_empty() -> None:
    library = lib(ChatEntry("a", "A"), ChatEntry("b", enabled=False))
    change = diff_libraries(library, library)
    assert change.is_empty
    assert change == LibraryChange()


def test_diff_empty_to_empty() -> None:
    assert diff_libraries(Library(), Library()).is_empty


def test_diff_reports_added_enabled_entries() -> None:
    change = diff_libraries(lib(ChatEntry("a")), lib(ChatEntry("a"), ChatEntry("b")))
    assert change.added == (ChatEntry("b"),)
    assert not change.removed


def test_diff_ignores_added_disabled_entries() -> None:
    change = diff_libraries(Library(), lib(ChatEntry("b", enabled=False)))
    assert change.is_empty


def test_diff_reports_removed_enabled_entries() -> None:
    change = diff_libraries(lib(ChatEntry("a"), ChatEntry("b")), lib(ChatEntry("a")))
    assert change.removed == (ChatEntry("b"),)


def test_diff_ignores_removed_disabled_entries() -> None:
    change = diff_libraries(lib(ChatEntry("a", enabled=False)), Library())
    assert change.is_empty


def test_diff_reports_disable_and_enable() -> None:
    old = lib(ChatEntry("a"), ChatEntry("b", enabled=False))
    new = lib(ChatEntry("a", enabled=False), ChatEntry("b"))
    change = diff_libraries(old, new)
    assert change.disabled == (ChatEntry("a", enabled=False),)
    assert change.enabled == (ChatEntry("b"),)
    assert not change.added
    assert not change.removed
    assert not change.renamed


def test_diff_reports_rename_from_none_to_a_name_and_back() -> None:
    assert diff_libraries(lib(ChatEntry("a")), lib(ChatEntry("a", "N"))).renamed == (
        ChatEntry("a", "N"),
    )
    assert diff_libraries(lib(ChatEntry("a", "N")), lib(ChatEntry("a"))).renamed == (
        ChatEntry("a"),
    )


def test_diff_rename_with_only_a_case_change_is_a_rename() -> None:
    change = diff_libraries(lib(ChatEntry("a", "N")), lib(ChatEntry("a", "n")))
    assert len(change.renamed) == 1


def test_diff_reenable_and_rename_are_both_reported() -> None:
    old = lib(ChatEntry("a", "Old", enabled=False))
    new = lib(ChatEntry("a", "New"))
    change = diff_libraries(old, new)
    assert change.enabled == (ChatEntry("a", "New"),)
    assert change.renamed == (ChatEntry("a", "New"),)
    assert not change.added


def test_diff_disable_and_rename_are_both_reported() -> None:
    old = lib(ChatEntry("a", "Old"))
    new = lib(ChatEntry("a", "New", enabled=False))
    change = diff_libraries(old, new)
    assert change.disabled == (ChatEntry("a", "New", enabled=False),)
    assert change.renamed == (ChatEntry("a", "New", enabled=False),)


def test_diff_rename_of_a_disabled_entry_is_still_reported() -> None:
    old = lib(ChatEntry("a", "Old", enabled=False))
    new = lib(ChatEntry("a", "New", enabled=False))
    change = diff_libraries(old, new)
    assert change.renamed == (ChatEntry("a", "New", enabled=False),)
    assert not change.enabled
    assert not change.disabled


def test_diff_matches_entries_by_stripped_ref_not_position() -> None:
    old = lib(ChatEntry("a"), ChatEntry("b"))
    new = lib(ChatEntry("b"), ChatEntry("a"))
    assert diff_libraries(old, new).is_empty


def test_diff_combined_changes_are_all_present() -> None:
    old = lib(
        ChatEntry("keep"), ChatEntry("gone"), ChatEntry("off"), ChatEntry("on", enabled=False)
    )
    new = lib(ChatEntry("keep"), ChatEntry("off", enabled=False), ChatEntry("on"), ChatEntry("new"))
    change = diff_libraries(old, new)
    assert [e.ref for e in change.added] == ["new"]
    assert [e.ref for e in change.removed] == ["gone"]
    assert [e.ref for e in change.disabled] == ["off"]
    assert [e.ref for e in change.enabled] == ["on"]
    assert not change.is_empty


def test_is_empty_reflects_each_field() -> None:
    entry = (ChatEntry("a"),)
    for field in ("added", "removed", "disabled", "enabled", "renamed"):
        kwargs: dict[str, Any] = {field: entry}
        assert not LibraryChange(**kwargs).is_empty


def test_chat_entry_key_is_the_stripped_ref() -> None:
    assert ChatEntry("  x ").key == "x"


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def test_watcher_initial_load_of_missing_file_is_empty(tmp_path: Path) -> None:
    watcher = LibraryWatcher(tmp_path / "chats.toml")
    assert watcher.load_initial() == Library()
    assert watcher.last_error is None
    assert watcher.check() is None


def test_watcher_detects_a_file_created_after_a_missing_start(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    write(path, '[[chat]]\nref = "a"\n')
    change = watcher.check()
    assert change is not None
    assert change.added == (ChatEntry("a"),)
    assert watcher.current.entries == (ChatEntry("a"),)


def test_watcher_returns_nothing_when_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    assert watcher.check() is None
    assert watcher.check() is None


def test_watcher_does_not_reread_when_signature_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    reads: list[Path] = []

    def spy(p: Path) -> Library:
        reads.append(p)
        return Library()

    monkeypatch.setattr("chatimport.library.load_library", spy)
    watcher.check()
    assert reads == []


def test_watcher_detects_replacement_by_equal_size_content(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "aaa"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    write(path, '[[chat]]\nref = "bbb"\n')
    bump_mtime(path)
    change = watcher.check()
    assert change is not None
    assert [e.ref for e in change.added] == ["bbb"]
    assert [e.ref for e in change.removed] == ["aaa"]


def test_watcher_detects_a_size_change_with_same_mtime(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    before = path.stat()
    write(path, '[[chat]]\nref = "a"\n[[chat]]\nref = "b"\n')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    change = watcher.check()
    assert change is not None
    assert [e.ref for e in change.added] == ["b"]


def test_watcher_touch_without_content_change_gives_no_change(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    bump_mtime(path)
    assert watcher.check() is None
    assert watcher.check() is None


def test_watcher_keeps_previous_library_on_syntax_error_and_reports_it(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    write(path, '[[chat]]\nref = "a\n')
    bump_mtime(path)
    assert watcher.check() is None
    assert watcher.last_error is not None
    assert watcher.current.entries == (ChatEntry("a"),)
    assert watcher.check() is None
    assert watcher.last_error is not None


def test_watcher_recovers_after_error_when_fixed(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    write(path, "garbage [[[")
    bump_mtime(path, 5)
    assert watcher.check() is None
    write(path, '[[chat]]\nref = "a"\n[[chat]]\nref = "b"\n')
    bump_mtime(path, 10)
    change = watcher.check()
    assert change is not None
    assert [e.ref for e in change.added] == ["b"]
    assert watcher.last_error is None


def test_watcher_error_then_revert_to_original_reports_nothing_but_clears_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chats.toml"
    original = '[[chat]]\nref = "a"\n'
    write(path, original)
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    write(path, "garbage [[[")
    bump_mtime(path, 5)
    watcher.check()
    write(path, original)
    bump_mtime(path, 10)
    assert watcher.check() is None
    assert watcher.last_error is None


def test_watcher_initial_error_raises_and_is_recorded_then_fix_is_picked_up(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chats.toml"
    write(path, "garbage [[[")
    watcher = LibraryWatcher(path)
    with pytest.raises(LibraryError):
        watcher.load_initial()
    assert watcher.last_error is not None
    assert watcher.current == Library()
    assert watcher.check() is None
    write(path, '[[chat]]\nref = "a"\n')
    bump_mtime(path)
    change = watcher.check()
    assert change is not None
    assert change.added == (ChatEntry("a"),)
    assert watcher.last_error is None


def test_watcher_deleted_file_does_not_crash_and_a_restored_file_is_picked_up(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chats.toml"
    text = '[[chat]]\nref = "a"\n'
    write(path, text)
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    path.unlink()
    watcher.check()
    write(path, text)
    watcher.check()
    assert watcher.current.entries == (ChatEntry("a"),)


def test_watcher_deleting_the_file_must_not_silently_stop_every_chat(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    path.unlink()
    change = watcher.check()
    assert change is None or not change.removed


class UnstatablePath(type(Path())):
    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        raise PermissionError("denied")


def test_watcher_stat_failure_is_reported_not_raised_by_check(tmp_path: Path) -> None:
    watcher = LibraryWatcher(UnstatablePath(tmp_path / "chats.toml"))
    assert watcher.check() is None
    assert watcher.last_error is not None
    assert "cannot stat" in watcher.last_error


def test_watcher_initial_stat_failure_raises_library_error(tmp_path: Path) -> None:
    watcher = LibraryWatcher(UnstatablePath(tmp_path / "chats.toml"))
    with pytest.raises(LibraryError, match="cannot stat"):
        watcher.load_initial()
    assert watcher.last_error is not None


def test_watcher_reports_rename_and_disable_in_one_change(tmp_path: Path) -> None:
    path = tmp_path / "chats.toml"
    write(path, '[[chat]]\nref = "a"\nname = "Old"\n')
    watcher = LibraryWatcher(path)
    watcher.load_initial()
    write(path, '[[chat]]\nref = "a"\nname = "New"\nenabled = false\n')
    bump_mtime(path)
    change = watcher.check()
    assert change is not None
    assert len(change.disabled) == 1
    assert len(change.renamed) == 1
