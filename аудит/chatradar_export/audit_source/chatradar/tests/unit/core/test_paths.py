from __future__ import annotations

import os
from pathlib import Path

import pytest

from chatimport import paths
from chatimport.paths import AppPaths, app_paths, library_path, normalize_root, resolve_root


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "FakeDesktop"
    monkeypatch.setattr(paths, "user_desktop_dir", lambda: str(folder))
    return folder


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


def test_app_paths_layout(tmp_path: Path) -> None:
    app = AppPaths(tmp_path)
    assert app.config_file == tmp_path / "config.toml"
    assert app.default_library_file == tmp_path / "chats.toml"
    assert app.session_file == tmp_path / "session" / "chatimport.session"
    assert app.log_dir == tmp_path / "logs"
    assert app.lock_file == tmp_path / "chatimport.lock"
    assert app.control_dir == tmp_path / "control"


def test_ensure_creates_folders_and_is_idempotent(tmp_path: Path) -> None:
    app = AppPaths(tmp_path / "deep" / "base")
    app.ensure()
    app.ensure()
    for folder in (app.base, app.session_file.parent, app.log_dir, app.control_dir):
        assert folder.is_dir()
    assert not app.session_file.exists()
    assert not app.lock_file.exists()


def test_app_paths_defaults_to_the_platform_data_folder() -> None:
    app = app_paths()
    assert app.base.name.lower() == "chatimport"
    assert app.base.is_absolute()


def test_app_paths_accepts_an_explicit_base(tmp_path: Path) -> None:
    assert app_paths(tmp_path).base == tmp_path


@pytest.mark.parametrize("name", ["ChatImport", "chatimport", "CHATIMPORT", "cHaTiMpOrT"])
def test_trailing_chatimport_is_kept_in_any_case(tmp_path: Path, name: str) -> None:
    assert normalize_root(str(tmp_path / name)) == tmp_path / name


def test_other_names_get_chatimport_appended(tmp_path: Path) -> None:
    assert normalize_root(str(tmp_path / "Data")) == tmp_path / "Data" / "ChatImport"


def test_name_that_merely_contains_chatimport_still_gets_a_subfolder(tmp_path: Path) -> None:
    value = tmp_path / "MyChatImport"
    assert normalize_root(str(value)) == value / "ChatImport"


def test_trailing_separator_is_ignored(tmp_path: Path) -> None:
    assert normalize_root(str(tmp_path / "Data") + os.sep) == tmp_path / "Data" / "ChatImport"
    assert normalize_root(str(tmp_path / "ChatImport") + os.sep) == tmp_path / "ChatImport"


def test_relative_path_stays_relative_and_gets_the_suffix() -> None:
    assert normalize_root("data") == Path("data") / "ChatImport"
    assert normalize_root("ChatImport") == Path("ChatImport")


def test_tilde_expands_to_the_home_folder(home: Path) -> None:
    assert normalize_root("~/Archive") == home / "Archive" / "ChatImport"
    assert normalize_root("~") == home / "ChatImport"


def test_environment_variables_expand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_TEST_BASE", str(tmp_path / "base"))
    reference = "%CI_TEST_BASE%" if os.name == "nt" else "$CI_TEST_BASE"
    assert normalize_root(reference + os.sep + "x") == tmp_path / "base" / "x" / "ChatImport"


def test_unknown_variable_is_left_literally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI_TEST_UNSET", raising=False)
    reference = "%CI_TEST_UNSET%" if os.name == "nt" else "$CI_TEST_UNSET"
    assert normalize_root(reference).parent.name == reference


def test_unicode_and_spaces_survive(tmp_path: Path) -> None:
    value = tmp_path / "\u0410\u0440\u0445\u0438\u0432 \u2764 dir"
    assert normalize_root(str(value)) == value / "ChatImport"


def test_dot_means_a_chatimport_folder_in_the_working_directory() -> None:
    assert normalize_root(".") == Path("ChatImport")


def test_cli_beats_env_config_and_desktop(desktop: Path, tmp_path: Path) -> None:
    result = resolve_root(
        str(tmp_path / "cli"), str(tmp_path / "cfg"), {"CHATIMPORT_ROOT": str(tmp_path / "env")}
    )
    assert result == tmp_path / "cli" / "ChatImport"


def test_env_beats_config_and_desktop(desktop: Path, tmp_path: Path) -> None:
    result = resolve_root(None, str(tmp_path / "cfg"), {"CHATIMPORT_ROOT": str(tmp_path / "env")})
    assert result == tmp_path / "env" / "ChatImport"


def test_config_beats_desktop(desktop: Path, tmp_path: Path) -> None:
    assert resolve_root(None, str(tmp_path / "cfg"), {}) == tmp_path / "cfg" / "ChatImport"


def test_desktop_is_the_last_resort(desktop: Path) -> None:
    assert resolve_root(None, "", {}) == desktop / "ChatImport"


@pytest.mark.parametrize("empty", ["", None])
def test_empty_cli_and_env_values_fall_through(
    desktop: Path, tmp_path: Path, empty: str | None
) -> None:
    env = {"CHATIMPORT_ROOT": ""}
    assert resolve_root(empty, str(tmp_path / "cfg"), env) == tmp_path / "cfg" / "ChatImport"


def test_explicit_env_mapping_ignores_the_process_environment(
    desktop: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CHATIMPORT_ROOT", str(tmp_path / "process"))
    assert resolve_root(None, "", {}) == desktop / "ChatImport"


def test_process_environment_is_used_without_an_explicit_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CHATIMPORT_ROOT", str(tmp_path / "process"))
    assert resolve_root() == tmp_path / "process" / "ChatImport"


def test_default_library_file_when_not_configured(tmp_path: Path) -> None:
    app = AppPaths(tmp_path)
    assert library_path("", app) == tmp_path / "chats.toml"


def test_configured_library_file_is_used(tmp_path: Path) -> None:
    app = AppPaths(tmp_path / "base")
    assert library_path(str(tmp_path / "mine.toml"), app) == tmp_path / "mine.toml"


def test_library_file_expands_tilde(home: Path, tmp_path: Path) -> None:
    app = AppPaths(tmp_path)
    assert library_path("~/chats.toml", app) == home / "chats.toml"


def test_library_file_expands_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_TEST_LIB", str(tmp_path / "lib"))
    reference = "%CI_TEST_LIB%" if os.name == "nt" else "$CI_TEST_LIB"
    assert library_path(reference + os.sep + "c.toml", AppPaths(tmp_path)) == (
        tmp_path / "lib" / "c.toml"
    )


def test_relative_library_file_is_not_anchored_to_the_base(tmp_path: Path) -> None:
    assert library_path("rel.toml", AppPaths(tmp_path / "base")) == Path("rel.toml")
