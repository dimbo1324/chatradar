"""Table-driven cases from `tests/fixtures/pipeline/*.json`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pipeline"


def load_cases(name: str) -> list[Any]:
    """Each case as a pytest param with its `id`."""
    rows: list[dict[str, Any]] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return [pytest.param(row, id=row["id"]) for row in rows]
