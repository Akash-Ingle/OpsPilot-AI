"""Keyed log ingestion endpoint.

Real apps ship batches of log lines here using their project API key. Lines are
persisted under the project, then an always-on watcher runs (as a background
task) to detect anomalies and open an incident automatically.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentProject, DBSession
from app.config import settings
from app.core.logging import logger
from app.core.metrics import LOGS_INGESTED_TOTAL
from app.core.rate_limit import limiter
from app.models.log import Log
from app.services.watcher import auto_analyze_project

router = APIRouter()


class IngestLogItem(BaseModel):
    message: str = Field(..., min_length=1)
    service_name: str = Field(default="app", max_length=128)
    severity: str = Field(default="info", max_length=32)
    timestamp: Optional[datetime] = None


class IngestRequest(BaseModel):
    logs: List[IngestLogItem] = Field(..., min_length=1)


class IngestResponse(BaseModel):
    ingested: int
    project_id: int
    watcher_scheduled: bool


@router.post(
    "",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a batch of logs for the authenticated project",
)
@limiter.limit(settings.rate_limit_ingest)
def ingest_logs(
    request: Request,
    response: Response,
    payload: IngestRequest,
    project: CurrentProject,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    if len(payload.logs) > settings.ingest_max_batch:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch too large (max {settings.ingest_max_batch} lines).",
        )

    now = datetime.now(timezone.utc)
    rows = [
        Log(
            project_id=project.id,
            timestamp=item.timestamp or now,
            service_name=item.service_name,
            severity=item.severity.lower(),
            message=item.message,
        )
        for item in payload.logs
    ]
    db.add_all(rows)
    db.commit()
    LOGS_INGESTED_TOTAL.inc(len(rows))

    logger.info(
        "ingest: project_id={} accepted {} log(s)", project.id, len(rows)
    )

    # Kick the always-on watcher after the response is sent. It re-checks the
    # cooldown + anomalies itself, so scheduling unconditionally is cheap.
    scheduled = settings.auto_analyze_enabled
    if scheduled:
        background_tasks.add_task(auto_analyze_project, project.id)

    return IngestResponse(
        ingested=len(rows), project_id=project.id, watcher_scheduled=scheduled
    )
