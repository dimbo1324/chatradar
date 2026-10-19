from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from chatradar.config import Settings
from chatradar.web.app import create_app
from tests.unit.web.fakes import build_read_services

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from chatradar.services.queries import ReadServices


def _install_container(monkeypatch: pytest.MonkeyPatch, build: Callable[[Settings], Any]) -> None:
    module = ModuleType("chatradar.services.container")
    module.build_read_services = build  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "chatradar.services.container", module)


def _plain(read: ReadServices) -> Callable[[Settings], ReadServices]:
    def build(settings: Settings) -> ReadServices:
        assert isinstance(settings, Settings)
        return read

    return build


def _awaitable(read: ReadServices) -> Callable[[Settings], Any]:
    async def build(settings: Settings) -> ReadServices:
        return read

    return build


@pytest.mark.parametrize("make_builder", [_plain, _awaitable])
def test_without_services_the_container_builds_them(
    monkeypatch: pytest.MonkeyPatch, make_builder: Callable[[ReadServices], Any]
) -> None:
    read, _, _ = build_read_services()
    _install_container(monkeypatch, make_builder(read))

    with TestClient(create_app()) as client:
        assert client.app.state.read is read  # type: ignore[attr-defined]
        assert client.get("/api/noise-reasons").json() == {"short": 1}


def test_container_context_manager_is_closed_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    read, _, _ = build_read_services()
    events: list[str] = []

    @asynccontextmanager
    async def build(settings: Settings) -> AsyncGenerator[ReadServices]:
        events.append("open")
        yield read
        events.append("close")

    _install_container(monkeypatch, build)

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
