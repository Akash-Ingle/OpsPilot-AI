"""Focused tests for the LLM output contract (LogReference + reasoning_steps)."""

import pytest
from pydantic import ValidationError

from app.schemas.analysis import LLMStructuredOutput, LogReference


# ---------------------------------------------------------------------------
# LogReference
# ---------------------------------------------------------------------------


def test_log_reference_accepts_log_id_only():
    ref = LogReference(log_id=42)
    assert ref.log_id == 42
    assert ref.excerpt is None


def test_log_reference_accepts_line_index_only():
    ref = LogReference(line_index=3)
    assert ref.line_index == 3


def test_log_reference_accepts_excerpt_only():
    ref = LogReference(excerpt="connection timeout to db")
    assert ref.excerpt == "connection timeout to db"


def test_log_reference_requires_any_identifier():
    with pytest.raises(ValidationError):
        LogReference(reason="this is not enough")


def test_log_reference_rejects_blank_excerpt_alone():
    """An all-whitespace excerpt is treated as missing."""
    with pytest.raises(ValidationError):
        LogReference(excerpt="   ")


def test_log_reference_normalizes_blank_reason_to_none():
    ref = LogReference(log_id=1, reason="   ")
    assert ref.reason is None


def test_log_reference_rejects_non_positive_line_index():
    with pytest.raises(ValidationError):
        LogReference(line_index=0)


# ---------------------------------------------------------------------------
# LLMStructuredOutput explainability fields
# ---------------------------------------------------------------------------


def _base_payload(**overrides):
    base = {
        "issue": "x",
        "root_cause": "y",
        "fix": "z",
        "severity": "high",
        "confidence": 0.8,
        "needs_more_data": False,
        "requested_action": "none",
        "requested_action_args": {},
        "reasoning_steps": ["observed the issue", "inferred the cause"],
        "relevant_log_lines": [{"log_id": 1, "reason": "evidence"}],
    }
    base.update(overrides)
    return base


def test_structured_output_requires_reasoning_steps():
    payload = _base_payload()
    payload.pop("reasoning_steps")
    with pytest.raises(ValidationError):
        LLMStructuredOutput.model_validate(payload)


def test_structured_output_requires_non_empty_reasoning_steps():
    with pytest.raises(ValidationError):
        LLMStructuredOutput.model_validate(_base_payload(reasoning_steps=[]))


def test_structured_output_drops_blank_reasoning_steps():
    """Pre-validator trims whitespace entries before min_length check."""
    out = LLMStructuredOutput.model_validate(
        _base_payload(reasoning_steps=["", "  ", "real step"])
    )
    assert out.reasoning_steps == ["real step"]


def test_structured_output_reasoning_steps_only_blank_fails():
    with pytest.raises(ValidationError):
        LLMStructuredOutput.model_validate(
            _base_payload(reasoning_steps=["", "  "])
        )


def test_structured_output_caps_reasoning_steps_length():
    with pytest.raises(ValidationError):
        LLMStructuredOutput.model_validate(
            _base_payload(reasoning_steps=[f"step {i}" for i in range(20)])
        )


def test_structured_output_relevant_log_lines_default_empty():
    payload = _base_payload()
    payload.pop("relevant_log_lines")
    out = LLMStructuredOutput.model_validate(payload)
    assert out.relevant_log_lines == []


def test_structured_output_accepts_mixed_reference_types():
    out = LLMStructuredOutput.model_validate(
        _base_payload(
            relevant_log_lines=[
                {"log_id": 10, "reason": "error log"},
                {"line_index": 4},
                {"excerpt": "boom"},
            ]
        )
    )
    assert len(out.relevant_log_lines) == 3
    assert out.relevant_log_lines[0].log_id == 10
    assert out.relevant_log_lines[1].line_index == 4
    assert out.relevant_log_lines[2].excerpt == "boom"
