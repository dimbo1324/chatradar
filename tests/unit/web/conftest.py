from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from chatradar.web.app import create_app
from tests.unit.web.fakes import FakeQueries, FakeSearch, build_read_services

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class Panel:
    client: TestClient
    queries: FakeQueries
    search: FakeSearch


@pytest.fixture
def panel() -> Iterator[Panel]:
    read, queries, search = build_read_services()
    with TestClient(create_app(read)) as client:
        yield Panel(client=client, queries=queries, search=search)
