"""Status bar items of the shell: the service-state chip and the global download indicator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from chatimport.gui.i18n import plural, tr
from chatimport.gui.icons import icon_pixmap
from chatimport.gui.shell_state import (
    DownloadSummary,
    ServiceState,
    download_summary,
    service_state,
)
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.progress import BusyStripe

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit

STATE_TONES: Final[dict[str, Tone]] = {
    "starting": "info",
    "running": "live",
    "paused": "muted",
    "stopping": "warning",
    "stopped": "muted",
    "failed": "danger",
}
_MAX_TEXT: Final = 380
_STRIPE_WIDTH: Final = 56
_KIND_ICONS: Final[dict[str, str]] = {
    "retrying": "refresh",
    "disk": "alert",
    "paused": "pause",
    "done": "check-circle",
    "empty": "check-circle",
    "queued": "hourglass",
}


class ServiceChip(Chip):
    def __init__(self, kit: UiKit) -> None:
        super().__init__(kit, "", "muted", dot=True)
        self._state: ServiceState = "starting"
        kit.language.changed.connect(self._retranslate)
        self.apply("starting")

    @property
    def state(self) -> ServiceState:
        return self._state

    def apply(self, state: ServiceState) -> None:
        self._state = state
        self.set_tone(STATE_TONES[state])
        self._retranslate()

    def update_from(self, snapshot: dict[str, Any] | None, failed: bool) -> None:
        self.apply(service_state(snapshot, failed))

    def _retranslate(self) -> None:
        name = tr(f"shell.state.{self._state}")
        self.set_text(name)
        self.setToolTip(tr("shell.state.tip", state=name))
        self.setAccessibleName(tr("shell.state.tip", state=name))


class DownloadIndicator(QFrame):
    """ "Downloading history: <chat> - N waiting" with a running stripe, or a calm "all done"."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("DownloadIndicator")
        self._summary = DownloadSummary("empty")
        self._icon = QLabel()
        self._stripe = BusyStripe(kit)
        self._stripe_box = QWidget()
        box = QVBoxLayout(self._stripe_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._stripe, 0, Qt.AlignmentFlag.AlignVCenter)
        self._text = QLabel()
        self._full = ""
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        for part in (self._icon, self._stripe_box, self._text):
            self._row.addWidget(part)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self.set_summary(self._summary)

    @property
    def summary(self) -> DownloadSummary:
        return self._summary

    @property
    def text(self) -> str:
        return self._full

    def update_from(self, snapshot: dict[str, Any] | None) -> None:
        self.set_summary(download_summary(snapshot))

    def set_summary(self, summary: DownloadSummary) -> None:
        self._summary = summary
        active = summary.kind == "active"
        self._stripe_box.setVisible(active)
        self._stripe.set_active(active)
        self._icon.setVisible(not active)
        self._restyle()
        self._retranslate()

    def _compose(self) -> str:
        summary = self._summary
        if summary.kind == "active":
            chat = summary.chat
            if summary.extra_active:
                chat = tr("shell.dl.more", chat=chat, n=summary.extra_active)
            text = tr("shell.dl.active", chat=chat)
            if summary.waiting:
                text = f"{text} - {plural(summary.waiting, 'shell.dl.waiting')}"
            return text
        if summary.kind == "queued":
            return f"{tr('shell.dl.queued')} - {plural(summary.waiting, 'shell.dl.waiting')}"
        return tr(f"shell.dl.{summary.kind}")

    def _retranslate(self) -> None:
        self._full = self._compose()
        self._text.setToolTip(self._full)
        self.setAccessibleName(self._full)
        metrics = QFontMetrics(self._text.font())
        width = self.kit.px(_MAX_TEXT)
        self._text.setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, width))

    def _restyle(self) -> None:
        px = self.kit.px
        palette = self.kit.palette
        self._row.setSpacing(px(SPACE[3]))
        self._stripe_box.setFixedWidth(px(_STRIPE_WIDTH))
        kind = self._summary.kind
        name = _KIND_ICONS.get(kind, "check-circle")
        color = {
            "disk": palette.warning,
            "retrying": palette.warning,
            "done": palette.live,
            "empty": palette.fg_faint,
        }.get(kind, palette.fg_muted)
        self._icon.setPixmap(icon_pixmap(name, color, px(12)))
        self._retranslate_width()

    def _retranslate_width(self) -> None:
        self._text.setMaximumWidth(self.kit.px(_MAX_TEXT) + self.kit.px(8))
