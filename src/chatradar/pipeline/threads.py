"""Stage `threads`: group the useful messages of a chat into discussions.

1. Reply links join messages (union-find).
2. A message without a reply joins the previous message of the same chat and forum topic
   when the gap is under `GAP`; otherwise it starts a new thread.
3. A thread's id is `thread_id_for(chat_id, earliest message id)`, so it is stable.

Only the tail of a chat is recomputed: from `OVERLAP` before its earliest pending message,
widened until every thread touching the window lies wholly inside it (a reply to an older
message pulls in that message's thread). Then the window's threads replace the stored ones
and every message in the window is marked; noise gets no thread.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING

from chatradar.domain.models import StageResult, Thread
from chatradar.domain.text import thread_id_for
from chatradar.pipeline.features import chrono_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from chatradar.domain.models import MessageKey, Source, StoredMessage
    from chatradar.pipeline.base import StageDeps

GAP = timedelta(minutes=30)
OVERLAP = timedelta(days=2)

THREADS_VERSION = 1


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        self._parent[self.find(a)] = self.find(b)


def group_threads(messages: Sequence[StoredMessage]) -> dict[str, Thread]:
    """Pure grouping of one chat's useful messages; returns msg_id → its thread.

    A reply whose target is not among `messages` counts as a message without a reply.
    """
    ordered = sorted(messages, key=chrono_key)
    by_id = {m.msg_id: m for m in ordered}
    sets = _UnionFind(by_id)
    previous: dict[str | None, StoredMessage] = {}
    for msg in ordered:
        if msg.reply_to is not None and msg.reply_to in by_id:
            sets.union(msg.msg_id, msg.reply_to)
        else:
            before = previous.get(msg.topic_id)
            if before is not None and msg.date - before.date < GAP:
                sets.union(msg.msg_id, before.msg_id)
        previous[msg.topic_id] = msg

    members: defaultdict[str, list[StoredMessage]] = defaultdict(list)
    for msg in ordered:
        members[sets.find(msg.msg_id)].append(msg)

    assigned: dict[str, Thread] = {}
    for group in members.values():
        root = group[0]
        thread = Thread(
            thread_id=thread_id_for(root.chat_id, root.msg_id),
            source=root.source,
            chat_id=root.chat_id,
            topic_id=root.topic_id,
            root_msg_id=root.msg_id,
            started_at=root.date,
            ended_at=max(m.date for m in group),
            msg_count=len(group),
            has_question=any(m.is_question for m in group),
        )
        for msg in group:
            assigned[msg.msg_id] = thread
    return assigned


def _is_ready(msg: StoredMessage) -> bool:
    return msg.versions.get("enrich") is not None


def _root_id(chat_id: str, thread_id: str | None) -> str | None:
    prefix = thread_id_for(chat_id, "")
    if thread_id is None or not thread_id.startswith(prefix):
        return None
    return thread_id.removeprefix(prefix)


class ThreadsStage:
    name = "threads"
    version = THREADS_VERSION
    depends_on: str | None = "enrich"

    async def run(self, deps: StageDeps, limit: int) -> int:
        pending = await deps.messages.pending_for(self.name, self.version, self.depends_on, limit)
        if not pending:
            return 0
        earliest: dict[tuple[Source, str], datetime] = {}
        for msg in pending:
            chat = (msg.source, msg.chat_id)
            earliest[chat] = min(earliest.get(chat, msg.date), msg.date)
        marked = 0
        for (source, chat_id), first in earliest.items():
            marked += await self._regroup(deps, source, chat_id, first - OVERLAP)
        return marked

    async def _regroup(self, deps: StageDeps, source: Source, chat_id: str, since: datetime) -> int:
        """Regroup the chat's tail; returns how many messages were marked."""
        window, since = await self._closed_window(deps, source, chat_id, since)
        ready = [m for m in window if _is_ready(m)]
        assigned = group_threads([m for m in ready if not m.is_noise])

        threads = {t.thread_id: t for t in assigned.values()}
        await deps.messages.save_threads(source, chat_id, since, list(threads.values()))
        results = [
            StageResult(
                key=m.key,
                values={"thread_id": t.thread_id if (t := assigned.get(m.msg_id)) else None},
            )
            for m in ready
        ]
        await deps.messages.mark(self.name, self.version, results)
        return len(results)

    async def _closed_window(
        self, deps: StageDeps, source: Source, chat_id: str, since: datetime
    ) -> tuple[list[StoredMessage], datetime]:
        """The chat from `since`, widened until no thread reaches back before it."""
        while True:
            window = await deps.messages.chat_window(source, chat_id, since)
            inside = {m.msg_id for m in window}
            useful = [m for m in window if _is_ready(m) and not m.is_noise]
            outer_targets: list[MessageKey] = [
                (source, chat_id, m.reply_to)
                for m in useful
                if m.reply_to is not None and m.reply_to not in inside
            ]
            targets = await deps.messages.get_many(outer_targets) if outer_targets else {}
            roots: set[str] = set()
            for msg in [*useful, *targets.values()]:
                root = _root_id(chat_id, msg.thread_id)
                if root is not None and root not in inside:
                    roots.add(root)
            root_keys: list[MessageKey] = [(source, chat_id, r) for r in roots]
            found = await deps.messages.get_many(root_keys) if root_keys else {}
            older = min((m.date for m in found.values()), default=since)
            if older >= since:
                return window, since
            since = older
