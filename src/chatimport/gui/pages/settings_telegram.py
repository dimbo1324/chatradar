"""The Telegram card: API credentials, the session status and the sign-in button."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from chatimport.config import ConfigError, load_config
from chatimport.config_edit import update_config
from chatimport.gui.i18n import tr
from chatimport.gui.login_flow import LoginDialog
from chatimport.gui.pages.settings_form import WIDE_EDITOR_WIDTH, FieldRow, SettingsCard
from chatimport.gui.pages.settings_support import (
    SettingsHooks,
    context_of,
    control_of,
    open_link,
)
from chatimport.gui.pages.support import MainThreadRunner, notify
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.chip import Chip

if TYPE_CHECKING:
    from concurrent.futures import Future

    from chatimport.context import ServiceContext
    from chatimport.gui.context import GuiContext
    from chatimport.telegram.session_probe import SessionInfo

log = logging.getLogger(__name__)

TELEGRAM_APPS_URL: Final = "https://my.telegram.org/apps"
API_HASH_PATTERN: Final = re.compile(r"[0-9A-Za-z]{16,64}")
BUSY_SERVICE: Final = ("running", "starting", "stopping")

type SessionState = str
SESSION_TONES: Final[dict[str, Tone]] = {
    "checking": "info",
    "signed_in": "live",
    "signed_out": "warning",
    "unknown": "muted",
    "no_credentials": "muted",
}


class TelegramCard(SettingsCard):
    saved = Signal()
    signed_in = Signal(str)

    def __init__(
        self,
        gui: GuiContext,
        hooks: SettingsHooks,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(gui.kit, "telegram", "send", parent)
        self.gui = gui
        self._hooks = hooks
        self._runner = MainThreadRunner(self)
        self._service = ""
        self._state: SessionState = "checking"
        self._handle: str | None = None
        self._probing = False
        self._baseline = ("", "")
        kit = gui.kit

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
        hash_box = QWidget()
        hash_row = QHBoxLayout(hash_box)
        hash_row.setContentsMargins(0, 0, 0, 0)
        hash_row.setSpacing(kit.px(SPACE[3]))
        hash_row.addWidget(self._api_hash, 1)
        hash_row.addWidget(self._reveal)
        for edit in (self._api_id, self._api_hash):
            edit.textChanged.connect(self._on_edited)

        self._id_row = FieldRow(kit, self._api_id, editor_width=WIDE_EDITOR_WIDTH)
        self._hash_row = FieldRow(kit, hash_box, editor_width=WIDE_EDITOR_WIDTH)
        self._link = Button(kit, variant="ghost", icon_name="external")
        self._link.clicked.connect(lambda: open_link(TELEGRAM_APPS_URL))
        link_row = QHBoxLayout()
        link_row.addStretch(1)
        link_row.addWidget(self._link)
        link_box = QWidget()
        link_box.setLayout(link_row)
        link_row.setContentsMargins(0, 0, 0, 0)

        self._chip = Chip(kit, "", "info", dot=True)
        self._sign_in = Button(kit, variant="primary", icon_name="send")
        self._sign_in.clicked.connect(self._open_login)
        self._recheck = Button(kit, variant="ghost", icon_name="refresh")
        self._recheck.clicked.connect(lambda: self.refresh_session())
        status_box = QWidget()
        status_row = QHBoxLayout(status_box)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(kit.px(SPACE[4]))
        status_row.addWidget(self._chip)
        status_row.addStretch(1)
        status_row.addWidget(self._recheck)
        status_row.addWidget(self._sign_in)
        self._session_row = FieldRow(kit, status_box, editor_width=None)

        self._save = Button(kit, variant="primary", icon_name="check")
        self._save.clicked.connect(self.save)
        self.add_row(self._id_row)
        self.add_row(self._hash_row)
        self.add_plain(link_box)
        self.add_row(self._session_row)
        self.add_footer_button(self._save)
        bind_kit(kit, language=self.retranslate)
        self.load()
        self.retranslate()

    def load(self) -> None:
        """Read the credentials from `config.toml` (the file is the source of truth)."""
        try:
            config = load_config(self.gui.service.paths.config_file).telegram
        except ConfigError:
            config = None
        api_id = "" if config is None or not config.api_id else str(config.api_id)
        api_hash = "" if config is None else config.api_hash
        for edit, value in ((self._api_id, api_id), (self._api_hash, api_hash)):
            edit.blockSignals(True)
            edit.setText(value)
            edit.blockSignals(False)
        self._baseline = (api_id, api_hash)
        self._on_edited()

    def retranslate(self) -> None:
        self.set_texts(tr("settings.card.telegram.title"), tr("settings.card.telegram.lede"))
        self._id_row.set_texts(tr("settings.tg.api_id"), tr("settings.tg.api_id_hint"))
        self._hash_row.set_texts(tr("settings.tg.api_hash"), tr("settings.tg.api_hash_hint"))
        self._session_row.set_texts(tr("settings.tg.session"), tr("settings.tg.session_hint"))
        self._link.setText(tr("settings.tg.get_credentials"))
        self._save.setText(tr("common.save"))
        self._recheck.setText(tr("settings.tg.check_again"))
        self._on_reveal(self._reveal.isChecked())
        self._render_session()

    def set_service_state(self, service: str) -> None:
        previous, self._service = self._service, service
        if previous != service:
            self.refresh_session(allow_probe=self.isVisible())

    @property
    def dirty(self) -> bool:
        return (self._api_id.text().strip(), self._api_hash.text().strip()) != self._baseline

    @property
    def credentials_saved(self) -> bool:
        return all(self._baseline) and self._baseline[0].isdigit() and int(self._baseline[0]) > 0

    def refresh_session(self, *, allow_probe: bool = True) -> None:
        if not self.credentials_saved:
            self._set_session("no_credentials")
        elif self._service in BUSY_SERVICE:
            self._set_session("signed_in", self._handle)
        elif not self.gui.service.paths.session_file.is_file():
            self._set_session("signed_out")
        elif allow_probe and not self._probing:
            self._probing = True
            self._set_session("checking")
            ctx = self._fresh_context()
            self._runner.submit(lambda: self._hooks.probe(ctx), self._probed)

    def _fresh_context(self) -> ServiceContext:
        ctx = context_of(self.gui, self._hooks)
        try:
            return replace(ctx, config=load_config(ctx.paths.config_file))
        except ConfigError:
            return ctx

    def _probed(self, done: Future[SessionInfo | None]) -> None:
        self._probing = False
        try:
            info = done.result()
        except Exception:
            log.exception("checking the Telegram session failed")
            self._set_session("unknown")
            return
        if info is None:
            self._set_session("signed_out")
        else:
            self._set_session("signed_in", info.handle)

    def _set_session(self, state: SessionState, handle: str | None = None) -> None:
        self._state = state
        if handle:
            self._handle = handle
        self._render_session()

    def _render_session(self) -> None:
        state = self._state
        text = tr(f"settings.tg.state.{state}")
        if state == "signed_in" and self._handle:
            text = tr("settings.tg.state.signed_in_as", handle=self._handle)
        self._chip.set_text(text)
        self._chip.set_tone(SESSION_TONES[state])
        self._chip.set_icon(
            {"signed_in": "check-circle", "signed_out": "alert", "unknown": "info"}.get(state)
        )
        self._sign_in.setVisible(state in ("signed_out", "unknown", "no_credentials"))
        self._sign_in.setEnabled(state in ("signed_out", "unknown"))
        self._sign_in.setText(tr("settings.tg.sign_in"))
        self._sign_in.setToolTip(
            tr("settings.tg.sign_in_needs_credentials") if state == "no_credentials" else ""
        )
        self._recheck.setVisible(
            state in ("signed_in", "unknown") and self._service not in BUSY_SERVICE
        )

    def _on_reveal(self, shown: bool) -> None:
        self._api_hash.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self._reveal.set_icon_name("lock" if shown else "eye")
        self._reveal.set_tooltip(tr("settings.tg.hide" if shown else "settings.tg.show"))

    def _on_edited(self, *_: object) -> None:
        self.clear_message()
        current = (self._api_id.text().strip(), self._api_hash.text().strip())
        dirty = current != self._baseline
        self._save.setEnabled(dirty)
        self.set_status(tr("settings.unsaved") if dirty else "")

    def save(self) -> None:
        api_id, api_hash = self._api_id.text().strip(), self._api_hash.text().strip()
        if not api_id.isdigit() or int(api_id) <= 0:
            self.show_message("danger", tr("settings.tg.err.api_id"))
            return
        if API_HASH_PATTERN.fullmatch(api_hash) is None:
            self.show_message("danger", tr("settings.tg.err.api_hash"))
            return
        try:
            update_config(
                self.gui.service.paths.config_file,
                {"telegram": {"api_id": int(api_id), "api_hash": api_hash}},
            )
        except ConfigError:
            log.exception("the Telegram credentials were rejected")
            self.show_message("danger", tr("settings.err.rejected"))
            return
        except OSError:
            log.exception("config.toml could not be written")
            self.show_message("danger", tr("settings.err.write"))
            return
        self._baseline = (api_id, api_hash)
        self.show_message("success", tr("settings.saved"))
        self._on_edited()
        self.show_message("success", tr("settings.saved"))
        self.refresh_session()
        self.saved.emit()

    def _open_login(self) -> None:
        dialog = LoginDialog(
            self.gui, self._hooks, control_of(self.gui, self._hooks), self.window()
        )
        dialog.signed_in.connect(self._on_signed_in)
        dialog.exec()

    def _on_signed_in(self, handle: str) -> None:
        self._set_session("signed_in", handle)
        notify(self, "success", tr("settings.tg.signed_in_toast", handle=handle))
        self.signed_in.emit(handle)
