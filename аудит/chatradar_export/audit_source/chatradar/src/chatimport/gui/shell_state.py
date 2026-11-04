"""Qt-free reading of a status snapshot for the shell: service state and history download."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, cast

type ServiceState = Literal[
    "starting", "running", "paused", "stopping", "stopped", "failed", "needs_setup"
]
type DownloadKind = Literal["active", "queued", "retrying", "disk", "paused", "done", "empty"]

Snapshot = dict[str, Any]

_KNOWN: Final = ("starting", "running", "stopping", "stopped", "needs_setup")
_IDLE_KINDS: Final[tuple[tuple[str, DownloadKind], ...]] = (
    ("retrying", "retrying"),
    ("disk_stopped", "disk"),
    ("paused", "paused"),
)


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    kind: DownloadKind
    chat: str = ""
    extra_active: int = 0
    waiting: int = 0


def _dicts(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [
        cast("dict[str, Any]", item) for item in cast("list[object]", raw) if isinstance(item, dict)
    ]


def _ints(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [item for item in cast("list[object]", raw) if isinstance(item, int)]


def chats_of(snapshot: Snapshot | None) -> list[dict[str, Any]]:
    return _dicts((snapshot or {}).get("chats"))


def service_state(snapshot: Snapshot | None, failed: bool) -> ServiceState:
    if failed:
        return "failed"
    if snapshot is None:
        return "starting"
    name = str(snapshot.get("service", "stopped"))
    if name not in _KNOWN:
        return "stopped"
    chats = chats_of(snapshot)
    if name == "running" and chats and all(bool(c.get("paused")) for c in chats):
        return "paused"
    return cast("ServiceState", name)


def _title_of(chats: list[dict[str, Any]], chat_id: int) -> str:
    for chat in chats:
        if chat.get("chat_id") == chat_id:
            return str(chat.get("title") or chat_id)
    return str(chat_id)


def _backfill_states(chats: list[dict[str, Any]]) -> set[str]:
    states: set[str] = set()
    for chat in chats:
        info = chat.get("backfill")
        if isinstance(info, dict):
            states.add(str(cast("dict[str, Any]", info).get("state")))
    return states


def download_summary(snapshot: Snapshot | None) -> DownloadSummary:
    chats = chats_of(snapshot)
    raw_block = (snapshot or {}).get("backfill")
    block = cast("dict[str, Any]", raw_block) if isinstance(raw_block, dict) else {}
    active = _ints(block.get("active"))
    waiting = len(_ints(block.get("waiting")))
    if active:
        return DownloadSummary("active", _title_of(chats, active[0]), len(active) - 1, waiting)
    if waiting:
        return DownloadSummary("queued", waiting=waiting)
    states = _backfill_states(chats)
    for state, kind in _IDLE_KINDS:
        if state in states:
            return DownloadSummary(kind)
    return DownloadSummary("done" if chats else "empty")
