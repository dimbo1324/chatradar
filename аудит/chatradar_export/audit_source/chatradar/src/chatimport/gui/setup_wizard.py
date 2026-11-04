"""The first-run wizard: API keys, sign-in, chats, folder and run mode, then Finish.

Every step reads the files again when it is shown, so the wizard works the same when it is
started fresh, resumed, or run again later from Settings: finished steps arrive prefilled and
the sign-in step knows the session already exists. Finish applies the run mode, remembers that
the wizard was completed and starts (or restarts) the service.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from PySide6.QtWidgets import QDialog, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.locales import onboarding as _onboarding_strings
from chatimport.gui.pages.settings_support import SettingsHooks, control_of
from chatimport.gui.pages.support import notify
from chatimport.gui.setup_steps import KeysStep, SignInStep, WizardEnv, WizardStep
from chatimport.gui.setup_steps_data import ChatsStep, FolderStep
from chatimport.gui.setup_steps_run import RunModeStep, SummaryStep
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import make_label

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext

_ = _onboarding_strings
log = logging.getLogger(__name__)

DIALOG_WIDTH: Final = 700
DIALOG_HEIGHT: Final = 540


class SetupWizard(QDialog):
    def __init__(
        self,
        gui: GuiContext,
        hooks: SettingsHooks | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.gui = gui
        kit = gui.kit
        hooks = hooks or SettingsHooks()
        env = WizardEnv(gui, hooks, control_of(gui, hooks))
        self._env = env
        self._index = 0
        self._finishing = False
        self.setModal(True)
        self.setMinimumSize(kit.px(DIALOG_WIDTH), kit.px(DIALOG_HEIGHT))

        self._mode = RunModeStep(env)
        self.steps: list[WizardStep] = [
            KeysStep(env),
            SignInStep(env),
            ChatsStep(env),
            FolderStep(env),
            self._mode,
            SummaryStep(env, self._mode),
        ]
        self._chips = [Chip(kit, "", "muted") for _ in self.steps]
        self._counter = make_label("", "caption")
        self._stack = QStackedWidget()
        for step in self.steps:
            self._stack.addWidget(step)
            step.changed.connect(self._refresh_nav)

        self._cancel = Button(kit)
        self._cancel.clicked.connect(self.reject)
        self._back = Button(kit, icon_name="chevron-left")
        self._back.clicked.connect(self._go_back)
        self._skip = Button(kit)
        self._skip.clicked.connect(self._go_skip)
        self._next = Button(kit, variant="primary")
        self._next.clicked.connect(self._go_next)
        self._finish = Button(kit, variant="primary", icon_name="check")
        self._finish.clicked.connect(self._on_finish)

        chips = QHBoxLayout()
        chips.setSpacing(kit.px(SPACE[3]))
        for chip in self._chips:
            chips.addWidget(chip)
        chips.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(kit.px(SPACE[3]))
        buttons.addWidget(self._cancel)
        buttons.addStretch(1)
        for button in (self._back, self._skip, self._next, self._finish):
            buttons.addWidget(button)
        column = QVBoxLayout(self)
        gap = kit.px(SPACE[6])
        column.setContentsMargins(gap, gap, gap, gap)
        column.setSpacing(gap)
        column.addLayout(chips)
        column.addWidget(self._counter)
        column.addWidget(self._stack, 1)
        column.addLayout(buttons)
        bind_kit(kit, language=self._retranslate)
        self._retranslate()
        self._show(0)

    @property
    def index(self) -> int:
        return self._index

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("setup.wizard.title"))
        self._cancel.setText(tr("common.cancel"))
        self._back.setText(tr("setup.wizard.back"))
        self._skip.setText(tr("setup.wizard.skip"))
        self._next.setText(tr("setup.wizard.next"))
        self._finish.setText(tr("setup.wizard.finish"))
        self._refresh_nav()

    def _show(self, index: int) -> None:
        self._index = index
        self._stack.setCurrentIndex(index)
        self.steps[index].enter()
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        last = len(self.steps) - 1
        step = self.steps[self._index]
        for position, (chip, other) in enumerate(zip(self._chips, self.steps, strict=True)):
            tone: Tone = (
                "success"
                if position < self._index
                else "info"
                if position == self._index
                else "muted"
            )
            chip.set_text(f"{position + 1}. {tr(f'setup.step.{other.name}')}")
            chip.set_tone(tone)
        self._counter.setText(tr("setup.wizard.step_of", n=self._index + 1, total=len(self.steps)))
        skipping = step.skippable and not step.can_advance() and self._index < last
        busy = self._finishing
        self._back.setVisible(self._index > 0)
        self._back.setEnabled(not busy)
        self._skip.setVisible(skipping)
        self._next.setVisible(not skipping and self._index < last)
        self._next.setEnabled(step.can_advance())
        self._finish.setVisible(self._index == last)
        self._finish.setEnabled(not busy)

    def _go_back(self) -> None:
        self._show(self._index - 1)

    def _go_skip(self) -> None:
        self._show(self._index + 1)

    def _go_next(self) -> None:
        if self.steps[self._index].commit():
            self._show(self._index + 1)

    def _on_finish(self) -> None:
        self._finishing = True
        self._refresh_nav()
        self._mode.apply(self._applied)

    def _applied(self, ok: bool) -> None:
        if not ok:
            parent = self.parentWidget()
            if parent is not None:
                notify(parent, "warning", tr("setup.finish.autostart_failed"))
        self.gui.settings.update(setup_completed=True)
        control = self._env.control
        if control is not None:
            if control.is_alive:
                control.restart()
            else:
                control.start_service()
        self.accept()
