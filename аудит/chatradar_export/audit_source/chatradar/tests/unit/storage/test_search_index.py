# pyright: reportPrivateUsage=false
from __future__ import annotations

import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import search_index, search_reader
from chatimport.records import DeleteRecord, EditRecord, MediaSavedRecord, Record
from chatimport.search_db import SearchError, database_path
from chatimport.search_index import (
    ChatRow,
    PartMark,
    SearchIndex,
    open_reader,
    open_writer,
    reset_index,
)
from chatimport.search_reader import fts_phrase
from chatimport.search_types import IndexState, IndexStatus, SearchBackend, SearchQuery
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import chars
from tests.unit.storage.search_helpers import OTHER_CHAT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

E_ACUTE = chars(0xE9)
YO_UPPER_WORD = chars(0x401, 0x43B, 0x43A, 0x430)
YE_LOWER_WORD = chars(0x435, 0x43B, 0x43A, 0x430)
YE_UPPER_WORD = chars(0x415, 0x41B, 0x41A, 0x410)


def edit(msg_id: int, text: str, hours: int, chat_id: int = CHAT_ID) -> EditRecord:
    return EditRecord(chat_id, msg_id, NOW + timedelta(hours=hours), NOW, text=text)


def delete(*msg_ids: int, chat_id: int = CHAT_ID) -> DeleteRecord:
    return DeleteRecord(chat_id, msg_ids, NOW)


@pytest.fixture
def index(tmp_path: Path) -> Iterator[SearchIndex]:
    writer = open_writer(tmp_path)
    writer.upsert_chat(CHAT_ID, "Chat", "pub", "chat_folder")
    yield writer
    writer.close()


@pytest.fixture
def reader(tmp_path: Path, index: SearchIndex) -> Iterator[SearchBackend]:
    backend = open_reader(tmp_path)
    assert backend is not None
    yield backend
    backend.close()


def put(index: SearchIndex, *records: Record, chat_id: int = CHAT_ID) -> int:
    return index.apply(chat_id, records)


def ids(reader: SearchBackend, text: str, **kwargs: Any) -> list[int]:
    return [hit.msg_id for hit in reader.search(SearchQuery(text, **kwargs)).hits]


def pairs(reader: SearchBackend, text: str) -> list[tuple[int, int]]:
    return [(hit.chat_id, hit.msg_id) for hit in reader.search(SearchQuery(text)).hits]


def test_search_returns_the_newest_first_with_every_detail(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="Hello one"), msg(2, text="hello two"), msg(3, text="other"))
    query = SearchQuery("HELLO")
    page = reader.search(query)
    assert page.total == 2
    assert page.query is query
    assert [hit.msg_id for hit in page.hits] == [2, 1]
    hit = page.hits[0]
    assert hit.chat_id == CHAT_ID
    assert hit.chat_title == "Chat"
    assert hit.date == NOW - timedelta(hours=998)
    assert hit.date.utcoffset() == timedelta(0)
    assert hit.text == "hello two"
    assert hit.edited is False
    assert hit.link == "https://t.me/pub/2"


def test_links_follow_the_chat_kind_and_the_title_falls_back_to_the_folder(
    index: SearchIndex, reader: SearchBackend
) -> None:
    index.upsert_chat(CHAT_ID, "Chat", None, "chat_folder")
    index.upsert_chat(-5, "Group", None, "group_5")
    index.upsert_chat(-7, "", None, "folder_x")
    put(index, msg(1, text="zzz one"))
    put(index, msg(1, chat_id=-5, text="zzz two"), chat_id=-5)
    put(index, msg(1, chat_id=-7, text="zzz three"), chat_id=-7)
    hits = {hit.chat_id: hit for hit in reader.search(SearchQuery("zzz")).hits}
    assert hits[CHAT_ID].link == "https://t.me/c/1234567890/1"
    assert hits[-5].link is None
    assert hits[-7].chat_title == "folder_x"


