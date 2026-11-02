"""The SQLite file behind search: schema, connections and recovery.

Design (why this shape):

- `messages` is an ordinary table holding the original text next to its folded key
  (`search_fold.search_key`). `fts` is an FTS5 *external-content* table over `messages.folded`
  with the `trigram` tokenizer, so it stores only the index, never a second copy of the text,
  and a hit is a case-, accent- and yo-insensitive substring match in any language. The
  folded column also serves the bounded scan for queries too short for trigrams.
- Triggers keep `fts` in step with `messages`; the writer never touches `fts` directly.
- The file is a derived cache of the JSONL parts (like `state.json`): any version mismatch or
  corruption throws it away and it is rebuilt, never repaired.
- WAL mode: the service writes while the CLI and the window read through `mode=ro`
  connections of their own.
"""

from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING, Final

from chatimport.ports import ChatImportError
from chatimport.storage.fileio import unlink_file

if TYPE_CHECKING:
    from pathlib import Path

SEARCH_DB: Final = "_search.db"
SCHEMA_VERSION: Final = 1
MIN_SQLITE: Final = (3, 34, 0)
BUSY_TIMEOUT_MS: Final = 5000

SCHEMA: Final = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    username TEXT,
    folder TEXT NOT NULL,
    gen INTEGER NOT NULL DEFAULT 0,
    reconciling INTEGER NOT NULL DEFAULT 0,
    messages INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE marks (
    chat_id INTEGER NOT NULL,
    part TEXT NOT NULL,
    offset INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    head_crc INTEGER NOT NULL,
    tail_crc INTEGER NOT NULL,
    PRIMARY KEY (chat_id, part)
) WITHOUT ROWID;
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    msg_id INTEGER NOT NULL,
    date INTEGER NOT NULL,
    text TEXT NOT NULL,
    folded TEXT NOT NULL,
    ver INTEGER NOT NULL,
    edited INTEGER NOT NULL,
    gen INTEGER NOT NULL,
    UNIQUE (chat_id, msg_id)
);
CREATE INDEX messages_newest ON messages (date DESC, msg_id DESC);
CREATE TABLE pending (
    chat_id INTEGER NOT NULL,
    msg_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ver INTEGER NOT NULL,
    text TEXT NOT NULL,
    gen INTEGER NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
) WITHOUT ROWID;
CREATE VIRTUAL TABLE fts USING fts5(
    folded, content='messages', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER messages_after_insert AFTER INSERT ON messages BEGIN
    INSERT INTO fts (rowid, folded) VALUES (new.id, new.folded);
END;
CREATE TRIGGER messages_after_delete AFTER DELETE ON messages BEGIN
    INSERT INTO fts (fts, rowid, folded) VALUES ('delete', old.id, old.folded);
END;
CREATE TRIGGER messages_after_update AFTER UPDATE OF folded ON messages BEGIN
    INSERT INTO fts (fts, rowid, folded) VALUES ('delete', old.id, old.folded);
    INSERT INTO fts (rowid, folded) VALUES (new.id, new.folded);
END;
"""


class SearchError(ChatImportError):
    """The search index cannot be used right now; the message never carries a query."""


def fts5_trigram_available() -> bool:
    """True when this SQLite is new enough and was built with FTS5 and the trigram tokenizer."""
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        return False
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE probe USING fts5(x, tokenize='trigram')")
    except sqlite3.Error:
        return False
    finally:
        probe.close()
    return True


def database_path(root: Path) -> Path:
    return root / SEARCH_DB


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _drop_everything(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for kind, name, _sql in rows:
        if kind == "trigger":
            conn.execute(f"DROP TRIGGER IF EXISTS {_quote(name)}")
    for kind, name, sql in rows:
        if kind == "table" and sql.upper().startswith("CREATE VIRTUAL"):
            conn.execute(f"DROP TABLE IF EXISTS {_quote(name)}")
    for kind, name, _sql in rows:
        if kind == "table":
            conn.execute(f"DROP TABLE IF EXISTS {_quote(name)}")
        elif kind == "index":
            conn.execute(f"DROP INDEX IF EXISTS {_quote(name)}")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _open_checked(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            _drop_everything(conn)
            _create_schema(conn)
        conn.execute("SELECT count(*) FROM chats").fetchone()
    except BaseException:
        conn.close()
        raise
    return conn


def delete_database(path: Path) -> None:
    """Remove the file and its WAL side files; raises `SearchError` when one cannot go."""
    for target in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        try:
            unlink_file(target, missing_ok=True)
        except OSError as error:
            raise SearchError(f"cannot remove {target.name}: {error.strerror}") from error


def connect_writer(path: Path) -> sqlite3.Connection:
    """Open (or create) the index for writing. A file of another version is rebuilt in place;
    a file SQLite cannot read at all is deleted and created again."""
    try:
        return _open_checked(path)
    except sqlite3.DatabaseError as error:
        if isinstance(error, sqlite3.OperationalError) and "locked" in str(error):
            raise SearchError("the search index is busy") from error
    delete_database(path)
    try:
        return _open_checked(path)
    except sqlite3.Error as error:
        raise SearchError("cannot create the search index") from error


def connect_reader(path: Path) -> sqlite3.Connection | None:
    """A read-only connection, or None when the file is missing, of another version or
    unreadable. Several readers may be open next to the one writer."""
    if not path.is_file():
        return None
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
        )
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            conn.close()
            return None
        conn.execute("SELECT count(*) FROM chats").fetchone()
    except sqlite3.Error:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        return None
    return conn
