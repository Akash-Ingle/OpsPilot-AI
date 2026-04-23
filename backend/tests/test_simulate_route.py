"""Integration tests for the /simulate endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.log import Log


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app), TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


def test_list_scenarios(client):
    tc, _ = client
    res = tc.get(settings.api_v1_prefix + "/simulate/scenarios")
    assert res.status_code == 200
    names = {item["name"] for item in res.json()}
    assert names == {"database_failure", "memory_leak", "latency_spike"}


def test_simulate_persists_logs(client):
    tc, session_factory = client
    res = tc.post(
        settings.api_v1_prefix + "/simulate",
        json={"scenario": "database_failure", "seed": 42, "duration_minutes": 5},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["persisted"] is True
    assert body["count"] > 0
    assert len(body["sample"]) <= 5

    db = session_factory()
    try:
        total = db.scalar(select(func.count()).select_from(Log))
        assert total == body["count"]
    finally:
        db.close()


def test_simulate_dry_run_does_not_persist(client):
    tc, session_factory = client
    res = tc.post(
        settings.api_v1_prefix + "/simulate",
        json={"scenario": "memory_leak", "seed": 1, "persist": False},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["persisted"] is False
    assert body["count"] > 0

    db = session_factory()
    try:
        assert db.scalar(select(func.count()).select_from(Log)) == 0
    finally:
        db.close()


def test_simulate_rejects_unknown_scenario(client):
    tc, _ = client
    res = tc.post(
        settings.api_v1_prefix + "/simulate",
        json={"scenario": "definitely-not-real"},
    )
    # Pydantic Literal validation → 422.
    assert res.status_code == 422
