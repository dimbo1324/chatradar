from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests never read the real configuration, library or ChatImport folder."""
    for key in [k for k in os.environ if k.startswith("CHATIMPORT_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHATIMPORT_ROOT", str(tmp_path / "ChatImport"))
    return tmp_path
