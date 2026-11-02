from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPalette

from chatimport.gui import icons, style_assets
from chatimport.gui.format import Freshness
from chatimport.gui.icons import ICON_PATHS, icon, icon_pixmap
from chatimport.gui.kit import build_kit
from chatimport.gui.stylesheet import TONES, build_stylesheet, tone_colors
from chatimport.gui.theme import ThemeManager, freshness_color, qt_palette, system_theme
from chatimport.gui.tokens import DARK, LIGHT, PALETTES, SPACE
from chatimport.gui.zoom import ZoomManager

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from chatimport.gui.settings import GuiSettingsStore
    from tests.unit.gui.conftest import FakeBridge


@pytest.fixture(autouse=True)
def isolated_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def cache_dir(_name: str) -> str:
        return str(tmp_path)

    monkeypatch.setattr(style_assets, "user_cache_dir", cache_dir)
    style_assets.asset_url.cache_clear()
    yield
    style_assets.asset_url.cache_clear()


def test_palettes_are_complete_and_distinct() -> None:
    assert PALETTES == {"light": LIGHT, "dark": DARK}
    assert LIGHT.colors().keys() == DARK.colors().keys()
    assert "name" not in LIGHT.colors()
    for colors in (LIGHT.colors(), DARK.colors()):
        assert all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in colors.values())
    assert LIGHT.canvas != DARK.canvas
    assert sorted(SPACE) == list(range(1, 12))


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=lambda p: p.name)
@pytest.mark.parametrize("scale", [0.7, 1.0, 2.0])
def test_stylesheet_resolves_every_placeholder(palette: object, scale: float) -> None:
    sheet = build_stylesheet(palette, scale)  # type: ignore[arg-type]
    assert not re.search(r"@[a-z0-9_]+", sheet)
    assert palette.canvas in sheet  # type: ignore[attr-defined]
    for tone in TONES:
        assert f'tone="{tone}"' in sheet


def test_stylesheet_scales_pixels_and_floors_at_one() -> None:
    assert "min-height: 1px" in build_stylesheet(LIGHT, 0.01)
    assert build_stylesheet(LIGHT, 2.0) != build_stylesheet(LIGHT, 1.0)
    assert build_stylesheet(LIGHT) == build_stylesheet(LIGHT, 1.0)


def test_tone_colors_cover_every_tone() -> None:
    for tone in TONES:
        background, border, foreground = tone_colors(DARK, tone)
        assert background.startswith("#")
        assert border.startswith("#")
        assert foreground.startswith("#")
    assert tone_colors(LIGHT, "danger") == (
        LIGHT.danger_soft,
        LIGHT.danger_soft_border,
        LIGHT.danger,
    )
    with pytest.raises(KeyError):
        tone_colors(LIGHT, "nope")


def test_asset_url_writes_once_and_reuses(tmp_path: Path) -> None:
    first = style_assets.asset_url("check", "#ffffff")
    target = tmp_path / "gui-icons" / "check-ffffff.svg"
    assert first == f"url({target.as_posix()})"
    assert "<path" in target.read_text(encoding="utf-8")
    target.write_text("kept", encoding="utf-8")
    style_assets.asset_url.cache_clear()
    assert style_assets.asset_url("check", "#ffffff") == first
    assert target.read_text(encoding="utf-8") == "kept"


def test_asset_url_zero_weight_uses_the_default(tmp_path: Path) -> None:
    style_assets.asset_url("check", "#000000", 0)
    text = (tmp_path / "gui-icons" / "check-000000.svg").read_text(encoding="utf-8")
    assert f'stroke-width="{icons.DEFAULT_WEIGHT}"' in text


def test_asset_url_falls_back_when_the_folder_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, not a folder", encoding="utf-8")
    monkeypatch.setattr(style_assets, "_folder", lambda: blocker / "inside")
    assert style_assets.asset_url("check", "#123456") == "none"


def test_every_icon_renders(qapp: QApplication) -> None:
    for name in ICON_PATHS:
        pixmap = icon_pixmap(name, "#336699", 12)
        assert not pixmap.isNull()
        assert pixmap.devicePixelRatio() >= 2


def test_icon_modes_and_size_floor(qapp: QApplication) -> None:
    plain = icon("home", "#111111")
    assert not plain.pixmap(16, QIcon.Mode.Normal).isNull()
    full = icon("home", "#111111", 20, disabled_color="#999999", active_color="#0000ff")
    assert not full.pixmap(20, QIcon.Mode.Disabled).isNull()
    assert not full.pixmap(20, QIcon.Mode.Active).isNull()
    assert icon_pixmap("home", "#111111", 0).width() > 0
    assert icon_pixmap("home", "#111111", 16) is icon_pixmap("home", "#111111", 16)


def test_pixel_density_without_a_screen(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert icons._pixel_density() >= 2  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: None))
    assert icons._pixel_density() == 2  # pyright: ignore[reportPrivateUsage]


