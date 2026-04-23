"""Unit tests for the evaluation service (ground truth + scoring + persistence)."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.analysis import Analysis
from app.models.evaluation import Evaluation
from app.models.incident import Incident, Severity
from app.services import evaluation_service
from app.services.evaluation_service import (
    SCENARIO_GROUND_TRUTH,
    evaluate_and_store,
    evaluate_prediction,
    get_ground_truth,
    list_ground_truths,
    summarize,
)


# ---------------------------------------------------------------------------
# Test DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """Fresh in-memory SQLite session per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    # Register all model tables.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _persist_incident_with_analysis(db, structured: Dict[str, Any]) -> tuple[int, int]:
    incident = Incident(
        title="Test incident",
        severity=Severity(structured.get("severity", "high")),
        root_cause=structured.get("root_cause"),
        suggested_fix=structured.get("fix"),
    )
    db.add(incident)
    db.flush()
    analysis = Analysis(
        incident_id=incident.id,
        llm_output=json.dumps(structured),
        structured_output=structured,
        confidence_score=float(structured.get("confidence", 0.0)),
        step_index=0,
    )
    db.add(analysis)
    db.commit()
    db.refresh(incident)
    db.refresh(analysis)
    return incident.id, analysis.id


# ---------------------------------------------------------------------------
# Ground-truth helpers
# ---------------------------------------------------------------------------


def test_all_three_scenarios_have_ground_truth():
    assert set(SCENARIO_GROUND_TRUTH) == {
        "database_failure",
        "memory_leak",
        "latency_spike",
    }
    for gt in list_ground_truths():
        assert gt.accepted_severities, "must accept at least one severity"
        assert gt.root_cause_keywords
        assert gt.min_root_cause >= 1
        assert gt.fix_keywords
        assert gt.min_fix >= 1


def test_get_ground_truth_raises_on_unknown():
    with pytest.raises(KeyError):
        get_ground_truth("no_such_scenario")


# ---------------------------------------------------------------------------
# Pure scoring
# ---------------------------------------------------------------------------


def _db_failure_correct_prediction() -> Dict[str, Any]:
    return {
        "root_cause": (
            "The primary database connection pool is exhausted; connections "
            "to db-primary are timing out and upstream services cascade."
        ),
        "severity": "high",
        "fix": "Scale the connection pool and add a circuit breaker.",
        "confidence": 0.85,
    }


def test_evaluate_prediction_correct_db_failure():
    gt = get_ground_truth("database_failure")
    result = evaluate_prediction(_db_failure_correct_prediction(), gt)

    assert result.root_cause_match is True
    assert result.severity_match is True
    assert result.fix_match is True
    assert result.overall_correct is True
    assert result.score > 0.85
    assert "database" in result.matched_keywords
    assert result.keyword_coverage > 0.5


def test_evaluate_prediction_wrong_root_cause():
    gt = get_ground_truth("database_failure")
    prediction = {
        "root_cause": "Authentication service is rejecting users.",
        "severity": "high",
        "fix": "Restart the auth service.",
        "confidence": 0.9,
    }
    result = evaluate_prediction(prediction, gt)
    assert result.root_cause_match is False
    assert result.severity_match is True  # severity still matches by luck
    assert result.overall_correct is False
    assert result.score < 0.5  # mostly wrong
    assert result.missing_keywords  # at least some expected keywords absent


def test_evaluate_prediction_wrong_severity():
    gt = get_ground_truth("database_failure")  # accepts {high, critical}
    prediction = {
        "root_cause": "The database connection pool is exhausted due to timeouts.",
        "severity": "low",  # mismatched
        "fix": "Scale the connection pool.",
        "confidence": 0.7,
    }
    result = evaluate_prediction(prediction, gt)
    assert result.root_cause_match is True
    assert result.severity_match is False
    assert result.overall_correct is False  # requires BOTH rc + severity


