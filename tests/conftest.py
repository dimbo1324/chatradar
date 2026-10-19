from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from chatradar.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Tests never read the real .env and never write to the real data/."""
    for key in [k for k in os.environ if k.startswith("CHATRADAR_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHATRADAR_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
