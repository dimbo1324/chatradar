"""Wizard steps five and six: how the program starts, and the summary before Finish."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QRadioButton, QWidget

from chatimport import autostart
from chatimport.gui.i18n import tr
from chatimport.gui.pages.support import MainThreadRunner
from chatimport.gui.setup_logic import read_state
from chatimport.gui.setup_steps import WizardEnv, WizardStep
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.labels import make_label

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

log = logging.getLogger(__name__)


class RunModeStep(WizardStep):
    name = "mode"

    def __init__(self, env: WizardEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, parent)
        self._runner = MainThreadRunner(self)
        self._auto = QRadioButton()
        self._manual = QRadioButton()
        self._auto_hint = make_label("", "caption", wrap=True)
        self._manual_hint = make_label("", "caption", wrap=True)
        self._unsupported = Callout(self.kit, "info", "")
        self._auto.setChecked(True)
        for widget in (self._auto, self._auto_hint, self._manual, self._manual_hint):
            self.column.addWidget(widget)
        self.column.addWidget(self._unsupported)
        self.column.addStretch(1)
        for radio in (self._auto, self._manual):
            radio.toggled.connect(self.changed)
        if not autostart.supported():
            self._auto.setEnabled(False)
            self._manual.setChecked(True)
        self._unsupported.setVisible(not autostart.supported())
        self.retranslate()

    @property
    def autostart_chosen(self) -> bool:
        return self._auto.isChecked()

    def retranslate(self) -> None:
        super().retranslate()
        self._auto.setText(tr("setup.mode.auto"))
        self._manual.setText(tr("setup.mode.manual"))
        self._auto_hint.setText(tr("setup.mode.auto_hint"))
        self._manual_hint.setText(tr("setup.mode.manual_hint"))
        self._unsupported.set_body(tr("setup.mode.unsupported"))

    def apply(self, done: Callable[[bool], None]) -> None:
        """Create or remove the logon task on a worker thread; `done(ok)` runs on the main one."""
        if not autostart.supported():
            done(True)
            return
        task, executable = self.env.hooks.autostart_task, self.env.hooks.executable
        if self.autostart_chosen:
            self._runner.submit(
                lambda: autostart.enable(task, executable=executable),
                lambda future: done(self._succeeded(future)),
            )
        else:
            self._runner.submit(
                lambda: autostart.disable(task), lambda future: done(self._succeeded(future))
            )

    @staticmethod
    def _succeeded(future: Future[autostart.AutostartStatus]) -> bool:
        try:
            future.result()
        except autostart.AutostartError as error:
            log.warning("autostart failed: %s", error.reason)
            return False
        except Exception:
            log.exception("autostart failed")
            return False
        return True


class SummaryStep(WizardStep):
    name = "summary"
    has_lede = False

    def __init__(
        self,
        env: WizardEnv,
        run_mode: RunModeStep,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(env, parent)
        self._run_mode = run_mode
        self._lines = [make_label("", "secondary", wrap=True) for _ in range(5)]
        self._incomplete = Callout(self.kit, "warning", "")
        self._hint = make_label("", "caption", wrap=True)
        for line in self._lines:
            self.column.addWidget(line)
        self.column.addWidget(self._incomplete)
        self.column.addWidget(self._hint)
        self.column.addStretch(1)
        self._lede.hide()
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self._incomplete.set_body(tr("setup.summary.incomplete"))
        self._hint.setText(tr("setup.summary.finish_hint"))
        self._render()

    def enter(self) -> None:
        self._render()

    def _render(self) -> None:
        context = self.env.context
        state = read_state(
            context.paths.config_file, context.paths.session_file, context.library_file
        )
        mode = "auto" if self._run_mode.autostart_chosen else "manual"
        texts = (
            tr("setup.summary.keys.ok" if state.keys_saved else "setup.summary.keys.missing"),
            tr("setup.summary.signin.ok" if state.signed_in else "setup.summary.signin.missing"),
            tr("setup.summary.chats", n=state.chats),
            tr("setup.summary.folder", path=str(state.root)),
            tr(f"setup.summary.mode.{mode}"),
        )
        for line, text in zip(self._lines, texts, strict=True):
            line.setText(text)
        self._incomplete.setVisible(not (state.keys_saved and state.signed_in))
