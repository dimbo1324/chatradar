from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from scripts import check_language

if TYPE_CHECKING:
    from pathlib import Path

CYR = "\u043f\u0440\u0438\u0432\u0435\u0442"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)  # noqa: S603, S607


def write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    return tmp_path


@pytest.mark.parametrize(
    "char",
    [
        "\u0400",
        "\u0410",
        "\u044f",
        "\u04ff",
        "\u0500",
        "\u052f",
        "\u1c80",
        "\u1c8f",
        "\u2de0",
        "\u2dff",
        "\ua640",
        "\ua69f",
        "\u0451",
        "\u0404",
    ],
)
def test_every_cyrillic_block_edge_is_detected(char: str) -> None:
    assert check_language.CYRILLIC.search(f"English {char} text")


@pytest.mark.parametrize(
    "char",
    [
        "\u03ff",
        "\u0530",
        "\u0531",
        "\u1c7f",
        "\u1c90",
        "\u2ddf",
        "\u2e00",
        "\ua63f",
        "\ua6a0",
        "a",
        "\u00e9",
        "\u03b1",
        "\u4e2d",
        "\U0001f600",
        "\u00f1",
        "\u0131",
    ],
)
def test_neighbouring_scripts_and_symbols_are_not_flagged(char: str) -> None:
    assert not check_language.CYRILLIC.search(f"English {char} text")


def test_a_single_cyrillic_homoglyph_inside_an_english_word_is_found(tmp_path: Path) -> None:
    write(tmp_path / "a.py", "name = 'c\u043empany'\n")

    assert check_language.find_hits(tmp_path, ["a.py"]) == ["a.py:1"]


@pytest.mark.parametrize(
    ("path", "checked"),
    [
        ("tests/fixtures/x.json", False),
        ("tests/fixtures/deep/er/x.txt", False),
        ("tests/fixtures_extra/x.json", True),
        ("tests/fixtures", True),
        ("my/tests/fixtures/x.json", True),
        ("logo.PNG", False),
        ("logo.Jpeg", False),
        ("archive.ZIP", False),
        ("data.db", False),
        ("notes.png.md", True),
        ("Makefile", True),
        (".gitignore", True),
        ("a.woff2", False),
    ],
)
def test_language_scope_rules(path: str, checked: bool) -> None:
    assert check_language.is_checked(path) is checked


def test_hits_use_one_based_line_numbers_across_crlf_files(tmp_path: Path) -> None:
    write(tmp_path / "w.md", f"one\r\ntwo\r\n{CYR}\r\nfour\r\n{CYR}\r\n")

    assert check_language.find_hits(tmp_path, ["w.md"]) == ["w.md:3", "w.md:5"]


def test_only_the_first_hit_per_line_is_reported_once(tmp_path: Path) -> None:
    write(tmp_path / "w.md", f"{CYR} {CYR} {CYR}\n")

    assert check_language.find_hits(tmp_path, ["w.md"]) == ["w.md:1"]


def test_a_bom_does_not_hide_or_invent_hits(tmp_path: Path) -> None:
    write(tmp_path / "bom.md", b"\xef\xbb\xbfplain english\n")
    write(tmp_path / "bom_bad.md", b"\xef\xbb\xbf" + f"\n{CYR}\n".encode())

    assert check_language.find_hits(tmp_path, ["bom.md", "bom_bad.md"]) == ["bom_bad.md:2"]


def test_undecodable_and_missing_files_are_skipped_quietly(tmp_path: Path) -> None:
    write(tmp_path / "latin1.txt", bytes([0x63, 0x61, 0x66, 0xE9, 0x20, 0xEF, 0xF0]))
    write(tmp_path / "ok.md", CYR)

    hits = check_language.find_hits(tmp_path, ["latin1.txt", "ghost.md", "ok.md"])

    assert hits == ["ok.md:1"]


def test_a_directory_entry_such_as_a_submodule_is_skipped_on_every_platform(tmp_path: Path) -> None:
    (tmp_path / "vendor").mkdir()
    write(tmp_path / "ok.md", CYR)

    assert check_language.find_hits(tmp_path, ["vendor", "ok.md"]) == ["ok.md:1"]


def test_files_in_the_allowed_fixture_folder_may_be_russian(tmp_path: Path) -> None:
    write(tmp_path / "tests/fixtures/chat.json", CYR)

    assert check_language.find_hits(tmp_path, ["tests/fixtures/chat.json"]) == []


SEPARATORS = ["\x0c", "\u2028", "\x1c", "\x85"]


@pytest.mark.parametrize("separator", SEPARATORS)
def test_line_numbers_match_what_an_editor_shows_for_unusual_line_separators(
    tmp_path: Path, separator: str
) -> None:
    write(tmp_path / "odd.md", f"first\nsecond{separator}still second\n{CYR}\n")

    assert check_language.find_hits(tmp_path, ["odd.md"]) == ["odd.md:3"]


def test_main_passes_on_a_clean_repo_and_names_the_file_count(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / "a.md", "fine\n")
    write(repo / "src/b.py", "x = 1\n")

    assert check_language.main(root=repo) == 0

    assert capsys.readouterr().out == "ok  language: 2 files, English only\n"


def test_main_reports_file_and_line_to_stderr(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo / "docs/x.md", f"ok\n{CYR}\n")

    assert check_language.main(root=repo) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "docs/x.md:2" in captured.err
    assert "Cyrillic" in captured.err


def test_main_scans_untracked_files_but_not_ignored_ones(repo: Path) -> None:
    write(repo / ".gitignore", "ignored/\n")
    write(repo / "ignored/secret.md", CYR)
    write(repo / "fresh.md", "fine\n")

    assert check_language.main(root=repo) == 0

    write(repo / "fresh.md", CYR)
    assert check_language.main(root=repo) == 1


def test_main_skips_a_tracked_file_that_was_deleted_from_disk(repo: Path) -> None:
    write(repo / "gone.md", CYR)
    git(repo, "add", "gone.md")
    (repo / "gone.md").unlink()

    assert check_language.main(root=repo) == 0


def test_main_caps_the_listing_at_fifty_and_counts_the_rest(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for number in range(60):
        write(repo / f"f{number:02d}.md", CYR)

    assert check_language.main(root=repo) == 1

    err = capsys.readouterr().err
    assert "f49.md:1" in err
    assert "f50.md:1" not in err
    assert "... and 10 more" in err


def test_main_with_exactly_fifty_hits_prints_no_more_line(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for number in range(50):
        write(repo / f"f{number:02d}.md", CYR)

    assert check_language.main(root=repo) == 1

    err = capsys.readouterr().err
    assert "f49.md:1" in err
    assert "more" not in err


def test_file_names_with_spaces_and_unicode_are_handled(repo: Path) -> None:
    write(repo / "my notes/\u00e9t\u00e9 plan.md", CYR)

    assert check_language.main(root=repo) == 1
    assert check_language.candidate_files(repo) == ["my notes/\u00e9t\u00e9 plan.md"]


def test_candidate_files_are_sorted_and_unique(repo: Path) -> None:
    for name in ("b.md", "a.md", "c/d.md"):
        write(repo / name, "x")
    git(repo, "add", "a.md")

    assert check_language.candidate_files(repo) == ["a.md", "b.md", "c/d.md"]
