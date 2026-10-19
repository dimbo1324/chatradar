from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from chatradar.domain.lexicon import LexiconKind, TermDecision, TermStatus
from chatradar.pipeline.noise import NOISE_REASONS
from chatradar.web.app import create_app
from tests.unit.web.fakes import message, sample_data
from tests.unit.web.fakes_feedback import FeedbackKit, bare_read

if TYPE_CHECKING:
    from collections.abc import Iterator

WRITE = {"X-Requested-With": "chatradar"}
DECISION = {"kind": "gratitude", "lang": "ru", "term": "thanks", "decision": "accept"}
LABEL = {"source": "telegram", "chat_id": "-100500", "msg_id": "4", "is_noise": True}


@pytest.fixture
def kit() -> FeedbackKit:
    return FeedbackKit()


@pytest.fixture
def client(kit: FeedbackKit) -> Iterator[TestClient]:
    with TestClient(create_app(kit.read, kit.feedback)) as test_client:
        yield test_client


def post(client: TestClient, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
    return client.post(path, json=body, headers=WRITE if headers is None else headers)


def test_summary(client: TestClient) -> None:
    body = client.get("/api/lexicon/summary").json()

    assert body["revision"] == 3
    assert body["pending_apply"] is True
    assert body["by_status"] == {"candidate": 2}
    assert body["labels"] == 0


def test_terms_defaults_and_page(client: TestClient, kit: FeedbackKit) -> None:
    body = client.get("/api/lexicon/terms").json()

    assert kit.lexicon.list_calls[-1] == {
        "kind": None,
        "status": None,
        "lang": None,
        "order": "score",
        "limit": 100,
        "offset": 0,
    }
    assert body["total"] == 2
    assert [item["term"] for item in body["items"]] == ["thanks", "gracias"]


def test_terms_filters_are_delegated(client: TestClient, kit: FeedbackKit) -> None:
    response = client.get(
        "/api/lexicon/terms",
        params={
            "kind": "gratitude",
            "status": "candidate",
            "lang": "es",
            "order": "recent",
            "limit": 5,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    assert kit.lexicon.list_calls[-1] == {
        "kind": LexiconKind.GRATITUDE,
        "status": TermStatus.CANDIDATE,
        "lang": "es",
        "order": "recent",
        "limit": 5,
        "offset": 1,
    }
    assert response.json()["items"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"kind": "nope"},
        {"status": "nope"},
        {"order": "nope"},
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
    ],
)
def test_terms_validation(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/api/lexicon/terms", params=params).status_code == 422


def test_decision_accepts_a_term(client: TestClient, kit: FeedbackKit) -> None:
    response = post(client, "/api/lexicon/decision", {**DECISION, "note": "ok"})

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["decided_by"] == "human"
    assert kit.lexicon.decide_calls == [
        (LexiconKind.GRATITUDE, "ru", "thanks", TermDecision.ACCEPT, "human", "ok")
    ]


def test_decision_unknown_term_is_404(client: TestClient) -> None:
    response = post(client, "/api/lexicon/decision", {**DECISION, "term": "missing"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Term not found"}


@pytest.mark.parametrize(
    "body",
    [
        {**DECISION, "decision": "maybe"},
        {**DECISION, "kind": "nope"},
        {**DECISION, "term": ""},
        {**DECISION, "extra": 1},
        {"kind": "gratitude", "term": "thanks", "decision": "accept"},
        {**DECISION, "note": "x" * 501},
    ],
)
def test_decision_validation(client: TestClient, body: dict[str, Any]) -> None:
    assert post(client, "/api/lexicon/decision", body).status_code == 422


def test_label_is_saved_and_listed(client: TestClient, kit: FeedbackKit) -> None:
    response = post(client, "/api/labels", {**LABEL, "reason": "short", "is_question": False})

    assert response.status_code == 200
    saved = response.json()
    assert (saved["msg_id"], saved["is_noise"], saved["reason"], saved["by"]) == (
        "4",
        True,
        "short",
        "human",
    )
    assert len(kit.labels.saved) == 1
    assert [row["msg_id"] for row in client.get("/api/labels").json()] == ["4"]
    assert kit.labels.list_limits == [5000]


def test_labels_limit(client: TestClient, kit: FeedbackKit) -> None:
    client.get("/api/labels", params={"limit": 7})

    assert kit.labels.list_limits == [7]
    assert client.get("/api/labels", params={"limit": 0}).status_code == 422
    assert client.get("/api/labels", params={"limit": 5001}).status_code == 422


def test_label_unknown_message_is_404(client: TestClient) -> None:
    response = post(client, "/api/labels", {**LABEL, "msg_id": "999"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Message not found"}


def test_label_reason_without_noise_is_422(client: TestClient, kit: FeedbackKit) -> None:
    response = post(client, "/api/labels", {**LABEL, "is_noise": False, "reason": "short"})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert kit.labels.saved == []


def test_label_unknown_reason_is_422(client: TestClient) -> None:
    assert post(client, "/api/labels", {**LABEL, "reason": "nope"}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {**LABEL, "source": "icq"},
        {**LABEL, "is_noise": "maybe"},
        {**LABEL, "extra": 1},
        {"source": "telegram", "chat_id": "-100500", "msg_id": "4"},
        {**LABEL, "msg_id": ""},
    ],
)
def test_label_validation(client: TestClient, body: dict[str, Any]) -> None:
    assert post(client, "/api/labels", body).status_code == 422


def test_quality(client: TestClient) -> None:
    body = client.get("/api/quality").json()

    assert body["source"] == "human-labels"
    assert body["total"] == 0
    assert body["lexicon_revision"] == 3


def test_noise_reason_list_is_sorted(client: TestClient) -> None:
    assert client.get("/api/noise-reason-list").json() == sorted(NOISE_REASONS)


def test_single_message(client: TestClient) -> None:
    response = client.get("/api/messages/telegram/-100500/2")

    assert response.status_code == 200
    assert response.json()["msg_id"] == "2"
    assert response.json()["chat_id"] == "-100500"


def test_single_message_unknown_is_404(client: TestClient) -> None:
    response = client.get("/api/messages/telegram/-100500/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Message not found"}


def test_single_message_bad_source_is_422(client: TestClient) -> None:
    assert client.get("/api/messages/icq/-100500/2").status_code == 422


def test_single_message_ids_with_dash_and_colon() -> None:
    odd = message(1, "odd ids").model_copy(update={"chat_id": "-1001:x-y", "msg_id": "5:6-7"})
    kit = FeedbackKit([*sample_data()[1], odd])

    with TestClient(create_app(kit.read, kit.feedback)) as client:
        response = client.get("/api/messages/telegram/-1001:x-y/5:6-7")

    assert response.status_code == 200
    assert response.json()["msg_id"] == "5:6-7"


def test_missing_optional_services_give_503() -> None:
    with TestClient(create_app(bare_read())) as client:
        for path in (
            "/api/lexicon/summary",
            "/api/lexicon/terms",
            "/api/labels",
            "/api/quality",
            "/api/messages/telegram/-100500/1",
        ):
            response = client.get(path)
            assert response.status_code == 503, path
            assert "without" in response.json()["detail"]
        assert post(client, "/api/labels", LABEL).status_code == 503
        assert post(client, "/api/lexicon/decision", DECISION).status_code == 503


def test_guard_requires_the_header(client: TestClient, kit: FeedbackKit) -> None:
    response = post(client, "/api/labels", LABEL, headers={})

    assert response.status_code == 403
    assert "detail" in response.json()
    assert kit.labels.saved == []


def test_guard_rejects_a_wrong_header_value(client: TestClient) -> None:
    response = post(client, "/api/lexicon/decision", DECISION, headers={"X-Requested-With": "x"})

    assert response.status_code == 403


def test_guard_rejects_a_foreign_origin(client: TestClient, kit: FeedbackKit) -> None:
    headers = {**WRITE, "Origin": "http://evil.example"}

    assert post(client, "/api/labels", LABEL, headers).status_code == 403
    assert kit.labels.saved == []


@pytest.mark.parametrize(
    "origin", ["https://testserver", "http://testserver:8000", "null", "http://testserver/x"]
)
def test_guard_rejects_lookalike_origins(client: TestClient, origin: str) -> None:
    assert post(client, "/api/labels", LABEL, {**WRITE, "Origin": origin}).status_code == 403


@pytest.mark.parametrize("origin", ["http://testserver", "http://testserver:80"])
def test_guard_accepts_the_same_origin(client: TestClient, origin: str) -> None:
    assert post(client, "/api/labels", LABEL, {**WRITE, "Origin": origin}).status_code == 200


def test_guard_leaves_get_alone(client: TestClient) -> None:
    response = client.get("/api/labels", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200


def test_guard_covers_every_unsafe_method(client: TestClient) -> None:
    assert client.put("/api/labels", json=LABEL).status_code == 403
    assert client.delete("/api/labels").status_code == 403


def assert_secured(response: Any, status: int) -> None:
    assert response.status_code == status
    assert "content-security-policy" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_guard_rejection_keeps_the_security_headers(client: TestClient) -> None:
    assert_secured(post(client, "/api/labels", LABEL, headers={}), 403)


def test_not_found_keeps_the_security_headers(client: TestClient) -> None:
    assert_secured(post(client, "/api/labels", {**LABEL, "msg_id": "999"}), 404)


def test_validation_error_keeps_the_security_headers(client: TestClient) -> None:
    assert_secured(post(client, "/api/labels", {}), 422)


def test_unavailable_keeps_the_security_headers() -> None:
    with TestClient(create_app(bare_read())) as client:
        assert_secured(client.get("/api/quality"), 503)
