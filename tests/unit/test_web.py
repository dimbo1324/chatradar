from __future__ import annotations

from fastapi.testclient import TestClient

from chatradar.web.app import create_app


def test_healthz() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
