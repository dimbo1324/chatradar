from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from chatimport.gui import strings
from chatimport.gui.format import format_bytes, format_count
from chatimport.gui.models.data_models import (
    LEFT,
    MEDIA_SHARE_ROLE,
    RIGHT,
    SHARE_ROLE,
    TONE_ROLE,
    IssueColumn,
    IssueRow,
    IssuesModel,
    PreviewColumn,
    PreviewModel,
    UsageColumn,
    UsageModel,
    parse_issues,
)
from chatimport.gui.strings import translate
from chatimport.trim import ChatTrimPreview
from chatimport.usage import ChatUsage
from tests.unit.gui.logic.spy import record

if TYPE_CHECKING:
    from collections.abc import Iterator

DISPLAY = Qt.ItemDataRole.DisplayRole
ALIGN = Qt.ItemDataRole.TextAlignmentRole
TIP = Qt.ItemDataRole.ToolTipRole


@pytest.fixture(autouse=True)
def english() -> Iterator[None]:
    strings.set_current_language("en")
    yield
    strings.set_current_language("en")


def cell(model: QAbstractTableModel, row: int, column: int, role: Any = DISPLAY) -> Any:
    return model.data(model.index(row, column), role)


def usage(
    title: str | None, jsonl: int, media: int = 0, records: int | None = 3, parts: int = 1
) -> ChatUsage:
    return ChatUsage(1, title, Path("data") / "folder_x", jsonl, media, parts, records)


def trim(
    title: str, deleted: int, total: int, freed: int, oldest: datetime | None
) -> ChatTrimPreview:
    return ChatTrimPreview(1, title, total, deleted, 1, freed, oldest)


def test_usage_model_sorts_by_size_and_formats(qapp: object) -> None:
    model = UsageModel()
    model.set_usage([usage("Small", 100), usage("Big", 3_000, 1_000, 12_345, 4), usage(None, 500)])
    assert model.rowCount() == 3
    assert model.columnCount() == 5
    assert cell(model, 0, UsageColumn.CHAT) == "Big"
    assert cell(model, 0, UsageColumn.SIZE) == format_bytes(4_000, "en")
    assert cell(model, 0, UsageColumn.MESSAGES) == "12,345"
    assert cell(model, 0, UsageColumn.PARTS) == "4"
    assert cell(model, 0, UsageColumn.SHARE) is None
    assert cell(model, 1, UsageColumn.CHAT) == "Unreadable chat (folder_x)"
    assert cell(model, 0, UsageColumn.CHAT, TIP) == str(Path("data") / "folder_x")
    assert cell(model, 0, UsageColumn.SIZE, TIP) is None
    assert cell(model, 0, UsageColumn.CHAT, SHARE_ROLE) == 1.0
    assert cell(model, 2, UsageColumn.CHAT, SHARE_ROLE) == pytest.approx(100 / 4_000)
    assert cell(model, 0, UsageColumn.CHAT, MEDIA_SHARE_ROLE) == pytest.approx(0.25)
    assert cell(model, 0, UsageColumn.SIZE, ALIGN) == RIGHT
    assert cell(model, 0, UsageColumn.CHAT, ALIGN) == LEFT
    assert cell(model, 0, UsageColumn.CHAT, Qt.ItemDataRole.DecorationRole) is None
    assert model.data(QModelIndex()) is None
    assert model.data(model.createIndex(9, 0)) is None
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0


def test_usage_model_handles_unknown_records_and_empty_data(qapp: object) -> None:
    model = UsageModel()
    model.set_usage([])
    assert model.rowCount() == 0
    model.set_usage([usage("A", 0, 0, None)])
    assert model.data(model.index(0, UsageColumn.MESSAGES)) == "-"
    assert model.data(model.index(0, UsageColumn.CHAT), SHARE_ROLE) == 0.0
    assert model.data(model.index(0, UsageColumn.CHAT), MEDIA_SHARE_ROLE) == 0.0


