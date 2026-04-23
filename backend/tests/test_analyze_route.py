"""Integration tests for POST /analyze."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm_client import LLMError, LLMTimeoutError, LLMValidationError
from app.agent.orchestrator import AgentRunResult, AgentStep
from app.api.routes import analyze as analyze_route
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.log import Log
from app.schemas.analysis import (
    AgentObservability,
    IterationRecord,
    LLMStructuredOutput,
    ToolCallRecord,
)

VALID_OUTPUT = LLMStructuredOutput(
    issue="DB connection pool exhausted",
    root_cause="api-gateway holding connections on slow payments-svc calls",
    fix="Increase pool size to 50 and add circuit breaker on payments-svc",
    severity="high",
    confidence=0.83,
    needs_more_data=False,
    requested_action="none",
    requested_action_args={},
    reasoning_steps=[
        "Observed sustained connection-timeout errors on api-gateway.",
        "Pattern matches prior db pool exhaustion incidents.",
        "Pool saturation cascades into 5xx responses from api-gateway.",
    ],
    relevant_log_lines=[
        {"log_id": 1, "reason": "first db-primary connection timeout"},
        {"log_id": 5, "reason": "still timing out after 50s"},
    ],
)


def _make_run_result(
    final: LLMStructuredOutput = VALID_OUTPUT,
    *,
    iterations: int = 1,
    duration_ms: float = 12.5,
    stopped_reason: str = "confident",
    tools_called=None,
) -> AgentRunResult:
    """Build a deterministic AgentRunResult for route tests."""
    tools_called = list(tools_called or [])
    now = datetime.now(timezone.utc)
    trace = [
        AgentStep(step=i + 1, response=final.model_dump(mode="json"))
        for i in range(iterations)
    ]
    obs = AgentObservability(
        iterations=iterations,
        max_iterations=max(iterations, 3),
        duration_ms=duration_ms,
        started_at=now,
        finished_at=now,
        stopped_reason=stopped_reason,
        low_confidence_retries=0,
        confidence_progression=[round(float(final.confidence), 4)] * iterations,
        tools_called=tools_called,
        iteration_trace=[
            IterationRecord(
                step=i + 1,
                confidence=float(final.confidence),
                severity=final.severity.value
                if hasattr(final.severity, "value")
                else str(final.severity),
                needs_more_data=bool(final.needs_more_data),
                requested_action=str(final.requested_action),
                low_confidence_retry=False,
                tool_call=None,
                duration_ms=duration_ms / max(iterations, 1),
            )
            for i in range(iterations)
        ],
    )
    return AgentRunResult(
        final=final,
        iterations=iterations,
        trace=trace,
        observability=obs,
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Return a TestClient backed by a fresh in-memory SQLite DB."""
    # StaticPool ensures the single in-memory DB is reused across sessions;
    # otherwise each new connection gets a fresh (empty) schema.
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


def _seed_logs(session_factory, count: int = 10, service: str = "api-gateway") -> None:
    db = session_factory()
    base = datetime(2026, 4, 23, 14, 0, tzinfo=timezone.utc)
    for i in range(count):
        db.add(
            Log(
                timestamp=base + timedelta(seconds=i * 10),
                service_name=service,
                severity="error" if i < count - 1 else "info",
                message=f"connection timeout to db-primary #{i}",
            )
        )
    db.commit()
    db.close()


def test_analyze_empty_logs_returns_400(client):
    tc, _ = client
    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 400
    assert "No logs" in res.json()["detail"]


