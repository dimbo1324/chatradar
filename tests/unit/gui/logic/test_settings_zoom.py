from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtWidgets import QWidget

from chatimport.gui import settings as settings_module
from chatimport.gui import zoom as zoom_module
from chatimport.gui.format import FreshnessThresholds
from chatimport.gui.settings import (
    SETTINGS_VERSION,
    GuiSettings,
    GuiSettingsStore,
    WindowGeometry,
    settings_from_json,
    system_language,
)
from chatimport.gui.tokens import ZOOM_MAX, ZOOM_MIN
from chatimport.gui.zoom import (
    ZoomManager,
    _CtrlWheelFilter,  # pyright: ignore[reportPrivateUsage]
    auto_factor_for_width,
    clamp_factor,
    install_zoom_inputs,
    round_factor,
    screen_auto_factor,
    step_from,
)

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QApplication


@pytest.mark.parametrize(
    ("name", "expected"),
    [("ru_RU", "ru"), ("Russian_Russia", "ru"), ("en_US", "en"), (None, "en")],
)
def test_system_language(monkeypatch: pytest.MonkeyPatch, name: str | None, expected: str) -> None:
    monkeypatch.setattr(settings_module.locale, "getlocale", lambda: (name, None))
    assert system_language() == expected


def test_defaults_and_thresholds_for() -> None:
    custom = FreshnessThresholds(1, 2, 3)
    settings = GuiSettings(language="en", freshness_per_chat={"7": custom})
    assert settings.thresholds_for(7) == custom
    assert settings.thresholds_for("7") == custom
    assert settings.thresholds_for(8) == settings.freshness


@pytest.mark.parametrize("raw", [None, [], "text", 5])
def test_non_object_json_gives_defaults(raw: Any) -> None:
    assert settings_from_json(raw) == GuiSettings()


def test_full_valid_json() -> None:
    raw = {
        "language": "ru",
        "theme": "dark",
        "zoom": 1.25,
        "sidebar_collapsed": True,
        "close_to_tray": False,
        "start_hidden": True,
        "last_page": "chats",
        "chats_absolute_time": True,
        "geometry": {"x": 1, "y": 2, "width": 800, "height": 600, "maximized": True},
        "freshness": {"fresh_below": 10, "recent_below": 20, "stale_below": 30},
        "freshness_per_chat": {"5": {"fresh_below": 1, "recent_below": 2, "stale_below": 3}},
    }
    settings = settings_from_json(raw)
    assert settings.language == "ru"
    assert settings.theme == "dark"
    assert settings.zoom == 1.25
    assert settings.sidebar_collapsed
    assert not settings.close_to_tray
    assert settings.start_hidden
    assert settings.last_page == "chats"
    assert settings.chats_absolute_time
    assert settings.geometry == WindowGeometry(1, 2, 800, 600, maximized=True)
    assert settings.freshness == FreshnessThresholds(10, 20, 30)
    assert settings.freshness_per_chat == {"5": FreshnessThresholds(1, 2, 3)}


def test_bad_fields_fall_back_to_defaults() -> None:
    defaults = GuiSettings()
    raw = {
        "language": "de",
        "theme": "blue",
        "zoom": "big",
        "last_page": 4,
        "geometry": "none",
        "freshness": {"fresh_below": 100, "recent_below": 50, "stale_below": 10},
        "freshness_per_chat": {"1": "bad", "2": {"fresh_below": True}},
    }
    settings = settings_from_json(raw)
    assert settings.language == defaults.language
    assert settings.theme == "system"
    assert settings.zoom is None
    assert settings.last_page == "overview"
    assert settings.geometry is None
    assert settings.freshness == defaults.freshness
    assert settings.freshness_per_chat == {"1": defaults.freshness, "2": defaults.freshness}
    assert settings.close_to_tray


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, None),
        ("1", None),
        (0.1, ZOOM_MIN),
        (9, ZOOM_MAX),
        (1, 1.0),
    ],
)
def test_zoom_field(raw: Any, expected: float | None) -> None:
    assert settings_from_json({"zoom": raw}).zoom == expected


@pytest.mark.parametrize(
    "geometry",
    [
        {"x": 1, "y": 2, "width": 800},
        {"x": "a", "y": 2, "width": 800, "height": 600},
        {"x": None, "y": 2, "width": 800, "height": 600},
        {"x": 1, "y": 2, "width": 199, "height": 600},
        {"x": 1, "y": 2, "width": 800, "height": 149},
    ],
)
def test_bad_geometry_is_dropped(geometry: dict[str, Any]) -> None:
    assert settings_from_json({"geometry": geometry}).geometry is None


def test_geometry_maximized_must_be_exactly_true() -> None:
    base = {"x": 0, "y": 0, "width": 300, "height": 300}
    assert settings_from_json({"geometry": {**base, "maximized": "yes"}}).geometry == (
        WindowGeometry(0, 0, 300, 300, maximized=False)
    )


def test_store_missing_and_broken_files_give_defaults(tmp_path: Path) -> None:
    assert GuiSettingsStore(tmp_path / "none.json").settings == GuiSettings(
        language=GuiSettings().language
    )
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert GuiSettingsStore(broken).settings.theme == "system"


