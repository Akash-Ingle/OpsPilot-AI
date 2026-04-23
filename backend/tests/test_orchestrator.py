"""Tests for run_agent_once and run_agent_loop."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.agent import orchestrator, tools
from app.agent.orchestrator import (
    AgentRunResult,
    run_agent_loop,
    run_agent_once,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import ToolResult
from app.schemas.analysis import LLMStructuredOutput


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


def _valid(**overrides: Any) -> Dict[str, Any]:
    base = {
        "issue": "DB connection pool exhausted",
        "root_cause": "api-gateway holding connections on slow payments-svc calls",
        "fix": "Increase pool size to 50 and add circuit breaker on payments-svc",
        "severity": "high",
        "confidence": 0.83,
        "needs_more_data": False,
        "requested_action": "none",
        "requested_action_args": {},
        "reasoning_steps": [
            "Observed repeated connection-timeout errors on api-gateway.",
            "The repeated pattern points at an exhausted DB connection pool.",
        ],
        "relevant_log_lines": [
            {"log_id": 1, "reason": "first connection timeout"},
            {"log_id": 2, "reason": "repeat confirms sustained failure"},
        ],
    }
    base.update(overrides)
    return base


def _logs() -> List[FakeLog]:
    ts = datetime(2026, 4, 23, 14, 0, tzinfo=timezone.utc)
    return [
        FakeLog(1, ts, "api-gateway", "error", "connection timeout to db-primary"),
        FakeLog(2, ts, "api-gateway", "error", "connection timeout to db-primary"),
    ]


def _anoms() -> List[FakeAnomaly]:
    return [
        FakeAnomaly(
            kind="error_spike",
            service="api-gateway",
            severity="high",
            summary="2 errors in api-gateway",
            score=0.7,
            evidence_log_ids=[1, 2],
        )
    ]


# ---------------------------------------------------------------------------
# run_agent_once
# ---------------------------------------------------------------------------


def test_run_agent_once_returns_validated_model(monkeypatch):
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: _valid())
    result = run_agent_once(_logs(), _anoms())
    assert isinstance(result, LLMStructuredOutput)
    assert result.severity.value == "high"


def test_run_agent_once_passes_system_prompt(monkeypatch):
    captured: dict = {}

    def fake(system, user):
        captured["system"] = system
        captured["user"] = user
        return _valid()

    monkeypatch.setattr(orchestrator, "call_llm", fake)
    run_agent_once(_logs(), _anoms())
    assert captured["system"] == SYSTEM_PROMPT
    assert "### Logs summary" in captured["user"]


# ---------------------------------------------------------------------------
# run_agent_loop: happy paths
# ---------------------------------------------------------------------------


def test_loop_terminates_immediately_when_confident(monkeypatch):
    calls = {"n": 0}

    def fake(system, user):
        calls["n"] += 1
        return _valid(needs_more_data=False)

    monkeypatch.setattr(orchestrator, "call_llm", fake)

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert isinstance(result, AgentRunResult)
    assert result.iterations == 1
    assert calls["n"] == 1
    assert result.final.needs_more_data is False
    assert len(result.trace) == 1
    assert result.trace[0].tool_call is None
    assert result.trace[0].tool_result is None


def test_loop_dispatches_tool_and_reruns_llm(monkeypatch):
    """Step 1: needs_more_data=True + get_metrics. Step 2: resolves."""
    responses = [
        _valid(
            needs_more_data=True,
            requested_action="get_metrics",
            requested_action_args={"service": "api-gateway"},
            confidence=0.4,
        ),
        _valid(needs_more_data=False, confidence=0.9),
    ]
    seen_prompts: List[str] = []

    def fake_llm(system, user):
        seen_prompts.append(user)
        return responses.pop(0)

    def fake_get_metrics(service):
        return ToolResult(ok=True, data={"service": service, "cpu": 94.2, "memory_mb": 1700})

    monkeypatch.setattr(orchestrator, "call_llm", fake_llm)
    monkeypatch.setitem(tools.TOOL_REGISTRY, "get_metrics", fake_get_metrics)

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)

    assert result.iterations == 2
    assert result.final.needs_more_data is False
    assert result.final.confidence == 0.9

    step1 = result.trace[0]
    assert step1.tool_call == {"name": "get_metrics", "args": {"service": "api-gateway"}}
    assert step1.tool_result["ok"] is True
    assert step1.tool_result["data"]["cpu"] == 94.2
    # LLM-friendly rendering is captured for the next prompt.
    assert step1.tool_text is not None
    assert "tool_call: get_metrics" in step1.tool_text
    assert "api-gateway" in step1.tool_text

    step2 = result.trace[1]
    assert step2.tool_call is None

    # Step 2 prompt contains the tool result from step 1 (context maintained).
    assert "Prior reasoning and tool results" in seen_prompts[1]
    assert "get_metrics" in seen_prompts[1]
    assert "cpu" in seen_prompts[1]
    assert "Prior reasoning and tool results" not in seen_prompts[0]


# ---------------------------------------------------------------------------
# run_agent_loop: termination edge cases
# ---------------------------------------------------------------------------


def test_loop_caps_at_max_iterations(monkeypatch):
    call_count = {"n": 0}

    def fake_llm(system, user):
        call_count["n"] += 1
        return _valid(
            needs_more_data=True,
            requested_action="fetch_logs",
            requested_action_args={"time_range": "15m"},
            confidence=0.5,
        )

    monkeypatch.setattr(orchestrator, "call_llm", fake_llm)
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "fetch_logs",
        lambda time_range, service=None: ToolResult(
            ok=True, data={"note": "more logs", "time_range": time_range}
        ),
    )

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 3
    assert call_count["n"] == 3
    # After step 3 we do NOT dispatch another tool (hit the cap first).
    assert result.trace[2].tool_call is None
    assert result.trace[0].tool_call is not None
    assert result.trace[1].tool_call is not None


def test_final_turn_prompt_instructs_commitment(monkeypatch):
    seen_prompts: List[str] = []
    responses = [
        _valid(needs_more_data=True, requested_action="get_metrics",
               requested_action_args={"service": "x"}),
        _valid(needs_more_data=True, requested_action="get_metrics",
               requested_action_args={"service": "x"}),
        _valid(needs_more_data=True, requested_action="get_metrics",
               requested_action_args={"service": "x"}),
    ]

    def fake_llm(system, user):
        seen_prompts.append(user)
        return responses.pop(0)

    monkeypatch.setattr(orchestrator, "call_llm", fake_llm)
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "get_metrics",
        lambda service: ToolResult(ok=True, data={"service": service}),
    )

    run_agent_loop(_logs(), _anoms(), max_iterations=3)

    assert "Final turn" not in seen_prompts[0]
    assert "Final turn" not in seen_prompts[1]
    assert "Final turn" in seen_prompts[2]


def test_loop_exits_when_action_is_none_but_needs_more_data(monkeypatch):
    call_count = {"n": 0}

    def fake_llm(system, user):
        call_count["n"] += 1
        return _valid(needs_more_data=True, requested_action="none")

    monkeypatch.setattr(orchestrator, "call_llm", fake_llm)

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 1
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Tool-dispatch error handling (delegated to execute_tool now)
# ---------------------------------------------------------------------------


def test_loop_handles_unknown_tool_gracefully(monkeypatch):
    """Registered tool is temporarily removed -> captured error, loop continues."""
    responses = [
        _valid(needs_more_data=True, requested_action="fetch_logs",
               requested_action_args={"time_range": "15m"}),
        _valid(needs_more_data=False, confidence=0.7),
    ]
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: responses.pop(0))

    original = tools.TOOL_REGISTRY.copy()
    try:
        del tools.TOOL_REGISTRY["fetch_logs"]
        result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    finally:
        tools.TOOL_REGISTRY.clear()
        tools.TOOL_REGISTRY.update(original)

    assert result.iterations == 2
    step1 = result.trace[0]
    assert step1.tool_call["name"] == "fetch_logs"
    assert step1.tool_result["ok"] is False
    assert "unknown tool" in step1.tool_result["error"]


def test_loop_handles_tool_bad_args(monkeypatch):
    """execute_tool's arg validator surfaces the error before the tool runs."""
    responses = [
        _valid(
            needs_more_data=True,
            requested_action="scale_service",
            requested_action_args={"wrong_kwarg": "x"},
        ),
        _valid(needs_more_data=False),
    ]
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: responses.pop(0))

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 2
    assert result.trace[0].tool_result["ok"] is False
    err = result.trace[0].tool_result["error"]
    assert "argument validation failed" in err
    assert "wrong_kwarg" in err


