from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QModelIndex, Qt

from chatimport.gui.format import format_exact
from chatimport.gui.models.log_model import (
    COLUMN_KEYS,
    MAX_ROWS,
    RECORD_ROLE,
    Column,
    LogFilterProxy,
    LogModel,
    local_time_text,
)
from chatimport.gui.models.log_parser import Level, LogRecord
from chatimport.gui.strings import translate
from tests.unit.gui.logic.spy import record

BASE = datetime(2026, 10, 31, 20, 0, 0, tzinfo=UTC)


def rec(
    n: int, level: Level = Level.INFO, logger: str = "chatimport.worker", detail: str = ""
) -> LogRecord:
    return LogRecord(BASE + timedelta(seconds=n), level, logger, f"message {n}", detail)


def cell(
    model: LogModel, row: int, column: Column, role: int = Qt.ItemDataRole.DisplayRole
) -> object:
    return model.data(model.index(row, column), role)


def test_basic_shape_and_headers(qapp: object) -> None:
    model = LogModel("en")
    assert model.rowCount() == 0
    assert model.columnCount() == len(Column)
    assert model.limit == MAX_ROWS
    model.append([rec(0)])
    parent = model.index(0, 0)
    assert model.rowCount(parent) == 0
    assert model.columnCount(parent) == 0
    for column, key in COLUMN_KEYS.items():
        assert model.headerData(column, Qt.Orientation.Horizontal) == translate("en", key)
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None


def test_data_roles(qapp: object) -> None:
    model = LogModel("en")
    record = rec(1, Level.WARNING, "chatimport.worker_backfill")
    model.append([record])
    assert cell(model, 0, Column.TIME) == local_time_text(record)
    assert cell(model, 0, Column.LEVEL) == translate("en", "log.level.warning")
    assert cell(model, 0, Column.SOURCE) == "worker_backfill"
    assert cell(model, 0, Column.MESSAGE) == "message 1"
    assert cell(model, 0, Column.TIME, RECORD_ROLE) is record
    assert cell(model, 0, Column.TIME, Qt.ItemDataRole.ToolTipRole) == format_exact(record.time)
    assert cell(model, 0, Column.SOURCE, Qt.ItemDataRole.ToolTipRole) == record.logger
    assert cell(model, 0, Column.LEVEL, Qt.ItemDataRole.ToolTipRole) is None
    assert cell(model, 0, Column.MESSAGE, Qt.ItemDataRole.DecorationRole) is None
    assert model.data(QModelIndex()) is None
    assert model.data(model.createIndex(5, 0)) is None
    assert model.record_at(0) is record
    assert model.records() == [record]


def test_counts_follow_appends_overflow_and_clear(qapp: object) -> None:
    model = LogModel("en", limit=5)
    model.append([])
    model.append([rec(0, Level.WARNING), rec(1, Level.ERROR), rec(2, Level.CRITICAL)])
    assert (model.warnings, model.errors) == (1, 2)
    model.append([rec(3), rec(4), rec(5)])
    assert model.rowCount() == 5
    assert (model.warnings, model.errors) == (0, 2)
    assert model.record_at(0).message == "message 1"
    model.append([rec(n) for n in range(10, 20)])
    assert [r.message for r in model.records()] == [f"message {n}" for n in range(15, 20)]
    assert (model.warnings, model.errors) == (0, 0)
    model.append([rec(30, Level.ERROR)])
    model.clear()
    assert model.rowCount() == 0
    assert model.errors == 0


@pytest.mark.parametrize(
    ("existing", "older", "taken", "first_after"),
    [
        (5, [], 0, None),
        (10, [1], 0, None),
        (7, [1, 2, 3, 4, 5], 3, "message 3"),
        (0, [1, 2], 2, "message 1"),
        (5, [1, 2, 3], 3, "message 1"),
    ],
)
def test_prepend(
    qapp: object, existing: int, older: list[int], taken: int, first_after: str | None
) -> None:
    model = LogModel("en", limit=10)
    model.append([rec(100 + n) for n in range(existing)])
    assert model.prepend([rec(n) for n in older]) == taken
    if first_after is not None:
        assert model.record_at(0).message == first_after
    assert model.rowCount() == existing + taken


def test_set_language_retranslates_only_with_rows(qapp: object) -> None:
    model = LogModel("en")
    signals: list[str] = []
    record(model.dataChanged, signals, "data")
    record(model.headerDataChanged, signals, "header")
    model.set_language("ru")
    assert signals == []
    model.append([rec(1)])
    model.set_language("en")
    assert signals == ["header", "data"]
    assert cell(model, 0, Column.LEVEL) == translate("en", "log.level.info")


def make_proxy() -> tuple[LogModel, LogFilterProxy]:
    model = LogModel("en")
    model.append(
        [
            rec(0, Level.DEBUG, "chatimport.router"),
            rec(1, Level.INFO, "chatimport.worker"),
            rec(2, Level.ERROR, "chatimport.worker", "Traceback (most recent call last):\nboom"),
            rec(3, Level.WARNING, "other.lib"),
        ]
    )
    return model, LogFilterProxy(model)


def shown(proxy: LogFilterProxy) -> list[str]:
    return [proxy.record_at(row).message for row in range(proxy.rowCount())]


def test_proxy_accepts_everything_by_default(qapp: object) -> None:
    _, proxy = make_proxy()
    assert proxy.level is Level.DEBUG
    assert proxy.rowCount() == 4


def test_proxy_filters(qapp: object) -> None:
    _, proxy = make_proxy()
    proxy.set_level(Level.WARNING)
    assert shown(proxy) == ["message 2", "message 3"]
    proxy.set_level(Level.DEBUG)
    proxy.set_show_tracebacks(False)
    assert shown(proxy) == ["message 0", "message 1", "message 3"]
    proxy.set_show_tracebacks(True)
    proxy.set_logger_prefix("chatimport.w")
    assert shown(proxy) == ["message 1", "message 2"]
    proxy.set_logger_prefix("")
    proxy.set_query("BOOM  traceback")
    assert shown(proxy) == ["message 2"]
    proxy.set_query("worker 3")
    assert shown(proxy) == []
    proxy.set_query("")
    assert proxy.rowCount() == 4


def test_proxy_maps_rows_back_to_records(qapp: object) -> None:
    model, proxy = make_proxy()
    proxy.set_level(Level.ERROR)
    assert proxy.record_at(0) is model.record_at(2)
