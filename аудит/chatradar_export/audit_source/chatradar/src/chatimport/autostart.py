"""Start ChatImport at logon: one Task Scheduler task for the current user (Windows only).

The task needs no administrator rights: it runs in the owner's own session, one minute after
logon, with no execution time limit and also on battery. Other platforms report "unsupported".
"""

from __future__ import annotations

import contextlib
import getpass
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal
from xml.sax.saxutils import escape

from chatimport.ports import ChatImportError

TASK_NAME: Final = "ChatImport"
LOGON_DELAY: Final = "PT1M"
MODULE_ARGUMENTS: Final = "-m chatimport window --hidden"
_TIMEOUT_SECONDS: Final = 30
_COMMAND_RE: Final = re.compile(r"<Command>(.*?)</Command>", re.DOTALL)
_ARGUMENTS_RE: Final = re.compile(r"<Arguments>(.*?)</Arguments>", re.DOTALL)
_SETTINGS_RE: Final = re.compile(r"<Settings>(.*?)</Settings>", re.DOTALL)
_DISABLED_RE: Final = re.compile(r"<Enabled>\s*false\s*</Enabled>")
_CREATE_NO_WINDOW: Final = 0x08000000
_NOT_FOUND_MARKERS: Final = ("0x80070002", "cannot find", "not exist")

type FailureReason = Literal["unsupported", "denied", "failed"]


class AutostartError(ChatImportError):
    """The task could not be read, created or removed; `reason` is for the interface."""

    def __init__(self, reason: FailureReason, message: str) -> None:
        super().__init__(message)
        self.reason: FailureReason = reason


class AutostartState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ABSENT = "absent"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class AutostartStatus:
    state: AutostartState
    command: str | None = None
    current: bool = True

    @property
    def enabled(self) -> bool:
        return self.state is AutostartState.ENABLED

    @property
    def supported(self) -> bool:
        return self.state is not AutostartState.UNSUPPORTED


def supported() -> bool:
    return sys.platform == "win32"


def launcher(executable: str | None = None) -> str:
    """`pythonw.exe` next to the running interpreter (no console window), else the interpreter."""
    python = Path(executable or sys.executable)
    windowless = python.with_name("pythonw.exe")
    return str(windowless if windowless.is_file() else python)


def task_command(executable: str | None = None) -> tuple[str, str]:
    """The program and its arguments the task runs."""
    return launcher(executable), MODULE_ARGUMENTS


def build_task_xml(program: str, arguments: str, user: str) -> str:
    owner = escape(user)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Starts the ChatImport archive window when you log on.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{owner}</UserId>
      <Delay>{LOGON_DELAY}</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{owner}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(f'"{program}"')}</Command>
      <Arguments>{escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    name = getpass.getuser()
    return f"{domain}\\{name}" if domain else name


def _schtasks(*args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell, task name is ours
            ["schtasks", *args],  # noqa: S607 - resolved from the system path on Windows
            capture_output=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AutostartError("failed", f"schtasks did not run: {type(error).__name__}") from error


def _text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        with contextlib.suppress(UnicodeError):
            return raw.decode(encoding)
    return raw.decode("cp1252", errors="replace")


def _failure(result: subprocess.CompletedProcess[bytes]) -> AutostartError:
    detail = _text(result.stderr or result.stdout).strip()
    lowered = detail.lower()
    reason: FailureReason = "denied" if "access is denied" in lowered else "failed"
    return AutostartError(reason, f"schtasks exit code {result.returncode}: {detail[:200]}")


def _is_absent(result: subprocess.CompletedProcess[bytes]) -> bool:
    detail = _text(result.stderr or result.stdout).lower()
    if any(marker in detail for marker in _NOT_FOUND_MARKERS):
        return True
    return result.returncode == 1 and "denied" not in detail


def status(task_name: str = TASK_NAME, *, executable: str | None = None) -> AutostartStatus:
    """The current state of the task; `current` is False when it points somewhere else."""
    if not supported():
        return AutostartStatus(AutostartState.UNSUPPORTED)
    result = _schtasks("/Query", "/TN", task_name, "/XML")
    if result.returncode != 0:
        if _is_absent(result):
            return AutostartStatus(AutostartState.ABSENT)
        raise _failure(result)
    xml = _text(result.stdout)
    command = _COMMAND_RE.search(xml)
    arguments = _ARGUMENTS_RE.search(xml)
    program = (command.group(1).strip().strip('"') if command else "").replace("&amp;", "&")
    args = (arguments.group(1).strip() if arguments else "").replace("&amp;", "&")
    expected_program, expected_args = task_command(executable)
    current = Path(program).resolve() == Path(expected_program).resolve() and (
        args == expected_args
    )
    settings = _SETTINGS_RE.search(xml)
    off = settings is not None and _DISABLED_RE.search(settings.group(1)) is not None
    state = AutostartState.DISABLED if off else AutostartState.ENABLED
    return AutostartStatus(state, f"{program} {args}".strip(), current)


def enable(task_name: str = TASK_NAME, *, executable: str | None = None) -> AutostartStatus:
    """Create or replace the task."""
    if not supported():
        raise AutostartError("unsupported", "autostart is available on Windows only")
    program, arguments = task_command(executable)
    xml = build_task_xml(program, arguments, _current_user())
    with tempfile.TemporaryDirectory(prefix="chatimport-task-") as folder:
        definition = Path(folder) / "task.xml"
        definition.write_bytes(b"\xff\xfe" + xml.encode("utf-16-le"))
        result = _schtasks("/Create", "/TN", task_name, "/XML", str(definition), "/F")
    if result.returncode != 0:
        raise _failure(result)
    return status(task_name, executable=executable)


def disable(task_name: str = TASK_NAME) -> AutostartStatus:
    """Delete the task; deleting a task that does not exist succeeds."""
    if not supported():
        raise AutostartError("unsupported", "autostart is available on Windows only")
    if status(task_name).state is AutostartState.ABSENT:
        return AutostartStatus(AutostartState.ABSENT)
    result = _schtasks("/Delete", "/TN", task_name, "/F")
    if result.returncode != 0:
        raise _failure(result)
    return AutostartStatus(AutostartState.ABSENT)
