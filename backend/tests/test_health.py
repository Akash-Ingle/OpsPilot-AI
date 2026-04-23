"""Smoke tests for app bootstrap."""

from fastapi.testclient import TestClient

from app.main import app


def test_root():
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert res.json()["name"]


def test_health():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
