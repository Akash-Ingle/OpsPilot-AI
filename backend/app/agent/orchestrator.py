"""Agent orchestration.

Public entry points:

- `run_agent_once(logs, anomalies)`: single-shot analysis. One LLM call, no
  tool dispatch.
- `run_agent_loop(logs, anomalies, max_iterations=3)`: multi-step reasoning
  loop. The LLM may request tool calls via `needs_more_data=true`; tool results
  are fed back into the next iteration's context. Stops when the model no
  longer needs more data, or when `max_iterations` is reached.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.agent.llm_client import call_llm
from app.agent.prompts import SYSTEM_PROMPT, build_analysis_prompt
from app.agent.tools import execute_tool
from app.config import settings
from app.core.logging import logger
from app.schemas.analysis import (
    AgentObservability,
    IterationRecord,
    LLMStructuredOutput,
    StoppedReason,
    ToolCallRecord,
)
from app.services import memory_service


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AgentStep:
    """A single iteration of the agent loop."""

    step: int
    response: Dict[str, Any]
    tool_call: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None
    tool_text: Optional[str] = None  # LLM-friendly rendering of the tool execution
    low_confidence_retry: bool = False  # iteration was forced by confidence threshold


@dataclass
class AgentRunResult:
    final: LLMStructuredOutput
    iterations: int
    trace: List[AgentStep] = field(default_factory=list)
    observability: Optional[AgentObservability] = None


# ---------------------------------------------------------------------------
# Single-shot
# ---------------------------------------------------------------------------


def run_agent_once(
    logs: Sequence[Any],
    anomalies: Sequence[Any],
) -> LLMStructuredOutput:
    """Run a single LLM analysis pass over the given logs and anomalies."""
    logger.info(
        "run_agent_once: analyzing {} log(s) and {} anomaly signal(s)",
        len(logs),
        len(anomalies),
    )

    historical = _fetch_historical_context(logs)
    user_prompt = build_analysis_prompt(logs, anomalies, historical_incidents=historical)
    logger.debug("Built user prompt ({} chars)", len(user_prompt))

    raw = call_llm(SYSTEM_PROMPT, user_prompt)
    result = LLMStructuredOutput.model_validate(raw)

    logger.info(
        "LLM response: severity={} confidence={:.2f} needs_more_data={} "
        "requested_action={}",
        _sev(result),
        float(result.confidence),
        result.needs_more_data,
        result.requested_action,
    )
    logger.debug("LLM response full payload: {}", result.model_dump(mode="json"))

    return result


# ---------------------------------------------------------------------------
# Multi-step loop
# ---------------------------------------------------------------------------


def run_agent_loop(
    logs: Sequence[Any],
    anomalies: Sequence[Any],
    max_iterations: int = 3,
) -> AgentRunResult:
    """Run the multi-step reasoning loop with tool dispatch.

    On each iteration:
      1. Render the user prompt = analysis base + all prior steps/tool results
         accumulated so far.
      2. Call the LLM, validate output.
      3. If `needs_more_data` is false OR max_iterations reached: stop.
      4. Else: dispatch `requested_action` via TOOL_REGISTRY, append the tool
         result to the context, and continue.

    Args:
        logs: Log entries (ORM `Log` instances or dicts).
        anomalies: Detected anomalies (`Anomaly` dataclasses or dicts).
        max_iterations: Upper bound on LLM calls (default 3, capped to [1, 10]).

    Returns:
        AgentRunResult with the final structured output, total iterations used,
        and a trace of every step (including tool calls/results).
    """
    max_iterations = max(1, min(int(max_iterations), 10))
    min_confidence = float(settings.llm_min_confidence)

    logger.info(
        "run_agent_loop: starting (logs={} anomalies={} max_iterations={} "
        "min_confidence={:.2f})",
        len(logs),
        len(anomalies),
        max_iterations,
        min_confidence,
    )

    historical = _fetch_historical_context(logs)
    base_prompt = build_analysis_prompt(
        logs, anomalies, historical_incidents=historical
    )
    trace: List[AgentStep] = []
    final_result: Optional[LLMStructuredOutput] = None
    extra_nudge: Optional[str] = None

    # --- Observability bookkeeping -----------------------------------------
    started_at = datetime.now(timezone.utc)
    loop_t0 = time.perf_counter()
    iteration_records: List[IterationRecord] = []
    tool_records: List[ToolCallRecord] = []
    confidence_progression: List[float] = []
    stopped_reason: StoppedReason = "max_iterations"

    for step in range(1, max_iterations + 1):
        is_final_turn = step == max_iterations
        user_prompt = _compose_iteration_prompt(
            base_prompt, trace, is_final_turn, extra_nudge=extra_nudge
        )
        extra_nudge = None  # consume once

        logger.info(
            "[step {}/{}] calling LLM (prompt_chars={}, prior_steps={})",
            step,
            max_iterations,
            len(user_prompt),
            len(trace),
        )

        iter_t0 = time.perf_counter()
        raw = call_llm(SYSTEM_PROMPT, user_prompt)
        result = LLMStructuredOutput.model_validate(raw)
        final_result = result

        confidence = float(result.confidence)
        confidence_progression.append(round(confidence, 4))

        logger.info(
            "[step {}/{}] LLM response: severity={} confidence={:.2f} "
            "needs_more_data={} requested_action={}",
            step,
            max_iterations,
            _sev(result),
            confidence,
            result.needs_more_data,
            result.requested_action,
        )

        current_step = AgentStep(step=step, response=result.model_dump(mode="json"))
        trace.append(current_step)

        # Will be populated below if this iteration dispatches a tool.
        tool_record: Optional[ToolCallRecord] = None

        # --- Termination analysis ------------------------------------------
        # Success: model is done AND confident enough.
        if not result.needs_more_data and confidence >= min_confidence:
            stopped_reason = "confident"
            iteration_records.append(
                _make_iter_record(step, result, current_step, iter_t0, tool_record)
            )
            logger.info(
                "[step {}/{}] model confident (confidence={:.2f} >= {:.2f}); loop finished",
                step, max_iterations, confidence, min_confidence,
            )
            break

        if is_final_turn:
            # We hit the cap. Distinguish "max_iterations while low confidence"
            # from plain max so operators can see calibration issues at a glance.
            stopped_reason = (
                "low_confidence_final" if confidence < min_confidence else "max_iterations"
            )
            iteration_records.append(
                _make_iter_record(step, result, current_step, iter_t0, tool_record)
            )
            logger.warning(
                "[step {}/{}] max iterations reached; accepting current answer "
                "(needs_more_data={}, confidence={:.2f})",
                step, max_iterations, result.needs_more_data, confidence,
            )
            break

        # Low-confidence path: model claims done, but confidence is below the
        # threshold. Force another iteration rather than stopping early.
        if not result.needs_more_data and confidence < min_confidence:
            current_step.low_confidence_retry = True
            iteration_records.append(
                _make_iter_record(step, result, current_step, iter_t0, tool_record)
            )
            logger.warning(
                "[step {}/{}] low confidence {:.2f} < {:.2f}; forcing another iteration",
                step, max_iterations, confidence, min_confidence,
            )
            extra_nudge = (
                f"Your previous answer reported confidence={confidence:.2f}, which "
                f"is below the required threshold of {min_confidence:.2f}. Either "
                "request more data via a tool call (set needs_more_data=true and "
                "a non-'none' requested_action), or re-examine the evidence to "
                "produce a more confident final answer."
            )
            continue

        # Model wants more data but did not pick a tool - cannot make progress.
        if result.requested_action == "none":
            stopped_reason = "no_progress"
            iteration_records.append(
                _make_iter_record(step, result, current_step, iter_t0, tool_record)
            )
            logger.warning(
                "[step {}/{}] needs_more_data=true but requested_action='none'; "
                "cannot make progress - stopping",
                step, max_iterations,
            )
            break

        # Dispatch the requested tool and attach its result to the step.
        tool_t0 = time.perf_counter()
        execution = execute_tool(
            result.requested_action, result.requested_action_args or {}
        )
        tool_duration_ms = (time.perf_counter() - tool_t0) * 1000.0

        current_step.tool_call = {"name": execution.name, "args": dict(execution.args)}
        current_step.tool_result = {
            "ok": execution.ok,
            "data": execution.data,
            "error": execution.error,
        }
        current_step.tool_text = execution.to_llm_text()

        tool_record = ToolCallRecord(
            step=step,
            name=execution.name,
            args=dict(execution.args),
            ok=execution.ok,
            error=execution.error,
            duration_ms=round(tool_duration_ms, 3),
        )
        tool_records.append(tool_record)

        logger.info(
            "[step {}/{}] tool invoked: {}({}) ok={} error={} duration_ms={:.2f}",
            step,
            max_iterations,
            execution.name,
            execution.args,
            execution.ok,
            execution.error,
            tool_duration_ms,
        )

        iteration_records.append(
            _make_iter_record(step, result, current_step, iter_t0, tool_record)
        )

    assert final_result is not None  # loop always runs at least once

    finished_at = datetime.now(timezone.utc)
    total_duration_ms = (time.perf_counter() - loop_t0) * 1000.0
    low_conf_retries = sum(1 for s in trace if s.low_confidence_retry)

    observability = AgentObservability(
        iterations=len(trace),
        max_iterations=max_iterations,
        duration_ms=round(total_duration_ms, 3),
        started_at=started_at,
        finished_at=finished_at,
        stopped_reason=stopped_reason,
        low_confidence_retries=low_conf_retries,
        confidence_progression=confidence_progression,
        tools_called=tool_records,
        iteration_trace=iteration_records,
    )

    logger.info(
        "run_agent_loop: done (iterations={} tools={} duration_ms={:.1f} "
        "stopped_reason={} final_severity={} final_confidence={:.2f})",
        len(trace),
        len(tool_records),
        total_duration_ms,
        stopped_reason,
        _sev(final_result),
        float(final_result.confidence),
    )

    return AgentRunResult(
        final=final_result,
        iterations=len(trace),
        trace=trace,
        observability=observability,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_historical_context(logs: Sequence[Any], n_results: int = 3) -> List[Any]:
    """Pull top-K similar past incidents from vector memory, safely.

    Never raises: memory retrieval is a soft enhancement. Any failure (Chroma
    disabled, embedding error, empty store, etc.) degrades to an empty list
    and the agent proceeds without historical context.
    """
    try:
        similar = memory_service.retrieve_similar_incidents(logs, n_results=n_results)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("memory retrieval failed ({}); proceeding without history", exc)
        return []
    if similar:
        logger.info(
            "retrieved {} similar past incident(s) from memory (top distance={:.3f})",
            len(similar),
            float(similar[0].distance) if hasattr(similar[0], "distance") else 0.0,
        )
    return list(similar)


def _sev(result: LLMStructuredOutput) -> str:
    """Extract a string severity whether the field is an Enum or a raw str."""
    sev = result.severity
    return sev.value if hasattr(sev, "value") else str(sev)


def _make_iter_record(
    step: int,
    result: LLMStructuredOutput,
    agent_step: AgentStep,
    iter_t0: float,
    tool_record: Optional[ToolCallRecord],
) -> IterationRecord:
    """Snapshot the just-completed iteration into an `IterationRecord`."""
    duration_ms = (time.perf_counter() - iter_t0) * 1000.0
    return IterationRecord(
        step=step,
        confidence=float(result.confidence),
        severity=_sev(result),
        needs_more_data=bool(result.needs_more_data),
        requested_action=str(result.requested_action),
        low_confidence_retry=agent_step.low_confidence_retry,
        tool_call=tool_record,
        duration_ms=round(duration_ms, 3),
    )


def _compose_iteration_prompt(
    base_prompt: str,
    trace: Sequence[AgentStep],
    is_final_turn: bool,
    extra_nudge: Optional[str] = None,
) -> str:
    """Build the per-iteration user prompt by appending prior steps + tool data."""
    sections: List[str] = [base_prompt.rstrip()]

    if trace:
        sections.append("### Prior reasoning and tool results")
        for step in trace:
            resp = step.response
            sections.append(
                f"- Step {step.step} response: "
                f"severity={resp.get('severity')}, "
                f"confidence={resp.get('confidence')}, "
                f"needs_more_data={resp.get('needs_more_data')}, "
                f"requested_action={resp.get('requested_action')}"
            )
            if resp.get("root_cause"):
                sections.append(f"  root_cause: {resp['root_cause']}")
            if step.tool_text:
                # Indent the pre-formatted tool execution text for readability.
                for line in step.tool_text.splitlines():
                    sections.append(f"  {line}")

    if extra_nudge:
        sections.append(f"### Note\n{extra_nudge}")

    if is_final_turn:
        sections.append(
            "### Final turn"
            "\nThis is your last opportunity to respond. You MUST set "
            "needs_more_data=false and requested_action='none' and commit to "
            "your best diagnosis based on the evidence collected so far."
        )

    return "\n\n".join(sections) + "\n"


__all__ = [
    "AgentStep",
    "AgentRunResult",
    "run_agent_once",
    "run_agent_loop",
]
