from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QModelIndex, Qt

from chatimport.gui import strings
from chatimport.gui.format import Freshness, FreshnessThresholds, format_exact
from chatimport.gui.models.chats_model import (
    ROW_ROLE,
    SORT_ROLE,
    ChatsFilterProxy,
    ChatsTableModel,
    Column,
    FilterMode,
    matches_mode,
)
from chatimport.gui.models.presentation import (
    age_seconds,
    countdown_text,
    freshness_of,
    history_chip,
    history_detail,
    history_tooltip,
    last_message_text,
    last_message_tooltip,
    span_text,
    status_chip,
    status_kind,
)
from chatimport.gui.models.snapshot import BackfillView, ChatRow
from chatimport.gui.strings import translate
from chatimport.runtime import BackfillState
from tests.unit.gui.logic.spy import record

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW = datetime(2026, 10, 31, 20, 0, 0, tzinfo=UTC)
THRESHOLDS = FreshnessThresholds()


@pytest.fixture(autouse=True)
def english() -> Iterator[None]:
    strings.set_current_language("en")
    yield
    strings.set_current_language("en")


def row(chat_id: int = 1, title: str = "Example group", **changes: Any) -> ChatRow:
    return replace(ChatRow(chat_id, title, "live"), **changes)


def backfill(state: BackfillState, **fields: Any) -> BackfillView:
    return BackfillView(state=state, **fields)


@pytest.mark.parametrize(
    ("changes", "kind", "tone", "icon"),
    [
        ({"phase": "no_access"}, "no_access", "danger", "ban"),
        ({"backfill": backfill(BackfillState.NO_ACCESS)}, "no_access", "danger", "ban"),
        ({"error": "boom"}, "error", "danger", "alert"),
        ({"paused": True}, "paused", "muted", "pause"),
        ({"phase": "paused"}, "paused", "muted", "pause"),
        ({}, "live", "live", "radio"),
        ({"phase": "starting"}, "starting", "info", "activity"),
    ],
)
def test_status_chip(changes: dict[str, Any], kind: str, tone: str, icon: str) -> None:
    chat = row(**changes)
    assert status_kind(chat) == kind
    chip = status_chip(chat, "en")
    assert (chip.tone, chip.icon) == (tone, icon)
    assert chip.text == translate("en", f"chats.status.{kind}")
    assert status_chip(chat, "ru").text == translate("ru", f"chats.status.{kind}")


@pytest.mark.parametrize("state", list(BackfillState))
def test_history_chip_for_every_state(state: BackfillState) -> None:
    chip = history_chip(row(backfill=backfill(state)), "en")
    assert chip.text == translate("en", f"chats.history.{state.value}")
    assert chip.icon
    assert chip.tone


@pytest.mark.parametrize(
    ("seconds", "english"),
    [(-3, "0 s"), (0, "0 s"), (0.2, "1 s"), (4, "4 s"), (4.01, "5 s"), (65, "1 min 5 s")],
)
def test_countdown_text(seconds: float, english: str) -> None:
    assert countdown_text(seconds, "en") == english


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (backfill(BackfillState.RETRYING, retry_at=NOW + timedelta(seconds=65)), "in 1 min 5 s"),
        (backfill(BackfillState.RETRYING, retry_at=NOW - timedelta(seconds=1)), "now"),
        (backfill(BackfillState.RETRYING), ""),
        (backfill(BackfillState.RUNNING, month="2026-03"), "2026-03"),
        (backfill(BackfillState.RUNNING), ""),
        (backfill(BackfillState.DONE, month="2026-03"), ""),
    ],
)
def test_history_detail(info: BackfillView, expected: str) -> None:
    assert history_detail(row(backfill=info), NOW, "en") == expected


def test_age_and_freshness() -> None:
    assert age_seconds(row(), NOW) is None
    assert freshness_of(row(), NOW, THRESHOLDS) is Freshness.UNKNOWN
    recent = row(newest_date=NOW - timedelta(seconds=30))
    assert age_seconds(recent, NOW) == 30
    assert freshness_of(recent, NOW, THRESHOLDS) is Freshness.FRESH
    future = row(newest_date=NOW + timedelta(hours=1))
    assert age_seconds(future, NOW) == 0.0
    old = row(newest_date=NOW - timedelta(days=3))
    assert freshness_of(old, NOW, THRESHOLDS) is Freshness.DORMANT


