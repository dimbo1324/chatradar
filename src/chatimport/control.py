"""File-based command queue between the CLI/tray and the running service (spec §9.3).

Everything lives in the control folder; there are no network ports.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from filelock import FileLock, Timeout

from chatimport.ports import ChatImportError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from chatimport.ports import Clock

log = logging.getLogger(__name__)

COMMANDS = (
    "trim",
    "pause",
    "resume",
    "recheck",
    "status",
    "reload_config",
    "set_root",
    "shutdown",
    "refetch",
    "deeper",
    "check",
)
RESULT_SUFFIX = ".result.json"
STALE_RESULT_SECONDS = 600
POLL_SECONDS = 1.0


class AlreadyRunning(ChatImportError):
    """Another ChatImport service instance holds the lock."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict[str, Any])


type Handler = Callable[[dict[str, Any]], Awaitable[CommandResult]]


class _BadCommand(ValueError):
    pass


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


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
    )


class ControlServer:
    def __init__(self, control_dir: Path, handlers: Mapping[str, Handler], *, clock: Clock) -> None:
        self._dir = control_dir
        self._handlers = handlers
        self._clock = clock

    async def run(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                await self.process_pending()
            except OSError:
                log.exception("control folder scan failed")
            await self._clock.sleep(POLL_SECONDS)

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
        request_id = stem
        try:
            request = _read_object(path)
            request_id = str(request.get("id", stem))
            command = str(request.get("command", ""))
            raw_args: object = request.get("args") or {}
            if not isinstance(raw_args, dict):
                raise _BadCommand("args is not an object")
        except (OSError, ValueError) as exc:
            result = CommandResult(False, f"invalid command file: {type(exc).__name__}: {exc}")
        else:
            result = await self._dispatch(command, cast("dict[str, Any]", raw_args))
        payload = {
            "id": request_id,
            "ok": result.ok,
            "message": result.message,
            "data": result.data,
        }
        _write_json_atomic(self._dir / f"{stem}{RESULT_SUFFIX}", payload)
        _remove(path)

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
    timeout: float = 30.0,
    poll: float = 0.25,
) -> CommandResult:
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
            with contextlib.suppress(OSError):
                command_path.unlink()
            raise TimeoutError(
                f"no answer to {command!r} within {timeout:g} s; "
                "the ChatImport service may not be running"
            )
        time.sleep(poll)


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
