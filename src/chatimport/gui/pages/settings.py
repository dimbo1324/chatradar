"""The Settings page: a section list on the left, one card per section in a scrolling column.

`config.toml` cards are saved per card and need a service restart to apply; the window's own
preferences apply at once. The page keeps no copy of the configuration: cards read the file
whenever the page is shown and nothing is unsaved.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from chatimport.config import Config, ConfigError, load_config
from chatimport.gui.i18n import tr
from chatimport.gui.locales import settings as _settings_strings
from chatimport.gui.pages.settings_appearance import AppearanceCard
from chatimport.gui.pages.settings_config import ConfigCard, build_config_cards
from chatimport.gui.pages.settings_support import SettingsHooks, context_of, control_of
from chatimport.gui.pages.settings_system import AboutCard, StartupCard
from chatimport.gui.pages.settings_telegram import TelegramCard
from chatimport.gui.pages.support import notify
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.nav_item import NavItem

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from chatimport.gui.context import GuiContext
    from chatimport.gui.pages.settings_form import SettingsCard

_ = _settings_strings
log = logging.getLogger(__name__)

NAV_WIDTH: Final = 156
CONTENT_WIDTH: Final = 760
SPY_MARGIN: Final = 60
RUNNING: Final = ("running", "starting")
NAV_ICONS: Final = {
    "telegram": "send",
    "collection": "download",
    "recheck": "refresh",
    "disk": "disk",
    "media": "package",
    "privacy": "shield",
    "appearance": "sliders",
    "startup": "play",
    "about": "info",
}


class SettingsPage(QWidget):
    title_key = "nav.settings"
    subtitle_key = "settings.subtitle"

    def __init__(
        self,
        gui: GuiContext,
        parent: QWidget | None = None,
        *,
        hooks: SettingsHooks | None = None,
    ) -> None:
        super().__init__(parent)
        self.gui = gui
        self._hooks = hooks or SettingsHooks()
        self._control = control_of(gui, self._hooks)
        self._service = ""
        kit = gui.kit
        config_file = context_of(gui, self._hooks).paths.config_file
        self._config_file = config_file

        self.telegram = TelegramCard(gui, self._hooks)
        self.config_cards: list[ConfigCard] = build_config_cards(kit, config_file)
        self.appearance = AppearanceCard(gui)
        self.startup = StartupCard(gui, self._hooks)
        self.about = AboutCard(gui, self._hooks)
        self.cards: dict[str, SettingsCard] = {
            "telegram": self.telegram,
            **{card.key: card for card in self.config_cards},
            "appearance": self.appearance,
            "startup": self.startup,
            "about": self.about,
        }
        self.telegram.saved.connect(self._on_config_saved)
        for card in self.config_cards:
            card.saved.connect(self._on_config_saved)

        self._restart_button = Button(kit, variant="primary", icon_name="refresh")
        self._restart_button.clicked.connect(self._restart_service)
        self._restart_note = Callout(kit, "warning", "", action=self._restart_button)
        self._restart_note.hide()
        self._invalid = Callout(kit, "danger", "")
        self._invalid.hide()

        self._nav_items: dict[str, NavItem] = {}
        nav = self._nav = QVBoxLayout()
        nav.setSpacing(kit.px(SPACE[1]))
        for key in self.cards:
            item = NavItem(kit, key, NAV_ICONS[key], "")
            item.clicked.connect(lambda _=False, key=key: self.show_section(key))
            self._nav_items[key] = item
            nav.addWidget(item)
        nav.addStretch(1)
        self._nav_box = QFrame()
        self._nav_box.setLayout(nav)
        divider = QFrame()
        set_role(divider, "vdivider")

        self._column = QVBoxLayout()
        self._column.addWidget(self._invalid)
        self._column.addWidget(self._restart_note)
        for card in self.cards.values():
            self._column.addWidget(card)
        self._column.addStretch(1)
        self._content = QWidget()
        self._content.setLayout(self._column)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        wrap.addWidget(self._content, 100)
        wrap.addStretch(1)
        host = self._host = QWidget()
        host.setLayout(wrap)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(host)
        self._scroll.verticalScrollBar().valueChanged.connect(self._spy)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._nav_box)
        row.addWidget(divider)
        row.addWidget(self._scroll, 1)

        gui.bridge.snapshot.connect(self._on_snapshot)
        bind_kit(kit, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()
        self.reload()
        last = gui.bridge.last_snapshot
        if last is not None:
            self._on_snapshot(last)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.reload()
        self.startup.refresh()
        self.telegram.refresh_session()
        self.about.retranslate()

    def reload(self) -> None:
        """Re-read `config.toml` into every card that has no unsaved edit."""
        try:
            config = load_config(self._config_file)
        except ConfigError:
            log.exception("config.toml is invalid")
            config = Config()
            self._invalid.set_body(tr("settings.invalid_config"))
            self._invalid.show()
        else:
            self._invalid.hide()
        for card in self.config_cards:
            if not card.dirty:
                card.load(config)
        if not self.telegram.dirty:
            self.telegram.load()

    def show_section(self, key: str) -> None:
        card = self.cards.get(key)
        if card is None:
            return
        self._activate(key)
        self._scroll_to(card)
        QTimer.singleShot(0, lambda: self._scroll_to(card))

    def _scroll_to(self, card: SettingsCard) -> None:
        offset = card.mapTo(self._host, card.rect().topLeft()).y()
        self._scroll.verticalScrollBar().setValue(max(offset - self.gui.kit.px(SPACE[5]), 0))

    def _activate(self, key: str) -> None:
        for name, item in self._nav_items.items():
            item.set_active(name == key)

    def _spy(self, value: int) -> None:
        current = next(iter(self.cards))
        limit = value + self.gui.kit.px(SPY_MARGIN)
        host = self._host
        for key, card in self.cards.items():
            if card.mapTo(host, card.rect().topLeft()).y() <= limit:
                current = key
        self._activate(current)

    def _restyle(self) -> None:
        px = self.gui.kit.px
        self._nav_box.setFixedWidth(px(NAV_WIDTH))
        self._nav.setContentsMargins(px(SPACE[4]), px(SPACE[6]), px(SPACE[4]), px(SPACE[4]))  # pyright: ignore[reportOptionalMemberAccess]
        self._content.setMaximumWidth(px(CONTENT_WIDTH))
        pad = px(SPACE[6])
        self._column.setContentsMargins(pad, px(SPACE[7]), pad, px(SPACE[8]))
        self._column.setSpacing(px(SPACE[6]))

    def _retranslate(self) -> None:
        for key, item in self._nav_items.items():
            item.set_label(tr(f"settings.card.{key}.title"))
        self._restart_note.set_title(tr("settings.restart.title"))
        self._restart_note.set_body(tr("settings.restart.body"))
        self._restart_button.setText(tr("settings.restart.action"))

    def _on_snapshot(self, snapshot: dict[str, Any]) -> None:
        service = str(snapshot.get("service", ""))
        if service == self._service:
            return
        self._service = service
        self.telegram.set_service_state(service)
        if service not in RUNNING:
            self._restart_note.hide()

    def _on_config_saved(self) -> None:
        if self._service in RUNNING and self._control is not None:
            self._restart_note.show()
        else:
            notify(self, "info", tr("settings.saved_next_start"))

    def _restart_service(self) -> None:
        self._restart_note.hide()
        if self._control is not None:
            self._control.restart()
            notify(self, "info", tr("settings.restart.started"))
