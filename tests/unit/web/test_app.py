from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient

from chatradar.config import Settings
from chatradar.web.app import create_app
from tests.unit.web.fakes import build_read_services

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import pytest

    from chatradar.services.queries import ReadServices


FEEDBACK = object()  # stands in for FeedbackServices; the app only stores it


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch, read: ReadServices, events: list[str] | None = None
) -> None:
    @asynccontextmanager
    async def open_runtime(settings: Settings) -> AsyncGenerator[Any]:
        assert isinstance(settings, Settings)
        if events is not None:
            events.append("open")
        yield SimpleNamespace(read=read, feedback=FEEDBACK)
        if events is not None:
            events.append("close")

    monkeypatch.setattr("chatradar.web.app.open_runtime", open_runtime)


def test_without_services_the_runtime_provides_them(monkeypatch: pytest.MonkeyPatch) -> None:
    read, _, _ = build_read_services()
    _install_runtime(monkeypatch, read)

    with TestClient(create_app()) as client:
        assert client.app.state.read is read  # type: ignore[attr-defined]
        assert client.app.state.feedback is FEEDBACK  # type: ignore[attr-defined]
        assert client.get("/api/noise-reasons").json() == {"short": 1}


def test_runtime_is_closed_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    read, _, _ = build_read_services()
    events: list[str] = []
    _install_runtime(monkeypatch, read, events)

    with TestClient(create_app()) as client:
        assert client.get("/api/chats").status_code == 200
        assert events == ["open"]

    assert events == ["open", "close"]


def test_docs_page_is_exempt_from_the_csp() -> None:
    read, _, _ = build_read_services()

    with TestClient(create_app(read)) as client:
        response = client.get("/api/docs")

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
