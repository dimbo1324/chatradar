"""The writing side of the search index (the service is the one writer).

A batch is applied in one transaction together with the watermarks of the parts it came from,
so a crash leaves either both or neither, and every operation is idempotent by
`(chat_id, msg_id)`. Edit and delete records may be seen before their message (a month
backfilled later), so they wait in `pending` until the message arrives; a delete is final.

A *reconcile* (a part was rewritten) re-reads a whole chat without a gap in the results: the
chat's generation is bumped, rows are re-stamped as the scan meets them, and only rows of the
older generation are swept when the scan finishes.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chatimport.records import DeleteRecord, EditRecord, MessageRecord, format_dt
from chatimport.search_db import (
    SearchError,
    connect_writer,
    database_path,
    delete_database,
    fts5_trigram_available,
)
from chatimport.search_fold import clean_text, search_key
from chatimport.search_reader import SearchReader, open_reader

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Sequence
    from datetime import datetime
    from pathlib import Path

    from chatimport.records import Record
    from chatimport.search_types import IndexState

__all__ = [
    "ChatRow",
    "PartMark",
    "SearchIndex",
    "SearchReader",
    "fts5_trigram_available",
    "open_reader",
    "open_writer",
    "reset_index",
]

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PartMark:
    """How far one part has been indexed: `offset` bytes (whole lines only), the size and
    mtime seen before reading, and checksums of the first and last bytes before `offset`."""

    part: str
    offset: int
    size: int
    mtime_ns: int
    head_crc: int
    tail_crc: int


@dataclass(frozen=True, slots=True)
class ChatRow:
    chat_id: int
    title: str
    username: str | None
    folder: str
    gen: int
    reconciling: bool
    messages: int


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


class SearchIndex:
    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self._path = path
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextlib.contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute("ROLLBACK")
                raise

    def _gen(self, chat_id: int) -> int:
        row = self._conn.execute("SELECT gen FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return int(row[0]) if row is not None else 0

    def chat_rows(self) -> dict[int, ChatRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id, title, username, folder, gen, reconciling, messages FROM chats"
            ).fetchall()
        return {r[0]: ChatRow(r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6]) for r in rows}

    def marks(self, chat_id: int) -> dict[str, PartMark]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT part, offset, size, mtime_ns, head_crc, tail_crc FROM marks "
                "WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        return {r[0]: PartMark(*r) for r in rows}

    def indexed_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(SUM(messages), 0) FROM chats").fetchone()
        return int(row[0])

    def upsert_chat(self, chat_id: int, title: str, username: str | None, folder: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO chats (chat_id, title, username, folder) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (chat_id) DO UPDATE SET title = excluded.title, "
                "username = excluded.username, folder = excluded.folder",
                (chat_id, clean_text(title), username, folder),
            )

    def set_status(self, state: IndexState, total: int, now: datetime) -> None:
        values = {"state": state.value, "total": str(total), "updated_at": format_dt(now)}
        with self._transaction() as conn:
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                values.items(),
            )

    def apply(self, chat_id: int, records: Iterable[Record], marks: Sequence[PartMark] = ()) -> int:
        """Apply records and watermarks in one transaction; returns the change in messages."""
        with self._transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO chats (chat_id, title, folder) VALUES (?, '', '')",
                (chat_id,),
            )
            gen = self._gen(chat_id)
            delta = 0
            for record in records:
                if isinstance(record, MessageRecord):
                    delta += _apply_message(conn, chat_id, gen, record)
                elif isinstance(record, EditRecord):
                    _apply_edit(conn, chat_id, gen, record)
                elif isinstance(record, DeleteRecord):
                    delta -= _apply_delete(conn, chat_id, gen, record)
            conn.executemany(
                "INSERT INTO marks (chat_id, part, offset, size, mtime_ns, head_crc, tail_crc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (chat_id, part) DO UPDATE SET "
                "offset = excluded.offset, size = excluded.size, mtime_ns = excluded.mtime_ns, "
                "head_crc = excluded.head_crc, tail_crc = excluded.tail_crc",
                [
                    (chat_id, m.part, m.offset, m.size, m.mtime_ns, m.head_crc, m.tail_crc)
                    for m in marks
                ],
            )
            _add_messages(conn, chat_id, delta)
        return delta

    def remove_below(self, chat_id: int, floor_id: int) -> int:
        """Forget messages with `msg_id < floor_id` (their parts were trimmed away)."""
        with self._transaction() as conn:
            removed = conn.execute(
                "DELETE FROM messages WHERE chat_id = ? AND msg_id < ?", (chat_id, floor_id)
            ).rowcount
            conn.execute(
                "DELETE FROM pending WHERE chat_id = ? AND msg_id < ?", (chat_id, floor_id)
            )
            _add_messages(conn, chat_id, -removed)
        return removed

    def forget_parts(self, chat_id: int, parts: Iterable[str]) -> None:
        with self._transaction() as conn:
            conn.executemany(
                "DELETE FROM marks WHERE chat_id = ? AND part = ?", [(chat_id, p) for p in parts]
            )

    def drop_chat(self, chat_id: int) -> None:
        with self._transaction() as conn:
            for table in ("messages", "pending", "marks", "chats"):
                conn.execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))  # noqa: S608 - fixed names

    def begin_reconcile(self, chat_id: int) -> None:
        """Start a full re-read of the chat: the next generation, no watermarks."""
        with self._transaction() as conn:
            conn.execute(
                "UPDATE chats SET gen = gen + 1, reconciling = 1 WHERE chat_id = ?", (chat_id,)
            )
            conn.execute("DELETE FROM marks WHERE chat_id = ?", (chat_id,))

    def finish_reconcile(self, chat_id: int) -> None:
        """Sweep everything the finished re-read did not meet again."""
        with self._transaction() as conn:
            gen = self._gen(chat_id)
            conn.execute("DELETE FROM messages WHERE chat_id = ? AND gen <> ?", (chat_id, gen))
            conn.execute("DELETE FROM pending WHERE chat_id = ? AND gen <> ?", (chat_id, gen))
            conn.execute(
                "UPDATE chats SET reconciling = 0, messages = "
                "(SELECT COUNT(*) FROM messages WHERE chat_id = ?) WHERE chat_id = ?",
                (chat_id, chat_id),
            )


def _add_messages(conn: sqlite3.Connection, chat_id: int, delta: int) -> None:
    if delta:
        conn.execute("UPDATE chats SET messages = messages + ? WHERE chat_id = ?", (delta, chat_id))


def _tombstoned(conn: sqlite3.Connection, chat_id: int, gen: int, msg_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pending WHERE chat_id = ? AND msg_id = ? AND kind = 'delete' AND gen = ?",
        (chat_id, msg_id, gen),
    ).fetchone()
    return row is not None


def _apply_message(conn: sqlite3.Connection, chat_id: int, gen: int, record: MessageRecord) -> int:
    if record.service is not None or _tombstoned(conn, chat_id, gen, record.msg_id):
        return 0
    text = clean_text(record.text)
    folded = search_key(text)
    ver = _epoch(record.edit_date) if record.edit_date is not None else 0
    edited = 1 if record.edit_date is not None else 0
    inserted = conn.execute(
        "INSERT INTO messages (chat_id, msg_id, date, text, folded, ver, edited, gen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (chat_id, msg_id) DO NOTHING",
        (chat_id, record.msg_id, _epoch(record.date), text, folded, ver, edited, gen),
    ).rowcount
    if not inserted:
        conn.execute(
            "UPDATE messages SET text = ?, folded = ?, ver = ?, edited = ?, gen = ? "
            "WHERE chat_id = ? AND msg_id = ? AND (gen <> ? OR ver < ?)",
            (text, folded, ver, edited, gen, chat_id, record.msg_id, gen, ver),
        )
    _consume_pending_edit(conn, chat_id, gen, record.msg_id)
    return inserted


def _consume_pending_edit(conn: sqlite3.Connection, chat_id: int, gen: int, msg_id: int) -> None:
    row = conn.execute(
        "SELECT ver, text FROM pending "
        "WHERE chat_id = ? AND msg_id = ? AND kind = 'edit' AND gen = ?",
        (chat_id, msg_id, gen),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "UPDATE messages SET text = ?, folded = ?, ver = ?, edited = 1 "
        "WHERE chat_id = ? AND msg_id = ? AND ver <= ?",
        (row[1], search_key(row[1]), row[0], chat_id, msg_id, row[0]),
    )
    conn.execute("DELETE FROM pending WHERE chat_id = ? AND msg_id = ?", (chat_id, msg_id))


def _apply_edit(conn: sqlite3.Connection, chat_id: int, gen: int, record: EditRecord) -> None:
    text = clean_text(record.text)
    ver = _epoch(record.edit_date)
    changed = conn.execute(
        "UPDATE messages SET text = ?, folded = ?, ver = ?, edited = 1 "
        "WHERE chat_id = ? AND msg_id = ? AND gen = ? AND ver <= ?",
        (text, search_key(text), ver, chat_id, record.msg_id, gen, ver),
    ).rowcount
    if changed:
        return
    known = conn.execute(
        "SELECT 1 FROM messages WHERE chat_id = ? AND msg_id = ? AND gen = ?",
        (chat_id, record.msg_id, gen),
    ).fetchone()
    if known is not None or _tombstoned(conn, chat_id, gen, record.msg_id):
        return
    conn.execute(
        "INSERT INTO pending (chat_id, msg_id, kind, ver, text, gen) "
        "VALUES (?, ?, 'edit', ?, ?, ?) ON CONFLICT (chat_id, msg_id) DO UPDATE SET "
        "ver = excluded.ver, text = excluded.text, gen = excluded.gen "
        "WHERE pending.kind = 'edit' "
        "AND (pending.gen <> excluded.gen OR pending.ver <= excluded.ver)",
        (chat_id, record.msg_id, ver, text, gen),
    )


def _apply_delete(conn: sqlite3.Connection, chat_id: int, gen: int, record: DeleteRecord) -> int:
    removed = 0
    for msg_id in record.msg_ids:
        removed += conn.execute(
            "DELETE FROM messages WHERE chat_id = ? AND msg_id = ?", (chat_id, msg_id)
        ).rowcount
        conn.execute(
            "INSERT INTO pending (chat_id, msg_id, kind, ver, text, gen) "
            "VALUES (?, ?, 'delete', 0, '', ?) ON CONFLICT (chat_id, msg_id) DO UPDATE SET "
            "kind = 'delete', ver = 0, text = '', gen = excluded.gen",
            (chat_id, msg_id, gen),
        )
    return removed


def open_writer(root: Path) -> SearchIndex:
    """The index of `root`, created or rebuilt as needed; raises `SearchError` when it cannot
    be opened and FTS5 with the trigram tokenizer is missing."""
    if not fts5_trigram_available():
        raise SearchError("this SQLite has no FTS5 trigram tokenizer")
    path = database_path(root)
    return SearchIndex(connect_writer(path), path)


def reset_index(root: Path) -> None:
    """Delete the index file; the next `open_writer` builds it again from scratch."""
    delete_database(database_path(root))
    log.warning("search index deleted for a rebuild")
