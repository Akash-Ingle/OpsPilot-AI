"""Unit tests for API key generation and Slack alert formatting."""

from app.models.incident import Incident, Severity
from app.schemas.analysis import LLMStructuredOutput
from app.services.alerting import build_slack_payload
from app.services.api_key import generate_key, hash_key


def test_generate_key_is_prefixed_hashed_and_unique():
    a = generate_key()
    b = generate_key()
    assert a.raw.startswith("opsp_")
    assert a.raw != b.raw
    assert a.key_hash == hash_key(a.raw)
    assert a.key_hash != a.raw  # stored value is a hash, not the secret
    assert len(a.key_hash) == 64  # sha256 hex
    assert a.display_prefix.startswith("opsp_") and len(a.display_prefix) <= 12


def test_build_slack_payload_includes_severity_root_cause_and_fix():
    incident = Incident(id=7, title="DB down", severity=Severity.CRITICAL)
    result = LLMStructuredOutput(
        issue="Primary database unreachable",
        root_cause="Connection pool exhausted on db-primary.",
        fix="Increase pool size and add a circuit breaker.",
        severity="critical",
        confidence=0.93,
        reasoning_steps=["Saw connection timeouts", "Pool exhausted", "DB primary unreachable"],
    )

    payload = build_slack_payload(
        incident, result, similar_summary="DB outage last week — pool exhaustion"
    )

    assert "Primary database unreachable" in payload["text"]
    blob = str(payload["blocks"])
    assert "critical" in blob
    assert "93%" in blob
    assert "Connection pool exhausted" in blob
    assert "Increase pool size" in blob
    assert "Similar past incident" in blob
