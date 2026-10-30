"""File-based command queue between the CLI/tray and the running service (spec §9.3).

Everything lives in the control folder; there are no network ports. The server claims a
command file by renaming it before running it, so every command runs at most once: a file it
cannot claim waits for the next poll, and a claim left by a crash is answered, never re-run.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Final, cast

from filelock import FileLock, Timeout

from chatimport.commands import COMMAND_NAMES, CommandResult, Handler
from chatimport.ports import ChatImportError
from chatimport.storage.fileio import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from chatimport.ports import Clock

__all__ = [
    "COMMANDS",
    "RESULT_SUFFIX",
    "AlreadyRunning",
    "CommandResult",
    "ControlServer",
    "Handler",
    "acquire_instance_lock",
    "send_command",
    "service_running",
]

log = logging.getLogger(__name__)

COMMANDS: Final = COMMAND_NAMES
RESULT_SUFFIX = ".result.json"
CLAIM_SUFFIX: Final = ".claimed"
STALE_RESULT_SECONDS = 600
POLL_SECONDS = 1.0
MAX_COMMAND_BYTES: Final = 64 * 1024
DEFAULT_TIMEOUT: Final = 30.0
COMMAND_TIMEOUTS: Final[dict[str, float]] = {
    "set_root": 3600.0,
    "check": 600.0,
    "trim": 600.0,
    "deeper": 600.0,
    "recheck": 600.0,
}


class AlreadyRunning(ChatImportError):
    """Another ChatImport service instance holds the lock."""


class _BadCommand(ValueError):
    pass


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False).encode(), unique=True)


def _read_object(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise _BadCommand("not a JSON object")
    return cast("dict[str, Any]", value)


def _is_command_file(path: Path) -> bool:
    return (
        path.suffix == ".json"
        and not path.name.startswith(".")
        and not path.name.endswith(RESULT_SUFFIX)
        and path.is_file()
    )


def _claim(path: Path, stem: str) -> Path | None:
    """Rename the command file aside; None when it is busy (it is retried on the next poll)."""
    claimed = path.with_name(f".{stem}{CLAIM_SUFFIX}")
    try:
        path.replace(claimed)
    except OSError:
        log.warning("command file busy; retried on the next poll", extra={"file": path.name})
        return None
    return claimed


def _load_request(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_COMMAND_BYTES:
        raise _BadCommand("command file too large")
    return _read_object(path)


def _args_of(request: dict[str, Any]) -> dict[str, Any]:
    raw_args: object = request.get("args") or {}
    if not isinstance(raw_args, dict):
        raise _BadCommand("args is not an object")
    return cast("dict[str, Any]", raw_args)


class ControlServer:
    def __init__(self, control_dir: Path, handlers: Mapping[str, Handler], *, clock: Clock) -> None:
        self._dir = control_dir
        self._handlers = handlers
        self._clock = clock

    async def run(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self.answer_interrupted()
        while True:
            try:
                await self.process_pending()
            except Exception:
                log.exception("control folder scan failed")
            await self._clock.sleep(POLL_SECONDS)

    def answer_interrupted(self) -> int:
        """Answer every claim a previous run left behind and drop it, without running it."""
        count = 0
        for path in self._dir.glob(f".*{CLAIM_SUFFIX}"):
            stem = path.name.removeprefix(".").removesuffix(CLAIM_SUFFIX)
            result = CommandResult(False, "interrupted by a service stop; not run again")
            self._finish(path, stem, stem, result)
            count += 1
        return count

    async def process_pending(self) -> int:
        self._drop_stale_results()
        files: list[tuple[int, str, Path]] = []
        for path in self._dir.iterdir():
            if _is_command_file(path):
                with contextlib.suppress(OSError):
                    files.append((path.stat().st_mtime_ns, path.name, path))
        files.sort()
        for _, _, path in files:
            await self._process(path)
        return len(files)

    async def _process(self, path: Path) -> None:
        stem = path.name.removesuffix(".json")
        claimed = _claim(path, stem)
        if claimed is None:
            return
        request_id = stem
        try:
            request = _load_request(claimed)
            request_id = str(request.get("id", stem))
            command = str(request.get("command", ""))
            args = _args_of(request)
        except Exception as exc:
            result = CommandResult(False, f"invalid command file: {type(exc).__name__}: {exc}")
        else:
            result = await self._dispatch(command, args)
        self._finish(claimed, stem, request_id, result)

    def _finish(self, claimed: Path, stem: str, request_id: str, result: CommandResult) -> None:
        payload: dict[str, Any] = {
            "id": request_id,
            "ok": result.ok,
            "message": result.message,
            "data": result.data,
        }
        target = self._dir / f"{stem}{RESULT_SUFFIX}"
        try:
            try:
                _write_json_atomic(target, payload)
            except TypeError, ValueError:
                log.exception("command result is not JSON", extra={"file": claimed.name})
                payload.update(ok=False, message="the result could not be encoded", data={})
                _write_json_atomic(target, payload)
        except OSError:
            log.exception("could not write a command result", extra={"file": claimed.name})
        try:
            claimed.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("could not delete a claimed command file", extra={"file": claimed.name})

    async def _dispatch(self, command: str, args: dict[str, Any]) -> CommandResult:
        handler = self._handlers.get(command)
        if handler is None:
            return CommandResult(False, f"unknown command: {command!r}")
        try:
            return await handler(args)
        except Exception as exc:
            log.exception("command %s failed", command)
            return CommandResult(False, f"{type(exc).__name__}: {exc}")

    def _drop_stale_results(self) -> None:
        now = self._clock.now().timestamp()
        for path in self._dir.glob(f"*{RESULT_SUFFIX}"):
            with contextlib.suppress(OSError):
                if now - path.stat().st_mtime > STALE_RESULT_SECONDS:
                    path.unlink()


def send_command(
    control_dir: Path,
    command: str,
    args: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
    poll: float = 0.25,
) -> CommandResult:
    """Queue a command and wait for its answer. Without `timeout`, long commands (trim,
    check, set_root, ...) get a longer wait than quick ones."""
    if timeout is None:
        timeout = COMMAND_TIMEOUTS.get(command, DEFAULT_TIMEOUT)
    control_dir.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    stem = f"{command}-{request_id}"
    command_path = control_dir / f"{stem}.json"
    result_path = control_dir / f"{stem}{RESULT_SUFFIX}"
    _write_json_atomic(command_path, {"id": request_id, "command": command, "args": args or {}})
    deadline = time.monotonic() + timeout
    while True:
        if result_path.exists():
            try:
                payload = _read_object(result_path)
            except OSError, ValueError:
                payload = None
            if payload is not None:
                with contextlib.suppress(OSError):
                    result_path.unlink()
                data: object = payload.get("data") or {}
                return CommandResult(
                    bool(payload.get("ok", False)),
                    str(payload.get("message", "")),
                    cast("dict[str, Any]", data) if isinstance(data, dict) else {},
                )
        if time.monotonic() >= deadline:
            raise TimeoutError(_timeout_message(command, command_path, timeout))
        time.sleep(poll)


def _timeout_message(command: str, command_path: Path, timeout: float) -> str:
    try:
        command_path.unlink()
    except FileNotFoundError:
        return (
            f"no answer to {command!r} within {timeout:g} s; the service took the command "
            "and may still be running it; do not repeat it, check the status later"
        )
    except OSError:
        pass
    return (
        f"no answer to {command!r} within {timeout:g} s; the ChatImport service may not be running"
    )


def service_running(lock_file: Path) -> bool:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_file))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return True
    lock.release()
    return False


def acquire_instance_lock(lock_file: Path) -> FileLock:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_file))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise AlreadyRunning("another ChatImport instance is already running") from exc
    return lock
