"""Unit tests for the public-demo cached-analysis fallback."""

import pytest

from app.agent.demo_cache import (
    build_cached_run,
    cached_run_for_logs,
    classify_scenario,
)
from app.schemas.analysis import LLMStructuredOutput
from app.services.evaluation_service import evaluate_prediction, get_ground_truth
from app.services.log_generator import generate_scenario

SCENARIOS = ["database_failure", "memory_leak", "latency_spike"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_classify_recognizes_generated_scenarios(scenario):
    """Logs from each generator should classify back to their scenario."""
    logs = [l.model_dump() for l in generate_scenario(scenario, seed=1)]
    assert classify_scenario(logs) == scenario


def test_classify_returns_none_for_unrelated_logs():
    logs = [
        {"service_name": "web", "message": "GET /health 200 in 5ms"},
        {"service_name": "web", "message": "cache hit rate=0.91"},
    ]
    assert classify_scenario(logs) is None


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_build_cached_run_is_valid_and_confident(scenario):
    run = build_cached_run(scenario)
    assert isinstance(run.final, LLMStructuredOutput)
    assert run.iterations == 1
    assert run.observability is not None
    assert run.observability.stopped_reason == "confident"
    assert run.final.confidence >= 0.6
    assert run.final.reasoning_steps  # non-empty chain-of-thought


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_cached_analyses_pass_the_eval_ground_truth(scenario):
    """A cached answer should be at least as good as a correct live run: it must
    pass the same accuracy/severity gate the eval harness uses."""
    run = build_cached_run(scenario)
    predicted = run.final.model_dump(mode="json")
    result = evaluate_prediction(predicted, get_ground_truth(scenario))
    assert result.overall_correct, (
        f"{scenario}: cached analysis failed eval "
        f"(rc={result.root_cause_match} sev={result.severity_match} "
        f"fix={result.fix_match})"
    )
    assert result.severity_match


def test_cached_run_for_logs_roundtrip():
    logs = [l.model_dump() for l in generate_scenario("memory_leak", seed=2)]
    run = cached_run_for_logs(logs)
    assert run is not None
    assert run.final.severity.value == "critical"
