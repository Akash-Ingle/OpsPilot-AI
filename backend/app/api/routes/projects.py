"""Project (tenant) management: create a project + API key, view/update settings.

Onboarding flow for "connect your app":
  1. POST /projects            -> creates a project, returns the API key ONCE.
  2. PATCH /projects/me        -> (with the key) set the Slack webhook / toggle alerts.
  3. POST /ingest              -> (with the key) ship logs; the watcher does the rest.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentProject, DBSession
from app.config import settings
from app.core.logging import logger
from app.core.rate_limit import limiter
from app.models.incident import Incident
from app.models.log import Log
from app.models.project import Project
from app.services.api_key import generate_key

router = APIRouter()


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class ProjectCreatedResponse(BaseModel):
    id: int
    name: str
    api_key: str = Field(..., description="Shown only once - store it now.")
    key_prefix: str


class ProjectUpdateRequest(BaseModel):
    slack_webhook_url: Optional[str] = Field(default=None, max_length=500)
    alerts_enabled: Optional[bool] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    alerts_enabled: bool
    slack_configured: bool
    last_auto_analysis_at: Optional[datetime]
    log_count: int
    incident_count: int
    created_at: datetime


def _to_out(db, project: Project) -> ProjectOut:
    log_count = db.query(Log).filter(Log.project_id == project.id).count()
    incident_count = (
        db.query(Incident).filter(Incident.project_id == project.id).count()
    )
    return ProjectOut(
        id=project.id,
        name=project.name,
        key_prefix=project.key_prefix,
        alerts_enabled=project.alerts_enabled,
        slack_configured=bool(project.slack_webhook_url),
        last_auto_analysis_at=project.last_auto_analysis_at,
        log_count=log_count,
        incident_count=incident_count,
        created_at=project.created_at,
    )


@router.post(
    "",
    response_model=ProjectCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project and issue an API key (key shown once)",
)
@limiter.limit(settings.rate_limit_project_create)
def create_project(
    request: Request, response: Response, payload: ProjectCreateRequest, db: DBSession
) -> ProjectCreatedResponse:
    key = generate_key()
    project = Project(
        name=payload.name.strip(),
        key_hash=key.key_hash,
        key_prefix=key.display_prefix,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info("projects: created project id={} name={!r}", project.id, project.name)
    return ProjectCreatedResponse(
        id=project.id,
        name=project.name,
        api_key=key.raw,
        key_prefix=project.key_prefix,
    )


@router.get(
    "/me",
    response_model=ProjectOut,
    summary="Get the current project (by API key) with ingest/incident stats",
)
def get_current_project(project: CurrentProject, db: DBSession) -> ProjectOut:
    return _to_out(db, project)


@router.patch(
    "/me",
    response_model=ProjectOut,
    summary="Update the current project's alerting settings",
)
def update_current_project(
    project: CurrentProject, payload: ProjectUpdateRequest, db: DBSession
) -> ProjectOut:
    if payload.slack_webhook_url is not None:
        url = payload.slack_webhook_url.strip()
        project.slack_webhook_url = url or None
    if payload.alerts_enabled is not None:
        project.alerts_enabled = payload.alerts_enabled
    db.commit()
    db.refresh(project)
    logger.info(
        "projects: updated project id={} slack_configured={} alerts_enabled={}",
        project.id,
        bool(project.slack_webhook_url),
        project.alerts_enabled,
    )
    return _to_out(db, project)