def test_last_message_text() -> None:
    moment = NOW - timedelta(minutes=5)
    assert last_message_text(row(), NOW, False, "en") == "never"
    assert last_message_text(row(), NOW, True, "en") == "never"
    chat = row(newest_date=moment)
    assert last_message_text(chat, NOW, False, "en") == "5 min ago"
    assert last_message_text(chat, NOW, True, "en") == moment.astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def test_last_message_tooltip() -> None:
    empty = last_message_tooltip(row(), NOW, "en").splitlines()
    assert empty == [translate("en", "chats.tip.no_messages"), translate("en", "chats.tip.toggle")]
    moment = NOW - timedelta(hours=1)
    chat = row(newest_date=moment, last_contact_at=NOW - timedelta(seconds=30))
    lines = last_message_tooltip(chat, NOW, "en").splitlines()
    assert lines == [
        format_exact(moment),
        "1 h ago",
        "Last contact: 30 s ago",
        translate("en", "chats.tip.toggle"),
    ]


def test_history_tooltip() -> None:
    plain = history_tooltip(row(), NOW, "en").splitlines()
    assert plain == [translate("en", "chats.history_tip.idle")]
    retry_at = NOW + timedelta(minutes=1)
    full = backfill(
        BackfillState.RETRYING, month="2026-03", progress=0.4, retry_at=retry_at, detail="Flood"
    )
    lines = history_tooltip(row(backfill=full), NOW, "en").splitlines()
    assert lines == [
        translate("en", "chats.history_tip.retrying"),
        "Fetching 2026-03",
        translate("en", "chats.tip.approx"),
        format_exact(retry_at),
        "Last error type: Flood",
    ]
    done = backfill(BackfillState.DONE, progress=1.0, retry_at=retry_at)
    assert history_tooltip(row(backfill=done), NOW, "en").splitlines() == [
        translate("en", "chats.history_tip.done")
    ]


def test_span_text() -> None:
    assert span_text(row()) == "—"
    assert span_text(row(oldest_date=NOW)) == "—"
    same = row(oldest_date=NOW, newest_date=NOW)
    month = NOW.astimezone().strftime("%Y-%m")
    assert span_text(same) == month
    wide = row(oldest_date=NOW - timedelta(days=400), newest_date=NOW)
    first = wide.oldest_date.astimezone().strftime("%Y-%m")  # type: ignore[union-attr]
    assert span_text(wide) == f"{first} → {month}"


@pytest.mark.parametrize(
    ("mode", "changes", "expected"),
    [
        (FilterMode.ALL, {}, True),
        (FilterMode.RUNNING, {"backfill": backfill(BackfillState.RUNNING)}, True),
        (FilterMode.RUNNING, {}, False),
        (FilterMode.WAITING, {"backfill": backfill(BackfillState.WAITING)}, True),
        (FilterMode.WAITING, {"backfill": backfill(BackfillState.RETRYING)}, True),
        (FilterMode.WAITING, {"backfill": backfill(BackfillState.DONE)}, False),
        (FilterMode.PAUSED, {"paused": True}, True),
        (FilterMode.PAUSED, {"backfill": backfill(BackfillState.PAUSED)}, True),
        (FilterMode.PAUSED, {}, False),
        (FilterMode.PROBLEMS, {"error": "x"}, True),
        (FilterMode.PROBLEMS, {"backfill": backfill(BackfillState.DISK_STOPPED)}, True),
        (FilterMode.PROBLEMS, {}, False),
        (FilterMode.SILENT_1H, {}, True),
        (FilterMode.SILENT_1H, {"newest_date": NOW - timedelta(minutes=59)}, False),
        (FilterMode.SILENT_1H, {"newest_date": NOW - timedelta(hours=1)}, True),
        (FilterMode.SILENT_1D, {"newest_date": NOW - timedelta(hours=23)}, False),
        (FilterMode.SILENT_7D, {"newest_date": NOW - timedelta(days=6)}, False),
        (FilterMode.SILENT_7D, {"newest_date": NOW - timedelta(days=8)}, True),
    ],
)
def test_matches_mode(mode: FilterMode, changes: dict[str, Any], expected: bool) -> None:
    assert matches_mode(row(**changes), mode, NOW) is expected


def make_model(absolute: bool = False) -> ChatsTableModel:
    return ChatsTableModel(lambda: NOW, lambda _id: THRESHOLDS, absolute_time=absolute)


def display(model: ChatsTableModel, r: int, column: Column, role: int = 0) -> object:
    return model.data(model.index(r, column), role or Qt.ItemDataRole.DisplayRole)


def test_set_rows_adds_changes_and_removes_in_place(qapp: object) -> None:
    model = make_model()
    log: list[str] = []
    record(model.rowsInserted, log, "insert")
    record(model.rowsRemoved, log, "remove")
    record(model.dataChanged, log, "data")
    model.set_rows([row(1), row(2), row(3)])
    assert model.chat_ids() == [1, 2, 3]
    assert log == ["insert"]
    log.clear()
    model.set_rows([row(1), row(2), row(3)])
    assert log == []
    model.set_rows([row(1), row(2, records=5), row(4)])
    assert model.chat_ids() == [1, 2, 4]
    assert log == ["remove", "data", "insert"]
    assert model.row_at(1).records == 5
    assert model.now() == NOW


