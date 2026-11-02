# pyright: reportPrivateUsage=false
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import search_db
from chatimport.search_db import (
    SCHEMA_VERSION,
    SEARCH_DB,
    SearchError,
    connect_reader,
    connect_writer,
    database_path,
    delete_database,
    fts5_trigram_available,
)

if TYPE_CHECKING:
    from pathlib import Path


def insert_chat(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO chats (chat_id, title, folder) VALUES (1, 'title', 'folder')")


def chat_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM chats").fetchone()[0]


def set_version(path: Path, version: int) -> None:
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(f"PRAGMA user_version = {version}")


class BrokenProbe:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError("no such module: fts5")

    def close(self) -> None:
        self.closed = True


def test_the_index_lives_next_to_the_chat_folders(tmp_path: Path) -> None:
    assert database_path(tmp_path) == tmp_path / SEARCH_DB
    assert SEARCH_DB.startswith("_")


def test_fts5_trigram_is_available_here() -> None:
    assert fts5_trigram_available() is True


def test_an_old_sqlite_has_no_trigram_tokenizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_db.sqlite3, "sqlite_version_info", (3, 33, 9))
    assert fts5_trigram_available() is False


def test_a_build_without_fts5_is_reported_and_the_probe_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = BrokenProbe()

    def connect(_target: str) -> BrokenProbe:
        return probe

    monkeypatch.setattr(search_db.sqlite3, "connect", connect)
    assert fts5_trigram_available() is False
    assert probe.closed


def test_a_new_database_is_wal_with_the_whole_schema(tmp_path: Path) -> None:
    conn = connect_writer(database_path(tmp_path))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()
    assert {
        "meta",
        "chats",
        "marks",
        "messages",
        "pending",
        "fts",
        "messages_newest",
        "messages_after_insert",
        "messages_after_delete",
        "messages_after_update",
    } <= names


def test_an_existing_database_keeps_its_rows(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    conn = connect_writer(path)
    insert_chat(conn)
    conn.close()
    again = connect_writer(path)
    try:
        assert chat_count(again) == 1
    finally:
        again.close()


def test_another_schema_version_is_rebuilt_in_place(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    conn = connect_writer(path)
    insert_chat(conn)
    conn.close()
    set_version(path, 99)
    rebuilt = connect_writer(path)
    try:
        assert chat_count(rebuilt) == 0
        assert rebuilt.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        rebuilt.execute(
            "INSERT INTO messages (chat_id, msg_id, date, text, folded, ver, edited, gen) "
            "VALUES (1, 1, 1, 'abc', 'abc', 0, 0, 0)"
        )
        found = rebuilt.execute("SELECT rowid FROM fts WHERE fts MATCH '\"abc\"'").fetchall()
        assert len(found) == 1
    finally:
        rebuilt.close()


def test_a_file_that_is_not_a_database_is_replaced(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    path.write_bytes(b"this is not a database " * 100)
    path.with_name(path.name + "-wal").write_bytes(b"junk")
    conn = connect_writer(path)
    try:
        assert chat_count(conn) == 0
    finally:
        conn.close()


def test_a_database_that_fails_once_is_deleted_and_created_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = database_path(tmp_path)
    conn = connect_writer(path)
    insert_chat(conn)
    conn.close()
    real = search_db._open_checked
    calls: list[int] = []

    def flaky(target: Path) -> sqlite3.Connection:
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return real(target)

    monkeypatch.setattr(search_db, "_open_checked", flaky)
    fresh = connect_writer(path)
    try:
        assert len(calls) == 2
        assert chat_count(fresh) == 0
    finally:
        fresh.close()


def test_a_busy_database_is_reported_without_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = database_path(tmp_path)
    path.write_bytes(b"keep me")

    def locked(_target: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(search_db, "_open_checked", locked)
    with pytest.raises(SearchError, match="busy"):
        connect_writer(path)
    assert path.read_bytes() == b"keep me"


def test_a_database_that_cannot_be_recreated_raises_a_search_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_target: Path) -> sqlite3.Connection:
        raise sqlite3.DatabaseError("still broken")

    monkeypatch.setattr(search_db, "_open_checked", broken)
    with pytest.raises(SearchError, match="cannot create"):
        connect_writer(database_path(tmp_path))


def test_delete_database_removes_the_wal_side_files_too(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    side = [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]
    for file in side:
        file.write_bytes(b"x")
    delete_database(path)
    assert not any(file.exists() for file in side)
    delete_database(path)


def test_delete_database_reports_a_file_that_cannot_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_path: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(search_db, "unlink_file", refuse)
    with pytest.raises(SearchError, match="cannot remove"):
        delete_database(database_path(tmp_path))


def test_quoting_doubles_embedded_quotes() -> None:
    assert search_db._quote('a"b') == '"a""b"'


def test_a_reader_needs_a_file(tmp_path: Path) -> None:
    assert connect_reader(database_path(tmp_path)) is None


def test_a_reader_sees_what_the_writer_commits_and_cannot_write(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    writer = connect_writer(path)
    reader = connect_reader(path)
    assert reader is not None
    try:
        assert chat_count(reader) == 0
        insert_chat(writer)
        assert chat_count(reader) == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            insert_chat(reader)
    finally:
        reader.close()
        writer.close()


@pytest.mark.parametrize("version", [0, 7])
def test_a_reader_refuses_another_schema_version(tmp_path: Path, version: int) -> None:
    path = database_path(tmp_path)
    connect_writer(path).close()
    set_version(path, version)
    assert connect_reader(path) is None


def test_a_reader_refuses_a_file_that_is_not_a_database(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    path.write_bytes(b"this is not a database " * 100)
    assert connect_reader(path) is None


def test_a_reader_refuses_a_database_without_the_tables(tmp_path: Path) -> None:
    path = database_path(tmp_path)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("CREATE TABLE other (a)")
        raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    assert connect_reader(path) is None


def test_a_reader_gives_up_when_the_connection_cannot_be_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = database_path(tmp_path)
    connect_writer(path).close()

    def refuse(*_args: Any, **_kwargs: Any) -> sqlite3.Connection:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(search_db.sqlite3, "connect", refuse)
    assert connect_reader(path) is None
