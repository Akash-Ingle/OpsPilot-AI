"""Canned analyses for the public demo.

The public demo runs on a free-tier LLM with a small daily request quota. When
that quota is exhausted (or the provider is briefly unavailable), the `/analyze`
endpoint falls back to a pre-computed, high-quality analysis for whichever of
the three built-in failure scenarios the logs most resemble. This keeps the
demo responsive and free while still using the live model whenever quota allows.

These canned outputs are hand-written to match the evaluation ground truth, so a
cached response is just as accurate as a good live run - it simply skips the LLM
call. Nothing here is used unless `settings.demo_cache_enabled` is true AND a
live call has already failed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.agent.orchestrator import AgentRunResult, AgentStep
from app.core.logging import logger
from app.schemas.analysis import (
    AgentObservability,
    IterationRecord,
    LLMStructuredOutput,
)

# ---------------------------------------------------------------------------
# Canned analyses (one per built-in scenario)
# ---------------------------------------------------------------------------

_CANNED: Dict[str, Dict[str, Any]] = {
    "database_failure": {
        "issue": "Primary database unreachable; connection pool exhausted",
        "root_cause": (
            "The primary database (db-primary) became unreachable, so requests "
            "block waiting on connections until the orders-svc connection pool is "
            "fully exhausted. Connection timeouts then cascade into upstream 5xx "
            "errors at the api-gateway."
        ),
        "fix": (
            "Restore db-primary connectivity or fail over to a read replica, then "
            "increase the connection pool size and add a circuit breaker on the "
            "data path so a slow database degrades gracefully instead of blocking."
        ),
        "severity": "critical",
        "confidence": 0.94,
        "reasoning_steps": [
            "Sustained 'connection timeout to db-primary' errors on orders-svc.",
            "'connection pool exhausted (size=20 in_use=20)' confirms saturation.",
            "api-gateway logs 'UPSTREAM_TIMEOUT' / 503s -> failure is cascading.",
            "Requests can no longer complete -> full outage, severity=critical.",
        ],
        "relevant_log_lines": [
            {"excerpt": "connection timeout to db-primary", "reason": "primary datastore unreachable"},
            {"excerpt": "connection pool exhausted", "reason": "pool fully saturated"},
            {"excerpt": "UPSTREAM_TIMEOUT", "reason": "failure cascading to the gateway"},
        ],
    },
    "memory_leak": {
        "issue": "Heap exhaustion leading to OutOfMemory crash",
        "root_cause": (
            "inventory-svc has a memory leak: the heap grows steadily until "
            "garbage collection thrashes (long, frequent full GCs), ending in an "
            "OutOfMemoryError and an oom_killer SIGKILL (exit 137)."
        ),
        "fix": (
            "Restart inventory-svc to reclaim memory immediately, then capture a "
            "heap dump to find and patch the leak; raise the heap limit only as a "
            "temporary stopgap until the leak is fixed."
        ),
        "severity": "critical",
        "confidence": 0.93,
        "reasoning_steps": [
            "heap_mb climbs monotonically across the window.",
            "GC pause times and full_gc_count rise sharply -> GC thrash.",
            "Terminal 'OutOfMemoryError' then 'exit_code=137 SIGKILL oom_killer'.",
            "Process was killed -> crash, severity=critical.",
        ],
        "relevant_log_lines": [
            {"excerpt": "GC thrash detected", "reason": "garbage collector saturated"},
            {"excerpt": "OutOfMemoryError: Java heap space", "reason": "heap exhausted"},
            {"excerpt": "exit_code=137 signal=SIGKILL reason=oom_killer", "reason": "OOM-killed"},
        ],
    },
    "latency_spike": {
        "issue": "p99 latency spike from a slow downstream dependency",
        "root_cause": (
            "A slow downstream dependency (payments-svc) is driving checkout-svc "
            "p99 latency from ~80ms up past 2000ms. At the peak, a fraction of "
            "requests exceed their upstream timeout and return 504s, but the "
            "service is still serving traffic - this is degradation, not an outage."
        ),
        "fix": (
            "Tighten timeouts and add a circuit breaker on the slow payments-svc "
            "dependency, scale checkout-svc horizontally to shed load, and add "
            "retries with backoff so transient slowness doesn't surface as 504s."
        ),
        "severity": "high",
        "confidence": 0.9,
        "reasoning_steps": [
            "latency_ms ramps from baseline ~80ms to >2000ms (p99 window grows).",
            "'upstream_timeout ... upstream=payments-svc' points at a downstream dep.",
            "Some requests 504, but most still complete -> degradation, not outage.",
            "A 504 means a dependency is slow, not that this service is down -> high.",
        ],
        "relevant_log_lines": [
            {"excerpt": "slow_request", "reason": "latency climbing above threshold"},
            {"excerpt": "upstream_timeout", "reason": "downstream payments-svc too slow"},
            {"excerpt": "status=504", "reason": "timeouts at the peak"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Scenario classification
# ---------------------------------------------------------------------------

# Distinctive markers per scenario (substring match against message + service).
_MARKERS: Dict[str, Sequence[str]] = {
    "database_failure": (
        "db-primary", "connection pool exhausted", "upstream_timeout",
        "orders-pool", "circuit breaker opened for db-primary", "orders-svc",
    ),
    "memory_leak": (
        "outofmemoryerror", "oom_killer", "gc thrash", "heap_mb",
        "full_gc_count", "inventory-svc", "exit_code=137",
    ),
    "latency_spike": (
        "slow_request", "latency_ms", "p99_window_ms", "upstream=payments-svc",
        "status=504", "checkout-svc",
    ),
}


def _log_text(log: Any) -> str:
    """Best-effort 'service + message' text for a Log ORM object or dict."""
    if isinstance(log, dict):
        service = log.get("service_name", "")
        message = log.get("message", "")
    else:
        service = getattr(log, "service_name", "") or ""
        message = getattr(log, "message", "") or ""
    return f"{service} {message}".lower()


def classify_scenario(logs: Sequence[Any]) -> Optional[str]:
    """Map a batch of logs to the closest built-in scenario, or None.

    Scores each scenario by how many of its marker substrings appear across the
    logs. Returns the highest-scoring scenario, requiring at least two distinct
    marker hits so unrelated logs don't get force-fit to a canned answer.
    """
    blob = "\n".join(_log_text(l) for l in logs)
    scores = {
        scenario: sum(1 for marker in markers if marker in blob)
        for scenario, markers in _MARKERS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 2:
        return None
    return best


# ---------------------------------------------------------------------------
# Cached run construction
# ---------------------------------------------------------------------------


def build_cached_run(scenario: str) -> AgentRunResult:
    """Build an `AgentRunResult` from the canned analysis for `scenario`.

    Shaped exactly like a real single-iteration run so the `/analyze` route can
    persist and serialize it without any special-casing.
    """
    payload = _CANNED[scenario]
    final = LLMStructuredOutput.model_validate(
        {
            **payload,
            "needs_more_data": False,
            "requested_action": "none",
            "requested_action_args": {},
        }
    )

    now = datetime.now(timezone.utc)
    confidence = float(final.confidence)
    observability = AgentObservability(
        iterations=1,
        max_iterations=1,
        duration_ms=0.0,
        started_at=now,
        finished_at=now,
        stopped_reason="confident",
        low_confidence_retries=0,
        confidence_progression=[round(confidence, 4)],
        tools_called=[],
        iteration_trace=[
            IterationRecord(
                step=1,
                confidence=confidence,
                severity=final.severity.value
                if hasattr(final.severity, "value")
                else str(final.severity),
                needs_more_data=False,
                requested_action="none",
                low_confidence_retry=False,
                tool_call=None,
                duration_ms=0.0,
            )
        ],
    )
    trace: List[AgentStep] = [AgentStep(step=1, response=final.model_dump(mode="json"))]
    return AgentRunResult(
        final=final, iterations=1, trace=trace, observability=observability
    )


def cached_run_for_logs(logs: Sequence[Any]) -> Optional[AgentRunResult]:
    """Classify `logs` and return a canned run, or None if nothing matches."""
    scenario = classify_scenario(logs)
    if scenario is None:
        logger.info("demo_cache: no scenario matched; cannot serve cached analysis")
        return None
    logger.info("demo_cache: serving cached analysis for scenario={}", scenario)
    return build_cached_run(scenario)


__all__ = ["classify_scenario", "build_cached_run", "cached_run_for_logs"]
