from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatradar.pipeline.base import NORMALIZE_VERSION
from tests.integration.storage.helpers import CHAT, OTHER, make_message

if TYPE_CHECKING:
    from chatradar.storage.db.repositories import SqlRepository

pytestmark = pytest.mark.integration


async def _fill(repo: SqlRepository) -> None:
    await repo.upsert_chats([CHAT, OTHER])
    batch = [make_message(i, chat=CHAT) for i in range(1, 8)]
    batch += [make_message(i, chat=OTHER) for i in range(1, 4)]
    # Same instant for two messages: the id decides.
    batch += [make_message(20, chat=CHAT, minutes=3), make_message(9, chat=OTHER, minutes=1)]
    await repo.upsert_many(batch, NORMALIZE_VERSION)


async def _collect(repo: SqlRepository, size: int) -> list[list[tuple[str, str, str]]]:
    return [
        [(m.chat_id, m.date.isoformat(), m.msg_id) for m in batch]
        async for batch in repo.iter_all(size)
    ]


async def test_iter_all_orders_by_source_chat_date_and_id(repo: SqlRepository) -> None:
    await _fill(repo)

    flat = [row for batch in await _collect(repo, 2000) for row in batch]

    assert len(flat) == 12
    assert flat == sorted(flat, key=lambda r: (r[0], r[1], r[2]))


@pytest.mark.parametrize("size", [1, 2, 5, 12, 13])
async def test_batches_are_complete_and_ordered_like_one_big_batch(
    repo: SqlRepository, size: int
) -> None:
    await _fill(repo)
    whole = [row for batch in await _collect(repo, 2000) for row in batch]

    batches = await _collect(repo, size)

    assert [row for batch in batches for row in batch] == whole
    assert all(len(batch) == size for batch in batches[:-1])
    assert 0 < len(batches[-1]) <= size


async def test_iter_all_on_an_empty_database(repo: SqlRepository) -> None:
    assert await _collect(repo, 10) == []


async def test_iter_all_rejects_a_bad_batch_size(repo: SqlRepository) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        await anext(repo.iter_all(0))
