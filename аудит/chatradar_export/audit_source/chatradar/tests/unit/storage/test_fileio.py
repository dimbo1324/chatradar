from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from chatimport.storage import fileio
from chatimport.storage.fileio import (
    PRIVATE_FILE_MODE,
    append_line,
    atomic_write_bytes,
    atomic_writer,
    replace_file,
    unlink_file,
    walk_files,
)


def make_dir_link(link: Path, target: Path) -> None:
    """A symbolic link, or on Windows without that right a directory junction."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("symbolic links are not available")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(fileio.time, "sleep", slept.append)
    monkeypatch.setattr(fileio, "RETRY_SHARING_VIOLATIONS", True)
    return slept


@pytest.mark.parametrize("unique", [False, True])
def test_failed_write_leaves_no_temp_and_keeps_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unique: bool
) -> None:
    target = tmp_path / "x.json"
    target.write_bytes(b"old")

    def broken(_fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(OSError, match="fsync failed"):
        atomic_write_bytes(target, b"new", unique=unique)
    monkeypatch.undo()
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_unique_temp_names_differ_and_live_next_to_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen.append(Path(src).name)
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    atomic_write_bytes(tmp_path / "x.json", b"1", unique=True)
    atomic_write_bytes(tmp_path / "x.json", b"2", unique=True)
    assert len(set(seen)) == 2
    assert all(name.startswith(".x.json.") and name.endswith(".tmp") for name in seen)
    assert (tmp_path / "x.json").read_bytes() == b"2"


def test_streaming_writer_publishes_only_on_success(tmp_path: Path) -> None:
    target = tmp_path / "big.json"
    with atomic_writer(target) as handle:
        handle.write(b"[")
        assert not target.exists()
        handle.write(b"]")
    assert target.read_bytes() == b"[]"

    def interrupted() -> None:
        with atomic_writer(target) as handle:
            handle.write(b"partial")
            raise RuntimeError

    with pytest.raises(RuntimeError):
        interrupted()
    assert target.read_bytes() == b"[]"
    assert [p.name for p in tmp_path.iterdir()] == ["big.json"]


def test_private_mode_creates_an_owner_only_file(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    atomic_write_bytes(target, b"secret = 1\n", mode=PRIVATE_FILE_MODE)
    assert target.read_bytes() == b"secret = 1\n"
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == PRIVATE_FILE_MODE


def test_private_mode_tolerates_a_failing_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(Path, "chmod", refuse)
    atomic_write_bytes(tmp_path / "c.toml", b"x", mode=PRIVATE_FILE_MODE)
    assert (tmp_path / "c.toml").read_bytes() == b"x"


def test_atomic_write_retries_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    real = os.replace
    failures = iter([True, True])

    def flaky(src: Any, dst: Any) -> None:
        if next(failures, False):
            raise PermissionError("sharing violation")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    atomic_write_bytes(tmp_path / "state.json", b"{}")
    assert (tmp_path / "state.json").read_bytes() == b"{}"
    assert no_sleep == [0.05, 0.1]


def test_retry_gives_up_after_the_last_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    def locked(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("still open")

    path = tmp_path / "part.jsonl"
    path.write_bytes(b"x")
    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(PermissionError, match="still open"):
        unlink_file(path)
    assert no_sleep == list(fileio.RETRY_DELAYS)


def test_without_retries_the_first_permission_error_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def locked(src: Any, dst: Any) -> None:
        calls.append("replace")
        raise PermissionError("denied")

    monkeypatch.setattr(fileio, "RETRY_SHARING_VIOLATIONS", False)
    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(PermissionError):
        replace_file(tmp_path / "a", tmp_path / "b")
    assert calls == ["replace"]


def test_unlink_missing_ok(tmp_path: Path) -> None:
    unlink_file(tmp_path / "absent", missing_ok=True)
    with pytest.raises(FileNotFoundError):
        unlink_file(tmp_path / "absent")


def test_append_line_creates_the_folder_and_appends(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "log.jsonl"
    append_line(path, b"a\n")
    append_line(path, b"b\n")
    assert path.read_bytes() == b"a\nb\n"


def test_walk_files_lists_files_and_skips_chosen_folders(tmp_path: Path) -> None:
    (tmp_path / "a" / "media").mkdir(parents=True)
    (tmp_path / "a" / "1.jsonl").write_bytes(b"1")
    (tmp_path / "a" / "media" / "5.jpg").write_bytes(b"j")
    (tmp_path / "top.txt").write_bytes(b"t")
    every = sorted(Path(e.path).name for e in walk_files(tmp_path))
    assert every == ["1.jsonl", "5.jpg", "top.txt"]
    without_media = sorted(
        Path(e.path).name for e in walk_files(tmp_path, skip_dir=lambda e: e.name == "media")
    )
    assert without_media == ["1.jsonl", "top.txt"]


def test_walk_files_yields_a_folder_link_without_following_it(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "inside.txt").write_bytes(b"x")
    root = tmp_path / "root"
    root.mkdir()
    make_dir_link(root / "link", target)
    entries = list(walk_files(root))
    assert [Path(e.path).name for e in entries] == ["link"]
    assert entries[0].is_symlink() or entries[0].is_junction()