def test_applying_twice_changes_nothing(index: SearchIndex, reader: SearchBackend) -> None:
    records = [msg(1, text="same text"), msg(2, text="other text")]
    assert put(index, *records) == 2
    assert put(index, *records) == 0
    assert index.indexed_count() == 2
    assert reader.search(SearchQuery("text")).total == 2


def test_case_accents_and_yo_do_not_matter(index: SearchIndex, reader: SearchBackend) -> None:
    put(index, msg(1, text=f"Caf{E_ACUTE} au lait"), msg(2, text=f"{YO_UPPER_WORD} stands"))
    assert ids(reader, "CAFE") == [1]
    assert ids(reader, f"caf{E_ACUTE}") == [1]
    assert ids(reader, YE_LOWER_WORD) == [2]
    assert ids(reader, YE_UPPER_WORD) == [2]
    assert ids(reader, YO_UPPER_WORD.lower()) == [2]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ('"hi"', [1]),
        ("0% s", [2]),
        ("a_b", [4]),
        ("x*y", [6]),
        ("AND", [7]),
        ("or near", [7]),
        ("it's", [8]),
        ("a or b", [9]),
        ("col:", [10]),
        ("(paren)", [11]),
        ("back\\slash", [12]),
        ("NEAR(", []),
        ('" OR ""', []),
        ("%", [2]),
        ("_", [4]),
        ("*", [6]),
        ('"', [1]),
        ("'", [8]),
    ],
)
def test_special_characters_in_a_query_are_plain_text(
    index: SearchIndex, reader: SearchBackend, query: str, expected: list[int]
) -> None:
    texts = [
        'say "hi" now',
        "100% sure",
        "100 sure",
        "a_b",
        "axb",
        "x*y",
        "AND OR NEAR",
        "it's",
        "a OR b",
        "col:umn",
        "(paren)",
        "back\\slash",
    ]
    put(index, *(msg(i, text=text) for i, text in enumerate(texts, start=1)))
    assert sorted(ids(reader, query)) == expected
    assert reader.search(SearchQuery(query)).total == len(expected)


def test_a_short_query_scans_for_the_substring_newest_first(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="hello"), msg(2, text="she said"), msg(3, text="oh no"))
    page = reader.search(SearchQuery("he"))
    assert [hit.msg_id for hit in page.hits] == [2, 1]
    assert page.total == 2
    assert ids(reader, "O") == [3, 1]


