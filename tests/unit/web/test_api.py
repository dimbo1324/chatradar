from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from chatradar import __version__
from chatradar.domain.models import MessageFilter, SearchFilters, Source
from tests.unit.web.fakes import CHAT, STAGES

if TYPE_CHECKING:
    from tests.unit.web.conftest import Panel

THREAD_ID = f"{CHAT.chat_id}:1"


def test_healthz(panel: Panel) -> None:
    response = panel.client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_chats_returns_summaries(panel: Panel) -> None:
    body = panel.client.get("/api/chats").json()

    assert len(body) == 1
    assert body[0]["chat"]["chat_id"] == CHAT.chat_id
    assert body[0]["message_count"] == 4
    assert body[0]["noise_count"] == 1
    assert body[0]["first_message_at"] == "2026-10-01T09:00:00Z"


def test_pipeline_passes_stage_versions(panel: Panel) -> None:
    body = panel.client.get("/api/pipeline").json()

    assert body["total_messages"] == 4
    assert [s["stage"] for s in body["stages"]] == [name for name, _ in STAGES]
    assert panel.queries.calls == [("pipeline_stats", list(STAGES))]


def test_messages_defaults(panel: Panel) -> None:
    body = panel.client.get("/api/messages").json()

    assert body["total"] == 4
    assert (body["limit"], body["offset"]) == (50, 0)
    assert panel.queries.calls == [("list_messages", MessageFilter())]


def test_messages_parses_every_filter(panel: Panel) -> None:
    params = {
        "source": "telegram",
        "chat_id": CHAT.chat_id,
        "date_from": "2026-10-01T00:00:00Z",
        "date_to": "2026-10-02T00:00:00+03:00",
        "lang": "ru",
        "is_noise": "false",
        "noise_reason": "short",
        "is_question": "true",
        "thread_id": THREAD_ID,
        "limit": "10",
        "offset": "5",
    }

    response = panel.client.get("/api/messages", params=params)

    assert response.status_code == 200
    assert panel.queries.calls == [
        (
            "list_messages",
            MessageFilter(
                source=Source.TELEGRAM,
                chat_id=CHAT.chat_id,
                date_from=datetime(2026, 10, 1, tzinfo=UTC),
                date_to=datetime(2026, 10, 1, 21, tzinfo=UTC),
                lang="ru",
                is_noise=False,
                noise_reason="short",
                is_question=True,
                thread_id=THREAD_ID,
                limit=10,
                offset=5,
            ),
        )
    ]


def test_messages_filters_and_pages(panel: Panel) -> None:
    body = panel.client.get("/api/messages", params={"is_noise": "true"}).json()
    paged = panel.client.get("/api/messages", params={"limit": 2, "offset": 2}).json()

    assert [m["noise_reason"] for m in body["items"]] == ["short"]
    assert [m["msg_id"] for m in paged["items"]] == ["3", "4"]
    assert paged["total"] == 4


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "501"},
        {"offset": "-1"},
        {"limit": "ten"},
        {"source": "icq"},
        {"is_noise": "maybe"},
        {"date_from": "2026-10-01T00:00:00"},
        {"date_to": "yesterday"},
    ],
)
def test_messages_rejects_invalid_parameters(panel: Panel, params: dict[str, str]) -> None:
    response = panel.client.get("/api/messages", params=params)

    assert response.status_code == 422
    assert panel.queries.calls == []


def test_messages_accepts_the_limit_bounds(panel: Panel) -> None:
    assert panel.client.get("/api/messages", params={"limit": 1}).status_code == 200
    assert panel.client.get("/api/messages", params={"limit": 500}).status_code == 200


@pytest.mark.parametrize("path", ["/api/threads/-100500%3A1", "/api/threads/-100500:1"])
def test_thread_with_colon_id(panel: Panel, path: str) -> None:
    response = panel.client.get(path)

    assert response.status_code == 200
    body = response.json()
    assert body["thread"]["thread_id"] == THREAD_ID
    assert [m["msg_id"] for m in body["messages"]] == ["1", "2", "3"]
    assert panel.queries.calls == [("get_thread", THREAD_ID)]


def test_unknown_thread_is_404(panel: Panel) -> None:
    response = panel.client.get("/api/threads/-100500%3A999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Thread not found"}


def test_search_returns_hits_with_markers(panel: Panel) -> None:
    body = panel.client.get("/api/search", params={"q": "online"}).json()

    assert len(body) == 1
    assert body[0]["thread"]["thread_id"] == THREAD_ID
    assert "[[online]]" in body[0]["snippet"]
    assert body[0]["link"] == "https://t.me/demo/1"
    assert panel.search.calls == [("online", SearchFilters())]


def test_search_parses_filters(panel: Panel) -> None:
    params = {
        "q": "permit",
        "source": "telegram",
        "chat_id": CHAT.chat_id,
        "date_from": "2026-10-01T00:00:00Z",
        "date_to": "2026-10-03T00:00:00Z",
        "limit": "5",
    }

    assert panel.client.get("/api/search", params=params).status_code == 200
    assert panel.search.calls == [
        (
            "permit",
            SearchFilters(
                source=Source.TELEGRAM,
                chat_id=CHAT.chat_id,
                date_from=datetime(2026, 10, 1, tzinfo=UTC),
                date_to=datetime(2026, 10, 3, tzinfo=UTC),
                limit=5,
            ),
        )
    ]


@pytest.mark.parametrize("q", ["", "   "])
def test_empty_search_returns_nothing_without_the_index(panel: Panel, q: str) -> None:
    response = panel.client.get("/api/search", params={"q": q})

    assert response.status_code == 200
    assert response.json() == []
    assert panel.search.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": "x", "limit": "0"},
        {"q": "x", "limit": "101"},
        {"q": "x", "source": "icq"},
        {"q": "x", "date_from": "2026-10-01T00:00:00"},
    ],
)
def test_search_rejects_invalid_parameters(panel: Panel, params: dict[str, str]) -> None:
    assert panel.client.get("/api/search", params=params).status_code == 422
    assert panel.search.calls == []


def test_review_samples_each_side(panel: Panel) -> None:
    noise = panel.client.get("/api/review", params={"noise": "true"}).json()
    clean = panel.client.get("/api/review", params={"noise": "false", "n": "2"}).json()

    assert [m["msg_id"] for m in noise] == ["4"]
    assert len(clean) == 2
    assert panel.queries.calls == [("sample", (True, 100)), ("sample", (False, 2))]


@pytest.mark.parametrize(
    "params", [{}, {"noise": "maybe"}, {"noise": "true", "n": "0"}, {"noise": "true", "n": "201"}]
)
def test_review_rejects_invalid_parameters(panel: Panel, params: dict[str, str]) -> None:
    assert panel.client.get("/api/review", params=params).status_code == 422
    assert panel.queries.calls == []


def test_noise_reasons(panel: Panel) -> None:
    assert panel.client.get("/api/noise-reasons").json() == {"short": 1}
