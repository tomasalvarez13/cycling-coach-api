from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "service" in payload


def test_versioned_healthcheck() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
