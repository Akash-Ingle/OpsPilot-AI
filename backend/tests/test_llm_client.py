"""Unit tests for the LLM client (providers mocked)."""

import json

import pytest

from app.agent import llm_client
from app.agent.llm_client import (
    LLMError,
    LLMProvider,
    LLMValidationError,
    _parse_and_validate,
    call_llm,
)


VALID_PAYLOAD = {
    "issue": "API gateway returning 5xx",
    "root_cause": "DB connection pool exhausted",
    "fix": "Increase pool size and restart gateway",
    "severity": "high",
    "confidence": 0.82,
    "needs_more_data": False,
    "requested_action": "none",
    "requested_action_args": {},
    "reasoning_steps": [
        "Observed 6 connection-timeout errors on api-gateway within 2 minutes.",
        "All timeouts targeted db-primary, so the fault is in DB connectivity.",
        "Saturation in the pool explains the cascading 5xx from api-gateway.",
    ],
    "relevant_log_lines": [
        {"log_id": 101, "reason": "First db-primary connection timeout"},
        {"log_id": 105, "reason": "Repeated after 90s - sustained failure"},
    ],
}


class ScriptedProvider(LLMProvider):
    """Provider stub that returns a pre-scripted list of responses."""

    name = "scripted"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if not self._responses:
            raise AssertionError("ScriptedProvider out of responses")
        return self._responses.pop(0)


@pytest.fixture
def patch_provider(monkeypatch):
    """Install a scripted provider and clear the factory cache."""

    def _install(responses):
        provider = ScriptedProvider(responses)
        llm_client._get_provider.cache_clear()
        monkeypatch.setattr(llm_client, "_get_provider", lambda: provider)
        return provider

    yield _install
    llm_client._get_provider.cache_clear()


def test_parse_and_validate_accepts_valid_json():
    obj, err = _parse_and_validate(json.dumps(VALID_PAYLOAD))
    assert err is None
    assert obj["severity"] == "high"
    assert obj["confidence"] == 0.82


def test_parse_and_validate_strips_code_fence():
    fenced = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    obj, err = _parse_and_validate(fenced)
    assert err is None
    assert obj is not None


def test_parse_and_validate_rejects_non_json():
    obj, err = _parse_and_validate("not json at all")
    assert obj is None
    assert "JSON" in err


def test_parse_and_validate_rejects_bad_schema():
    bad = {**VALID_PAYLOAD, "severity": "banana"}
    obj, err = _parse_and_validate(json.dumps(bad))
    assert obj is None
    assert "schema" in err.lower()


def test_salvage_fixes_unknown_severity():
    bad = {**VALID_PAYLOAD, "severity": "banana"}
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    assert obj["severity"] == "medium"  # salvage default


def test_salvage_clamps_confidence_out_of_range():
    bad = {**VALID_PAYLOAD, "confidence": 7.3}
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    assert obj["confidence"] == 1.0


def test_salvage_coerces_string_confidence():
    bad = {**VALID_PAYLOAD, "confidence": "0.42"}
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    assert obj["confidence"] == 0.42


def test_salvage_defaults_missing_optional_fields():
    partial = {
        "issue": "x",
        "root_cause": "y",
        "fix": "z",
        "severity": "high",
        # no confidence / needs_more_data / requested_action / args / reasoning / refs
    }
    obj, err = _parse_and_validate(json.dumps(partial), allow_salvage=True)
    assert err is None
    assert obj["confidence"] == 0.5
    assert obj["needs_more_data"] is False
    assert obj["requested_action"] == "none"
    assert obj["requested_action_args"] == {}
    # Salvage synthesizes a placeholder reasoning step and an empty refs list.
    assert isinstance(obj["reasoning_steps"], list)
    assert len(obj["reasoning_steps"]) >= 1
    assert "did not provide" in obj["reasoning_steps"][0].lower()
    assert obj["relevant_log_lines"] == []


def test_salvage_refuses_when_required_text_missing():
    """No essential fields -> salvage must return None, validation error raised."""
    bare = {"severity": "high"}  # no issue/root_cause/fix
    obj, err = _parse_and_validate(json.dumps(bare), allow_salvage=True)
    assert obj is None
    assert err is not None


def test_salvage_normalizes_bogus_requested_action():
    bad = {**VALID_PAYLOAD, "requested_action": "teleport"}
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    assert obj["requested_action"] == "none"


