"""`GuiContext`: everything a window page needs, and the bridge it talks to the service through."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from chatimport.gui.kit import UiKit

if TYPE_CHECKING:
    from concurrent.futures import Future

    from PySide6.QtCore import SignalInstance

    from chatimport.commands import CommandResult
    from chatimport.context import ServiceContext
    from chatimport.gui.i18n import LanguageManager
    from chatimport.gui.settings import GuiSettingsStore
    from chatimport.gui.theme import ThemeManager
    from chatimport.gui.zoom import ZoomManager


class ServiceBridge(Protocol):
    """The window's only door to the service (implemented by the service host).

    `execute` is thread-safe and returns at once; the result arrives on the future.
    `snapshot` is a Qt signal carrying the status dict, always emitted on the main thread.
    """

    snapshot: SignalInstance

    @property
    def last_snapshot(self) -> dict[str, Any] | None: ...

    def execute(
        self, command: str, args: dict[str, Any] | None = None
    ) -> Future[CommandResult]: ...


@dataclass(frozen=True, slots=True)
class GuiContext:
    service: ServiceContext
    theme: ThemeManager
    language: LanguageManager
    zoom: ZoomManager
    settings: GuiSettingsStore
    bridge: ServiceBridge

    @property
    def kit(self) -> UiKit:
        return UiKit(theme=self.theme, language=self.language, zoom=self.zoom)