def test_the_short_scan_stops_at_the_cap(
    index: SearchIndex, reader: SearchBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(index, *(msg(i, text=f"ab {i}") for i in range(1, 6)))
    monkeypatch.setattr(search_reader, "SHORT_SCAN_CAP", 3)
    page = reader.search(SearchQuery("a"))
    assert [hit.msg_id for hit in page.hits] == [5, 4, 3]
    assert page.total == 3


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_an_empty_query_finds_nothing(index: SearchIndex, reader: SearchBackend, text: str) -> None:
    put(index, msg(1, text="something"))
    page = reader.search(SearchQuery(text))
    assert page.hits == ()
    assert page.total == 0


def test_no_chats_selected_finds_nothing(index: SearchIndex, reader: SearchBackend) -> None:
    put(index, msg(1, text="something"))
    page = reader.search(SearchQuery("something", chat_ids=frozenset()))
    assert (page.hits, page.total) == ((), 0)


@pytest.mark.parametrize("text", ["alpha", "al"])
def test_filters_by_chat_and_by_date(index: SearchIndex, reader: SearchBackend, text: str) -> None:
    index.upsert_chat(OTHER_CHAT, "Other", None, "other_folder")
    put(index, *(msg(i, text=f"alpha {i}") for i in (1, 2, 3)))
    put(index, *(msg(i, chat_id=OTHER_CHAT, text=f"alpha {i}") for i in (1, 2)), chat_id=OTHER_CHAT)
    assert pairs(reader, text) == [
        (CHAT_ID, 3),
        (CHAT_ID, 2),
        (OTHER_CHAT, 2),
        (CHAT_ID, 1),
        (OTHER_CHAT, 1),
    ]
    assert ids(reader, text, chat_ids=frozenset({OTHER_CHAT})) == [2, 1]
    both = frozenset({OTHER_CHAT, CHAT_ID})
    assert reader.search(SearchQuery(text, chat_ids=both)).total == 5
    assert ids(reader, text, chat_ids=frozenset({CHAT_ID}), since=msg(2).date) == [3, 2]
    assert ids(reader, text, chat_ids=frozenset({CHAT_ID}), until=msg(3).date) == [2, 1]
    window = {"since": msg(2).date, "until": msg(3).date, "chat_ids": frozenset({CHAT_ID})}
    assert ids(reader, text, **window) == [2]
    naive = msg(2).date.replace(tzinfo=None)
    assert ids(reader, text, chat_ids=frozenset({CHAT_ID}), since=naive) == [3, 2]


def test_pages_total_and_clamps(
    index: SearchIndex, reader: SearchBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(index, *(msg(i, text=f"page {i}") for i in range(1, 6)))
    assert ids(reader, "page", limit=2) == [5, 4]
    assert ids(reader, "page", limit=2, offset=2) == [3, 2]
    assert ids(reader, "page", limit=2, offset=4) == [1]
    assert ids(reader, "page", limit=2, offset=10) == []
    assert ids(reader, "page", offset=-3) == [5, 4, 3, 2, 1]
    empty = reader.search(SearchQuery("page", limit=0))
    assert (empty.hits, empty.total) == ((), 5)
    assert reader.search(SearchQuery("page", limit=-4)).hits == ()
    assert reader.search(SearchQuery("page", limit=2, offset=4)).total == 5
    monkeypatch.setattr(search_reader, "MAX_LIMIT", 2)
    assert ids(reader, "page", limit=100) == [5, 4]


def test_an_edit_replaces_the_text_and_marks_the_message(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="first draft"))
    put(index, edit(1, "final wording", hours=1))
    assert ids(reader, "first draft") == []
    page = reader.search(SearchQuery("final wording"))
    assert [(hit.msg_id, hit.text, hit.edited) for hit in page.hits] == [(1, "final wording", True)]


def test_an_older_edit_never_replaces_a_newer_one(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="original"))
    put(index, edit(1, "newest wording", hours=5), edit(1, "older wording", hours=3))
    assert ids(reader, "newest wording") == [1]
    assert ids(reader, "older wording") == []


def test_a_message_line_with_an_edit_date_is_already_edited(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="first", edit_date=NOW + timedelta(hours=1)))
    assert reader.search(SearchQuery("first")).hits[0].edited is True
    put(index, msg(1, text="second", edit_date=NOW + timedelta(hours=2)))
    assert ids(reader, "second") == [1]
    put(index, msg(1, text="third"))
    assert ids(reader, "third") == []
    assert ids(reader, "second") == [1]


def test_an_edit_seen_before_its_message_waits_for_it(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, edit(1, "edited text", hours=1))
    assert ids(reader, "edited text") == []
    put(index, msg(1, text="original text"))
    assert ids(reader, "original text") == []
    page = reader.search(SearchQuery("edited text"))
    assert [(hit.msg_id, hit.edited) for hit in page.hits] == [(1, True)]


def test_the_newest_waiting_edit_wins_in_either_order(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, edit(1, "version one", hours=1), edit(1, "version two", hours=2))
    put(index, edit(2, "version two b", hours=2), edit(2, "version one b", hours=1))
    put(index, msg(1, text="x"), msg(2, text="y"))
    assert ids(reader, "version two") == [2, 1]
    assert ids(reader, "version one") == []


def test_a_message_line_newer_than_a_waiting_edit_keeps_its_own_text(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, edit(1, "older edit", hours=1))
    put(index, msg(1, text="newer line", edit_date=NOW + timedelta(hours=2)))
    assert ids(reader, "newer line") == [1]
    assert ids(reader, "older edit") == []