def test_headers_and_retranslate(qapp: object) -> None:
    model = UsageModel()
    horizontal = Qt.Orientation.Horizontal
    assert model.headerData(0, horizontal) == translate("en", "data.storage.col.chat")
    assert model.headerData(UsageColumn.SIZE, horizontal, ALIGN) == RIGHT
    assert model.headerData(UsageColumn.CHAT, horizontal, ALIGN) == LEFT
    assert model.headerData(0, horizontal, TIP) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(7, horizontal) is None
    signals: list[str] = []
    record(model.headerDataChanged, signals, "header")
    record(model.dataChanged, signals, "data")
    model.retranslate()
    assert signals == ["header"]
    model.set_usage([usage("A", 1)])
    signals.clear()
    model.retranslate()
    assert signals == ["header", "data"]


def test_preview_model(qapp: object) -> None:
    oldest = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    model = PreviewModel()
    model.set_preview(
        [
            trim("Nothing", 0, 10, 0, oldest),
            trim("Some", 5, 12_000, 2_048, oldest),
            trim("All", 10, 10, 9_999_999, None),
        ]
    )
    assert [cell(model, r, PreviewColumn.CHAT) for r in range(3)] == ["All", "Some", "Nothing"]
    assert (
        cell(model, 1, PreviewColumn.RECORDS)
        == f"{format_count(5, 'en')} / {format_count(12_000, 'en')}"
    )
    assert cell(model, 1, PreviewColumn.SIZE) == format_bytes(2_048, "en")
    assert cell(model, 2, PreviewColumn.SIZE) == "-"
    assert cell(model, 1, PreviewColumn.OLDEST) == f"{oldest.astimezone():%Y-%m-%d}"
    assert cell(model, 0, PreviewColumn.OLDEST) == translate("en", "data.cleanup.oldest_none")
    assert cell(model, 2, PreviewColumn.OLDEST) == f"{oldest.astimezone():%Y-%m-%d}"
    assert cell(model, 0, PreviewColumn.SIZE, ALIGN) == RIGHT
    assert cell(model, 0, PreviewColumn.CHAT, ALIGN) == LEFT
    assert cell(model, 0, PreviewColumn.CHAT, TIP) is None
    assert model.data(QModelIndex()) is None
    assert model.data(model.createIndex(9, 0)) is None
    assert model.rowCount(model.index(0, 0)) == 0


def test_preview_oldest_dash_when_nothing_is_deleted(qapp: object) -> None:
    model = PreviewModel()
    model.set_preview([trim("Keep", 0, 5, 0, None)])
    assert model.data(model.index(0, PreviewColumn.OLDEST)) == "-"


def test_issues_model(qapp: object) -> None:
    model = IssuesModel()
    model.set_issues(
        [
            IssueRow("error", "folder_a", "bad part"),
            IssueRow("warning", "folder_b", "stale state"),
            IssueRow("info", "folder_c", "note"),
            IssueRow("weird", "folder_d", "other"),
        ]
    )
    assert model.rowCount() == 4
    assert cell(model, 0, IssueColumn.SEVERITY) == translate("en", "data.integrity.severity.error")
    assert cell(model, 3, IssueColumn.SEVERITY) == "weird"
    assert cell(model, 0, IssueColumn.FOLDER) == "folder_a"
    assert cell(model, 0, IssueColumn.MESSAGE) == "bad part"
    assert [cell(model, r, 0, TONE_ROLE) for r in range(4)] == [
        "danger",
        "warning",
        "info",
        "neutral",
    ]
    assert cell(model, 0, IssueColumn.MESSAGE, TIP) == "bad part"
    assert cell(model, 0, IssueColumn.FOLDER, TIP) is None
    assert cell(model, 0, IssueColumn.MESSAGE, Qt.ItemDataRole.DecorationRole) is None
    assert model.data(QModelIndex()) is None
    assert model.data(model.createIndex(9, 0)) is None
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.headerData(IssueColumn.FOLDER, Qt.Orientation.Horizontal) == translate(
        "en", "data.integrity.col.folder"
    )


def test_parse_issues() -> None:
    assert parse_issues({}) == []
    assert parse_issues({"issues": "nope"}) == []
    rows = parse_issues(
        {
            "issues": [
                {"severity": "error", "folder": "f", "message": "m"},
                {"severity": "info"},
                "junk",
                {"folder": 5, "message": None},
            ]
        }
    )
    assert rows == [
        IssueRow("error", "f", "m"),
        IssueRow("info", "", ""),
        IssueRow("", "5", "None"),
    ]