def test_loop_handles_tool_returning_error(monkeypatch):
    responses = [
        _valid(
            needs_more_data=True,
            requested_action="scale_service",
            requested_action_args={"service_name": "x", "replicas": 500},
        ),
        _valid(needs_more_data=False, confidence=0.7),
    ]
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: responses.pop(0))

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 2
    assert result.trace[0].tool_result["ok"] is False
    assert "replicas" in result.trace[0].tool_result["error"]


def test_max_iterations_is_clamped(monkeypatch):
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: _valid())

    result = run_agent_loop(_logs(), _anoms(), max_iterations=0)
    assert result.iterations == 1  # clamped up to 1

    result = run_agent_loop(_logs(), _anoms(), max_iterations=999)
    assert result.iterations == 1  # model says no more data, stops at 1


# ---------------------------------------------------------------------------
# Confidence threshold handling
# ---------------------------------------------------------------------------


def test_low_confidence_forces_another_iteration(monkeypatch):
    """Model says done but confidence below threshold -> force another LLM call."""
    monkeypatch.setattr(orchestrator.settings, "llm_min_confidence", 0.6)
    responses = [
        _valid(needs_more_data=False, confidence=0.4),   # below threshold
        _valid(needs_more_data=False, confidence=0.85),  # final answer
    ]
    seen_prompts: List[str] = []

    def fake_llm(system, user):
        seen_prompts.append(user)
        return responses.pop(0)

    monkeypatch.setattr(orchestrator, "call_llm", fake_llm)

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 2
    assert result.final.confidence == 0.85

    # Step 1 is marked as a low-confidence forced retry.
    assert result.trace[0].low_confidence_retry is True
    assert result.trace[1].low_confidence_retry is False

    # The second prompt must contain the low-confidence nudge.
    assert "below the required threshold" in seen_prompts[1]
    assert "0.40" in seen_prompts[1]