def test_deleted_messages_leave_the_results(index: SearchIndex, reader: SearchBackend) -> None:
    put(index, msg(1, text="keep one"), msg(2, text="keep two"), msg(3, text="keep three"))
    assert put(index, delete(1, 3)) == -2
    assert ids(reader, "keep") == [2]
    assert index.indexed_count() == 1
    assert put(index, delete(99)) == 0


def test_a_delete_is_final_whatever_order_it_is_seen_in(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, delete(5))
    put(index, msg(5, text="late message"))
    assert ids(reader, "late message") == []
    put(index, msg(6, text="plain message"))
    put(index, delete(6))
    put(index, msg(6, text="plain message"))
    assert ids(reader, "message") == []
    assert index.indexed_count() == 0


def test_an_edit_of_a_deleted_message_is_dropped(index: SearchIndex, reader: SearchBackend) -> None:
    put(index, delete(1))
    put(index, edit(1, "late edit", hours=1))
    put(index, msg(1, text="back again"))
    assert ids(reader, "back again") == []
    assert ids(reader, "late edit") == []


def test_service_messages_are_skipped_and_empty_ones_can_gain_text(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="joined the group", service="join"), msg(2, text=""))
    assert ids(reader, "joined") == []
    assert index.indexed_count() == 1
    put(index, edit(2, "caption added later", hours=1))
    assert ids(reader, "caption") == [2]


def test_other_record_kinds_are_ignored(index: SearchIndex) -> None:
    assert put(index, MediaSavedRecord(CHAT_ID, 1, "file.jpg", NOW)) == 0
    assert index.indexed_count() == 0


def test_text_with_lone_surrogates_is_stored_cleaned(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="a" + chr(0xD800) + "bcd"))
    assert ids(reader, "a" + chr(0xD800) + "bc") == [1]
    assert reader.search(SearchQuery("a?bc")).hits[0].text == "a?bcd"


def test_remove_below_forgets_the_trimmed_history(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(3, text="m three"), msg(4, text="m four"), msg(5, text="m five"))
    put(index, edit(1, "waiting edit", hours=1), delete(2, 9))
    assert index.remove_below(CHAT_ID, 4) == 1
    assert ids(reader, "m ") == [5, 4]
    assert index.remove_below(CHAT_ID, 4) == 0
    put(index, msg(1, text="uno"), msg(2, text="dos"), msg(9, text="nueve"))
    assert ids(reader, "uno") == [1]
    assert reader.search(SearchQuery("uno")).hits[0].edited is False
    assert ids(reader, "dos") == [2]
    assert ids(reader, "nueve") == []
    assert index.indexed_count() == 4


def test_drop_chat_removes_everything_of_one_chat(
    index: SearchIndex, reader: SearchBackend
) -> None:
    index.upsert_chat(OTHER_CHAT, "Other", None, "other_folder")
    mark = PartMark("2026-10_001.jsonl", 1, 2, 3, 4, 5)
    index.apply(CHAT_ID, [msg(1, text="shared word"), delete(7)], [mark])
    index.apply(OTHER_CHAT, [msg(1, chat_id=OTHER_CHAT, text="shared word")], [mark])
    index.drop_chat(CHAT_ID)
    assert pairs(reader, "shared") == [(OTHER_CHAT, 1)]
    assert CHAT_ID not in index.chat_rows()
    assert index.marks(CHAT_ID) == {}
    assert index.marks(OTHER_CHAT) == {mark.part: mark}
    assert index.indexed_count() == 1


