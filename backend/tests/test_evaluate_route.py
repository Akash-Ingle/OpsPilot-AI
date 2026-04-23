"""Integration tests for the /evaluate API routes."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.analysis import Analysis
from app.models.incident import Incident, Severity


@pytest.fixture
def client():
    """TestClient backed by an in-memory SQLite DB with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    # Ensure all ORM models are registered BEFORE create_all.
    from app import models  # noqa: F401

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def _override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app), SessionLocal
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


def _seed_incident(SessionLocal, *, root_cause: str, severity: str, fix: str, confidence: float):
    db = SessionLocal()
    try:
        structured = {
            "issue": "x",
            "root_cause": root_cause,
            "fix": fix,
            "severity": severity,
            "confidence": confidence,
            "needs_more_data": False,
            "requested_action": "none",
            "requested_action_args": {},
            "reasoning_steps": ["step 1"],
            "relevant_log_lines": [],
        }
        incident = Incident(
            title="DB outage", severity=Severity(severity),
            root_cause=root_cause, suggested_fix=fix,
        )
        db.add(incident)
        db.flush()
        analysis = Analysis(
            incident_id=incident.id,
            llm_output=json.dumps(structured),
            structured_output=structured,
            confidence_score=confidence,
            step_index=0,
        )
        db.add(analysis)
        db.commit()
        db.refresh(incident)
        db.refresh(analysis)
        return incident.id, analysis.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /evaluate/scenarios
# ---------------------------------------------------------------------------


def test_list_scenarios_exposes_ground_truth(client):
    tc, _ = client
    res = tc.get(settings.api_v1_prefix + "/evaluate/scenarios")
    assert res.status_code == 200
    body = res.json()
    names = {s["scenario_name"] for s in body}
    assert names == {"database_failure", "memory_leak", "latency_spike"}

    db_failure = next(s for s in body if s["scenario_name"] == "database_failure")
    assert "database" in db_failure["root_cause_keywords"]
    assert db_failure["min_root_cause_matches"] >= 1
    assert "high" in db_failure["accepted_severities"]


# ---------------------------------------------------------------------------
# POST /evaluate
# ---------------------------------------------------------------------------


def test_evaluate_happy_path(client):
    tc, SessionLocal = client
    incident_id, analysis_id = _seed_incident(
        SessionLocal,
        root_cause="database connection pool timeout unreachable db-primary",
        severity="high",
        fix="scale the connection pool and add a breaker",
        confidence=0.88,
    )

    res = tc.post(
        settings.api_v1_prefix + "/evaluate",
        json={"incident_id": incident_id, "scenario_name": "database_failure"},
    )
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["incident_id"] == incident_id
    assert body["analysis_id"] == analysis_id
    assert body["scenario_name"] == "database_failure"
    assert body["overall_correct"] is True
    assert body["root_cause_match"] is True
    assert body["severity_match"] is True
    assert body["score"] > 0.8
    assert body["confidence"] == pytest.approx(0.88)
    assert "database" in body["matched_keywords"]
    assert body["predicted_output"]["root_cause"].startswith("database connection")


def test_evaluate_unknown_scenario_returns_400(client):
    tc, SessionLocal = client
    incident_id, _ = _seed_incident(
        SessionLocal,
        root_cause="x", severity="high", fix="y", confidence=0.5,
    )
    res = tc.post(
        settings.api_v1_prefix + "/evaluate",
        json={"incident_id": incident_id, "scenario_name": "bogus_name"},
    )
    # Pydantic rejects bogus Literal values with 422 at the request layer.
    assert res.status_code in (400, 422)


def test_evaluate_missing_incident_returns_404(client):
    tc, _ = client
    res = tc.post(
        settings.api_v1_prefix + "/evaluate",
        json={"incident_id": 9999, "scenario_name": "database_failure"},
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /evaluate/summary
# ---------------------------------------------------------------------------


def test_summary_empty(client):
    tc, _ = client
    res = tc.get(settings.api_v1_prefix + "/evaluate/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["accuracy"] == 0.0
    assert body["by_scenario"] == []
    assert body["calibration"]["gap"] is None


def test_summary_aggregates_multiple_evaluations(client):
    tc, SessionLocal = client

    # Seed one correct + one incorrect eval for database_failure.
    iid_good, _ = _seed_incident(
        SessionLocal,
        root_cause="database connection pool exhausted, timeouts to db-primary",
        severity="high",
        fix="scale pool and add circuit breaker",
        confidence=0.9,
    )
    iid_bad, _ = _seed_incident(
        SessionLocal,
        root_cause="the auth service is misbehaving",
        severity="low",
        fix="restart auth",
        confidence=0.4,
    )

    for iid in (iid_good, iid_bad):
        r = tc.post(
            settings.api_v1_prefix + "/evaluate",
            json={"incident_id": iid, "scenario_name": "database_failure"},
        )
        assert r.status_code == 201

    res = tc.get(settings.api_v1_prefix + "/evaluate/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert body["accuracy"] == pytest.approx(0.5)
    assert body["calibration"]["mean_confidence_when_correct"] == pytest.approx(0.9)
    assert body["calibration"]["mean_confidence_when_incorrect"] == pytest.approx(0.4)
    assert body["calibration"]["gap"] == pytest.approx(0.5)

    assert len(body["by_scenario"]) == 1
    scn = body["by_scenario"][0]
    assert scn["scenario_name"] == "database_failure"
    assert scn["total"] == 2
    assert scn["accuracy"] == pytest.approx(0.5)


def test_summary_scenario_filter(client):
    tc, SessionLocal = client
    iid, _ = _seed_incident(
        SessionLocal,
        root_cause="database connection pool timeout",
        severity="high",
        fix="scale pool",
        confidence=0.8,
    )
    tc.post(
        settings.api_v1_prefix + "/evaluate",
        json={"incident_id": iid, "scenario_name": "database_failure"},
    )

    # Filter: database_failure returns the single eval.
    res = tc.get(settings.api_v1_prefix + "/evaluate/summary", params={"scenario": "database_failure"})
    assert res.status_code == 200
    assert res.json()["total"] == 1

    # Filter: memory_leak returns zero.
    res = tc.get(settings.api_v1_prefix + "/evaluate/summary", params={"scenario": "memory_leak"})
    assert res.status_code == 200
    assert res.json()["total"] == 0