def test_high_confidence_still_terminates_immediately(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "llm_min_confidence", 0.6)
    monkeypatch.setattr(
        orchestrator, "call_llm",
        lambda s, u: _valid(needs_more_data=False, confidence=0.8),
    )
    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 1
    assert result.trace[0].low_confidence_retry is False


def test_low_confidence_on_final_turn_accepts_answer(monkeypatch):
    """If the model is still low-confidence at max_iterations, accept anyway."""
    monkeypatch.setattr(orchestrator.settings, "llm_min_confidence", 0.6)
    monkeypatch.setattr(
        orchestrator, "call_llm",
        lambda s, u: _valid(needs_more_data=False, confidence=0.3),
    )
    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 3
    assert result.final.confidence == 0.3
    # All iterations except the last were low-confidence retries.
    assert result.trace[0].low_confidence_retry is True
    assert result.trace[1].low_confidence_retry is True
    assert result.trace[2].low_confidence_retry is False  # final turn accepts


def test_threshold_configurable(monkeypatch):
    """Setting llm_min_confidence=0 disables the forced-retry behavior."""
    monkeypatch.setattr(orchestrator.settings, "llm_min_confidence", 0.0)
    monkeypatch.setattr(
        orchestrator, "call_llm",
        lambda s, u: _valid(needs_more_data=False, confidence=0.1),
    )
    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    assert result.iterations == 1  # no forced retry
    assert result.trace[0].low_confidence_retry is False


# ---------------------------------------------------------------------------
# Vector-memory integration
# ---------------------------------------------------------------------------


from app.services import memory_service as memory_service_module
from app.services.memory_service import SimilarIncident