def test_evaluate_prediction_empty_fields_safe():
    gt = get_ground_truth("memory_leak")
    result = evaluate_prediction(
        {"root_cause": "", "severity": "", "fix": "", "confidence": None},
        gt,
    )
    assert result.root_cause_match is False
    assert result.severity_match is False
    assert result.fix_match is False
    assert result.overall_correct is False
    assert result.score == 0.0
    assert result.predicted_severity == "unknown"
    assert result.confidence == 0.0


def test_evaluate_prediction_clamps_confidence_out_of_range():
    gt = get_ground_truth("database_failure")
    result = evaluate_prediction(
        {
            "root_cause": "database connection pool timeout",
            "severity": "high",
            "fix": "scale pool",
            "confidence": 5.2,  # silly, should clamp
        },
        gt,
    )
    assert result.confidence == 1.0


def test_evaluate_prediction_memory_leak_partial_credit():
    gt = get_ground_truth("memory_leak")
    prediction = {
        # Exactly one root-cause keyword hit when min is 2 -> root_cause_match False
        # but score is still positive thanks to severity + fix.
        "root_cause": "OutOfMemory errors in the worker.",
        "severity": "critical",
        "fix": "Restart the worker.",
        "confidence": 0.5,
    }
    result = evaluate_prediction(prediction, gt)
    assert result.root_cause_match is False  # only 1 keyword hit
    assert result.severity_match is True
    assert result.fix_match is True
    assert 0.0 < result.score < 1.0
    assert result.overall_correct is False


def test_evaluate_prediction_substring_not_overmatching():
    """'memory' must not match inside 'telemetry'. Whole-token matching."""
    gt = get_ground_truth("memory_leak")
    prediction = {
        "root_cause": "telemetry pipeline slowdown",  # 'memory' substring inside 'telemetry'
        "severity": "high",
        "fix": "investigate",
        "confidence": 0.3,
    }
    result = evaluate_prediction(prediction, gt)
    assert "memory" in result.missing_keywords
    assert "memory" not in result.matched_keywords


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_evaluate_and_store_persists_row(db):
    incident_id, analysis_id = _persist_incident_with_analysis(
        db, _db_failure_correct_prediction()
    )

    row = evaluate_and_store(db, "database_failure", incident_id)

    assert isinstance(row, Evaluation)
    assert row.id is not None
    assert row.incident_id == incident_id
    assert row.analysis_id == analysis_id
    assert row.scenario_name == "database_failure"
    assert row.overall_correct is True
    assert row.score > 0.8
    assert row.predicted_output["root_cause"].startswith("The primary database")
    assert "database" in row.matched_keywords

    # Re-read from DB to confirm it's persisted, not only in session cache.
    fetched = db.query(Evaluation).filter_by(id=row.id).first()
    assert fetched is not None
    assert fetched.score == pytest.approx(row.score)


def test_evaluate_and_store_resolves_explicit_analysis(db):
    incident_id, first_analysis = _persist_incident_with_analysis(
        db, _db_failure_correct_prediction()
    )
    # Add a second (weaker) analysis to the same incident.
    weak = {
        "root_cause": "unknown",
        "severity": "low",
        "fix": "investigate further",
        "confidence": 0.2,
    }
    analysis2 = Analysis(
        incident_id=incident_id,
        llm_output=json.dumps(weak),
        structured_output=weak,
        confidence_score=0.2,
        step_index=1,
    )
    db.add(analysis2)
    db.commit()
    db.refresh(analysis2)

    # Default picks the latest (weak) analysis -> incorrect.
    latest_eval = evaluate_and_store(db, "database_failure", incident_id)
    assert latest_eval.analysis_id == analysis2.id
    assert latest_eval.overall_correct is False

    # Explicit first analysis -> correct.
    first_eval = evaluate_and_store(
        db, "database_failure", incident_id, analysis_id=first_analysis
    )
    assert first_eval.analysis_id == first_analysis
    assert first_eval.overall_correct is True


def test_evaluate_and_store_unknown_incident_raises(db):
    with pytest.raises(LookupError):
        evaluate_and_store(db, "database_failure", incident_id=9999)


