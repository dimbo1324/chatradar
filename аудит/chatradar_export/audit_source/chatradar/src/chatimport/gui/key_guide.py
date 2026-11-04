"""The "How do I get these keys?" dialog: seven numbered steps with painted sketches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.key_guide_art import KINDS, SchemeArt
from chatimport.gui.locales import onboarding as _onboarding_strings
from chatimport.gui.pages.settings_support import open_link
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import make_label

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit

_ = _onboarding_strings
SITE_URL: Final = "https://my.telegram.org"
DIALOG_WIDTH: Final = 760
DIALOG_HEIGHT: Final = 640


class _StepRow(QWidget):
    def __init__(self, kit: UiKit, number: int, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._number = number
        self._badge = Chip(kit, str(number), "accent")
        self._title = make_label("", "section", wrap=True)
        self._body = make_label("", "secondary", wrap=True)
        self.open_button: Button | None = None
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(kit.px(SPACE[2]))
        texts.addWidget(self._title)
        texts.addWidget(self._body)
        if number == 1:
            self.open_button = Button(kit, variant="primary", icon_name="external")
            self.open_button.clicked.connect(lambda: open_link(SITE_URL))
            holder = QHBoxLayout()
            holder.addWidget(self.open_button)
            holder.addStretch(1)
            texts.addLayout(holder)
        texts.addStretch(1)
        badge = QVBoxLayout()
        badge.setContentsMargins(0, 0, 0, 0)
        badge.addWidget(self._badge)
        badge.addStretch(1)
        art = QVBoxLayout()
        art.setContentsMargins(0, 0, 0, 0)
        art.addWidget(SchemeArt(kit, kind))
        art.addStretch(1)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(kit.px(SPACE[5]))
        row.addLayout(badge)
        row.addLayout(texts, 1)
        row.addLayout(art)

    def retranslate(self) -> None:
        self._title.setText(tr(f"setup.guide.step.{self._number}.title"))
        self._body.setText(tr(f"setup.guide.step.{self._number}.body"))
        if self.open_button is not None:
            self.open_button.setText(tr("setup.guide.open"))


class KeyGuideDialog(QDialog):
    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        kit = gui.kit
        self.setMinimumSize(kit.px(DIALOG_WIDTH), kit.px(DIALOG_HEIGHT))
        self._lede = make_label("", "muted", wrap=True)
        self.steps = [_StepRow(kit, index, kind) for index, kind in enumerate(KINDS, start=1)]
        self._trouble = Callout(kit, "warning", "")
        self._secret = Callout(kit, "danger", "")
        self._close = Button(kit)
        self._close.clicked.connect(self.accept)

        content = QVBoxLayout()
        gap = kit.px(SPACE[6])
        content.setContentsMargins(gap, gap, gap, gap)
        content.setSpacing(gap)
        content.addWidget(self._lede)
        for step in self.steps:
            content.addWidget(step)
        content.addWidget(self._trouble)
        content.addWidget(self._secret)
        content.addStretch(1)
        host = QWidget()
        host.setLayout(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(host)
        footer = QHBoxLayout()
        footer.setContentsMargins(gap, 0, gap, gap)
        footer.addStretch(1)
        footer.addWidget(self._close)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(scroll, 1)
        column.addLayout(footer)
        bind_kit(kit, language=self._retranslate)
        self._retranslate()

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("setup.guide.title"))
        self._lede.setText(tr("setup.guide.lede"))
        for step in self.steps:
            step.retranslate()
        self._trouble.set_title(tr("setup.guide.trouble.title"))
        self._trouble.set_body(tr("setup.guide.trouble.body"))
        self._secret.set_title(tr("setup.guide.secret.title"))
        self._secret.set_body(tr("setup.guide.secret.body"))
        self._close.setText(tr("common.close"))
