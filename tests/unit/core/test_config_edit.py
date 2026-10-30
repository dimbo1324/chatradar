from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

import pytest

from chatimport.config import ConfigError, load_config
from chatimport.config_edit import set_output_root


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_missing_file_is_created_with_the_section(config_file: Path) -> None:
    set_output_root(config_file, "D:/Data")
    assert read(config_file) == '[output]\nroot_dir = "D:/Data"\n'
    assert load_config(config_file).output.root_dir == "D:/Data"


def test_missing_parent_folder_is_created(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "config.toml"
    set_output_root(target, "x")
    assert load_config(target).output.root_dir == "x"
    assert leftovers(target.parent) == ["config.toml"]


def test_empty_file_gets_the_section_without_a_leading_blank_line(config_file: Path) -> None:
    write(config_file, "")
    set_output_root(config_file, "x")
    assert read(config_file) == '[output]\nroot_dir = "x"\n'


def test_whitespace_only_file(config_file: Path) -> None:
    write(config_file, "\n\n")
    set_output_root(config_file, "x")
    assert load_config(config_file).output.root_dir == "x"


def test_section_is_appended_after_other_sections_with_a_blank_line(config_file: Path) -> None:
    write(config_file, "[telegram]\napi_id = 5\n")
    set_output_root(config_file, "x")
    assert read(config_file) == '[telegram]\napi_id = 5\n\n[output]\nroot_dir = "x"\n'


def test_last_line_without_newline_is_terminated_first(config_file: Path) -> None:
    write(config_file, "[telegram]\napi_id = 5")
    set_output_root(config_file, "x")
    assert read(config_file) == '[telegram]\napi_id = 5\n\n[output]\nroot_dir = "x"\n'


def test_trailing_blank_line_is_not_doubled(config_file: Path) -> None:
    write(config_file, "[telegram]\napi_id = 5\n\n")
    set_output_root(config_file, "x")
    assert read(config_file) == '[telegram]\napi_id = 5\n\n[output]\nroot_dir = "x"\n'


def test_existing_root_dir_is_replaced_and_neighbours_survive(config_file: Path) -> None:
    text = (
        "# my settings\n"
        "[telegram]\n"
        "api_id = 5  # id\n"
        "\n"
        "[output]\n"
        "# where to write\n"
        'root_dir = "old"\n'
        "include_raw = true  # big\n"
        "\n"
        "[live]\n"
        "flush_every_messages = 7\n"
    )
    write(config_file, text)
    set_output_root(config_file, "new")
    assert read(config_file) == text.replace('"old"', '"new"')
    config = load_config(config_file)
    assert config.output.root_dir == "new"
    assert config.output.include_raw is True
    assert config.live.flush_every_messages == 7


def test_output_section_without_root_dir_gets_the_key_after_its_last_key(
    config_file: Path,
) -> None:
    text = (
        "[output]\ninclude_raw = true\nmax_chunk_mb = 5  # c\n\n[live]\nflush_every_seconds = 9\n"
    )
    write(config_file, text)
    set_output_root(config_file, "x")
    assert read(config_file) == (
        '[output]\ninclude_raw = true\nmax_chunk_mb = 5  # c\nroot_dir = "x"\n\n'
        "[live]\nflush_every_seconds = 9\n"
    )


def test_empty_output_section_gets_the_key_right_below_the_header(config_file: Path) -> None:
    write(config_file, "[output]\n[live]\nflush_every_seconds = 9\n")
    set_output_root(config_file, "x")
    assert read(config_file) == '[output]\nroot_dir = "x"\n[live]\nflush_every_seconds = 9\n'


def test_output_section_as_last_block_without_trailing_newline(config_file: Path) -> None:
    write(config_file, "[output]\ninclude_raw = true")
    set_output_root(config_file, "x")
    assert read(config_file) == '[output]\ninclude_raw = true\nroot_dir = "x"\n'


@pytest.mark.parametrize("header", ["[output]", "  [output]", "[ output ]", "[output]   # c"])
def test_header_spellings_are_recognised(config_file: Path, header: str) -> None:
    write(config_file, f"{header}\ninclude_raw = true\n")
    set_output_root(config_file, "x")
    text = read(config_file)
    assert text.count("[output") + text.count("[ output") == 1
    assert load_config(config_file).output.root_dir == "x"


def test_commented_out_header_and_key_are_ignored(config_file: Path) -> None:
    write(config_file, '# [output]\n# root_dir = "no"\n[live]\nflush_every_seconds = 9\n')
    set_output_root(config_file, "x")
    config = load_config(config_file)
    assert config.output.root_dir == "x"
    assert config.live.flush_every_seconds == 9
    assert read(config_file).startswith('# [output]\n# root_dir = "no"\n')


def test_key_that_merely_starts_with_root_dir_is_not_replaced(config_file: Path) -> None:
    write(config_file, "[output]\ninclude_raw = false\n")
    set_output_root(config_file, "a")
    set_output_root(config_file, "b")
    assert read(config_file).count("root_dir") == 1


def test_second_call_replaces_the_first_and_is_idempotent(config_file: Path) -> None:
    set_output_root(config_file, "one")
    set_output_root(config_file, "two")
    after_two = read(config_file)
    set_output_root(config_file, "two")
    assert read(config_file) == after_two
    assert load_config(config_file).output.root_dir == "two"


def test_other_sections_are_never_touched_when_output_is_in_the_middle(config_file: Path) -> None:
    text = (
        '[telegram]\napi_hash = "abc"\n\n[output]\nroot_dir = "old"\n\n'
        "[live]\nflush_every_seconds = 3\n"
    )
    write(config_file, text)
    set_output_root(config_file, "new")
    config = load_config(config_file)
    assert config.telegram.api_hash == "abc"
    assert config.live.flush_every_seconds == 3


def test_crlf_file_stays_crlf_when_replacing(config_file: Path) -> None:
    text = '[output]\r\nroot_dir = "old"\r\ninclude_raw = true\r\n'
    write(config_file, text)
    set_output_root(config_file, "new")
    assert read(config_file) == text.replace("old", "new")


def test_crlf_file_stays_crlf_when_inserting(config_file: Path) -> None:
    write(config_file, "[output]\r\ninclude_raw = true\r\n[live]\r\nflush_every_seconds = 4\r\n")
    set_output_root(config_file, "x")
    text = read(config_file)
    assert text.replace("\r\n", "").count("\n") == 0
    assert load_config(config_file).output.root_dir == "x"


def test_crlf_file_stays_crlf_when_appending_a_section(config_file: Path) -> None:
    write(config_file, "[live]\r\nflush_every_seconds = 4")
    set_output_root(config_file, "x")
    text = read(config_file)
    assert text.replace("\r\n", "").count("\n") == 0
    assert load_config(config_file).output.root_dir == "x"


def test_bom_is_accepted_and_dropped(config_file: Path) -> None:
    config_file.write_bytes(b"\xef\xbb\xbf[live]\nflush_every_seconds = 4\n")
    set_output_root(config_file, "x")
    assert not config_file.read_bytes().startswith(b"\xef\xbb\xbf")
    config = load_config(config_file)
    assert (config.live.flush_every_seconds, config.output.root_dir) == (4, "x")


WINDOWS_ROOTS = [
    "C:\\Users\\me\\Documents",
    "C:\\Users\\me\\ChatImport",
    "\\\\server\\share\\ChatImport",
    "D:\\data with spaces\\\u041f\u0430\u043f\u043a\u0430",
    "C:\\path\\ending\\with\\backslash\\",
    "C:\\new\\table\\u0041\\x",
    "%USERPROFILE%\\Archive",
    "~/Archive",
    'quote"inside',
    "tab\tinside",
    "C:/forward/slashes",
    "\U0001f4c1 emoji",
    "nul\x00inside",
    "bell\x07",
    "del\x7finside",
]


@pytest.mark.parametrize("root", WINDOWS_ROOTS)
def test_any_root_value_round_trips_exactly(config_file: Path, root: str) -> None:
    write(config_file, "[live]\nflush_every_seconds = 4\n")
    set_output_root(config_file, root)
    assert load_config(config_file).output.root_dir == root


@pytest.mark.parametrize("root", WINDOWS_ROOTS)
def test_replacing_a_value_keeps_the_file_parseable(config_file: Path, root: str) -> None:
    set_output_root(config_file, "first")
    set_output_root(config_file, root)
    assert load_config(config_file).output.root_dir == root


def test_unicode_line_separators_in_the_old_value_do_not_corrupt_replacement(
    config_file: Path,
) -> None:
    set_output_root(config_file, "a\u2028b")
    set_output_root(config_file, "clean")
    assert load_config(config_file).output.root_dir == "clean"


def test_unicode_line_separators_in_the_old_value_do_not_corrupt_insertion(
    config_file: Path,
) -> None:
    write(config_file, '[output]\nroot_dir = "a\u2028b"\ninclude_raw = true\n')
    set_output_root(config_file, "clean")
    config = load_config(config_file)
    assert config.output.root_dir == "clean"
    assert config.output.include_raw is True


def test_path_objects_are_accepted(config_file: Path, tmp_path: Path) -> None:
    set_output_root(config_file, tmp_path / "Data")
    assert load_config(config_file).output.root_dir == str(tmp_path / "Data")


def test_pure_windows_path_value(config_file: Path) -> None:
    set_output_root(config_file, PureWindowsPath("C:/Users/me/Data"))  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    assert load_config(config_file).output.root_dir == "C:\\Users\\me\\Data"


def test_string_config_file_argument_is_accepted(tmp_path: Path) -> None:
    target = str(tmp_path / "config.toml")
    set_output_root(target, "x")
    assert load_config(Path(target)).output.root_dir == "x"


def test_invalid_toml_is_refused_and_left_untouched(config_file: Path) -> None:
    write(config_file, "[output\nbroken = ")
    with pytest.raises(ConfigError):
        set_output_root(config_file, "x")
    assert read(config_file) == "[output\nbroken = "
    assert leftovers(config_file.parent) == ["config.toml"]


def test_file_with_unknown_keys_is_refused_and_left_untouched(config_file: Path) -> None:
    text = "[live]\nnope = 1\n"
    write(config_file, text)
    with pytest.raises(ConfigError, match="unknown keys"):
        set_output_root(config_file, "x")
    assert read(config_file) == text


def test_non_utf8_file_is_a_config_error(config_file: Path) -> None:
    config_file.write_bytes(b'[telegram]\napi_hash = "\xff"\n')
    with pytest.raises(ConfigError, match="cannot read"):
        set_output_root(config_file, "x")
    assert config_file.read_bytes() == b'[telegram]\napi_hash = "\xff"\n'


def test_directory_in_place_of_the_file_is_a_config_error(config_file: Path) -> None:
    config_file.mkdir()
    with pytest.raises(ConfigError, match="cannot read"):
        set_output_root(config_file, "x")


def test_two_output_sections_is_refused(config_file: Path) -> None:
    text = "[output]\ninclude_raw = true\n[output]\nmax_chunk_mb = 5\n"
    write(config_file, text)
    with pytest.raises(ConfigError):
        set_output_root(config_file, "x")
    assert read(config_file) == text


def test_atomic_failure_keeps_the_original(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = '[output]\nroot_dir = "old"\n'
    write(config_file, text)

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        set_output_root(config_file, "new")
    assert read(config_file) == text
    assert leftovers(config_file.parent) == ["config.toml"]


def test_result_is_always_valid_utf8_without_bom(config_file: Path) -> None:
    set_output_root(config_file, "\u041f\u0430\u043f\u043a\u0430")
    raw = config_file.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "\u041f\u0430\u043f\u043a\u0430".encode() in raw