def test_a_reconcile_keeps_results_visible_and_sweeps_what_is_gone(
    index: SearchIndex, reader: SearchBackend
) -> None:
    mark = PartMark("2026-10_001.jsonl", 1, 2, 3, 4, 5)
    index.apply(
        CHAT_ID, [msg(1, text="keep 1"), msg(2, text="gone 2"), msg(3, text="keep 3")], [mark]
    )
    index.apply(CHAT_ID, [delete(5)])
    index.begin_reconcile(CHAT_ID)
    row = index.chat_rows()[CHAT_ID]
    assert (row.gen, row.reconciling) == (1, True)
    assert index.marks(CHAT_ID) == {}
    assert sorted(ids(reader, "keep") + ids(reader, "gone")) == [1, 2, 3]

    put(index, edit(3, "keep 3 edited", hours=1))
    put(index, msg(1, text="keep 1 renewed"), msg(3, text="keep 3"), msg(5, text="was deleted"))
    index.finish_reconcile(CHAT_ID)

    row = index.chat_rows()[CHAT_ID]
    assert (row.gen, row.reconciling, row.messages) == (1, False, 3)
    assert ids(reader, "gone") == []
    assert ids(reader, "keep 3 edited") == [3]
    assert reader.search(SearchQuery("keep 3 edited")).hits[0].edited is True
    assert ids(reader, "keep 1 renewed") == [1]
    assert ids(reader, "was deleted") == [5]
    assert index.indexed_count() == 3


def test_marks_are_stored_replaced_and_forgotten(index: SearchIndex) -> None:
    first = PartMark("2026-10_001.jsonl", 10, 20, 30, 40, 50)
    second = PartMark("2026-10_002.jsonl", 1, 2, 3, 4, 5)
    assert put(index) == 0
    index.apply(CHAT_ID, [], [first, second])
    assert index.marks(CHAT_ID) == {first.part: first, second.part: second}
    moved = PartMark(first.part, 99, 120, 130, 140, 150)
    index.apply(CHAT_ID, [], [moved])
    assert index.marks(CHAT_ID)[first.part] == moved
    index.forget_parts(CHAT_ID, [second.part])
    assert set(index.marks(CHAT_ID)) == {first.part}
    index.begin_reconcile(CHAT_ID)
    assert index.marks(CHAT_ID) == {}


def test_chat_rows_follow_upserts_and_counts(index: SearchIndex) -> None:
    assert index.chat_rows() == {
        CHAT_ID: ChatRow(CHAT_ID, "Chat", "pub", "chat_folder", 0, False, 0)
    }
    index.upsert_chat(CHAT_ID, "New\x00 title", None, "renamed")
    put(index, msg(1, text="one"), msg(2, text="two"))
    assert index.chat_rows() == {
        CHAT_ID: ChatRow(CHAT_ID, "New title", None, "renamed", 0, False, 2)
    }
    put(index, msg(7, chat_id=-9, text="three"), chat_id=-9)
    assert index.chat_rows()[-9] == ChatRow(-9, "", None, "", 0, False, 1)


def test_status_before_during_and_after_the_build(
    index: SearchIndex, reader: SearchBackend
) -> None:
    assert reader.status() == IndexStatus(IndexState.BUILDING, 0, 0, None)
    put(index, msg(1, text="one"), msg(2, text="two"), msg(3, text="three"))
    index.set_status(IndexState.BUILDING, 10, NOW)
    assert reader.status() == IndexStatus(IndexState.BUILDING, 3, 10, NOW)
    index.set_status(IndexState.BUILDING, 1, NOW)
    assert reader.status().total == 3
    later = NOW + timedelta(minutes=5)
    index.set_status(IndexState.READY, 99, later)
    status = reader.status()
    assert status == IndexStatus(IndexState.READY, 3, 3, later)
    assert status.updated_at is not None
    assert status.updated_at.utcoffset() == timedelta(0)


def test_garbage_in_the_meta_table_is_survived(index: SearchIndex, reader: SearchBackend) -> None:
    put(index, msg(1, text="one"))
    index.set_status(IndexState.READY, 1, NOW)
    index._conn.execute("UPDATE meta SET value = 'bogus'")
    assert reader.status() == IndexStatus(IndexState.BUILDING, 1, 1, None)


