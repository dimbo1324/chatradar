"""The Combined file card: one file with every chat, kept current in the background."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout

from chatimport.config import Config, ConfigError, MergedConfig, load_config
from chatimport.config_edit import update_config
from chatimport.gui.format import format_ago, format_bytes, format_count, format_exact
from chatimport.gui.i18n import tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.locales import data_merged as _merged_strings
from chatimport.gui.pages.data_common import FieldRow, toolbar
from chatimport.gui.pages.data_section import Section
from chatimport.gui.strings import current_language, translate_plural
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.labels import ElidedLabel, make_label
from chatimport.gui.widgets.segmented import Segmented, SegmentOption
from chatimport.gui.widgets.switch import SwitchRow
from chatimport.merged_export import last_result, merged_path
from chatimport.records import format_dt

if TYPE_CHECKING:
    from concurrent.futures import Future
    from pathlib import Path

    from PySide6.QtWidgets import QWidget

    from chatimport.commands import CommandResult
    from chatimport.gui.pages.data_common import DataEnv
    from chatimport.merged_export import MergedResult

_ = (_data_strings, _merged_strings)
log = logging.getLogger(__name__)


class MergedCard(Section):
    def __init__(self, env: DataEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, "merged", "file", parent=parent)
        kit = self.kit
        self._busy = False
        self._translated = False
        self._loading = False
        self._building_remotely = False
        self._result: MergedResult | None = None
        self._config = MergedConfig()
        self.enabled = SwitchRow(kit, "", "", checked=False)
        self.format = Segmented(kit, self._format_options(), "json", compact=True)
        self.names = SwitchRow(kit, "", "", checked=False)
        self.names_warning = Callout(kit, "warning", "")
        self.names_warning.hide()
        self._state_caption = make_label("", "caption")
        self.state_label = make_label("", "body")
        self._last_caption = make_label("", "caption")
        self.last_label = make_label("", "body")
        self._size_caption = make_label("", "caption")
        self.size_label = make_label("", "body")
        self._path_caption = make_label("", "caption")
        self.path_label = ElidedLabel("", "mono")
        self.copy_button = IconButton(kit, "copy", "", variant="secondary")
        self.show_button = IconButton(kit, "folder-open", "", variant="secondary")
        self.build_button = Button(kit, "", variant="primary", icon_name="refresh")
        self._path_box = QFrame()
        set_role(self._path_box, "surface-sunken")
        self._path_row = QHBoxLayout(self._path_box)
        self._path_row.setSpacing(kit.px(SPACE[3]))
        self._path_row.addWidget(self.path_label, 1)
        self._path_row.addWidget(self.copy_button)
        self._path_row.addWidget(self.show_button)
        footer = toolbar(kit)
        footer.addStretch(1)
        footer.addWidget(self.build_button)
        self._format_field = FieldRow(kit, "", self.format)
        format_row = toolbar(kit)
        format_row.addWidget(self._format_field)
        format_row.addStretch(1)
        self.content.addWidget(self.enabled)
        self.content.addLayout(format_row)
        self.content.addWidget(self.names)
        self.content.addWidget(self.names_warning)
        for caption, value in (
            (self._state_caption, self.state_label),
            (self._last_caption, self.last_label),
            (self._size_caption, self.size_label),
        ):
            self.content.addWidget(caption)
            self.content.addWidget(value)
        self.content.addWidget(self._path_caption)
        self.content.addWidget(self._path_box)
        self.content.addLayout(footer)
        self.enabled.toggled.connect(self._save)
        self.format.selected.connect(self._save)
        self.names.toggled.connect(self._on_names)
        self.copy_button.clicked.connect(self._copy)
        self.show_button.clicked.connect(self._show)
        self.build_button.clicked.connect(self.build)
        env.root_changed.connect(self.refresh)
        env.gui.bridge.snapshot.connect(self._on_snapshot)
        bind_kit(kit, zoom=self._apply_sizes)
        self._apply_sizes()
        self.retranslate()
        self.refresh()

    def _apply_sizes(self) -> None:
        px = self.kit.px
        pad = px(SPACE[4])
        self._path_row.setContentsMargins(pad, px(SPACE[2]), px(SPACE[2]), px(SPACE[2]))

    def _format_options(self) -> list[SegmentOption]:
        return [
            SegmentOption("json", tr("data.merged.format.json"), tooltip=self._tip("json")),
            SegmentOption("jsonl", tr("data.merged.format.jsonl"), tooltip=self._tip("jsonl")),
        ]

    @staticmethod
    def _tip(name: str) -> str:
        return tr(f"data.merged.format.{name}_tip")

    def retranslate(self) -> None:
        self.enabled.set_texts(tr("data.merged.enabled"), tr("data.merged.enabled_hint"))
        self._format_field.set_caption(tr("data.merged.format"))
        if self._translated:
            self.format.set_options(self._format_options())
        self._translated = True
        self.names.set_texts(tr("data.merged.names"), tr("data.merged.names_hint"))
        self.names_warning.set_body(tr("data.merged.names_warning"))
        self._state_caption.setText(tr("data.merged.state"))
        self._last_caption.setText(tr("data.merged.last"))
        self._size_caption.setText(tr("data.merged.size"))
        self._path_caption.setText(tr("data.merged.path"))
        self.copy_button.set_tooltip(tr("data.merged.copy"))
        self.show_button.set_tooltip(tr("data.merged.show"))
        self._set_busy(self._busy)
        self._render()

    @property
    def config_file(self) -> Path:
        return self.env.gui.current.paths.config_file

    def _load_config(self) -> MergedConfig:
        try:
            return load_config(self.config_file).merged
        except ConfigError:
            log.warning("config.toml is invalid; the combined file card shows defaults")
            return Config().merged

    def refresh(self) -> None:
        """Re-read the saved settings and the last build from disk."""
        self._config = self._load_config()
        self._result = last_result(self.env.root)
        self._loading = True
        self.enabled.set_checked(self._config.enabled)
        self.format.set_value(self._config.format)
        self.names.set_checked(self._config.include_names)
        self._loading = False
        self.names_warning.setVisible(self._config.include_names)
        self._render()

    def _render(self) -> None:
        language = current_language()
        if self._busy or self._building_remotely:
            state = "building"
        else:
            state = "on" if self._config.enabled else "off"
        self.state_label.setText(tr(f"data.merged.state.{state}"))
        result = self._result
        if result is None:
            self.last_label.setText(tr("data.merged.last.never"))
            self.last_label.setToolTip("")
            self.size_label.setText("-")
            target = merged_path(self.env.root, self._config.format)
        else:
            moment = format_exact(result.built_at)
            age = max((datetime.now(UTC) - result.built_at).total_seconds(), 0.0)
            self.last_label.setText(
                tr("data.merged.last.value", moment=moment, ago=format_ago(age, language))
            )
            self.last_label.setToolTip(moment)
            self.size_label.setText(
                tr(
                    "data.merged.size.value",
                    records=translate_plural(
                        language,
                        result.records,
                        "data.merged.records",
                        n=format_count(result.records, language),
                    ),
                    size=format_bytes(result.bytes, language),
                )
            )
            target = result.path
        self.path_label.setText(str(target))
        self.path_label.setToolTip(str(target))
        has_file = result is not None
        self.copy_button.setEnabled(has_file)
        self.show_button.setEnabled(has_file)

    def _on_names(self, checked: bool) -> None:
        self.names_warning.setVisible(checked)
        self._save()

    def _save(self, *_: object) -> None:
        if self._loading:
            return
        changes = {
            "merged": {
                "enabled": self.enabled.is_checked(),
                "format": self.format.value,
                "include_names": self.names.is_checked(),
            }
        }
        try:
            update_config(self.config_file, changes)
        except ConfigError, OSError:
            log.exception("config.toml could not be updated for the combined file")
            self.env.toast("danger", tr("data.merged.save_failed"))
            self.refresh()
            return
        self._config = self._load_config()
        self._render()
        future = self.env.gui.bridge.execute("reload_config")
        self.env.runner.watch(future, self._reloaded)

    def _reloaded(self, done: Future[CommandResult]) -> None:
        ok = done.exception() is None and done.result().ok
        self.env.toast(
            "success" if ok else "info",
            tr("data.merged.saved" if ok else "data.merged.saved_later"),
        )

    def _on_snapshot(self, snapshot: dict[str, Any]) -> None:
        merged: dict[str, Any] = snapshot.get("merged") or {}
        building = bool(merged.get("building"))
        built = merged.get("last_built_at")
        known = format_dt(self._result.built_at) if self._result is not None else None
        self._building_remotely = building
        if built is not None and built != known and not self._busy:
            self._result = last_result(self.env.root)
        self._render()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.set_busy(busy)
        self.build_button.setText(tr("data.merged.building" if busy else "data.merged.build"))
        self.build_button.setEnabled(not busy)

    def build(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._render()
        args = {"format": self.format.value, "names": self.names.is_checked()}
        future = self.env.gui.bridge.execute("export_all", args)
        self.env.runner.watch(future, self._built)

    def _built(self, done: Future[CommandResult]) -> None:
        self._set_busy(False)
        self._result = last_result(self.env.root)
        self._render()
        if done.exception() is not None:
            self.env.unavailable()
            return
        result = done.result()
        if not result.ok:
            self.env.toast("danger", tr("data.merged.toast.failed"))
            return
        records = int(result.data.get("records", 0))
        language = current_language()
        phrase = translate_plural(
            language, records, "data.merged.records", n=format_count(records, language)
        )
        self.env.toast("success", tr("data.merged.toast.ok", records=phrase))

    def _copy(self) -> None:
        if self._result is not None:
            QGuiApplication.clipboard().setText(str(self._result.path))
            self.env.toast("info", tr("data.merged.copied"))

    def _show(self) -> None:
        if self._result is not None:
            self.env.open_folder(self._result.path.parent)
