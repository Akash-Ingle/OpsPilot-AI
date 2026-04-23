"""Routes for grading LLM analyses against simulated-scenario ground truth."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DBSession
from app.core.logging import logger
from app.schemas.evaluation import (
    EvaluateRequest,
    EvaluationOut,
    EvaluationSummary,
    ScenarioName,
)
from app.services import evaluation_service

router = APIRouter()


class GroundTruthInfo(BaseModel):
    """What the evaluator expects for a given scenario."""

    scenario_name: str
    reference_root_cause: str
    reference_fix: str
    accepted_severities: List[str] = Field(default_factory=list)
    root_cause_keywords: List[str] = Field(default_factory=list)
    min_root_cause_matches: int
    fix_keywords: List[str] = Field(default_factory=list)
    min_fix_matches: int


@router.get(
    "/scenarios",
    response_model=List[GroundTruthInfo],
    summary="List the ground-truth labels used to grade each scenario",
)
def list_scenarios() -> List[GroundTruthInfo]:
    return [
        GroundTruthInfo(
            scenario_name=gt.scenario,
            reference_root_cause=gt.reference_root_cause,
            reference_fix=gt.reference_fix,
            accepted_severities=sorted(gt.accepted_severities),
            root_cause_keywords=list(gt.root_cause_keywords),
            min_root_cause_matches=gt.min_root_cause,
            fix_keywords=list(gt.fix_keywords),
            min_fix_matches=gt.min_fix,
        )
        for gt in evaluation_service.list_ground_truths()
    ]


@router.post(
    "",
    response_model=EvaluationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate an incident's analysis against a known scenario's ground truth",
)
def evaluate(payload: EvaluateRequest, db: DBSession) -> EvaluationOut:
    try:
        row = evaluation_service.evaluate_and_store(
            db,
            scenario_name=payload.scenario_name,
            incident_id=payload.incident_id,
            analysis_id=payload.analysis_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("evaluate: unexpected failure: {}", exc)
        raise HTTPException(
            status_code=500, detail="Failed to run evaluation."
        ) from exc

    return EvaluationOut.model_validate(row)


@router.get(
    "/summary",
    response_model=EvaluationSummary,
    summary="Aggregate accuracy + confidence metrics across evaluations",
)
def summary(
    db: DBSession,
    scenario: Optional[ScenarioName] = Query(
        default=None, description="Filter to a single scenario"
    ),
) -> EvaluationSummary:
    try:
        return evaluation_service.summarize(db, scenario_name=scenario)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