def test_absolute_time_toggle_touches_only_its_column(qapp: object) -> None:
    model = make_model()
    model.set_absolute_time(False)
    model.set_rows([row(1, newest_date=NOW)])
    emitted: list[Any] = []
    record(model.dataChanged, emitted)
    model.set_absolute_time(True)
    assert model.absolute_time
    touched = [(first.column(), last.column()) for first, last, *_ in emitted]
    assert touched == [(Column.LAST_MESSAGE, Column.LAST_MESSAGE)]
    empty = make_model()
    empty.set_absolute_time(True)


def test_tick_and_retranslate_signals(qapp: object) -> None:
    model = make_model()
    model.tick()
    model.retranslate()
    model.set_rows(
        [
            row(1, newest_date=NOW),
            row(2, backfill=backfill(BackfillState.RETRYING, retry_at=NOW)),
        ]
    )
    emitted: list[Any] = []
    record(model.dataChanged, emitted)
    headers: list[Any] = []
    record(model.headerDataChanged, headers, 1)
    model.tick()
    cells = [(first.row(), first.column()) for first, *_ in emitted]
    assert cells == [(0, Column.LAST_MESSAGE), (1, Column.HISTORY)]
    emitted.clear()
    model.retranslate()
    assert [(first.row(), first.column()) for first, *_ in emitted] == [(0, 0)]
    assert headers == [1]


def test_shape_and_headers(qapp: object) -> None:
    model = make_model()
    model.set_rows([row(1)])
    parent = model.index(0, 0)
    assert model.rowCount() == 1
    assert model.columnCount() == len(Column)
    assert (model.rowCount(parent), model.columnCount(parent)) == (0, 0)
    horizontal = Qt.Orientation.Horizontal
    assert model.headerData(Column.CHAT, horizontal) == translate("en", "chats.col.chat")
    assert model.headerData(Column.LAST_MESSAGE, horizontal, Qt.ItemDataRole.ToolTipRole) == (
        translate("en", "chats.col.last_tip")
    )
    assert model.headerData(Column.CHAT, horizontal, Qt.ItemDataRole.ToolTipRole) is None
    align = model.headerData(Column.MESSAGES, horizontal, Qt.ItemDataRole.TextAlignmentRole)
    assert align == int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    assert model.headerData(Column.CHAT, horizontal, Qt.ItemDataRole.TextAlignmentRole) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(99, horizontal) is None
    assert model.headerData(-1, horizontal) is None


def test_cell_data(qapp: object) -> None:
    newest = NOW - timedelta(minutes=5)
    chat = row(
        7,
        "Example group",
        records=12_345,
        newest_date=newest,
        oldest_date=newest - timedelta(days=400),
        backfill=backfill(BackfillState.RETRYING, retry_at=NOW + timedelta(seconds=30)),
    )
    model = make_model()
    model.set_rows([chat])
    assert display(model, 0, Column.CHAT) == "Example group"
    assert display(model, 0, Column.STATUS) == "Live"
    assert display(model, 0, Column.HISTORY) == "Retrying"
    assert display(model, 0, Column.LAST_MESSAGE) == "5 min ago"
    assert display(model, 0, Column.MESSAGES) == "12,345"
    assert display(model, 0, Column.SPAN) == span_text(chat)
    tip = Qt.ItemDataRole.ToolTipRole
    assert display(model, 0, Column.CHAT, tip) == "Example group\n7"
    assert display(model, 0, Column.LAST_MESSAGE, tip) == last_message_tooltip(chat, NOW, "en")
    assert display(model, 0, Column.HISTORY, tip) == history_tooltip(chat, NOW, "en")
    assert display(model, 0, Column.STATUS, tip) is None
    right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    assert display(model, 0, Column.MESSAGES, Qt.ItemDataRole.TextAlignmentRole) == right
    assert display(model, 0, Column.CHAT, Qt.ItemDataRole.TextAlignmentRole) is None
    assert display(model, 0, Column.CHAT, Qt.ItemDataRole.AccessibleTextRole) == (
        "Example group: Retrying"
    )
    assert display(model, 0, Column.CHAT, Qt.ItemDataRole.DecorationRole) is None
    assert display(model, 0, Column.CHAT, ROW_ROLE) is chat
    assert display(model, 0, Column.CHAT, SORT_ROLE) == "example group"
    assert model.data(QModelIndex()) is None
    assert model.data(model.createIndex(3, 0)) is None