def test_chats_are_listed_by_title_with_message_counts(
    index: SearchIndex, reader: SearchBackend
) -> None:
    index.upsert_chat(-2, "beta", None, "beta_2")
    index.upsert_chat(-3, "", None, "zeta_3")
    index.upsert_chat(-4, "Empty", None, "empty_4")
    index.upsert_chat(-1, "Alpha", None, "alpha_1")
    for chat_id, count in ((-1, 2), (-2, 1), (-3, 3)):
        put(
            index,
            *(msg(i, chat_id=chat_id, text=f"word {i}") for i in range(1, count + 1)),
            chat_id=chat_id,
        )
    put(index, msg(1, text="x"))
    titles = [(c.chat_id, c.title, c.messages) for c in reader.chats()]
    assert titles == [(-1, "Alpha", 2), (-2, "beta", 1), (CHAT_ID, "Chat", 1), (-3, "zeta_3", 3)]


def test_context_returns_the_neighbours_with_edits_and_without_deletions(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, *(msg(i, text=f"m{i}") for i in range(1, 8)))
    put(index, edit(4, "m4 edited", hours=1), delete(6))
    around = reader.context(CHAT_ID, 5, before=2, after=2)
    assert [m.msg_id for m in around] == [3, 4, 5, 7]
    assert [m.is_target for m in around] == [False, False, True, False]
    assert around[1].text == "m4 edited"
    assert around[1].edited is True
    assert around[2].date == msg(5).date
    assert around[2].edited is False
    assert [m.msg_id for m in reader.context(CHAT_ID, 5)] == [2, 3, 4, 5, 7]
    assert [m.msg_id for m in reader.context(CHAT_ID, 5, before=-1, after=0)] == [5]
    assert [m.msg_id for m in reader.context(CHAT_ID, 7, before=10**6, after=10**6)] == [
        1,
        2,
        3,
        4,
        5,
        7,
    ]


def test_context_of_a_missing_message_is_empty(index: SearchIndex, reader: SearchBackend) -> None:
    put(index, msg(1, text="one"))
    assert reader.context(CHAT_ID, 2) == ()
    assert reader.context(OTHER_CHAT, 1) == ()


READER_CALLS: list[Callable[[SearchBackend], object]] = [
    lambda r: r.search(SearchQuery("anything")),
    lambda r: r.context(CHAT_ID, 1),
    lambda r: r.chats(),
    lambda r: r.status(),
]


@pytest.mark.parametrize("call", READER_CALLS)
def test_a_closed_reader_raises_a_search_error(
    reader: SearchBackend, call: Callable[[SearchBackend], object]
) -> None:
    reader.close()
    with pytest.raises(SearchError, match="cannot be read"):
        call(reader)
    reader.close()


def test_a_reader_may_be_used_from_another_thread(
    index: SearchIndex, reader: SearchBackend
) -> None:
    put(index, msg(1, text="threaded"))
    totals: list[int] = []
    worker = threading.Thread(
        target=lambda: totals.append(reader.search(SearchQuery("thread")).total)
    )
    worker.start()
    worker.join()
    assert totals == [1]


def test_a_failing_batch_is_rolled_back_whole(index: SearchIndex, reader: SearchBackend) -> None:
    def broken() -> Iterator[Record]:
        yield msg(1, text="inserted first")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        index.apply(CHAT_ID, broken())
    assert index.indexed_count() == 0
    assert ids(reader, "inserted") == []
    assert put(index, msg(2, text="works again")) == 1


def test_fts_phrases_double_their_quotes() -> None:
    assert fts_phrase('a"b') == '"a""b"'
    assert fts_phrase("plain") == '"plain"'


def test_there_is_no_reader_without_a_file(tmp_path: Path) -> None:
    assert open_reader(tmp_path) is None


def test_a_writer_needs_fts5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_index, "fts5_trigram_available", lambda: False)
    with pytest.raises(SearchError, match="FTS5"):
        open_writer(tmp_path)
    assert not database_path(tmp_path).exists()


def test_reset_index_deletes_the_file_and_a_new_writer_starts_empty(tmp_path: Path) -> None:
    first = open_writer(tmp_path)
    first.upsert_chat(1, "Chat", None, "folder")
    first.close()
    reset_index(tmp_path)
    assert not database_path(tmp_path).exists()
    second = open_writer(tmp_path)
    try:
        assert second.chat_rows() == {}
    finally:
        second.close()