def test_call_llm_salvages_on_final_attempt_only(patch_provider, monkeypatch):
    """Strict early attempts pressure the model; salvage kicks in only at the end."""
    monkeypatch.setattr(llm_client.settings, "llm_max_retries", 2)
    slightly_broken = {**VALID_PAYLOAD, "severity": "banana"}
    # All 3 attempts return the same slightly-broken payload.
    provider = patch_provider([json.dumps(slightly_broken)] * 3)
    result = call_llm("sys", "user")
    assert result["severity"] == "medium"  # salvaged
    assert len(provider.calls) == 3  # earlier attempts DID fail (triggering retries)


def test_call_llm_success_first_try(patch_provider):
    provider = patch_provider([json.dumps(VALID_PAYLOAD)])
    result = call_llm("sys", "user")
    assert result["issue"] == VALID_PAYLOAD["issue"]
    assert len(provider.calls) == 1


def test_call_llm_recovers_on_retry(patch_provider, monkeypatch):
    monkeypatch.setattr(llm_client.settings, "llm_max_retries", 2)
    provider = patch_provider([
        "garbage, not json",
        json.dumps(VALID_PAYLOAD),
    ])
    result = call_llm("sys", "user")
    assert result["severity"] == "high"
    assert len(provider.calls) == 2
    # Second attempt should include the corrective nudge.
    assert "rejected" in provider.calls[1][1].lower()


def test_call_llm_raises_after_exhausting_retries(patch_provider, monkeypatch):
    monkeypatch.setattr(llm_client.settings, "llm_max_retries", 2)
    provider = patch_provider(["nope", "still nope", "nope again"])
    with pytest.raises(LLMValidationError) as excinfo:
        call_llm("sys", "user")
    assert len(provider.calls) == 3  # 1 + 2 retries
    assert len(excinfo.value.errors) == 3
    assert excinfo.value.last_raw == "nope again"


def test_strict_validation_rejects_missing_reasoning_steps():
    """Early attempts must fail when reasoning_steps is absent (pressures the model)."""
    bad = {k: v for k, v in VALID_PAYLOAD.items() if k != "reasoning_steps"}
    obj, err = _parse_and_validate(json.dumps(bad))
    assert obj is None
    assert "schema" in err.lower()


def test_strict_validation_rejects_empty_reasoning_steps():
    bad = {**VALID_PAYLOAD, "reasoning_steps": []}
    obj, err = _parse_and_validate(json.dumps(bad))
    assert obj is None


def test_salvage_synthesizes_reasoning_when_missing():
    bad = {k: v for k, v in VALID_PAYLOAD.items() if k != "reasoning_steps"}
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    assert len(obj["reasoning_steps"]) == 1
    assert "did not provide" in obj["reasoning_steps"][0].lower()


def test_salvage_trims_blank_reasoning_steps():
    bad = {**VALID_PAYLOAD, "reasoning_steps": ["  ", "", "real step", "   "]}
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    assert obj["reasoning_steps"] == ["real step"]


def test_salvage_drops_malformed_log_references():
    """References without any identifier must be filtered out, not crash salvage."""
    bad = {
        **VALID_PAYLOAD,
        "relevant_log_lines": [
            {"log_id": 42, "reason": "ok"},
            {"reason": "no identifier - should be dropped"},
            {"excerpt": "   ", "reason": "blank excerpt - drop"},
            {"line_index": 3},
            "not a dict - should be dropped",
        ],
    }
    obj, err = _parse_and_validate(json.dumps(bad), allow_salvage=True)
    assert err is None
    refs = obj["relevant_log_lines"]
    assert len(refs) == 2
    assert refs[0]["log_id"] == 42
    assert refs[1]["line_index"] == 3


def test_strict_validation_rejects_empty_log_reference():
    """A LogReference without any identifier must fail strict validation."""
    bad = {
        **VALID_PAYLOAD,
        "relevant_log_lines": [{"reason": "no identifier"}],
    }
    obj, err = _parse_and_validate(json.dumps(bad))
    assert obj is None


def test_log_reference_accepts_excerpt_only():
    good = {
        **VALID_PAYLOAD,
        "relevant_log_lines": [{"excerpt": "connection timeout to db"}],
    }
    obj, err = _parse_and_validate(json.dumps(good))
    assert err is None
    assert obj["relevant_log_lines"][0]["excerpt"] == "connection timeout to db"


def test_unsupported_provider_raises(monkeypatch):
    llm_client._get_provider.cache_clear()
    monkeypatch.setattr(llm_client.settings, "llm_provider", "bogus")
    with pytest.raises(LLMError):
        llm_client._get_provider()
    llm_client._get_provider.cache_clear()
