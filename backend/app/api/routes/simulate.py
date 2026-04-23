"""Routes for generating synthetic DevOps scenarios (Plan §9)."""

from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import DBSession
from app.core.logging import logger
from app.models.log import Log
from app.schemas.log import LogOut
from app.services.log_generator import SCENARIO_META, generate_scenario

router = APIRouter()


ScenarioName = Literal["database_failure", "memory_leak", "latency_spike"]


class SimulateRequest(BaseModel):
    scenario: ScenarioName
    duration_minutes: Optional[int] = Field(
        default=None, ge=1, le=240, description="Override default duration"
    )
    seed: Optional[int] = Field(
        default=None, description="Seed for deterministic output"
    )
    service: Optional[str] = Field(
        default=None, description="Override the default service name"
    )
    persist: bool = Field(
        default=True, description="Persist generated logs to the DB"
    )


class SimulateResponse(BaseModel):
    scenario: str
    persisted: bool
    count: int
    sample: List[LogOut]


class ScenarioInfo(BaseModel):
    name: str
    description: str
    default_duration_min: int
    default_service: str


@router.get(
    "/scenarios",
    response_model=List[ScenarioInfo],
    summary="List available simulation scenarios",
)
def list_available_scenarios() -> List[ScenarioInfo]:
    return [
        ScenarioInfo(
            name=s.name,
            description=s.description,
            default_duration_min=s.default_duration_min,
            default_service=s.default_service,
        )
        for s in SCENARIO_META.values()
    ]


@router.post(
    "",
    response_model=SimulateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate (and optionally persist) a synthetic log scenario",
)
def run_simulation(payload: SimulateRequest, db: DBSession) -> SimulateResponse:
    try:
        generated = generate_scenario(
            payload.scenario,
            duration_minutes=payload.duration_minutes,
            seed=payload.seed,
            service=payload.service,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "simulate: scenario={} generated={} persist={}",
        payload.scenario,
        len(generated),
        payload.persist,
    )

    if not payload.persist:
        # Return a sample only; nothing written.
        sample = [
            LogOut(
                id=0,
                timestamp=item.timestamp,
                service_name=item.service_name,
                severity=item.severity,
                message=item.message,
                created_at=item.timestamp,
            )
            for item in generated[:5]
        ]
        return SimulateResponse(
            scenario=payload.scenario,
            persisted=False,
            count=len(generated),
            sample=sample,
        )

    try:
        rows = [Log(**entry.model_dump()) for entry in generated]
        db.add_all(rows)
        db.commit()
        for row in rows[:5]:
            db.refresh(row)
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        logger.exception("simulate: failed to persist generated logs: {}", exc)
        raise HTTPException(
            status_code=500, detail="Failed to persist generated logs"
        ) from exc

    return SimulateResponse(
        scenario=payload.scenario,
        persisted=True,
        count=len(rows),
        sample=[LogOut.model_validate(r) for r in rows[:5]],
    )
