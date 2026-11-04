"""Cards over `config.toml`: declared as field specs, saved through `config_edit.update_config`.

A card shows the values of the loaded `Config`, enables Save only while something changed,
validates before writing and never shows raw error text: a rejected value becomes a translated
message, the detail goes to the log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QSpinBox, QWidget

from chatimport.config import Config, ConfigError
from chatimport.config_edit import ConfigValue, update_config
from chatimport.gui.i18n import tr
from chatimport.gui.pages.settings_form import (
    EDITOR_WIDTH,
    WIDE_EDITOR_WIDTH,
    FieldRow,
    SettingsCard,
    TimeEdit,
)
from chatimport.gui.strings import has_key
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.switch import Switch

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from PySide6.QtCore import SignalInstance

    from chatimport.gui.kit import UiKit

log = logging.getLogger(__name__)

MEDIA_TYPES: Final = ("photo", "voice", "video_note", "video", "audio", "document", "sticker")
MAX_INT: Final = 1_000_000

type Kind = Literal["int", "float", "bool", "time", "media_types"]
type Values = dict[tuple[str, str], ConfigValue]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    section: str
    key: str
    kind: Kind
    minimum: float = 0
    maximum: float = MAX_INT
    unit: str = ""
    wide: bool = False

    @property
    def text_key(self) -> str:
        return f"settings.f.{self.section}.{self.key}"


class Editor:
    """One input and the three things a card needs from it."""

    def __init__(
        self,
        widget: QWidget,
        read: Callable[[], ConfigValue],
        write: Callable[[Any], None],
        changed: SignalInstance,
    ) -> None:
        self.widget = widget
        self.read = read
        self.write = write
        self.changed = changed


class MediaTypesEdit(QWidget):
    changed = Signal()

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._boxes = {name: QCheckBox() for name in MEDIA_TYPES}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(kit.px(16))
        grid.setVerticalSpacing(kit.px(6))
        for index, box in enumerate(self._boxes.values()):
            box.toggled.connect(self.changed)
            grid.addWidget(box, index // 2, index % 2)
        self.retranslate()

    def retranslate(self) -> None:
        for name, box in self._boxes.items():
            box.setText(tr(f"settings.media_type.{name}"))

    def selected(self) -> list[str]:
        return [name for name, box in self._boxes.items() if box.isChecked()]

    def select(self, names: Sequence[str]) -> None:
        for name, box in self._boxes.items():
            box.setChecked(name in names)


def make_editor(kit: UiKit, spec: FieldSpec) -> Editor:
    if spec.kind == "bool":
        switch = Switch(kit)
        return Editor(switch, switch.isChecked, switch.setChecked, switch.toggled)
    if spec.kind == "int":
        spin = QSpinBox()
        spin.setRange(int(spec.minimum), int(spec.maximum))
        return Editor(spin, spin.value, spin.setValue, spin.valueChanged)
    if spec.kind == "float":
        decimal = QDoubleSpinBox()
        decimal.setRange(spec.minimum, spec.maximum)
        decimal.setDecimals(1)
        decimal.setSingleStep(0.5)
        return Editor(decimal, decimal.value, decimal.setValue, decimal.valueChanged)
    if spec.kind == "time":
        clock = TimeEdit(kit)
        return Editor(clock, lambda: clock.text, clock.set_text, clock.changed)
    types = MediaTypesEdit(kit)
    return Editor(types, types.selected, types.select, types.changed)


class ConfigCard(SettingsCard):
    """Fields of one or more `config.toml` sections with a Save button."""

    saved = Signal()

    def __init__(
        self,
        kit: UiKit,
        key: str,
        icon_name: str,
        specs: Sequence[FieldSpec],
        config_file: Path,
        *,
        validate: Callable[[Values], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(kit, key, icon_name, parent)
        self._specs = tuple(specs)
        self._config_file = config_file
        self._validate = validate
        self._baseline: Values = {}
        self._editors: dict[tuple[str, str], Editor] = {}
        self._rows: dict[tuple[str, str], FieldRow] = {}
        for spec in self._specs:
            editor = make_editor(kit, spec)
            editor.changed.connect(self._on_edited)
            width = (
                None
                if spec.kind == "media_types"
                else (WIDE_EDITOR_WIDTH if spec.wide else EDITOR_WIDTH)
            )
            row = FieldRow(kit, editor.widget, editor_width=width)
            self._editors[spec.section, spec.key] = editor
            self._rows[spec.section, spec.key] = row
            self.add_row(row)
        self._save = Button(kit, variant="primary", icon_name="check")
        self._save.clicked.connect(self.save)
        self.add_footer_button(self._save)
        bind_kit(kit, language=self.retranslate)
        self.retranslate()
        self._baseline = self._current()
        self._save.setEnabled(False)

    @property
    def dirty(self) -> bool:
        return self._current() != self._baseline

    def load(self, config: Config) -> None:
        """Show the values of `config` and treat them as the saved state."""
        for spec in self._specs:
            section: Any = getattr(config, spec.section)
            editor = self._editors[spec.section, spec.key]
            editor.widget.blockSignals(True)
            editor.write(getattr(section, spec.key))
            editor.widget.blockSignals(False)
        self._baseline = self._current()
        self._after_edit()

    def retranslate(self) -> None:
        self.set_texts(tr(f"settings.card.{self.key}.title"), tr(f"settings.card.{self.key}.lede"))
        for spec in self._specs:
            hint_key = f"{spec.text_key}.hint"
            self._rows[spec.section, spec.key].set_texts(
                tr(f"{spec.text_key}.label"), tr(hint_key) if has_key(hint_key) else ""
            )
            widget = self._editors[spec.section, spec.key].widget
            if spec.unit and isinstance(widget, QSpinBox | QDoubleSpinBox):
                widget.setSuffix(" " + tr(f"settings.unit.{spec.unit}"))
            if isinstance(widget, MediaTypesEdit):
                widget.retranslate()
        self._save.setText(tr("common.save"))

    def _current(self) -> Values:
        return {pair: editor.read() for pair, editor in self._editors.items()}

    def _on_edited(self, *_: object) -> None:
        self.clear_message()
        self._after_edit()

    def _after_edit(self) -> None:
        dirty = self.dirty
        self._save.setEnabled(dirty)
        self.set_status(tr("settings.unsaved") if dirty else "")

    def save(self) -> None:
        values = self._current()
        problem = self._validate(values) if self._validate is not None else None
        if problem is not None:
            self.show_message("danger", tr(problem))
            return
        changes: dict[str, dict[str, ConfigValue]] = {}
        for (section, key), value in values.items():
            if value != self._baseline.get((section, key)):
                changes.setdefault(section, {})[key] = value
        try:
            update_config(self._config_file, changes)
        except ConfigError:
            log.exception("settings card %s was rejected", self.key)
            self.show_message("danger", tr("settings.err.rejected"))
            return
        except OSError:
            log.exception("config.toml could not be written")
            self.show_message("danger", tr("settings.err.write"))
            return
        self._baseline = values
        self.show_message("success", tr("settings.saved"))
        self._after_edit()
        self.saved.emit()


def _order(values: Values) -> str | None:
    low, high = values[("disk", "low_watermark_gb")], values[("disk", "high_watermark_gb")]
    if isinstance(low, int) and isinstance(high, int) and high <= low:
        return "settings.err.disk_order"
    return None


COLLECTION: Final = (
    FieldSpec("live", "flush_every_messages", "int", 1, 1000, "messages"),
    FieldSpec("live", "flush_every_seconds", "int", 1, 3600, "seconds"),
    FieldSpec("live", "reconcile_every_minutes", "int", 1, 1440, "minutes"),
    FieldSpec("backfill", "batch_size", "int", 1, 1000, "messages"),
    FieldSpec("backfill", "pause_between_requests_sec", "float", 0.5, 60, "seconds"),
    FieldSpec("backfill", "pause_between_chats_sec", "int", 1, 3600, "seconds"),
)
RECHECK: Final = (
    FieldSpec("recheck", "enabled", "bool"),
    FieldSpec("recheck", "days", "int", 1, 365, "days"),
    FieldSpec("recheck", "daily_at", "time", wide=True),
)
DISK: Final = (
    FieldSpec("disk", "low_watermark_gb", "int", 1, 100_000, "gb"),
    FieldSpec("disk", "high_watermark_gb", "int", 2, 100_000, "gb"),
    FieldSpec("disk", "protect_recent_days", "int", 0, 3650, "days"),
)
MEDIA: Final = (
    FieldSpec("media", "enabled", "bool"),
    FieldSpec("media", "types", "media_types", wide=True),
    FieldSpec("media", "max_file_mb", "int", 1, 4096, "mb"),
)
PRIVACY: Final = (
    FieldSpec("output", "include_sender_names", "bool"),
    FieldSpec("output", "include_raw", "bool"),
)


def build_config_cards(kit: UiKit, config_file: Path) -> list[ConfigCard]:
    return [
        ConfigCard(kit, "collection", "download", COLLECTION, config_file),
        ConfigCard(kit, "recheck", "refresh", RECHECK, config_file),
        ConfigCard(kit, "disk", "disk", DISK, config_file, validate=_order),
        ConfigCard(kit, "media", "package", MEDIA, config_file),
        ConfigCard(kit, "privacy", "shield", PRIVACY, config_file),
    ]
