"""Tests for build_analysis_prompt."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List

from app.agent.prompts import build_analysis_prompt


@dataclass
class FakeLog:
    id: int
    timestamp: datetime
    service_name: str
    severity: str
    message: str


@dataclass
class FakeAnomaly:
    kind: str
    service: str
    severity: str
    summary: str
    score: float
    evidence_log_ids: List[int]


BASE_TS = datetime(2026, 4, 23, 14, 0, 0, tzinfo=timezone.utc)


def _make_logs() -> List[FakeLog]:
    logs: List[FakeLog] = []
    # api-gateway: 6 identical errors (should dedup with "x5 more")
    for i in range(6):
        logs.append(
            FakeLog(
                id=100 + i,
                timestamp=BASE_TS + timedelta(seconds=i * 10),
                service_name="api-gateway",
                severity="error",
                message="connection timeout to db-primary after 5000ms",
            )
        )
    # api-gateway: one upstream error (different message)
    logs.append(
        FakeLog(
            id=110,
            timestamp=BASE_TS + timedelta(minutes=2),
            service_name="api-gateway",
            severity="error",
            message="upstream 503 from payments-svc",
        )
    )
    # payments: 3 latency warnings
    for i in range(3):
        logs.append(
            FakeLog(
                id=200 + i,
                timestamp=BASE_TS + timedelta(minutes=3, seconds=i * 20),
                service_name="payments",
                severity="warning",
                message=f"latency_ms={1200 + i * 100} POST /charge",
            )
        )
    # auth: info line (should appear last since no errors)
    logs.append(
        FakeLog(
            id=300,
            timestamp=BASE_TS + timedelta(minutes=5),
            service_name="auth",
            severity="info",
            message="rotating JWT keys",
        )
    )
    return logs


def _make_anomalies() -> List[FakeAnomaly]:
    return [
        FakeAnomaly(
            kind="error_spike",
            service="api-gateway",
            severity="high",
            summary="7 errors in api-gateway within 5 min window",
            score=0.88,
            evidence_log_ids=[100, 101, 102, 103, 104, 105, 110],
        ),
        FakeAnomaly(
            kind="repeated_error",
            service="api-gateway",
            severity="medium",
            summary='"connection timeout to db-primary..." repeated 6x',
            score=0.67,
            evidence_log_ids=[100, 101, 102, 103, 104, 105],
        ),
    ]


def test_summary_contains_expected_sections():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    for header in [
        "### Logs summary",
        "### Detected anomalies",
        "### Log excerpts",
        "### Task",
    ]:
        assert header in prompt


def test_summary_includes_stats():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    assert "Total logs: 11" in prompt
    # 3 services
    assert "Services (3)" in prompt
    # Severity breakdown mentions error/warning/info
    assert "error=" in prompt and "warning=" in prompt and "info=" in prompt


def test_anomalies_ranked_by_score():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    spike_idx = prompt.index("error_spike")
    repeated_idx = prompt.index("repeated_error")
    assert spike_idx < repeated_idx, "higher-score anomaly should appear first"
    assert "score=0.88" in prompt
    assert "score=0.67" in prompt


def test_no_anomalies_message():
    prompt = build_analysis_prompt(_make_logs(), [])
    assert "No anomalies detected" in prompt


def test_no_logs_message():
    prompt = build_analysis_prompt([], [])
    assert "No logs provided." in prompt
    assert "No anomalies detected" in prompt


def test_dedup_marks_duplicate_errors():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    # 6 identical "connection timeout" lines should collapse to one with "(x5 more)"
    assert "connection timeout to db-primary" in prompt
    assert "(x5 more)" in prompt


def test_errors_appear_before_info_lines():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    # api-gateway (has errors) should be ranked before auth (info only)
    assert prompt.index("[api-gateway]") < prompt.index("[auth]")


def test_accepts_dict_inputs():
    log_dicts: List[dict[str, Any]] = [
        {
            "id": 1,
            "timestamp": BASE_TS,
            "service_name": "svc-a",
            "severity": "error",
            "message": "boom",
        },
        {
            "id": 2,
            "timestamp": BASE_TS + timedelta(seconds=5),
            "service": "svc-a",  # alternate key should also work
            "severity": "error",
            "message": "boom",
        },
    ]
    anomaly_dicts = [
        {
            "kind": "error_spike",
            "service": "svc-a",
            "severity": "high",
            "summary": "2 errors in svc-a",
            "score": 0.5,
            "evidence_log_ids": [1, 2],
        }
    ]
    prompt = build_analysis_prompt(log_dicts, anomaly_dicts)
    assert "svc-a" in prompt
    assert "error_spike" in prompt
    assert "Total logs: 2" in prompt


def test_historical_incidents_section_omitted_when_empty():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    assert "Similar past incidents" not in prompt


def test_historical_incidents_rendered_when_provided():
    historical = [
        {
            "title": "DB pool exhausted during peak traffic",
            "severity": "high",
            "root_cause": "payments-svc holding connections",
            "fix": "increase pool to 50, add circuit breaker",
            "distance": 0.15,
        },
        {
            "title": "slow upstream causing cascade",
            "severity": "medium",
            "root_cause": "payments-svc p99 above SLO",
            "fix": "add retries with backoff",
            "distance": 0.42,
        },
    ]
    prompt = build_analysis_prompt(
        _make_logs(), _make_anomalies(), historical_incidents=historical
    )

    assert "### Similar past incidents" in prompt
    assert "DB pool exhausted during peak traffic" in prompt
    assert "slow upstream causing cascade" in prompt
    # similarity = 1 - distance, so 0.85 / 0.58.
    assert "similarity=0.85" in prompt
    assert "similarity=0.58" in prompt
    # Historical section precedes the log excerpts.
    assert prompt.index("Similar past incidents") < prompt.index("Log excerpts")


def test_excerpts_are_tagged_with_log_ids_for_citation():
    """Each excerpt line must include [log_id=N] so the model can cite them."""
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    # Known seeded ids from the fixture: 100, 110, 200-202, 300.
    assert "[log_id=100]" in prompt or "[log_id=110]" in prompt
    assert "[log_id=200]" in prompt
    # Explicit instruction about citing log_ids is present.
    assert "cite these ids" in prompt.lower()


def test_excerpts_without_ids_have_no_tag():
    """Logs without integer ids should not produce a bogus [log_id=] tag."""
    raw_logs = [
        {
            "timestamp": BASE_TS,
            "service_name": "svc-x",
            "severity": "error",
            "message": "something failed",
        }
    ]
    prompt = build_analysis_prompt(raw_logs, [])
    assert "[log_id=" not in prompt
    assert "something failed" in prompt


def test_task_section_instructs_reasoning_and_citation():
    prompt = build_analysis_prompt(_make_logs(), _make_anomalies())
    task = prompt.split("### Task", 1)[1]
    assert "reasoning_steps" in task
    assert "relevant_log_lines" in task


def test_historical_incidents_accepts_dataclasses():
    from app.services.memory_service import SimilarIncident

    historical = [
        SimilarIncident(
            incident_id=7,
            title="db timeout storm",
            severity="critical",
            root_cause="connection pool exhausted",
            fix="scale replicas",
            distance=0.05,
        ),
    ]
    prompt = build_analysis_prompt(
        _make_logs(), _make_anomalies(), historical_incidents=historical
    )
    assert "db timeout storm" in prompt
    assert "similarity=0.95" in prompt


def test_max_log_lines_caps_output():
    # Generate 100 distinct error logs; ask for max_log_lines=5.
    many = [
        FakeLog(
            id=i,
            timestamp=BASE_TS + timedelta(seconds=i),
            service_name=f"svc-{i % 3}",
            severity="error",
            message=f"unique error {i}",
        )
        for i in range(100)
    ]
    prompt = build_analysis_prompt(many, [], max_log_lines=5)
    # Count "- HH:MM:SS" excerpt lines by counting severity markers in excerpts.
    # A crude but effective check:
    excerpt_section = prompt.split("### Log excerpts")[1]
    dash_lines = [ln for ln in excerpt_section.splitlines() if ln.startswith("- ")]
    assert len(dash_lines) <= 5