def test_freshness_color_per_level() -> None:
    assert freshness_color(LIGHT, Freshness.FRESH) == LIGHT.live
    assert freshness_color(LIGHT, Freshness.RECENT) == LIGHT.fg_secondary
    assert freshness_color(LIGHT, Freshness.STALE) == LIGHT.warning
    assert freshness_color(LIGHT, Freshness.DORMANT) == LIGHT.fg_faint
    assert freshness_color(LIGHT, Freshness.UNKNOWN) == LIGHT.fg_faint


def test_qt_palette_maps_roles(qapp: QApplication) -> None:
    palette = qt_palette(DARK)
    assert palette.color(QPalette.ColorRole.Window).name() == DARK.canvas
    assert palette.color(QPalette.ColorRole.Highlight).name() == DARK.selection
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert disabled.name() == DARK.fg_faint


def test_system_theme_follows_the_style_hints(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert system_theme() in ("light", "dark")
    hints = QGuiApplication.styleHints()

    def dark(_self: object) -> Qt.ColorScheme:
        return Qt.ColorScheme.Dark

    def light(_self: object) -> Qt.ColorScheme:
        return Qt.ColorScheme.Light

    monkeypatch.setattr(type(hints), "colorScheme", dark)
    assert system_theme() == "dark"
    monkeypatch.setattr(type(hints), "colorScheme", light)
    assert system_theme() == "light"


def test_theme_without_an_application(qapp: QApplication) -> None:
    zoom = ZoomManager(1.0)
    seen: list[bool] = []
    manager = ThemeManager(zoom, "system", detect_system=lambda: "dark")
    manager.changed.connect(lambda: seen.append(True))
    assert manager.resolved == "dark"
    assert manager.is_dark
    assert manager.preference == "system"
    manager.set_preference("system")
    assert seen == []
    manager.set_preference("light")
    assert manager.resolved == "light"
    assert manager.palette is LIGHT
    assert not manager.is_dark
    manager.set_preference("dark")
    assert manager.palette is DARK
    assert seen == [True, True]
    zoom.zoom_in()
    assert manager.stylesheet() == build_stylesheet(DARK, zoom.factor)


def test_theme_with_an_application_applies_and_follows_the_system(
    qapp: QApplication,
) -> None:
    original_sheet = qapp.styleSheet()
    original_palette = qapp.palette()
    scheme = {"value": "light"}
    zoom = ZoomManager(1.0)
    manager = ThemeManager(
        zoom,
        "system",
        app=qapp,
        detect_system=lambda: scheme["value"],  # type: ignore[arg-type,return-value]
    )
    try:
        seen: list[bool] = []
        manager.changed.connect(lambda: seen.append(True))
        assert qapp.styleSheet() == build_stylesheet(LIGHT, 1.0)
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == LIGHT.canvas
        scheme["value"] = "dark"
        manager._on_system_changed(Qt.ColorScheme.Dark)  # pyright: ignore[reportPrivateUsage]
        assert manager.resolved == "dark"
        assert qapp.styleSheet() == build_stylesheet(DARK, 1.0)
        manager._on_system_changed(Qt.ColorScheme.Dark)  # pyright: ignore[reportPrivateUsage]
        assert seen == [True]
        zoom.zoom_in()
        assert qapp.styleSheet() == build_stylesheet(DARK, zoom.factor)
        manager.set_preference("light")
        manager._on_system_changed(Qt.ColorScheme.Light)  # pyright: ignore[reportPrivateUsage]
        assert manager.resolved == "light"
    finally:
        zoom.changed.disconnect(manager._on_zoom)  # pyright: ignore[reportPrivateUsage]
        qapp.setStyleSheet(original_sheet)
        qapp.setPalette(original_palette)


def test_build_kit_wires_persistence(qapp: QApplication, store: GuiSettingsStore) -> None:
    kit = build_kit(store, qapp)
    try:
        kit.zoom.set_factor(1.4)
        assert store.settings.zoom == pytest.approx(1.4)
        kit.theme.set_preference("dark")
        assert store.settings.theme == "dark"
        kit.language.set_language("ru")
        assert store.settings.language == "ru"
        assert kit.palette is DARK
        assert kit.px(10) == 14
    finally:
        kit.language.set_language("en")
        kit.zoom.changed.disconnect()


def test_build_kit_without_an_application(store: GuiSettingsStore) -> None:
    kit = build_kit(store, None)
    assert kit.zoom.factor == 1.0
    assert kit.zoom.auto
    kit.language.set_language("en")


def test_context_current_prefers_the_live_service_context(
    gui: GuiContext, bridge: FakeBridge
) -> None:
    assert gui.current is gui.service
    live = object()
    bridge.context = live  # type: ignore[attr-defined]
    assert gui.current is live
    bridge.context = None  # type: ignore[attr-defined]
    assert gui.current is gui.service


def test_context_kit_bundles_the_managers(gui: GuiContext, kit: UiKit) -> None:
    built = gui.kit
    assert built.theme is gui.theme
    assert built.language is gui.language
    assert built.zoom is gui.zoom