def test_evaluate_and_store_incident_without_analyses_raises(db):
    incident = Incident(title="bare", severity=Severity.HIGH)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    with pytest.raises(LookupError):
        evaluate_and_store(db, "database_failure", incident.id)


def test_evaluate_and_store_mismatched_analysis_raises(db):
    incident_id, analysis_id = _persist_incident_with_analysis(
        db, _db_failure_correct_prediction()
    )
    # Create a second incident, then try to grade it using the OTHER one's analysis id.
    other_id, _ = _persist_incident_with_analysis(db, _db_failure_correct_prediction())
    with pytest.raises(LookupError):
        evaluate_and_store(
            db, "database_failure", incident_id=other_id, analysis_id=analysis_id
        )


def test_evaluate_and_store_unknown_scenario_raises(db):
    incident_id, _ = _persist_incident_with_analysis(
        db, _db_failure_correct_prediction()
    )
    with pytest.raises(KeyError):
        evaluate_and_store(db, "nonsense_scenario", incident_id)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_summarize_empty_db(db):
    summary = summarize(db)
    assert summary.total == 0
    assert summary.accuracy == 0.0
    assert summary.mean_confidence == 0.0
    assert summary.calibration.mean_confidence_when_correct is None
    assert summary.calibration.mean_confidence_when_incorrect is None
    assert summary.calibration.gap is None
    assert summary.by_scenario == []


def _seed_run(db, scenario: str, predicted: Dict[str, Any]) -> None:
    iid, _ = _persist_incident_with_analysis(db, predicted)
    evaluate_and_store(db, scenario, iid)


def test_summarize_mixed_results(db):
    correct = _db_failure_correct_prediction()
    also_correct = {**correct, "confidence": 0.95}
    wrong_sev = {**correct, "severity": "low", "confidence": 0.9}
    wrong_cause = {
        "root_cause": "auth service failing",
        "severity": "high",
        "fix": "restart auth",
        "confidence": 0.3,
    }

    _seed_run(db, "database_failure", correct)
    _seed_run(db, "database_failure", also_correct)
    _seed_run(db, "database_failure", wrong_sev)
    _seed_run(db, "database_failure", wrong_cause)

    summary = summarize(db)
    assert summary.total == 4
    assert summary.accuracy == pytest.approx(0.5)  # 2/4 correct overall
    assert 0.0 < summary.mean_confidence < 1.0

    # Calibration: correct avg confidence (0.85/0.95) is HIGHER than incorrect (0.9/0.3).
    assert summary.calibration.mean_confidence_when_correct == pytest.approx(0.9)
    assert summary.calibration.mean_confidence_when_incorrect == pytest.approx(0.6)
    assert summary.calibration.gap == pytest.approx(0.3)

    assert len(summary.by_scenario) == 1
    ss = summary.by_scenario[0]
    assert ss.scenario_name == "database_failure"
    assert ss.total == 4
    assert ss.accuracy == pytest.approx(0.5)
    # Root cause: 3/4 correct (correct, also_correct, wrong_sev has good root cause).
    assert ss.root_cause_accuracy == pytest.approx(0.75)
    # Severity: 3/4 (only wrong_sev fails).
    assert ss.severity_accuracy == pytest.approx(0.75)


def test_summarize_filters_by_scenario(db):
    _seed_run(db, "database_failure", _db_failure_correct_prediction())

    memory_correct = {
        "root_cause": "heap OOM caused by memory leak in worker",
        "severity": "critical",
        "fix": "restart the service",
        "confidence": 0.8,
    }
    _seed_run(db, "memory_leak", memory_correct)

    db_only = summarize(db, scenario_name="database_failure")
    assert db_only.total == 1
    assert db_only.by_scenario[0].scenario_name == "database_failure"

    overall = summarize(db)
    assert overall.total == 2
    assert {s.scenario_name for s in overall.by_scenario} == {
        "database_failure",
        "memory_leak",
    }


def test_summarize_unknown_scenario_raises(db):
    with pytest.raises(KeyError):
        summarize(db, scenario_name="no_such_scenario")
