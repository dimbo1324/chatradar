from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chatimport.storage import media_files
from chatimport.storage.media_files import (
    ZONE_IDENTIFIER,
    delete_media,
    mark_downloaded,
    media_file_name,
    media_msg_id,
    safe_suffix,
    unique_media_path,
)


@pytest.mark.parametrize(
    ("suffix", "kind", "expected"),
    [
        (".jpg", "photo", ".jpg"),
        (".JPG", "photo", ".JPG"),
        (".pdf", "document", ".pdf"),
        (".bin", "video", ".bin"),
        ("", "document", ""),
        (".exe", "document", ".exe.bin"),
        (".lnk", "photo", ".lnk.bin"),
        (".hta", "document", ".hta.bin"),
        (".js", "document", ".js.bin"),
        (".pdf", "photo", ".pdf.bin"),
        (".jpg", "unknown_kind", ".jpg.bin"),
    ],
)
def test_safe_suffix_table(suffix: str, kind: str, expected: str) -> None:
    assert safe_suffix(suffix, kind) == expected


def test_media_executable_suffix_is_neutralised_and_still_parses_to_the_id(
    tmp_path: Path,
) -> None:
    downloaded = tmp_path / "report.pdf.exe"
    downloaded.write_bytes(b"MZ")
    final = unique_media_path(downloaded, 12345, "document")
    assert final.name == "12345.exe.bin"
    assert media_msg_id(final.name) == 12345


def test_unique_media_path_numbers_taken_names(tmp_path: Path) -> None:
    (tmp_path / "7.jpg").write_bytes(b"a")
    (tmp_path / "7_1.jpg").write_bytes(b"b")
    downloaded = tmp_path / "x.jpg"
    downloaded.write_bytes(b"c")
    assert unique_media_path(downloaded, 7, "photo").name == "7_2.jpg"
    assert media_file_name(7, ".jpg", 2) == "7_2.jpg"


@pytest.mark.parametrize(
    ("name", "expected"), [("5.jpg", 5), ("5_2.jpg", 5), ("5", 5), ("x5.jpg", None), ("", None)]
)
def test_media_msg_id(name: str, expected: int | None) -> None:
    assert media_msg_id(name) == expected


def test_delete_media_of_a_missing_folder_or_no_ids_does_nothing(tmp_path: Path) -> None:
    delete_media(tmp_path, "2026-10", [1])
    month = tmp_path / "media" / "2026-10"
    month.mkdir(parents=True)
    (month / "1.jpg").write_bytes(b"x")
    delete_media(tmp_path, "2026-10", [])
    assert (month / "1.jpg").exists()
    delete_media(tmp_path, "2026-10", [1])
    assert not month.exists()


def test_marking_is_a_no_op_off_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media_files, "MARK_OF_THE_WEB", False)
    path = tmp_path / "1.jpg"
    path.write_bytes(b"x")
    mark_downloaded(path)
    assert [p.name for p in tmp_path.iterdir()] == ["1.jpg"]


def test_marking_a_missing_file_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media_files, "MARK_OF_THE_WEB", True)
    mark_downloaded(tmp_path / "no_such_folder" / "1.jpg")


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
def test_media_gets_zone_identifier(tmp_path: Path) -> None:
    path = tmp_path / "5.exe.bin"
    path.write_bytes(b"MZ")
    mark_downloaded(path)
    assert Path(f"{path}:Zone.Identifier").read_bytes() == ZONE_IDENTIFIER
    assert path.read_bytes() == b"MZ"
