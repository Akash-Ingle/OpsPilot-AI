"""Pydantic schemas for analysis records and LLM output contract."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.incident import Severity


# ---------------------------------------------------------------------------
# Agent observability (populated by the orchestrator, not the LLM)
# ---------------------------------------------------------------------------


StoppedReason = Literal[
    "confident",          # model committed (needs_more_data=false, confidence >= threshold)
    "max_iterations",     # loop hit its iteration cap
    "no_progress",        # model asked for more data but requested_action="none"
    "low_confidence_final",  # max_iterations hit while still below confidence threshold
]


class ToolCallRecord(BaseModel):
    """One tool invocation executed during the agent loop."""

    step: int = Field(..., ge=1, description="1-based iteration number when this tool ran")
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    ok: bool
    error: Optional[str] = None
    duration_ms: float = Field(..., ge=0.0)


class IterationRecord(BaseModel):
    """Per-iteration snapshot of the agent's internal state."""

    step: int = Field(..., ge=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    severity: str
    needs_more_data: bool
    requested_action: str
    low_confidence_retry: bool = False
    tool_call: Optional[ToolCallRecord] = None
    duration_ms: float = Field(..., ge=0.0)


class AgentObservability(BaseModel):
    """End-to-end telemetry for one agent execution."""

    iterations: int = Field(..., ge=1)
    max_iterations: int = Field(..., ge=1)
    duration_ms: float = Field(..., ge=0.0)
    started_at: datetime
    finished_at: datetime

    stopped_reason: StoppedReason
    low_confidence_retries: int = Field(..., ge=0)

    confidence_progression: List[float] = Field(default_factory=list)
    tools_called: List[ToolCallRecord] = Field(default_factory=list)
    iteration_trace: List[IterationRecord] = Field(default_factory=list)


class LogReference(BaseModel):
    """A pointer to a specific log line the model used as evidence.

    The LLM can cite a log in one of three ways (most specific wins):
      - `log_id`    : the persistent DB id shown in the excerpt (preferred).
      - `line_index`: 1-based position in the prompt's excerpt block.
      - `excerpt`   : a short literal snippet pasted from the logs.

    At least ONE of these must be set so downstream consumers can actually
    locate the referenced line. `reason` explains *why* this log matters.
    """

    log_id: Optional[int] = Field(default=None, description="Persistent Log.id from the excerpt")
    line_index: Optional[int] = Field(
        default=None, ge=1, description="1-based index within the prompt's excerpt block"
    )
    excerpt: Optional[str] = Field(
        default=None, max_length=500, description="Short quoted log snippet"
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=300,
        description="One-line explanation of why this log is evidence",
    )

    @field_validator("excerpt", "reason", mode="before")
    @classmethod
    def _normalize_blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _require_identifier(self) -> "LogReference":
        if self.log_id is None and self.line_index is None and not self.excerpt:
            raise ValueError(
                "LogReference must set at least one of log_id, line_index, or excerpt"
            )
        return self


class LLMStructuredOutput(BaseModel):
    """Strict JSON contract the agent must return at each reasoning step."""

    issue: str
    root_cause: str
    fix: str
    severity: Severity
    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_more_data: bool = False
    requested_action: Literal[
        "fetch_logs",
        "get_metrics",
        "restart_service",
        "scale_service",
        "none",
    ] = "none"
    requested_action_args: Dict[str, Any] = Field(default_factory=dict)

    # --- Explainability ----------------------------------------------------
    reasoning_steps: List[str] = Field(
        ...,
        min_length=1,
        max_length=12,
        description=(
            "Ordered chain-of-thought bullets showing how the diagnosis was "
            "reached. Each step must be a concise sentence (<= 280 chars)."
        ),
    )
    relevant_log_lines: List[LogReference] = Field(
        default_factory=list,
        max_length=20,
        description="Specific logs cited as evidence for the diagnosis.",
    )

    @field_validator("reasoning_steps", mode="before")
    @classmethod
    def _drop_empty_steps(cls, value: Any) -> Any:
        """Trim/drop blank steps and cap each step's length defensively."""
        if not isinstance(value, list):
            return value
        cleaned: List[str] = []
        for step in value:
            if not isinstance(step, str):
                continue
            trimmed = step.strip()
            if not trimmed:
                continue
            cleaned.append(trimmed[:500])
        return cleaned


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    step_index: int
    llm_output: str
    structured_output: Optional[Dict[str, Any]] = None
    confidence_score: Optional[float] = None
    observability: Optional[AgentObservability] = None
    created_at: datetime


class AnalyzeRequest(BaseModel):
    """Trigger analysis over recent logs (optionally filtered by service)."""

    incident_id: Optional[int] = None
    log_ids: Optional[list[int]] = None
    service_name: Optional[str] = None
    limit: int = Field(default=200, ge=1, le=1000, description="How many recent logs to analyze")
    max_steps: int = Field(default=5, ge=1, le=10)


class AnalyzeResponse(BaseModel):
    incident_id: int
    analysis_id: int
    steps_run: int
    logs_analyzed: int
    anomalies_detected: int
    final: LLMStructuredOutput
    observability: AgentObservability