def test_absolute_time_display(qapp: object) -> None:
    moment = NOW - timedelta(minutes=5)
    model = make_model(absolute=True)
    model.set_rows([row(1, newest_date=moment)])
    assert display(model, 0, Column.LAST_MESSAGE) == moment.astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def test_freshness_uses_per_chat_thresholds(qapp: object) -> None:
    strict = FreshnessThresholds(10, 20, 30)
    model = ChatsTableModel(lambda: NOW, lambda cid: strict if cid == 1 else THRESHOLDS)
    first = row(1, newest_date=NOW - timedelta(seconds=40))
    second = row(2, newest_date=NOW - timedelta(seconds=40))
    assert model.freshness(first) is Freshness.DORMANT
    assert model.freshness(second) is Freshness.FRESH


@pytest.mark.parametrize(
    ("column", "low", "high"),
    [
        (Column.CHAT, row(title="alpha"), row(title="Beta")),
        (Column.STATUS, row(error="x"), row()),
        (Column.MESSAGES, row(records=1), row(records=9)),
        (Column.LAST_MESSAGE, row(newest_date=NOW), row(newest_date=NOW - timedelta(days=1))),
        (Column.LAST_MESSAGE, row(newest_date=NOW), row()),
        (Column.SPAN, row(oldest_date=NOW - timedelta(days=9)), row(oldest_date=NOW)),
        (Column.SPAN, row(oldest_date=NOW), row()),
        (
            Column.HISTORY,
            row(backfill=backfill(BackfillState.RUNNING, progress=0.9)),
            row(backfill=backfill(BackfillState.RUNNING, progress=0.1)),
        ),
        (
            Column.HISTORY,
            row(backfill=backfill(BackfillState.RUNNING)),
            row(backfill=backfill(BackfillState.DONE)),
        ),
    ],
)
def test_sort_values_order(column: Column, low: ChatRow, high: ChatRow) -> None:
    assert ChatsTableModel.sort_value(low, column) < ChatsTableModel.sort_value(high, column)  # type: ignore[operator]


def test_infinity_sorts_last() -> None:
    assert ChatsTableModel.sort_value(row(), Column.LAST_MESSAGE) == math.inf
    assert ChatsTableModel.sort_value(row(), Column.SPAN) == math.inf


def make_proxy(rows: list[ChatRow]) -> tuple[ChatsTableModel, ChatsFilterProxy]:
    model = make_model()
    model.set_rows(rows)
    return model, ChatsFilterProxy(model, lambda: NOW)


def titles(proxy: ChatsFilterProxy) -> list[object]:
    return [proxy.index(r, Column.CHAT).data() for r in range(proxy.rowCount())]


def test_proxy_query_and_mode(qapp: object) -> None:
    _, proxy = make_proxy(
        [
            row(101, "Alpha club"),
            row(202, "Beta Club", paused=True),
            row(303, "gamma", newest_date=NOW),
        ]
    )
    assert proxy.mode is FilterMode.ALL
    assert proxy.rowCount() == 3
    proxy.set_query("CLUB")
    assert sorted(str(title) for title in titles(proxy)) == ["Alpha club", "Beta Club"]
    proxy.set_query("club")
    proxy.set_query("303")
    assert titles(proxy) == ["gamma"]
    proxy.set_query("")
    proxy.set_mode(FilterMode.PAUSED)
    proxy.set_mode(FilterMode.PAUSED)
    assert proxy.mode is FilterMode.PAUSED
    assert titles(proxy) == ["Beta Club"]


def test_proxy_sorts_by_the_sort_role(qapp: object) -> None:
    _, proxy = make_proxy([row(1, "b"), row(2, "A"), row(3, "c")])
    proxy.sort(Column.CHAT, Qt.SortOrder.AscendingOrder)
    assert titles(proxy) == ["A", "b", "c"]
    proxy.sort(Column.CHAT, Qt.SortOrder.DescendingOrder)
    assert titles(proxy) == ["c", "b", "A"]


def test_proxy_refresh_time_only_matters_for_silence_modes(qapp: object) -> None:
    clock = {"now": NOW}
    model = make_model()
    model.set_rows([row(1, "x", newest_date=NOW)])
    proxy = ChatsFilterProxy(model, lambda: clock["now"])
    proxy.set_mode(FilterMode.SILENT_1H)
    assert proxy.rowCount() == 0
    clock["now"] = NOW + timedelta(hours=2)
    assert proxy.rowCount() == 0
    proxy.refresh_time()
    assert proxy.rowCount() == 1
    proxy.set_mode(FilterMode.ALL)
    proxy.refresh_time()
    assert proxy.rowCount() == 1


def test_proxy_over_a_foreign_model_accepts_everything(qapp: object) -> None:
    from PySide6.QtGui import QStandardItemModel

    proxy = ChatsFilterProxy(make_model(), lambda: NOW)
    foreign = QStandardItemModel()
    foreign.appendRow([])
    proxy.setSourceModel(foreign)
    assert proxy.filterAcceptsRow(0, QModelIndex())
