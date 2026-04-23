"""Pydantic schemas for the evaluation API (Plan §10.2)."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ScenarioName = Literal["database_failure", "memory_leak", "latency_spike"]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class EvaluateRequest(BaseModel):
    """Evaluate an existing incident's most recent analysis against a scenario."""

    incident_id: int = Field(..., ge=1, description="Incident to grade")
    scenario_name: ScenarioName = Field(
        ..., description="Scenario whose ground truth we're comparing against"
    )
    analysis_id: Optional[int] = Field(
        default=None,
        description="Specific analysis to grade; defaults to the latest for the incident",
    )


# ---------------------------------------------------------------------------
# Response / detail models
# ---------------------------------------------------------------------------


class EvaluationResult(BaseModel):
    """The pure-function scoring output (also embedded in DB rows)."""

    scenario_name: str
    expected_root_cause: str
    expected_severity: str
    expected_fix: str
    predicted_root_cause: str
    predicted_severity: str
    predicted_fix: str
    confidence: float

    root_cause_match: bool
    severity_match: bool
    fix_match: bool
    overall_correct: bool

    score: float = Field(..., ge=0.0, le=1.0)
    keyword_coverage: float = Field(..., ge=0.0, le=1.0)

    matched_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)


class EvaluationOut(EvaluationResult):
    """DB-persisted evaluation row (adds identifiers + timestamp)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: Optional[int] = None
    analysis_id: Optional[int] = None
    predicted_output: Optional[Dict[str, Any]] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Summary / aggregation
# ---------------------------------------------------------------------------


class ScenarioSummary(BaseModel):
    """Per-scenario aggregate metrics."""

    scenario_name: str
    total: int
    accuracy: float = Field(..., ge=0.0, le=1.0)
    mean_confidence: float = Field(..., ge=0.0, le=1.0)
    mean_score: float = Field(..., ge=0.0, le=1.0)
    root_cause_accuracy: float = Field(..., ge=0.0, le=1.0)
    severity_accuracy: float = Field(..., ge=0.0, le=1.0)
    fix_accuracy: float = Field(..., ge=0.0, le=1.0)


class CalibrationStats(BaseModel):
    """Is confidence meaningful? Compare mean confidence for correct vs incorrect."""

    mean_confidence_when_correct: Optional[float] = None
    mean_confidence_when_incorrect: Optional[float] = None
    gap: Optional[float] = Field(
        default=None,
        description="correct - incorrect; positive = well-calibrated, negative = overconfident when wrong",
    )


class EvaluationSummary(BaseModel):
    """Top-level aggregate response for GET /evaluate/summary."""

    total: int
    accuracy: float = Field(..., ge=0.0, le=1.0)
    mean_confidence: float = Field(..., ge=0.0, le=1.0)
    mean_score: float = Field(..., ge=0.0, le=1.0)
    calibration: CalibrationStats
    by_scenario: List[ScenarioSummary] = Field(default_factory=list)