def test_run_agent_once_injects_historical_context(monkeypatch):
    """The top-K similar past incidents must be rendered into the user prompt."""
    fake_similar = [
        SimilarIncident(
            incident_id=11,
            title="previous db pool exhaustion",
            severity="high",
            root_cause="payments-svc held connections",
            fix="increase pool + circuit breaker",
            distance=0.08,
        ),
    ]
    monkeypatch.setattr(
        memory_service_module,
        "retrieve_similar_incidents",
        lambda logs, n_results=3: fake_similar,
    )

    captured: dict = {}

    def fake(system, user):
        captured["user"] = user
        return _valid()

    monkeypatch.setattr(orchestrator, "call_llm", fake)

    run_agent_once(_logs(), _anoms())
    assert "Similar past incidents" in captured["user"]
    assert "previous db pool exhaustion" in captured["user"]
    assert "similarity=0.92" in captured["user"]


def test_run_agent_once_no_history_omits_section(monkeypatch):
    monkeypatch.setattr(
        memory_service_module,
        "retrieve_similar_incidents",
        lambda logs, n_results=3: [],
    )

    captured: dict = {}

    def fake(system, user):
        captured["user"] = user
        return _valid()

    monkeypatch.setattr(orchestrator, "call_llm", fake)

    run_agent_once(_logs(), _anoms())
    assert "Similar past incidents" not in captured["user"]


def test_run_agent_loop_passes_history_to_every_iteration(monkeypatch):
    """History is retrieved once and preserved across loop iterations."""
    fake_similar = [
        SimilarIncident(
            incident_id=1, title="prior db incident", severity="high",
            root_cause="pool exhausted", fix="scale db", distance=0.1,
        ),
    ]
    call_count = {"retrieve": 0}

    def fake_retrieve(logs, n_results=3):
        call_count["retrieve"] += 1
        return fake_similar

    monkeypatch.setattr(
        memory_service_module, "retrieve_similar_incidents", fake_retrieve
    )

    seen_prompts: List[str] = []
    responses = [
        _valid(
            needs_more_data=True,
            requested_action="get_metrics",
            requested_action_args={"service": "api-gateway"},
            confidence=0.4,
        ),
        _valid(needs_more_data=False, confidence=0.9),
    ]

    def fake_llm(system, user):
        seen_prompts.append(user)
        return responses.pop(0)

    monkeypatch.setattr(orchestrator, "call_llm", fake_llm)
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "get_metrics",
        lambda service: ToolResult(ok=True, data={"service": service, "cpu": 90}),
    )

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)

    # Retrieval happens exactly once per agent run, not per iteration.
    assert call_count["retrieve"] == 1
    assert result.iterations == 2
    # Historical context is present in BOTH iteration prompts (baked into base_prompt).
    assert "prior db incident" in seen_prompts[0]
    assert "prior db incident" in seen_prompts[1]


def test_memory_retrieval_failure_does_not_break_agent(monkeypatch):
    """A broken memory service must not propagate into the agent loop."""
    def boom(logs, n_results=3):
        raise RuntimeError("chroma died")

    monkeypatch.setattr(memory_service_module, "retrieve_similar_incidents", boom)
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: _valid())

    result = run_agent_loop(_logs(), _anoms(), max_iterations=2)
    assert result.iterations == 1
    assert result.final.severity.value == "high"


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def test_observability_populated_on_confident_single_iteration(monkeypatch):
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: _valid(confidence=0.9))

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    obs = result.observability
    assert obs is not None
    assert obs.iterations == 1
    assert obs.max_iterations == 3
    assert obs.stopped_reason == "confident"
    assert obs.low_confidence_retries == 0
    assert obs.tools_called == []
    assert obs.confidence_progression == [0.9]
    assert len(obs.iteration_trace) == 1
    assert obs.iteration_trace[0].step == 1
    assert obs.iteration_trace[0].confidence == pytest.approx(0.9)
    assert obs.iteration_trace[0].tool_call is None
    assert obs.iteration_trace[0].duration_ms >= 0.0
    assert obs.duration_ms >= 0.0
    assert obs.finished_at >= obs.started_at


