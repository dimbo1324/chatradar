from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from chatradar.pipeline.threads import GAP, ThreadsStage, group_threads
from tests.unit.pipeline.fakes import CHAT_ID, T0, make_deps, make_message

if TYPE_CHECKING:
    from chatradar.domain.models import StoredMessage

READY = {"noise": 1, "enrich": 1}
DAY = 24 * 60


def _ready(
    msg_id: int,
    text: str = "text",
    *,
    minutes: float = 0,
    reply_to: int | None = None,
    topic_id: str | None = None,
    is_question: bool = False,
) -> StoredMessage:
    """A message that went through noise and enrich as useful."""
    return make_message(
        msg_id,
        text,
        minutes=minutes,
        reply_to=reply_to,
        topic_id=topic_id,
        is_noise=False,
        is_question=is_question,
        versions=READY,
    )


def _groups(messages: list[StoredMessage]) -> list[set[str]]:
    assigned = group_threads(messages)
    by_thread: dict[str, set[str]] = {}
    for msg_id, thread in assigned.items():
        by_thread.setdefault(thread.thread_id, set()).add(msg_id)
    return sorted(by_thread.values(), key=lambda ids: min(int(i) for i in ids))


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        pytest.param(
            [
                _ready(1, minutes=0),
                _ready(2, minutes=60, reply_to=1),
                _ready(3, minutes=120, reply_to=2),
            ],
            [{"1", "2", "3"}],
            id="reply-chain-across-long-gaps",
        ),
        pytest.param(
            [_ready(1, minutes=0), _ready(2, minutes=10), _ready(3, minutes=50)],
            [{"1", "2"}, {"3"}],
            id="gap-splits",
        ),
        pytest.param(
            [_ready(1, minutes=0), _ready(2, minutes=GAP.total_seconds() / 60)],
            [{"1"}, {"2"}],
            id="gap-exactly-limit-splits",
        ),
        pytest.param(
            [_ready(1, minutes=0), _ready(2, minutes=29), _ready(3, minutes=58)],
            [{"1", "2", "3"}],
            id="gaps-chain-through-each-previous-message",
        ),
        pytest.param(
            [
                _ready(1, minutes=0, topic_id="7"),
                _ready(2, minutes=1, topic_id="8"),
                _ready(3, minutes=2, topic_id="7"),
                _ready(4, minutes=3),
            ],
            [{"1", "3"}, {"2"}, {"4"}],
            id="forum-topics-group-separately",
        ),
        pytest.param(
            [_ready(1, minutes=0), _ready(2, minutes=90, reply_to=999)],
            [{"1"}, {"2"}],
            id="reply-to-unknown-message-uses-the-gap-rule",
        ),
        pytest.param(
            [
                _ready(1, minutes=0),
                _ready(2, minutes=5),
                _ready(3, minutes=100),
                _ready(4, minutes=101, reply_to=1),
                _ready(5, minutes=102),
            ],
            [{"1", "2", "4", "5"}, {"3"}],
            id="message-without-reply-joins-the-previous-thread",
        ),
        pytest.param(
            [_ready(10, minutes=0), _ready(9, minutes=0)],
            [{"9", "10"}],
            id="same-time-numeric-ids",
        ),
    ],
)
def test_grouping(messages: list[StoredMessage], expected: list[set[str]]) -> None:
    assert _groups(messages) == expected


def test_thread_fields() -> None:
    assigned = group_threads(
        [
            _ready(11, minutes=1, reply_to=9, topic_id="3"),
            _ready(9, minutes=0, topic_id="3"),
            _ready(12, "Anyone selling a heater?", minutes=20, is_question=True, topic_id="3"),
        ]
    )
    thread = assigned["11"]
    assert {t.thread_id for t in assigned.values()} == {f"{CHAT_ID}:9"}
    assert thread.root_msg_id == "9"
    assert thread.topic_id == "3"
    assert thread.started_at == T0
    assert thread.ended_at == T0 + timedelta(minutes=20)
    assert thread.msg_count == 3
    assert thread.has_question is True


def test_without_questions_has_question_is_false() -> None:
    assert group_threads([_ready(1, is_question=False)])["1"].has_question is False


async def test_stage_gives_noise_no_thread_and_ignores_unready_messages() -> None:
    deps, repo, _ = make_deps(
        [
            _ready(1, minutes=0),
            make_message(2, "+", minutes=1, is_noise=True, versions=READY),
            _ready(3, minutes=2, reply_to=2),
            make_message(4, "not enriched yet", minutes=3, versions={"noise": 1}),
        ]
    )
    stage = ThreadsStage()

    assert await stage.run(deps, limit=100) == 3
    assert await stage.run(deps, limit=100) == 0
    assert repo.row(1).thread_id == f"{CHAT_ID}:1"
    assert repo.row(2).thread_id is None
    assert repo.row(3).thread_id == f"{CHAT_ID}:1"
    assert "threads" not in repo.row(4).versions
    assert repo.threads[f"{CHAT_ID}:1"].msg_count == 2


async def test_incremental_run_recomputes_only_the_tail() -> None:
    deps, repo, _ = make_deps([_ready(1, minutes=0), _ready(2, minutes=5)])
    stage = ThreadsStage()
    await stage.run(deps, limit=100)
    repo.add(_ready(3, minutes=10 * DAY), _ready(4, minutes=10 * DAY + 3))

    assert await stage.run(deps, limit=100) == 2
    assert repo.window_calls[-1] == (CHAT_ID, T0 + timedelta(days=8))
    assert set(repo.threads) == {f"{CHAT_ID}:1", f"{CHAT_ID}:3"}
    assert repo.threads[f"{CHAT_ID}:1"].msg_count == 2
    assert repo.row(4).thread_id == f"{CHAT_ID}:3"
    assert repo.row(1).versions["threads"] == 1


async def test_reply_to_an_old_thread_adopts_it_and_refreshes_its_stats() -> None:
    deps, repo, _ = make_deps(
        [_ready(1, minutes=0), _ready(2, minutes=5), _ready(3, minutes=2 * DAY)]
    )
    stage = ThreadsStage()
    await stage.run(deps, limit=100)
    late_answer = _ready(4, "It reopened last week", minutes=10 * DAY, reply_to=2)
    repo.add(late_answer)

    assert await stage.run(deps, limit=100) == 4, "the window widens to the old thread"
    assert repo.row(4).thread_id == f"{CHAT_ID}:1"
    thread = repo.threads[f"{CHAT_ID}:1"]
    assert thread.msg_count == 3
    assert thread.ended_at == late_answer.date
    assert repo.window_calls[-1] == (CHAT_ID, T0)
    assert set(repo.threads) == {f"{CHAT_ID}:1", f"{CHAT_ID}:3"}


async def test_late_message_merges_threads_and_drops_the_old_one() -> None:
    deps, repo, _ = make_deps([_ready(1, minutes=0), _ready(3, minutes=40)])
    stage = ThreadsStage()
    await stage.run(deps, limit=100)
    assert set(repo.threads) == {f"{CHAT_ID}:1", f"{CHAT_ID}:3"}
    repo.add(_ready(2, minutes=20))

    await stage.run(deps, limit=100)
    assert set(repo.threads) == {f"{CHAT_ID}:1"}
    assert {repo.row(i).thread_id for i in (1, 2, 3)} == {f"{CHAT_ID}:1"}
