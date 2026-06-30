"""Integration tests for the connect -> ingest -> watch -> alert product loop."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.demo_cache import build_cached_run
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.incident import Incident
from app.models.log import Log
from app.services import watcher as watcher_module
from tests._auth import login

API = settings.api_v1_prefix


@pytest.fixture
def client(monkeypatch):
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
    # The watcher opens its OWN session via SessionLocal; point it at the same
    # in-memory DB so the background task and the request share state.
    monkeypatch.setattr(watcher_module, "SessionLocal", TestingSession)
    # Don't call a real LLM: the watcher serves a deterministic cached run.
    monkeypatch.setattr(
        watcher_module,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=4: build_cached_run("database_failure"),
    )
    try:
        tc = TestClient(app)
        # Projects are now owned by a user, so creating one requires a session.
        login(tc)
        yield tc, TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


def _create_project(tc, name="My Site") -> str:
    res = tc.post(f"{API}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["api_key"].startswith("opsp_")
    assert body["key_prefix"].startswith("opsp_")
    return body["api_key"]


def _db_failure_logs(n=12):
    logs = [
        {
            "service_name": "orders-svc",
            "severity": "error",
            "message": f"connection timeout to db-primary after 5000ms pool=orders-pool waiting={i}",
        }
        for i in range(n)
    ]
    logs.append(
        {
            "service_name": "orders-svc",
            "severity": "critical",
            "message": "FATAL: connection pool exhausted (size=20 in_use=20) queue_depth=80",
        }
    )
    return logs


def test_ingest_requires_api_key(client):
    tc, _ = client
    res = tc.post(f"{API}/ingest", json={"logs": [{"message": "hi"}]})
    assert res.status_code == 401

    res = tc.post(
        f"{API}/ingest",
        headers={"Authorization": "Bearer opsp_bogus"},
        json={"logs": [{"message": "hi"}]},
    )
    assert res.status_code == 401


def test_ingest_persists_logs_scoped_to_project(client):
    tc, session_factory = client
    key = _create_project(tc)
    headers = {"Authorization": f"Bearer {key}"}

    res = tc.post(
        f"{API}/ingest",
        headers=headers,
        json={"logs": [{"message": "hello", "service_name": "web", "severity": "info"}]},
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["ingested"] == 1
    assert body["project_id"] > 0

    db = session_factory()
    try:
        rows = db.query(Log).all()
        assert len(rows) == 1
        assert rows[0].project_id == body["project_id"]
    finally:
        db.close()


def test_ingest_triggers_watcher_and_opens_incident_with_alert(client, monkeypatch):
    tc, session_factory = client
    captured = {}

    def fake_alert(url, incident, result, similar_summary=None, served_from_cache=False):
        captured["url"] = url
        captured["incident_id"] = incident.id
        captured["severity"] = (
            result.severity.value if hasattr(result.severity, "value") else result.severity
        )
        return True

    monkeypatch.setattr(
        "app.services.alerting.send_slack_incident_alert", fake_alert
    )

    key = _create_project(tc)
    headers = {"Authorization": f"Bearer {key}"}
    # Configure Slack so the alert path fires.
    tc.patch(
        f"{API}/projects/me",
        headers=headers,
        json={"slack_webhook_url": "https://hooks.slack.com/services/T/B/X"},
    )

    res = tc.post(f"{API}/ingest", headers=headers, json={"logs": _db_failure_logs()})
    assert res.status_code == 202

    db = session_factory()
    try:
        incidents = db.query(Incident).all()
        assert len(incidents) == 1
        assert incidents[0].project_id is not None
        assert incidents[0].severity.value == "critical"
    finally:
        db.close()

    assert captured.get("severity") == "critical"
    assert captured.get("url", "").startswith("https://hooks.slack.com/")


def test_watcher_cooldown_prevents_duplicate_incidents(client):
    tc, session_factory = client
    key = _create_project(tc)
    headers = {"Authorization": f"Bearer {key}"}

    tc.post(f"{API}/ingest", headers=headers, json={"logs": _db_failure_logs()})
    tc.post(f"{API}/ingest", headers=headers, json={"logs": _db_failure_logs()})

    db = session_factory()
    try:
        # Two ingests within the cooldown window must yield a single incident.
        assert db.query(Incident).count() == 1
    finally:
        db.close()


def test_no_anomaly_means_no_incident(client):
    tc, session_factory = client
    key = _create_project(tc)
    headers = {"Authorization": f"Bearer {key}"}

    tc.post(
        f"{API}/ingest",
        headers=headers,
        json={"logs": [{"message": "GET /health 200", "severity": "info"}]},
    )

    db = session_factory()
    try:
        assert db.query(Incident).count() == 0
    finally:
        db.close()


def test_projects_me_requires_key_and_reports_stats(client):
    tc, _ = client
    assert tc.get(f"{API}/projects/me").status_code == 401

    key = _create_project(tc)
    headers = {"Authorization": f"Bearer {key}"}
    tc.post(f"{API}/ingest", headers=headers, json={"logs": _db_failure_logs()})

    res = tc.get(f"{API}/projects/me", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["log_count"] == 13
    assert body["incident_count"] == 1
    assert body["last_auto_analysis_at"] is not None