def test_observability_tracks_tools_called_per_step(monkeypatch):
    responses = [
        _valid(
            needs_more_data=True,
            requested_action="get_metrics",
            requested_action_args={"service": "api-gateway"},
            confidence=0.4,
        ),
        _valid(
            needs_more_data=True,
            requested_action="fetch_logs",
            requested_action_args={"time_range": "15m"},
            confidence=0.55,
        ),
        _valid(needs_more_data=False, confidence=0.92),
    ]
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: responses.pop(0))
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "get_metrics",
        lambda service: ToolResult(ok=True, data={"service": service, "cpu": 90}),
    )
    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "fetch_logs",
        lambda time_range, service=None: ToolResult(
            ok=True, data={"time_range": time_range, "note": "more logs"}
        ),
    )

    result = run_agent_loop(_logs(), _anoms(), max_iterations=4)
    obs = result.observability
    assert obs is not None
    assert obs.iterations == 3
    assert obs.stopped_reason == "confident"

    assert [t.name for t in obs.tools_called] == ["get_metrics", "fetch_logs"]
    assert [t.step for t in obs.tools_called] == [1, 2]
    assert all(t.ok for t in obs.tools_called)
    assert all(t.duration_ms >= 0.0 for t in obs.tools_called)
    assert obs.tools_called[0].args == {"service": "api-gateway"}

    # Iteration trace mirrors tool dispatch per step.
    assert obs.iteration_trace[0].tool_call is not None
    assert obs.iteration_trace[0].tool_call.name == "get_metrics"
    assert obs.iteration_trace[1].tool_call is not None
    assert obs.iteration_trace[1].tool_call.name == "fetch_logs"
    assert obs.iteration_trace[2].tool_call is None
    assert obs.confidence_progression == [0.4, 0.55, 0.92]


def test_observability_records_failed_tool_call(monkeypatch):
    """Tool failures (bad args) show up as ok=False in tools_called."""
    responses = [
        _valid(
            needs_more_data=True,
            requested_action="scale_service",
            requested_action_args={"wrong": "x"},
            confidence=0.5,
        ),
        _valid(needs_more_data=False, confidence=0.9),
    ]
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: responses.pop(0))

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    obs = result.observability
    assert obs is not None
    assert len(obs.tools_called) == 1
    tc = obs.tools_called[0]
    assert tc.name == "scale_service"
    assert tc.ok is False
    assert tc.error is not None
    assert "wrong" in tc.error


def test_observability_stopped_reason_low_confidence_final(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "llm_min_confidence", 0.6)
    monkeypatch.setattr(
        orchestrator,
        "call_llm",
        lambda s, u: _valid(needs_more_data=False, confidence=0.3),
    )
    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    obs = result.observability
    assert obs is not None
    assert obs.iterations == 3
    assert obs.stopped_reason == "low_confidence_final"
    # Two low-confidence forced retries before hitting the cap on iteration 3.
    assert obs.low_confidence_retries == 2
    assert obs.confidence_progression == [0.3, 0.3, 0.3]


def test_observability_stopped_reason_no_progress(monkeypatch):
    """needs_more_data=true with requested_action='none' -> no_progress."""
    monkeypatch.setattr(
        orchestrator,
        "call_llm",
        lambda s, u: _valid(needs_more_data=True, requested_action="none", confidence=0.8),
    )
    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    obs = result.observability
    assert obs is not None
    assert obs.iterations == 1
    assert obs.stopped_reason == "no_progress"


def test_observability_confidence_progression_shows_change(monkeypatch):
    """Progression captures each step's confidence in order."""
    monkeypatch.setattr(orchestrator.settings, "llm_min_confidence", 0.6)
    responses = [
        _valid(needs_more_data=False, confidence=0.3),   # low -> forced retry
        _valid(needs_more_data=False, confidence=0.5),   # still low -> forced retry
        _valid(needs_more_data=False, confidence=0.85),  # accepted
    ]
    monkeypatch.setattr(orchestrator, "call_llm", lambda s, u: responses.pop(0))

    result = run_agent_loop(_logs(), _anoms(), max_iterations=3)
    obs = result.observability
    assert obs is not None
    assert obs.confidence_progression == [0.3, 0.5, 0.85]
    assert obs.stopped_reason == "confident"
    assert obs.low_confidence_retries == 2