def test_store_update_writes_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "gui.json"
    store = GuiSettingsStore(path)
    updated = store.update(theme="dark", zoom=1.5, geometry=WindowGeometry(1, 2, 640, 480))
    assert store.settings is updated
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["v"] == SETTINGS_VERSION
    assert payload["theme"] == "dark"
    again = GuiSettingsStore(path).settings
    assert again.theme == "dark"
    assert again.zoom == 1.5
    assert again.geometry == WindowGeometry(1, 2, 640, 480)


@pytest.mark.parametrize(
    ("factor", "expected"),
    [(1.234, 1.23), (0.994, 0.99), (2, 2.0)],
)
def test_round_factor(factor: float, expected: float) -> None:
    assert round_factor(factor) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (float("-inf"), 1.0),
        (0.1, ZOOM_MIN),
        (5, ZOOM_MAX),
        (1.234, 1.23),
    ],
)
def test_clamp_factor(factor: float, expected: float) -> None:
    assert clamp_factor(factor) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("factor", "direction", "expected"),
    [
        (1.0, 1, 1.05),
        (1.0, -1, 0.95),
        (0.87, 1, 0.9),
        (0.87, -1, 0.85),
        (ZOOM_MAX, 1, ZOOM_MAX),
        (ZOOM_MIN, -1, ZOOM_MIN),
        (1.2, 1, 1.25),
        (1.2, -1, 1.15),
    ],
)
def test_step_from(factor: float, direction: int, expected: float) -> None:
    assert step_from(factor, direction) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("width", "expected"),
    [(0, 1.0), (-5, 1.0), (1366, 0.7 + 0.15), (1920, 1.0), (3840, 1.5), (10_000, 1.5), (800, 0.85)],
)
def test_auto_factor_for_width(width: int, expected: float) -> None:
    assert auto_factor_for_width(width) == pytest.approx(expected, abs=0.011)


def test_screen_auto_factor_with_and_without_a_screen(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ZOOM_MIN <= screen_auto_factor() <= ZOOM_MAX
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: None))
    assert screen_auto_factor() == 1.0


def test_manager_auto_then_manual_then_reset(qapp: QApplication) -> None:
    manager = ZoomManager(None, 1.2)
    seen: list[float] = []
    manager.changed.connect(seen.append)
    assert manager.auto
    assert manager.stored is None
    assert manager.factor == pytest.approx(1.2)
    assert manager.percent == 120
    manager.zoom_in()
    assert not manager.auto
    assert manager.factor == pytest.approx(1.25)
    assert manager.stored == pytest.approx(1.25)
    manager.zoom_out()
    manager.zoom_out()
    manager.set_factor(1.25)
    manager.set_factor(1.25)
    manager.reset()
    manager.reset()
    assert manager.auto
    assert len(seen) == 5
    assert manager.scaled(10) == 12


def test_manager_defaults_and_stored_value(qapp: QApplication) -> None:
    assert ZoomManager().factor == 1.0
    manager = ZoomManager(1.3)
    assert not manager.auto
    assert manager.factor == pytest.approx(1.3)


def test_manager_limits(qapp: QApplication) -> None:
    top = ZoomManager(ZOOM_MAX)
    assert not top.can_zoom_in
    assert top.can_zoom_out
    bottom = ZoomManager(ZOOM_MIN)
    assert not bottom.can_zoom_out
    assert bottom.can_zoom_in
    top.zoom_in()
    assert top.factor == ZOOM_MAX


def wheel(delta: int, modifiers: Qt.KeyboardModifier) -> QWheelEvent:
    return QWheelEvent(
        QPointF(1, 1),
        QPointF(1, 1),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_wheel_filter(qapp: QApplication) -> None:
    host = QWidget()
    manager = ZoomManager(1.0)
    wheel_filter = _CtrlWheelFilter(manager, host)
    ctrl = Qt.KeyboardModifier.ControlModifier
    assert wheel_filter.eventFilter(host, wheel(120, ctrl))
    assert manager.factor == pytest.approx(1.05)
    assert wheel_filter.eventFilter(host, wheel(-120, ctrl))
    assert manager.factor == pytest.approx(1.0)
    assert wheel_filter.eventFilter(host, wheel(0, ctrl))
    assert manager.factor == pytest.approx(1.0)
    assert not wheel_filter.eventFilter(host, wheel(120, Qt.KeyboardModifier.NoModifier))
    assert not wheel_filter.eventFilter(host, QEvent(QEvent.Type.Wheel))
    assert not wheel_filter.eventFilter(host, QEvent(QEvent.Type.Show))
    host.deleteLater()


def test_install_zoom_inputs_binds_shortcuts(qapp: QApplication) -> None:
    window = QWidget()
    manager = ZoomManager(1.0)
    install_zoom_inputs(manager, window)
    from PySide6.QtGui import QShortcut

    shortcuts = {s.key().toString(): s for s in window.findChildren(QShortcut)}
    assert set(shortcuts) >= {"Ctrl+=", "Ctrl++", "Ctrl+-", "Ctrl+0"}
    shortcuts["Ctrl+="].activated.emit()
    assert manager.factor == pytest.approx(1.05)
    shortcuts["Ctrl+-"].activated.emit()
    shortcuts["Ctrl+0"].activated.emit()
    assert manager.auto
    window.deleteLater()
    qapp.processEvents()


def test_install_zoom_inputs_without_an_application(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(zoom_module.QGuiApplication, "instance", staticmethod(lambda: None))
    window = QWidget()
    install_zoom_inputs(ZoomManager(1.0), window)
    window.deleteLater()