def test_analyze_happy_path_creates_incident_and_analysis(client, monkeypatch):
    tc, session_factory = client
    _seed_logs(session_factory, count=10)

    monkeypatch.setattr(
        analyze_route,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=5: _make_run_result(),
    )

    res = tc.post(settings.api_v1_prefix + "/analyze", json={"limit": 50})
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["logs_analyzed"] == 10
    assert body["anomalies_detected"] >= 1  # 9 errors should trigger the spike rule
    assert body["steps_run"] == 1
    assert body["incident_id"] > 0
    assert body["analysis_id"] > 0
    assert body["final"]["severity"] == "high"
    assert body["final"]["confidence"] == 0.83

    # Verify persistence.
    db = session_factory()
    try:
        from app.models.analysis import Analysis
        from app.models.incident import Incident

        incident = db.get(Incident, body["incident_id"])
        assert incident is not None
        assert incident.title.startswith("DB connection pool")
        assert incident.severity.value == "high"
        assert incident.root_cause.startswith("api-gateway holding connections")

        analysis = db.get(Analysis, body["analysis_id"])
        assert analysis is not None
        assert analysis.incident_id == incident.id
        assert analysis.confidence_score == pytest.approx(0.83)
        assert analysis.structured_output["severity"] == "high"
    finally:
        db.close()


def test_analyze_response_exposes_explainability_fields(client, monkeypatch):
    """API response must surface reasoning_steps and relevant_log_lines."""
    tc, session_factory = client
    _seed_logs(session_factory, count=10)

    monkeypatch.setattr(
        analyze_route,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=5: _make_run_result(),
    )

    res = tc.post(settings.api_v1_prefix + "/analyze", json={"limit": 50})
    assert res.status_code == 201

    final = res.json()["final"]
    assert isinstance(final["reasoning_steps"], list)
    assert len(final["reasoning_steps"]) == 3
    assert "connection-timeout" in final["reasoning_steps"][0]

    refs = final["relevant_log_lines"]
    assert isinstance(refs, list)
    assert len(refs) == 2
    assert refs[0]["log_id"] == 1
    assert refs[0]["reason"].startswith("first db-primary")

    # The stored analysis snapshot should also contain the explainability fields.
    db = session_factory()
    try:
        from app.models.analysis import Analysis
        analysis = db.get(Analysis, res.json()["analysis_id"])
        assert analysis.structured_output["reasoning_steps"] == final["reasoning_steps"]
        assert analysis.structured_output["relevant_log_lines"] == refs
    finally:
        db.close()


def test_analyze_respects_service_filter(client, monkeypatch):
    tc, session_factory = client
    _seed_logs(session_factory, count=5, service="api-gateway")
    _seed_logs(session_factory, count=5, service="payments")

    captured: dict = {}

    def fake_run(logs, anomalies, max_iterations=5):
        captured["services"] = {l.service_name for l in logs}
        captured["count"] = len(logs)
        captured["max_iterations"] = max_iterations
        return _make_run_result()

    monkeypatch.setattr(analyze_route, "run_agent_loop", fake_run)

    res = tc.post(settings.api_v1_prefix + "/analyze", json={"service_name": "payments"})
    assert res.status_code == 201
    assert captured["services"] == {"payments"}
    assert captured["count"] == 5
    assert captured["max_iterations"] == 5  # AnalyzeRequest default


def test_analyze_timeout_returns_504(client, monkeypatch):
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    def boom(logs, anomalies, max_iterations=5):
        raise LLMTimeoutError("upstream timeout")

    monkeypatch.setattr(analyze_route, "run_agent_loop", boom)

    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 504
    assert "timed out" in res.json()["detail"].lower()


def test_analyze_validation_error_returns_502(client, monkeypatch):
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    def boom(logs, anomalies, max_iterations=5):
        raise LLMValidationError("unparseable", errors=["attempt 1: ..."])

    monkeypatch.setattr(analyze_route, "run_agent_loop", boom)

    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 502
    assert "invalid response" in res.json()["detail"].lower()


