"""The top bar: page title and subtitle, a slot for page actions, theme and language switchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.settings import THEME_PREFERENCES, ThemePreference
from chatimport.gui.strings import LANGUAGES, Language
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.labels import ElidedLabel
from chatimport.gui.widgets.segmented import Segmented, SegmentOption

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit

_THEME_ICONS: dict[str, str] = {"light": "sun", "dark": "moon", "system": "monitor"}


class ThemeSwitcher(Segmented):
    """Three icon segments (light, dark, follow the system) wired to the theme manager."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(
            kit, self._build_options(), kit.theme.preference, compact=True, parent=parent
        )
        self.setAccessibleName(tr("theme.label"))
        self.selected.connect(self._choose)
        kit.theme.changed.connect(self._sync)
        kit.language.changed.connect(self._retranslate)

    @staticmethod
    def _build_options() -> list[SegmentOption]:
        return [
            SegmentOption(
                value=name,
                label="",
                icon=_THEME_ICONS[name],
                tooltip=tr("theme.tip", mode=tr(f"theme.{name}")),
            )
            for name in THEME_PREFERENCES
        ]

    def _choose(self, value: str) -> None:
        preference: ThemePreference = "light" if value == "light" else "dark"
        self.kit.theme.set_preference("system" if value == "system" else preference)

    def _sync(self) -> None:
        self.set_value(self.kit.theme.preference)

    def _retranslate(self) -> None:
        self.set_options(self._build_options(), self.kit.theme.preference)
        self.setAccessibleName(tr("theme.label"))


class LanguageSwitcher(Segmented):
    """EN | RU segments wired to the language manager."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(
            kit, self._build_options(), kit.language.current, compact=True, parent=parent
        )
        self.setAccessibleName(tr("language.label"))
        self.selected.connect(self._choose)
        kit.language.changed.connect(self._retranslate)

    @staticmethod
    def _build_options() -> list[SegmentOption]:
        return [
            SegmentOption(
                value=code,
                label=tr(f"language.{code}_short"),
                tooltip=tr("language.tip", name=tr(f"language.{code}")),
            )
            for code in LANGUAGES
        ]

    def _choose(self, value: str) -> None:
        language: Language = "ru" if value == "ru" else "en"
        self.kit.language.set_language(language)

    def _retranslate(self) -> None:
        self.set_options(self._build_options(), self.kit.language.current)
        self.setAccessibleName(tr("language.label"))


class TopBar(QFrame):
    def __init__(
        self,
        kit: UiKit,
        title: str = "",
        subtitle: str = "",
        *,
        switchers: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("TopBar")
        self._title = QLabel(title)
        self._title.setObjectName("TopBarTitle")
        self._subtitle = ElidedLabel(subtitle)
        self._subtitle.setObjectName("TopBarSubtitle")
        self._subtitle.setVisible(bool(subtitle))
        self._texts = QVBoxLayout()
        self._texts.addWidget(self._title)
        self._texts.addWidget(self._subtitle)
        self._actions = QHBoxLayout()
        self._row = QHBoxLayout(self)
        self._row.addLayout(self._texts, 1)
        self._row.addLayout(self._actions)
        self.theme_switcher = ThemeSwitcher(kit) if switchers else None
        self.language_switcher = LanguageSwitcher(kit) if switchers else None
        for switcher in (self.language_switcher, self.theme_switcher):
            if switcher is not None:
                self._row.addWidget(switcher)
        bind_kit(kit, zoom=self._restyle)
        self._restyle()

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))

    def add_action(self, widget: QWidget) -> None:
        self._actions.addWidget(widget)

    def _restyle(self) -> None:
        px = self.kit.px
        self.setFixedHeight(px(LAYOUT["header"]))
        self._row.setContentsMargins(px(SPACE[8]), 0, px(SPACE[6]), 0)
        self._row.setSpacing(px(SPACE[5]))
        self._actions.setSpacing(px(SPACE[4]))
        self._texts.setContentsMargins(0, 0, 0, 0)
        self._texts.setSpacing(0)
