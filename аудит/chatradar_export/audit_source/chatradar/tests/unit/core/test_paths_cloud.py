from __future__ import annotations

import stat
import sys
from typing import TYPE_CHECKING

import pytest

from chatimport import paths
from chatimport.paths import app_paths, cloud_sync_warning, is_cloud_synced, resolve_root

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("name", ["OneDrive", "OneDrive - Contoso", "onedrive"])
def test_a_onedrive_component_is_cloud_synced(tmp_path: Path, name: str) -> None:
    assert is_cloud_synced(tmp_path / name / "Desktop" / "ChatImport", env={})


def test_a_folder_below_the_onedrive_variable_is_cloud_synced(tmp_path: Path) -> None:
    synced = tmp_path / "Sync Root"
    env = {"OneDriveCommercial": str(synced)}
    assert is_cloud_synced(synced / "Desktop" / "ChatImport", env=env)
    assert not is_cloud_synced(tmp_path / "Local" / "ChatImport", env=env)


def test_a_plain_folder_gets_no_warning(tmp_path: Path) -> None:
    assert cloud_sync_warning(tmp_path / "Data" / "ChatImport", env={}) is None


def test_default_root_under_onedrive_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "OneDrive" / "Desktop"
    monkeypatch.setattr(paths, "user_desktop_dir", lambda: str(desktop))
    root = resolve_root(env={})
    warning = cloud_sync_warning(root, env={})
    assert warning is not None
    assert str(root) in warning
    assert "set-root" in warning


def test_the_environment_defaults_to_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OneDrive", str(tmp_path / "cloud"))
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    assert is_cloud_synced(tmp_path / "cloud" / "x")
    assert not is_cloud_synced(tmp_path / "local" / "x")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_app_folders_are_private_on_posix(tmp_path: Path) -> None:
    base = tmp_path / "app"
    base.mkdir(mode=0o755)
    app = app_paths(base)
    app.ensure()
    for folder in (app.base, app.session_file.parent):
        assert stat.S_IMODE(folder.stat().st_mode) & 0o077 == 0


def test_posix_branch_restricts_base_and_session_and_tolerates_chmod_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path as RealPath

    changed: list[tuple[str, int]] = []

    def chmod(self: RealPath, mode: int, *, follow_symlinks: bool = True) -> None:
        changed.append((self.name, mode))
        if self.name == "session":
            raise PermissionError("not the owner")

    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(RealPath, "chmod", chmod)
    app = app_paths(tmp_path / "app")
    app.ensure()
    assert changed == [("app", 0o700), ("session", 0o700)]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows keeps the inherited ACL")
def test_app_folders_are_created_on_windows(tmp_path: Path) -> None:
    app = app_paths(tmp_path / "app")
    app.ensure()
    assert all(p.is_dir() for p in (app.base, app.session_file.parent, app.log_dir))
