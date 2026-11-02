from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.gui import setup_logic
from chatimport.gui.key_validation import validate_api_hash, validate_api_id
from chatimport.gui.settings import GuiSettingsStore, settings_from_json
from chatimport.gui.setup_logic import (
    add_refs,
    check_folder,
    current_root,
    read_state,
    split_refs,
)
from chatimport.library import load_library
from chatimport.paths import app_paths
from chatimport.refs import display_ref

if TYPE_CHECKING:
    from pathlib import Path

HASH = "0123456789abcdef0123456789ABCDEF"


@pytest.mark.parametrize("text", ["1", " 12345678 ", "999999999999"])
def test_api_id_accepts_positive_numbers(text: str) -> None:
    assert validate_api_id(text) is None


@pytest.mark.parametrize("text", ["", " ", "0", "-5", "12a", "1.5", "٣٤", "²"])
def test_api_id_rejects_everything_else(text: str) -> None:
    assert validate_api_id(text) == "settings.tg.err.api_id"


def test_api_hash_is_exactly_32_hex_characters() -> None:
    assert validate_api_hash(HASH) is None
    assert validate_api_hash(f"  {HASH}  ") is None
    for bad in ("", HASH[:-1], HASH + "0", "g" * 32, HASH[:-1] + "-"):
        assert validate_api_hash(bad) == "settings.tg.err.api_hash"


def test_split_refs_takes_lines_commas_and_spaces() -> None:
    text = " https://t.me/a\n@b, @c;\t\n\n@d "
    assert split_refs(text) == ["https://t.me/a", "@b", "@c", "@d"]
    assert split_refs("   ") == []


def test_add_refs_reports_every_line(tmp_path: Path) -> None:
    library = tmp_path / "chats.toml"
    invite = "https://t.me/+SecretInviteHash123"
    first = add_refs(library, f"@alpha_chat\nhello\n{invite}")
    assert [(r.ref, r.status) for r in first] == [
        ("@alpha_chat", "added"),
        ("hello", "invalid"),
        (display_ref(invite), "added"),
    ]
    assert "SecretInviteHash123" not in "".join(r.ref for r in first)
    assert len(load_library(library).entries) == 2
    second = add_refs(library, "https://t.me/Alpha_Chat\n@beta_chat\n@beta_chat\n12345")
    assert [r.status for r in second] == ["duplicate", "added", "duplicate", "added"]
    assert len(load_library(library).entries) == 4


def test_add_refs_with_a_broken_library(tmp_path: Path) -> None:
    library = tmp_path / "chats.toml"
    library.write_text("[[chat]\n", encoding="utf-8")
    results = add_refs(library, "@alpha_chat")
    assert [r.status for r in results] == ["error"]
    assert results[0].detail


def test_add_refs_reports_a_failed_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chatimport.library import LibraryError

    def refuse(*_: object) -> None:
        raise LibraryError("disk full")

    monkeypatch.setattr(setup_logic, "add_entry", refuse)
    results = add_refs(tmp_path / "chats.toml", "@alpha_chat")
    assert results[0].status == "error"
    assert results[0].detail == "disk full"


def test_current_root_follows_the_config_and_survives_a_broken_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHATIMPORT_ROOT")
    config = tmp_path / "config.toml"
    config.write_text(f'[output]\nroot_dir = "{(tmp_path / "elsewhere").as_posix()}"\n')
    assert current_root(config) == tmp_path / "elsewhere" / "ChatImport"
    config.write_text("[output\n")
    assert current_root(config).name == "ChatImport"


def test_check_folder_default_and_empty_text(tmp_path: Path) -> None:
    current, base = tmp_path / "ChatImport", tmp_path / "app"
    for text in ("", str(current)):
        check = check_folder(text, current, base)
        assert check.path == current
        assert not check.changed
        assert not check.cloud
        assert check.error == ""


def test_check_folder_new_location(tmp_path: Path) -> None:
    check = check_folder(str(tmp_path / "other"), tmp_path / "ChatImport", tmp_path / "app")
    assert check.path == tmp_path / "other" / "ChatImport"
    assert check.changed


def test_check_folder_refuses_the_application_folder(tmp_path: Path) -> None:
    base = tmp_path / "app"
    same = check_folder(str(base), base / "ChatImport", base)
    assert same.path is None
    assert "application folder" in same.error
    moved = check_folder(str(base / "inside"), tmp_path / "ChatImport", base)
    assert moved.path is None
    assert "application folder" in moved.error


def test_check_folder_refuses_a_non_empty_foreign_folder(tmp_path: Path) -> None:
    target = tmp_path / "ChatImport2" / "ChatImport"
    target.mkdir(parents=True)
    (target / "notes.txt").write_text("x", encoding="utf-8")
    check = check_folder(str(target), tmp_path / "ChatImport", tmp_path / "app")
    assert check.path is None
    assert "not empty" in check.error


def test_check_folder_reports_cloud_folders(tmp_path: Path) -> None:
    target = tmp_path / "OneDrive" / "Archive"
    check = check_folder(str(target), tmp_path / "ChatImport", tmp_path / "app")
    assert check.path is not None
    assert check.cloud


def test_check_folder_reports_unwritable_places(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    check = check_folder(str(blocker / "inside"), tmp_path / "ChatImport", tmp_path / "app")
    assert check.path is None
    assert check.error


def test_read_state_of_an_empty_installation(tmp_path: Path) -> None:
    paths = app_paths(tmp_path / "app")
    state = read_state(paths.config_file, paths.session_file, paths.default_library_file)
    assert not state.keys_saved
    assert not state.signed_in
    assert state.chats == 0
    assert state.root == tmp_path / "ChatImport"


def test_read_state_of_a_finished_installation(tmp_path: Path) -> None:
    paths = app_paths(tmp_path / "app")
    paths.ensure()
    paths.config_file.write_text(f'[telegram]\napi_id = 5\napi_hash = "{HASH}"\n')
    paths.session_file.write_bytes(b"")
    add_refs(paths.default_library_file, "@alpha_chat")
    state = read_state(paths.config_file, paths.session_file, paths.default_library_file)
    assert state.keys_saved
    assert state.signed_in
    assert state.chats == 1


def test_read_state_with_broken_files(tmp_path: Path) -> None:
    paths = app_paths(tmp_path / "app")
    paths.ensure()
    paths.config_file.write_text("[telegram\n")
    paths.default_library_file.write_text("[[chat]\n")
    state = read_state(paths.config_file, paths.session_file, paths.default_library_file)
    assert not state.keys_saved
    assert state.chats == 0


def test_read_state_rejects_a_legacy_short_hash(tmp_path: Path) -> None:
    paths = app_paths(tmp_path / "app")
    paths.ensure()
    paths.config_file.write_text('[telegram]\napi_id = 5\napi_hash = "abcdefghijklmnop"\n')
    state = read_state(paths.config_file, paths.session_file, paths.default_library_file)
    assert not state.keys_saved


def test_setup_completed_defaults_to_false_and_round_trips(tmp_path: Path) -> None:
    assert not settings_from_json({}).setup_completed
    assert not settings_from_json({"setup_completed": "yes"}).setup_completed
    path = tmp_path / "gui.json"
    path.write_text('{"v": 1, "theme": "dark"}', encoding="utf-8")
    store = GuiSettingsStore(path)
    assert not store.settings.setup_completed
    store.update(setup_completed=True)
    assert GuiSettingsStore(path).settings.setup_completed
