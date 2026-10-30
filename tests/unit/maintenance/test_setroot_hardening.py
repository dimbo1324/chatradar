from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from chatimport import setroot
from chatimport.ports import ChatImportError
from chatimport.setroot import move_root, validate_new_root
from tests.unit.storage.test_fileio import make_dir_link

if TYPE_CHECKING:
    from pathlib import Path


def test_set_root_refuses_app_data_folder(tmp_path: Path) -> None:
    old = tmp_path / "Desktop" / "ChatImport"
    old.mkdir(parents=True)
    base = tmp_path / "AppData" / "ChatImport"
    base.mkdir(parents=True)
    for target in (base, base / "data" / "ChatImport", tmp_path / "AppData"):
        with pytest.raises(ChatImportError, match="application folder"):
            validate_new_root(target, old, app_base=base)
    assert validate_new_root(tmp_path / "Data" / "ChatImport", old, app_base=base) == []


def test_set_root_refuses_foreign_non_empty_folder_without_move(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    foreign = tmp_path / "foreign" / "ChatImport"
    (foreign / "holiday").mkdir(parents=True)
    (foreign / "holiday" / "photo.jpg").write_bytes(b"x")
    with pytest.raises(ChatImportError, match="holds no ChatImport data"):
        validate_new_root(foreign, old, move=False)
    assert validate_new_root(foreign / ".." / "empty", old, move=False) == []


@pytest.mark.parametrize("marker", ["_status.json", "chat_-1/state.json"])
def test_an_existing_data_root_is_accepted_without_move(tmp_path: Path, marker: str) -> None:
    old = tmp_path / "old"
    old.mkdir()
    data = tmp_path / "data" / "ChatImport"
    (data / marker).parent.mkdir(parents=True, exist_ok=True)
    (data / marker).write_bytes(b"{}")
    assert validate_new_root(data, old, move=False) == []


def cross_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(old: Path, new: Path) -> bool:
        return False

    monkeypatch.setattr(setroot, "_same_volume", never)


async def test_move_root_with_symlink_inside_preserves_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 1000)
    old = tmp_path / "old" / "ChatImport"
    (old / "chat_-1").mkdir(parents=True)
    (old / "chat_-1" / "state.json").write_bytes(b"{}")
    try:
        (old / "chat_-1" / "media").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available")
    new = tmp_path / "new" / "ChatImport"
    cross_volume(monkeypatch)

    await move_root(old, new, move=True)

    link = new / "chat_-1" / "media"
    assert link.is_symlink()
    assert not old.exists()
    assert (outside / "big.bin").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are a Windows feature")
async def test_move_root_with_a_junction_inside_is_refused_before_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    old = tmp_path / "old" / "ChatImport"
    (old / "chat_-1").mkdir(parents=True)
    _winapi.CreateJunction(str(outside), str(old / "chat_-1" / "media"))
    new = tmp_path / "new" / "ChatImport"
    cross_volume(monkeypatch)

    with pytest.raises(ChatImportError, match="junction"):
        await move_root(old, new, move=True)
    assert not new.exists()
    assert (old / "chat_-1").is_dir()


def test_tree_stats_counts_a_link_as_one_file(tmp_path: Path) -> None:
    target = tmp_path / "t"
    target.mkdir()
    (target / "a").write_bytes(b"aa")
    root = tmp_path / "root"
    root.mkdir()
    (root / "f").write_bytes(b"123")
    make_dir_link(root / "link", target)
    files, _ = setroot._tree_stats(root)  # pyright: ignore[reportPrivateUsage]
    assert files == 2
