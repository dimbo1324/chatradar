"""The Appearance card: theme, language, zoom, tray behaviour and the freshness thresholds.

Everything here belongs to the window, not to the archive: changes apply at once and are kept
by `GuiSettingsStore`; nothing touches `config.toml` and no restart is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from chatimport.gui.format import DAY, FreshnessThresholds
from chatimport.gui.i18n import tr
from chatimport.gui.pages.settings_form import FieldRow, SettingsCard
from chatimport.gui.settings import THEME_PREFERENCES
from chatimport.gui.strings import LANGUAGES
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.segmented import Segmented, SegmentOption
from chatimport.gui.widgets.switch import Switch

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit

UNITS: Final = (("s", 1), ("min", 60), ("h", 3600), ("d", DAY))
THEME_ICONS: Final = {"light": "sun", "dark": "moon", "system": "monitor"}
THRESHOLD_KEYS: Final = ("fresh_below", "recent_below", "stale_below")
THRESHOLD_WIDTH: Final = 200
THEME_WIDTH: Final = 280


class ThresholdEdit(QWidget):
    """A whole number and a unit (seconds ... days) that together make a number of seconds."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spin = QSpinBox()
        self.spin.setRange(1, 99_999)
        self.unit = QComboBox()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(kit.px(SPACE[3]))
        row.addWidget(self.spin, 1)
        row.addWidget(self.unit, 1)
        self._fill_units()

    def _fill_units(self) -> None:
        index = self.unit.currentIndex()
        self.unit.blockSignals(True)
        self.unit.clear()
        for name, _ in UNITS:
            self.unit.addItem(tr(f"settings.unit.{name}"), name)
        self.unit.setCurrentIndex(max(index, 0))
        self.unit.blockSignals(False)

    def retranslate(self) -> None:
        self._fill_units()

    def seconds(self) -> int:
        return self.spin.value() * UNITS[self.unit.currentIndex()][1]

    def set_seconds(self, seconds: int) -> None:
        index = 0
        for position, (_, size) in enumerate(UNITS):
            if seconds >= size and seconds % size == 0:
                index = position
        self.spin.blockSignals(True)
        self.unit.blockSignals(True)
        self.unit.setCurrentIndex(index)
        self.spin.setValue(max(seconds // UNITS[index][1], 1))
        self.spin.blockSignals(False)
        self.unit.blockSignals(False)


class AppearanceCard(SettingsCard):
    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(gui.kit, "appearance", "sliders", parent)
        self.gui = gui
        kit = gui.kit
        self._theme = Segmented(kit, self._theme_options(), kit.theme.preference, compact=True)
        self._theme.selected.connect(self._pick_theme)
        self._language = Segmented(
            kit, self._language_options(), kit.language.current, compact=True
        )
        self._language.selected.connect(self._pick_language)

        self._zoom_out = IconButton(kit, "minus", "", size="sm")
        self._zoom_in = IconButton(kit, "plus", "", size="sm")
        self._zoom_auto = Button(kit, variant="ghost", size="sm")
        self._zoom_text = QLabel()
        self._zoom_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_out.clicked.connect(kit.zoom.zoom_out)
        self._zoom_in.clicked.connect(kit.zoom.zoom_in)
        self._zoom_auto.clicked.connect(kit.zoom.reset)
        zoom_box = QWidget()
        zoom_row = QHBoxLayout(zoom_box)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(kit.px(SPACE[3]))
        for part in (self._zoom_out, self._zoom_text, self._zoom_in, self._zoom_auto):
            zoom_row.addWidget(part)
        zoom_row.setStretch(1, 1)

        store = gui.settings
        self._tray = Switch(kit, checked=store.settings.close_to_tray)
        self._tray.toggled.connect(self._set_close_to_tray)
        self._hidden = Switch(kit, checked=store.settings.start_hidden)
        self._hidden.toggled.connect(self._set_start_hidden)

        self._rows = {
            "theme": FieldRow(kit, self._theme, editor_width=THEME_WIDTH),
            "language": FieldRow(kit, self._language, editor_width=THEME_WIDTH),
            "zoom": FieldRow(kit, zoom_box, editor_width=THEME_WIDTH),
            "tray": FieldRow(kit, self._tray, editor_width=None),
            "hidden": FieldRow(kit, self._hidden, editor_width=None),
        }
        for row in self._rows.values():
            self.add_row(row)

        self._edits = {key: ThresholdEdit(kit) for key in THRESHOLD_KEYS}
        self._threshold_rows = {
            key: FieldRow(kit, edit, editor_width=THRESHOLD_WIDTH)
            for key, edit in self._edits.items()
        }
        self._threshold_title = QLabel()
        self._threshold_title.setProperty("role", "section")
        self._reset = Button(kit, variant="ghost", size="sm", icon_name="refresh")
        self._reset.clicked.connect(self._reset_thresholds)
        self.add_plain(self._threshold_title)
        for row in self._threshold_rows.values():
            self.add_plain(row)
        self.add_footer_button(self._reset)
        for edit in self._edits.values():
            edit.spin.valueChanged.connect(self._apply_thresholds)
            edit.unit.currentIndexChanged.connect(self._apply_thresholds)

        bind_kit(kit, language=self.retranslate, zoom=self._show_zoom)
        self.retranslate()
        self._load_thresholds(store.settings.freshness)

    def _pick_theme(self, value: str) -> None:
        if value in THEME_PREFERENCES:
            self.gui.kit.theme.set_preference(value)

    def _pick_language(self, value: str) -> None:
        if value in LANGUAGES:
            self.gui.kit.language.set_language(value)

    def _set_close_to_tray(self, enabled: bool) -> None:
        self.gui.settings.update(close_to_tray=enabled)

    def _set_start_hidden(self, enabled: bool) -> None:
        self.gui.settings.update(start_hidden=enabled)

    def _theme_options(self) -> list[SegmentOption]:
        return [
            SegmentOption(name, tr(f"theme.{name}"), icon=THEME_ICONS[name])
            for name in THEME_PREFERENCES
        ]

    def _language_options(self) -> list[SegmentOption]:
        return [SegmentOption(name, tr(f"language.{name}")) for name in LANGUAGES]

    def retranslate(self) -> None:
        kit = self.gui.kit
        self.set_texts(tr("settings.card.appearance.title"), tr("settings.card.appearance.lede"))
        self._theme.set_options(self._theme_options(), kit.theme.preference)
        self._language.set_options(self._language_options(), kit.language.current)
        for name, row in self._rows.items():
            row.set_texts(tr(f"settings.appearance.{name}"), tr(f"settings.appearance.{name}_hint"))
        self._zoom_out.set_tooltip(tr("settings.appearance.zoom_out"))
        self._zoom_in.set_tooltip(tr("settings.appearance.zoom_in"))
        self._zoom_auto.setText(tr("settings.appearance.zoom_auto"))
        self._threshold_title.setText(tr("settings.appearance.thresholds"))
        for key, row in self._threshold_rows.items():
            row.set_texts(tr(f"settings.appearance.{key}"), tr(f"settings.appearance.{key}_hint"))
        for edit in self._edits.values():
            edit.retranslate()
        self._reset.setText(tr("settings.appearance.thresholds_reset"))
        self._show_zoom()

    def _show_zoom(self, *_: object) -> None:
        zoom = self.gui.kit.zoom
        suffix = f" ({tr('settings.appearance.zoom_auto_tag')})" if zoom.auto else ""
        self._zoom_text.setText(f"{zoom.percent} %{suffix}")
        self._zoom_out.setEnabled(zoom.can_zoom_out)
        self._zoom_in.setEnabled(zoom.can_zoom_in)

    def _load_thresholds(self, thresholds: FreshnessThresholds) -> None:
        for key, edit in self._edits.items():
            edit.set_seconds(getattr(thresholds, key))

    def _apply_thresholds(self, *_: object) -> None:
        candidate = FreshnessThresholds(
            **{key: edit.seconds() for key, edit in self._edits.items()}
        )
        if not candidate.is_ordered():
            self.show_message("warning", tr("settings.appearance.thresholds_order"))
            return
        self.clear_message()
        if candidate != self.gui.settings.settings.freshness:
            self.gui.settings.update(freshness=candidate)

    def _reset_thresholds(self) -> None:
        defaults = FreshnessThresholds()
        self._load_thresholds(defaults)
        self.clear_message()
        self.gui.settings.update(freshness=defaults)