def test_analyze_stores_incident_in_memory(client, monkeypatch):
    """After a successful /analyze, the created incident is handed to memory."""
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    monkeypatch.setattr(
        analyze_route,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=5: _make_run_result(),
    )

    captured: dict = {}

    def fake_store(incident, logs=None):
        captured["incident_id"] = incident.id
        captured["title"] = incident.title
        captured["logs_len"] = len(list(logs)) if logs is not None else 0
        return True

    monkeypatch.setattr(analyze_route.memory_service, "store_incident", fake_store)

    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 201
    body = res.json()

    assert captured["incident_id"] == body["incident_id"]
    assert captured["title"].startswith("DB connection pool")
    assert captured["logs_len"] == 5


def test_analyze_survives_memory_store_failure(client, monkeypatch):
    """A crashing memory.store_incident must not break the API response."""
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    monkeypatch.setattr(
        analyze_route,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=5: _make_run_result(),
    )

    def boom(incident, logs=None):
        raise RuntimeError("memory is down")

    monkeypatch.setattr(analyze_route.memory_service, "store_incident", boom)

    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 201
    assert res.json()["incident_id"] > 0


def test_analyze_generic_llm_error_returns_502(client, monkeypatch):
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    def boom(logs, anomalies, max_iterations=5):
        raise LLMError("api key not set")

    monkeypatch.setattr(analyze_route, "run_agent_loop", boom)

    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 502
    assert "api key" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def test_analyze_response_includes_observability(client, monkeypatch):
    """The /analyze response must include the observability payload."""
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    tool_call = ToolCallRecord(
        step=1,
        name="fetch_logs",
        args={"service_name": "api-gateway", "limit": 50},
        ok=True,
        error=None,
        duration_ms=4.2,
    )
    run_result = _make_run_result(
        iterations=2,
        duration_ms=42.0,
        stopped_reason="confident",
        tools_called=[tool_call],
    )

    monkeypatch.setattr(
        analyze_route,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=5: run_result,
    )

    res = tc.post(settings.api_v1_prefix + "/analyze", json={"max_steps": 3})
    assert res.status_code == 201, res.text
    body = res.json()

    # steps_run now reflects real iteration count from the agent.
    assert body["steps_run"] == 2

    obs = body["observability"]
    assert obs["iterations"] == 2
    assert obs["stopped_reason"] == "confident"
    assert obs["duration_ms"] == pytest.approx(42.0)
    assert obs["confidence_progression"] == [0.83, 0.83]
    assert obs["low_confidence_retries"] == 0
    assert isinstance(obs["started_at"], str)
    assert isinstance(obs["finished_at"], str)

    # Tools called and iteration trace are exposed to the UI.
    assert len(obs["tools_called"]) == 1
    assert obs["tools_called"][0]["name"] == "fetch_logs"
    assert obs["tools_called"][0]["step"] == 1
    assert obs["tools_called"][0]["ok"] is True

    assert len(obs["iteration_trace"]) == 2
    assert obs["iteration_trace"][0]["step"] == 1
    assert obs["iteration_trace"][0]["confidence"] == pytest.approx(0.83)


def test_analyze_persists_observability_on_analysis_row(client, monkeypatch):
    """The observability payload must be stored on the Analysis DB row."""
    tc, session_factory = client
    _seed_logs(session_factory, count=5)

    run_result = _make_run_result(iterations=3, stopped_reason="max_iterations")
    monkeypatch.setattr(
        analyze_route,
        "run_agent_loop",
        lambda logs, anomalies, max_iterations=5: run_result,
    )

    res = tc.post(settings.api_v1_prefix + "/analyze", json={})
    assert res.status_code == 201
    analysis_id = res.json()["analysis_id"]

    db = session_factory()
    try:
        from app.models.analysis import Analysis

        analysis = db.get(Analysis, analysis_id)
        assert analysis is not None
        assert analysis.observability is not None
        assert analysis.observability["iterations"] == 3
        assert analysis.observability["stopped_reason"] == "max_iterations"
        assert len(analysis.observability["iteration_trace"]) == 3
        # step_index tracks the final iteration position (0-based).
        assert analysis.step_index == 2
    finally:
        db.close()
