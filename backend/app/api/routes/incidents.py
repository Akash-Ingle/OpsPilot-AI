"""Routes for incident listing and detail.

Reads are scoped to the caller:
  * logged-in user (session cookie) -> incidents across all their projects
  * API key -> that project's incidents only
  * anonymous -> the public sandbox (``project_id IS NULL``)
Detail/patch return 404 (not 403) for incidents the caller can't access so the
existence of another tenant's data isn't leaked.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AccessibleProjectIds, DBSession
from app.models.incident import Incident, IncidentStatus, Severity
from app.schemas.incident import (
    IncidentDetail,
    IncidentOut,
    IncidentUpdate,
)

router = APIRouter()


def _scope(query, project_ids: Optional[List[int]]):
    """Restrict a query to the caller's accessible incidents."""
    if project_ids is None:
        return query.filter(Incident.project_id.is_(None))  # anonymous sandbox
    return query.filter(Incident.project_id.in_(project_ids or [-1]))


def _can_access(incident: Incident, project_ids: Optional[List[int]]) -> bool:
    if project_ids is None:
        return incident.project_id is None  # public sandbox incident
    return incident.project_id in project_ids


@router.get("", response_model=List[IncidentOut], summary="List incidents")
def list_incidents(
    db: DBSession,
    project_ids: AccessibleProjectIds,
    status_filter: Optional[IncidentStatus] = Query(None, alias="status"),
    severity: Optional[Severity] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[IncidentOut]:
    query = _scope(db.query(Incident), project_ids)
    if status_filter:
        query = query.filter(Incident.status == status_filter)
    if severity:
        query = query.filter(Incident.severity == severity)
    rows = query.order_by(Incident.detected_at.desc()).offset(offset).limit(limit).all()
    return [IncidentOut.model_validate(r) for r in rows]


@router.get(
    "/{incident_id}",
    response_model=IncidentDetail,
    summary="Get incident detail with analysis steps",
)
def get_incident(
    incident_id: int, db: DBSession, project_ids: AccessibleProjectIds
) -> IncidentDetail:
    incident = db.get(Incident, incident_id)
    if not incident or not _can_access(incident, project_ids):
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentDetail.model_validate(incident)


@router.patch(
    "/{incident_id}",
    response_model=IncidentOut,
    summary="Update an incident",
)
def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    db: DBSession,
    project_ids: AccessibleProjectIds,
) -> IncidentOut:
    incident = db.get(Incident, incident_id)
    if not incident or not _can_access(incident, project_ids):
        raise HTTPException(status_code=404, detail="Incident not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(incident, field, value)

    db.commit()
    db.refresh(incident)
    return IncidentOut.model_validate(incident)
