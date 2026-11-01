"""What the Settings page needs from the outside: service control, probes and test hooks.

The page talks to the service host through `ServiceControl` (the host implements it; the bridge
Protocol of the shell does not know it), and takes its slow or networked collaborators through
`SettingsHooks`, so a demo or a test can replace the Task Scheduler, the session probe and the
Telegram login without touching the real ones.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from chatimport import autostart

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from chatimport.context import ServiceContext
    from chatimport.gui.context import GuiContext
    from chatimport.telegram.session_probe import SessionInfo


@runtime_checkable
class ServiceControl(Protocol):
    """The part of the service host the Settings page uses."""

    @property
    def context(self) -> ServiceContext: ...

    @property
    def is_alive(self) -> bool: ...

    def start_service(self) -> bool: ...

    def stop_service(self, on_stopped: Callable[[], None] | None = None) -> None: ...

    def restart(self) -> None: ...


type LoginFunc = Callable[..., Awaitable[str]]
type ProbeFunc = Callable[[ServiceContext], SessionInfo | None]


def probe_session_blocking(ctx: ServiceContext) -> SessionInfo | None:
    from chatimport.telegram.session_probe import probe_session

    return asyncio.run(probe_session(ctx.config.telegram, ctx.paths.session_file))


def telegram_login(*args: Any, **kwargs: Any) -> Awaitable[str]:
    from chatimport.telegram.client import login

    return login(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class SettingsHooks:
    autostart_task: str = autostart.TASK_NAME
    probe: ProbeFunc = probe_session_blocking
    login: LoginFunc = telegram_login
    executable: str | None = None
    control: ServiceControl | None = field(default=None)


def control_of(gui: GuiContext, hooks: SettingsHooks) -> ServiceControl | None:
    if hooks.control is not None:
        return hooks.control
    return gui.bridge if isinstance(gui.bridge, ServiceControl) else None


def context_of(gui: GuiContext, hooks: SettingsHooks) -> ServiceContext:
    control = control_of(gui, hooks)
    return control.context if control is not None else gui.service


def open_path(path: Path) -> None:
    """Open a folder in the file manager (a file's folder for a file)."""
    target = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def open_link(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))
