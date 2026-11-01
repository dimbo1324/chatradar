"""The Startup card (Windows autostart) and the About card (version and file locations)."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Final

from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from chatimport import __version__, autostart
from chatimport.gui.i18n import tr
from chatimport.gui.pages.settings_form import FieldRow, SettingsCard
from chatimport.gui.pages.settings_support import SettingsHooks, context_of, open_path
from chatimport.gui.pages.support import MainThreadRunner
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import ElidedLabel, make_label
from chatimport.gui.widgets.switch import Switch

if TYPE_CHECKING:
    from concurrent.futures import Future
    from pathlib import Path

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit

log = logging.getLogger(__name__)

WINDOWS: Final = sys.platform == "win32"


class StartupCard(SettingsCard):
    """ "Start with Windows", bound to the Task Scheduler task through `autostart`."""

    def __init__(
        self, gui: GuiContext, hooks: SettingsHooks, parent: QWidget | None = None
    ) -> None:
        super().__init__(gui.kit, "startup", "play", parent)
        self.gui = gui
        self._hooks = hooks
        self._runner = MainThreadRunner(self)
        self._status: autostart.AutostartStatus | None = None
        self._busy = False
        kit = gui.kit
        self._switch = Switch(kit)
        self._switch.toggled.connect(self._on_toggled)
        self._row = FieldRow(kit, self._switch, editor_width=None)
        self._chip = Chip(kit, "", "muted")
        self._update = Button(kit, variant="secondary", size="sm", icon_name="refresh")
        self._update.clicked.connect(lambda: self._apply(True))
        state_box = QWidget()
        state_row = QHBoxLayout(state_box)
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.setSpacing(kit.px(SPACE[4]))
        state_row.addWidget(self._chip)
        state_row.addWidget(self._update)
        state_row.addStretch(1)
        self.add_row(self._row)
        self.add_plain(state_box)
        bind_kit(kit, language=self.retranslate)
        self.retranslate()
        if not autostart.supported():
            self._switch.setEnabled(False)
            self._render()

    def retranslate(self) -> None:
        self.set_texts(tr("settings.card.startup.title"), tr("settings.card.startup.lede"))
        self._row.set_texts(tr("settings.startup.switch"), tr("settings.startup.switch_hint"))
        self._update.setText(tr("settings.startup.update"))
        self._render()

    def refresh(self) -> None:
        """Ask Task Scheduler for the current state (on a worker thread)."""
        if not autostart.supported() or self._busy:
            return
        self._busy = True
        task, executable = self._hooks.autostart_task, self._hooks.executable
        self._runner.submit(lambda: autostart.status(task, executable=executable), self._done)

    def _on_toggled(self, enabled: bool) -> None:
        self._apply(enabled)

    def _apply(self, enabled: bool) -> None:
        if self._busy:
            return
        self._busy = True
        self.clear_message()
        self._switch.setEnabled(False)
        task, executable = self._hooks.autostart_task, self._hooks.executable
        if enabled:
            self._runner.submit(lambda: autostart.enable(task, executable=executable), self._done)
        else:
            self._runner.submit(lambda: autostart.disable(task), self._done)

    def _done(self, done: Future[autostart.AutostartStatus]) -> None:
        self._busy = False
        try:
            self._status = done.result()
        except autostart.AutostartError as error:
            log.warning("autostart failed: %s", error.reason)
            self.show_message("danger", tr(f"settings.startup.err.{error.reason}"))
        except Exception:
            log.exception("autostart failed")
            self.show_message("danger", tr("settings.startup.err.failed"))
        self._render()

    def _render(self) -> None:
        status = self._status
        supported = autostart.supported()
        state = status.state if status is not None else None
        enabled = state in (autostart.AutostartState.ENABLED,)
        self._switch.blockSignals(True)
        self._switch.setChecked(enabled)
        self._switch.blockSignals(False)
        self._switch.setEnabled(supported and not self._busy)
        stale = status is not None and enabled and not status.current
        self._update.setVisible(stale)
        if not supported:
            self._chip.set_text(tr("settings.startup.state.unsupported"))
            self._chip.set_tone("muted")
        elif self._busy and status is None:
            self._chip.set_text(tr("settings.startup.state.checking"))
            self._chip.set_tone("info")
        elif stale:
            self._chip.set_text(tr("settings.startup.state.other"))
            self._chip.set_tone("warning")
        elif enabled:
            self._chip.set_text(tr("settings.startup.state.enabled"))
            self._chip.set_tone("live")
        else:
            self._chip.set_text(tr("settings.startup.state.disabled"))
            self._chip.set_tone("muted")


class PathRow(QWidget):
    """A caption over a monospace path with copy and open buttons."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self._path: Path | None = None
        self._caption = make_label("", "caption")
        self._value = ElidedLabel("", "mono")
        self._copy = IconButton(kit, "copy", "", size="sm")
        self._open = IconButton(kit, "folder-open", "", size="sm")
        self._copy.clicked.connect(self._copy_path)
        self._open.clicked.connect(self._open_path)
        line = QHBoxLayout()
        line.setSpacing(kit.px(SPACE[3]))
        line.addWidget(self._value, 1)
        line.addWidget(self._copy)
        line.addWidget(self._open)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(kit.px(SPACE[1]))
        column.addWidget(self._caption)
        column.addLayout(line)

    def set_path(self, caption: str, path: Path) -> None:
        self._path = path
        self._caption.setText(caption)
        self._value.setText(str(path))
        self._copy.set_tooltip(tr("common.copy"))
        self._open.set_tooltip(tr("settings.about.open"))

    def _copy_path(self) -> None:
        if self._path is not None:
            QApplication.clipboard().setText(str(self._path))

    def _open_path(self) -> None:
        if self._path is not None:
            open_path(self._path)


class AboutCard(SettingsCard):
    def __init__(
        self, gui: GuiContext, hooks: SettingsHooks, parent: QWidget | None = None
    ) -> None:
        super().__init__(gui.kit, "about", "info", parent)
        self.gui = gui
        self._hooks = hooks
        self._version = make_label("", "secondary")
        self._rows = {name: PathRow(gui.kit) for name in ("data", "config", "library", "logs")}
        self.add_plain(self._version)
        for row in self._rows.values():
            self.add_plain(row)
        bind_kit(gui.kit, language=self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        ctx = context_of(self.gui, self._hooks)
        self.set_texts(tr("settings.card.about.title"), tr("settings.card.about.lede"))
        self._version.setText(tr("settings.about.version", version=__version__))
        paths = {
            "data": ctx.root,
            "config": ctx.paths.config_file,
            "library": ctx.library_file,
            "logs": ctx.paths.log_dir,
        }
        for name, row in self._rows.items():
            row.set_path(tr(f"settings.about.{name}"), paths[name])
