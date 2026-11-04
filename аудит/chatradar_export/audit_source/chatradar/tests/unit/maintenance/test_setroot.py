from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest

from chatimport import setroot
from chatimport.ports import ChatImportError
from chatimport.setroot import move_root, validate_new_root

ON_WINDOWS = sys.platform == "win32"


def populate(root: Path) -> dict[str, bytes]:
    files = {
        "chat_-1/2026-09_001.jsonl": b'{"a": 1}\n',
        "chat_-1/state.json": b"{}\n",
        "chat_-1/media/2026-09/5.jpg": b"\xff\xd8binary\x00",
        "_trim_log.jsonl": b"{}\n",
        "unicode_" + chr(0x436) + "/" + chr(0x444) + ".txt": (
            chr(0x444) + chr(0x430) + chr(0x439) + chr(0x43B)
        ).encode(),
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "empty_dir").mkdir()
    return files


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- validate_new_root


def test_same_folder_is_rejected(tmp_path: Path) -> None:
    old = tmp_path / "ChatImport"
    old.mkdir()

    with pytest.raises(ChatImportError, match="is the current folder"):
        validate_new_root(old, old)


def test_same_folder_spelled_differently_is_rejected(tmp_path: Path) -> None:
    old = tmp_path / "ChatImport"
    old.mkdir()

    with pytest.raises(ChatImportError, match="is the current folder"):
        validate_new_root(tmp_path / "x" / ".." / "ChatImport", old)


def test_new_folder_inside_the_old_one_is_rejected(tmp_path: Path) -> None:
    old = tmp_path / "ChatImport"
    old.mkdir()

    with pytest.raises(ChatImportError, match="must not be inside the current"):
        validate_new_root(old / "sub" / "deeper", old)
    assert not (old / "sub").exists()


def test_old_folder_inside_the_new_one_is_rejected(tmp_path: Path) -> None:
    old = tmp_path / "outer" / "ChatImport"
    old.mkdir(parents=True)

    with pytest.raises(ChatImportError, match="must not be inside the new"):
        validate_new_root(tmp_path / "outer", old)


def test_a_sibling_sharing_a_name_prefix_is_not_nested(tmp_path: Path) -> None:
    old = tmp_path / "ChatImport"
    old.mkdir()
    new = tmp_path / "ChatImport2"

    assert validate_new_root(new, old) == []
    assert new.is_dir()


@pytest.mark.skipif(not ON_WINDOWS, reason="paths are case-insensitive on Windows only")
def test_nesting_is_detected_regardless_of_letter_case_on_windows(tmp_path: Path) -> None:
    old = tmp_path / "ChatImport"
    old.mkdir()
    shouting = Path(str(old).upper()) / "inside"

    with pytest.raises(ChatImportError, match="must not be inside"):
        validate_new_root(shouting, old)


