"""Wizard steps one and two (API keys, Telegram sign-in) and the base class every step shares."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from chatimport.config import ConfigError, load_config
from chatimport.config_edit import update_config
from chatimport.gui.i18n import tr
from chatimport.gui.key_guide import KeyGuideDialog
from chatimport.gui.key_validation import validate_api_hash, validate_api_id
from chatimport.gui.locales import onboarding as _onboarding_strings
from chatimport.gui.login_flow import LoginDialog
from chatimport.gui.pages.settings_support import ServiceControl, SettingsHooks, context_of
from chatimport.gui.setup_logic import read_state
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import make_label

if TYPE_CHECKING:
    from chatimport.context import ServiceContext
    from chatimport.gui.context import GuiContext

_ = _onboarding_strings
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WizardEnv:
    gui: GuiContext
    hooks: SettingsHooks
    control: ServiceControl | None

    @property
    def context(self) -> ServiceContext:
        return context_of(self.gui, self.hooks)


class WizardStep(QWidget):
    """A page of the wizard. `skippable` steps may be left incomplete; `commit` saves on Next."""

    changed = Signal()
    name = ""
    skippable = False
    has_lede = True

    def __init__(self, env: WizardEnv, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.env = env
        self.kit = env.gui.kit
        self._heading = make_label("", "section", wrap=True)
        self._lede = make_label("", "muted", wrap=True)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(self.kit.px(SPACE[5]))
        self.column.addWidget(self._heading)
        self.column.addWidget(self._lede)
        bind_kit(self.kit, language=self.retranslate)

    def retranslate(self) -> None:
        self._heading.setText(tr(f"setup.{self.name}.heading"))
        if self.has_lede:
            self._lede.setText(tr(f"setup.{self.name}.lede"))

    def enter(self) -> None:
        """The step became visible: refresh from the files, earlier steps may have changed them."""

    def can_advance(self) -> bool:
        return True

    def commit(self) -> bool:
        return True


class KeysStep(WizardStep):
    name = "keys"

    def __init__(self, env: WizardEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, parent)
        kit = self.kit
        self._api_id = QLineEdit()
        self._api_id.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,12}")))
        self._api_id.setPlaceholderText("12345678")
        self._api_id.setProperty("role", "mono")
        self._api_hash = QLineEdit()
        self._api_hash.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_hash.setPlaceholderText("0123456789abcdef0123456789abcdef")
        self._api_hash.setProperty("role", "mono")
        self._api_hash.setMaxLength(64)
        self._reveal = IconButton(kit, "eye", "")
        self._reveal.setCheckable(True)
        self._reveal.toggled.connect(self._on_reveal)
        self._id_label = make_label("", "caption")
        self._hash_label = make_label("", "caption")
        self._id_error = make_label("", "error", wrap=True)
        self._hash_error = make_label("", "error", wrap=True)
        self._guide = Button(kit, variant="ghost", icon_name="info")
        self._guide.clicked.connect(self._open_guide)
        self._problem = Callout(kit, "danger", "")
        self._problem.hide()
        hash_row = QHBoxLayout()
        hash_row.setSpacing(kit.px(SPACE[3]))
        hash_row.addWidget(self._api_hash, 1)
        hash_row.addWidget(self._reveal)
        guide_row = QHBoxLayout()
        guide_row.addWidget(self._guide)
        guide_row.addStretch(1)
        for widget in (self._id_label, self._api_id, self._id_error, self._hash_label):
            self.column.addWidget(widget)
        self.column.addLayout(hash_row)
        self.column.addWidget(self._hash_error)
        self.column.addLayout(guide_row)
        self.column.addWidget(self._problem)
        self.column.addStretch(1)
        for edit in (self._api_id, self._api_hash):
            edit.textChanged.connect(self._on_edited)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self._id_label.setText(tr("settings.tg.api_id"))
        self._hash_label.setText(tr("settings.tg.api_hash"))
        self._api_id.setAccessibleName(tr("settings.tg.api_id"))
        self._api_hash.setAccessibleName(tr("settings.tg.api_hash"))
        self._guide.setText(tr("setup.keys.guide"))
        self._on_reveal(self._reveal.isChecked())
        self._validate()

    def enter(self) -> None:
        try:
            telegram = load_config(self.env.context.paths.config_file).telegram
        except ConfigError:
            return
        if telegram.api_id and not self._api_id.text():
            self._api_id.setText(str(telegram.api_id))
        if telegram.api_hash and not self._api_hash.text():
            self._api_hash.setText(telegram.api_hash)

    def can_advance(self) -> bool:
        return self._validate()

    def _validate(self) -> bool:
        checks = (
            (self._api_id, self._id_error, validate_api_id(self._api_id.text())),
            (self._api_hash, self._hash_error, validate_api_hash(self._api_hash.text())),
        )
        for edit, label, error in checks:
            shown = bool(error) and bool(edit.text().strip())
            label.setText(tr(error) if error and shown else "")
            label.setVisible(shown)
        return not any(error for _, _, error in checks)

    def _on_edited(self, *_: object) -> None:
        self._problem.hide()
        self._validate()
        self.changed.emit()

    def _on_reveal(self, shown: bool) -> None:
        self._api_hash.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self._reveal.set_icon_name("lock" if shown else "eye")
        self._reveal.set_tooltip(tr("settings.tg.hide" if shown else "settings.tg.show"))

    def _open_guide(self) -> None:
        KeyGuideDialog(self.env.gui, self.window()).exec()

    def commit(self) -> bool:
        if not self._validate():
            return False
        api_id, api_hash = int(self._api_id.text().strip()), self._api_hash.text().strip()
        path = self.env.context.paths.config_file
        try:
            saved = load_config(path).telegram
        except ConfigError:
            saved = None
        if saved is not None and (saved.api_id, saved.api_hash) == (api_id, api_hash):
            return True
        try:
            update_config(path, {"telegram": {"api_id": api_id, "api_hash": api_hash}})
        except ConfigError:
            log.exception("the Telegram credentials were rejected")
            return self._fail("setup.keys.error.rejected")
        except OSError:
            log.exception("config.toml could not be written")
            return self._fail("setup.keys.error.write")
        return True

    def _fail(self, key: str) -> bool:
        self._problem.set_body(tr(key))
        self._problem.show()
        return False


class SignInStep(WizardStep):
    name = "signin"
    skippable = True

    def __init__(self, env: WizardEnv, parent: QWidget | None = None) -> None:
        super().__init__(env, parent)
        self._signed_in = False
        self._keys_saved = False
        self._handle = ""
        self._chip = Chip(self.kit, "", "muted")
        self._button = Button(self.kit, variant="primary", icon_name="send")
        self._button.clicked.connect(self._open_login)
        self._note = Callout(self.kit, "warning", "")
        row = QHBoxLayout()
        row.setSpacing(self.kit.px(SPACE[4]))
        row.addWidget(self._chip)
        row.addWidget(self._button)
        row.addStretch(1)
        self.column.addLayout(row)
        self.column.addWidget(self._note)
        self.column.addStretch(1)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self._button.setText(tr("setup.signin.button"))
        self._note.set_body(tr("setup.signin.needs_keys"))
        self._render()

    def enter(self) -> None:
        context = self.env.context
        state = read_state(
            context.paths.config_file, context.paths.session_file, context.library_file
        )
        self._keys_saved, self._signed_in = state.keys_saved, state.signed_in
        self._render()
        self.changed.emit()

    def can_advance(self) -> bool:
        return self._signed_in

    def _render(self) -> None:
        if self._signed_in:
            text = (
                tr("setup.signin.signed_as", handle=self._handle)
                if self._handle
                else tr("setup.signin.done")
            )
            self._chip.set_text(text)
            self._chip.set_tone("success")
            self._chip.set_icon("check-circle")
        else:
            self._chip.set_text(tr("settings.tg.state.signed_out"))
            self._chip.set_tone("warning")
            self._chip.set_icon("alert")
        self._button.setVisible(not self._signed_in)
        self._button.setEnabled(self._keys_saved)
        self._note.setVisible(not self._signed_in and not self._keys_saved)

    def _open_login(self) -> None:
        dialog = LoginDialog(self.env.gui, self.env.hooks, self.env.control, self.window())
        dialog.signed_in.connect(self._on_signed_in)
        dialog.exec()

    def _on_signed_in(self, handle: str) -> None:
        self._handle = handle
        self._signed_in = True
        self._render()
        self.changed.emit()