def test_a_usable_folder_is_created_and_leaves_no_probe_behind(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "a" / "b" / "ChatImport"

    assert validate_new_root(new, old) == []

    assert new.is_dir()
    assert list(new.iterdir()) == []


def test_an_existing_non_empty_folder_is_valid_and_untouched(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    (new / "keep.txt").write_text("keep", encoding="utf-8")

    validate_new_root(new, old)

    assert [p.name for p in new.iterdir()] == ["keep.txt"]


def test_a_path_that_is_a_file_is_rejected_with_a_clear_error(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(ChatImportError, match="cannot write to"):
        validate_new_root(target, old)
    assert target.read_text(encoding="utf-8") == "x"


def test_an_unwritable_folder_is_rejected_and_the_probe_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "ro"

    def refuse(self: Path, data: bytes) -> int:
        raise PermissionError("read-only volume")

    monkeypatch.setattr(Path, "write_bytes", refuse)

    with pytest.raises(ChatImportError, match="read-only volume"):
        validate_new_root(new, old)

    assert list(new.iterdir()) == []


def test_a_probe_that_cannot_be_removed_does_not_mask_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    old.mkdir()
    real_unlink = Path.unlink

    def stubborn(self: Path, missing_ok: bool = False) -> None:
        if self.name.startswith(".chatimport-probe-"):
            raise PermissionError("antivirus holds it")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", stubborn)

    assert validate_new_root(tmp_path / "new", old) == []


@pytest.mark.parametrize(
    "name",
    ["OneDrive", "ONEDRIVE", "OneDrive-Personal", "onedrive", "My OneDrive Stuff"],
)
def test_onedrive_in_any_path_component_warns_case_insensitively(tmp_path: Path, name: str) -> None:
    old = tmp_path / "old"
    old.mkdir()

    warnings = validate_new_root(tmp_path / name / "ChatImport", old)

    assert len(warnings) == 1
    assert "OneDrive" in warnings[0]


@pytest.mark.parametrize("name", ["Dropbox", "one_drive", "drive", "Documents"])
def test_other_folders_do_not_warn(tmp_path: Path, name: str) -> None:
    old = tmp_path / "old"
    old.mkdir()

    assert validate_new_root(tmp_path / name / "ChatImport", old) == []


def test_relative_new_folder_is_resolved_against_the_working_directory(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()

    validate_new_root(Path("relative") / "ChatImport", old)

    assert (tmp_path / "relative" / "ChatImport").is_dir()


# ---------------------------------------------------------------- move_root (same volume)


async def test_move_false_touches_nothing(tmp_path: Path) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"

    await move_root(old, new, move=False)

    assert snapshot(old) == expected
    assert not new.exists()


async def test_same_volume_move_renames_the_whole_tree(tmp_path: Path) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "deep" / "er" / "new"

    await move_root(old, new, move=True)

    assert not old.exists()
    assert snapshot(new) == expected
    assert (new / "empty_dir").is_dir()


async def test_same_volume_move_never_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    populate(old)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("copytree used on the same volume")

    monkeypatch.setattr(setroot, "shutil", types.SimpleNamespace(copytree=forbidden))

    await move_root(old, tmp_path / "new", move=True)

    assert (tmp_path / "new").is_dir()


async def test_a_missing_old_folder_is_a_no_op(tmp_path: Path) -> None:
    new = tmp_path / "parent" / "new"

    await move_root(tmp_path / "ghost", new, move=True)

    assert not new.exists()
    assert not new.parent.exists()


async def test_an_empty_existing_target_is_replaced(tmp_path: Path) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    new.mkdir()

    await move_root(old, new, move=True)

    assert snapshot(new) == expected
    assert not old.exists()


async def test_a_non_empty_target_aborts_and_nothing_changes(tmp_path: Path) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    new.mkdir()
    (new / "precious.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(ChatImportError, match="already exists and is not empty"):
        await move_root(old, new, move=True)

    assert snapshot(old) == expected
    assert snapshot(new) == {"precious.txt": b"mine"}


async def test_a_target_that_is_a_file_aborts(tmp_path: Path) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    new.write_text("file", encoding="utf-8")

    with pytest.raises(ChatImportError, match="already exists and is not empty"):
        await move_root(old, new, move=True)

    assert snapshot(old) == expected
    assert new.read_text(encoding="utf-8") == "file"


async def test_a_failing_rename_propagates_and_keeps_the_old_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    expected = populate(old)

    def locked(self: Path, target: object) -> Path:
        raise PermissionError("explorer holds a handle")

    monkeypatch.setattr(Path, "replace", locked)

    with pytest.raises(PermissionError):
        await move_root(old, tmp_path / "new", move=True)

    assert snapshot(old) == expected


# ---------------------------------------------------------------- move_root (other volume)


@pytest.fixture
def other_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(old: Path, new: Path) -> bool:
        return False

    monkeypatch.setattr(setroot, "_same_volume", never)


@pytest.mark.usefixtures("other_volume")
async def test_cross_volume_move_copies_verifies_and_deletes_the_old_tree(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "far" / "new"

    await move_root(old, new, move=True)

    assert not old.exists()
    assert snapshot(new) == expected
    assert (new / "empty_dir").is_dir()


@pytest.mark.usefixtures("other_volume")
async def test_cross_volume_move_into_an_empty_existing_target(tmp_path: Path) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    new.mkdir()

    await move_root(old, new, move=True)

    assert snapshot(new) == expected


@pytest.mark.usefixtures("other_volume")
async def test_verification_mismatch_removes_the_copy_and_keeps_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    real_copytree = shutil.copytree

    def lossy(src: Path, dst: Path, **kwargs: object) -> Path:
        result = real_copytree(src, dst)
        (Path(dst) / "chat_-1" / "state.json").write_bytes(b"{")
        return Path(result)

    monkeypatch.setattr(
        setroot, "shutil", types.SimpleNamespace(copytree=lossy, rmtree=shutil.rmtree)
    )

    with pytest.raises(ChatImportError, match="does not match the original"):
        await move_root(old, new, move=True)

    assert snapshot(old) == expected
    assert not new.exists()


@pytest.mark.usefixtures("other_volume")
async def test_a_missing_file_in_the_copy_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    real_copytree = shutil.copytree

    def lossy(src: Path, dst: Path, **kwargs: object) -> Path:
        result = real_copytree(src, dst)
        (Path(dst) / "_trim_log.jsonl").unlink()
        return Path(result)

    monkeypatch.setattr(
        setroot, "shutil", types.SimpleNamespace(copytree=lossy, rmtree=shutil.rmtree)
    )

    with pytest.raises(ChatImportError):
        await move_root(old, new, move=True)

    assert snapshot(old) == expected
    assert not new.exists()


@pytest.mark.usefixtures("other_volume")
async def test_a_copy_that_fails_halfway_leaves_no_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    real_copytree = shutil.copytree

    def dying(src: Path, dst: Path, **kwargs: object) -> Path:
        real_copytree(src, dst)
        raise OSError("target disk is full")

    monkeypatch.setattr(
        setroot, "shutil", types.SimpleNamespace(copytree=dying, rmtree=shutil.rmtree)
    )

    with pytest.raises(OSError, match="target disk is full"):
        await move_root(old, new, move=True)

    assert snapshot(old) == expected
    assert not new.exists()


@pytest.mark.usefixtures("other_volume")
async def test_failing_to_delete_the_old_tree_only_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"
    real_rmtree = shutil.rmtree

    def selective(path: str | Path, *args: object, **kwargs: object) -> None:
        if Path(path) == old:
            raise PermissionError("a file is open")
        real_rmtree(path, *args, **kwargs)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType, reportCallIssue]

    monkeypatch.setattr(
        setroot, "shutil", types.SimpleNamespace(copytree=shutil.copytree, rmtree=selective)
    )

    with caplog.at_level("WARNING"):
        await move_root(old, new, move=True)

    assert "could not be fully deleted" in caplog.text
    assert snapshot(new) == expected
    assert old.exists()


@pytest.mark.usefixtures("other_volume")
async def test_cancellation_style_base_exceptions_also_clean_the_partial_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    populate(old)
    new = tmp_path / "new"
    real_copytree = shutil.copytree

    def interrupted(src: Path, dst: Path, **kwargs: object) -> Path:
        real_copytree(src, dst)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        setroot, "shutil", types.SimpleNamespace(copytree=interrupted, rmtree=shutil.rmtree)
    )

    with pytest.raises(KeyboardInterrupt):
        await move_root(old, new, move=True)

    assert not new.exists()
    assert old.exists()


async def test_rename_across_devices_falls_back_to_copy_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spec (set-root --move) requires a verified copy when a rename cannot work."""
    old = tmp_path / "old"
    expected = populate(old)
    new = tmp_path / "new"

    def cross_device(self: Path, target: object) -> Path:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(Path, "replace", cross_device)

    await move_root(old, new, move=True)

    assert snapshot(new) == expected
    assert not old.exists()
