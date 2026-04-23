"""Routes for incident listing and detail."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DBSession
from app.models.incident import Incident, IncidentStatus, Severity
from app.schemas.incident import (
    IncidentCreate,
    IncidentDetail,
    IncidentOut,
    IncidentUpdate,
)

router = APIRouter()


@router.get("", response_model=List[IncidentOut], summary="List incidents")
def list_incidents(
    db: DBSession,
    status_filter: Optional[IncidentStatus] = Query(None, alias="status"),
    severity: Optional[Severity] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[IncidentOut]:
    query = db.query(Incident)
    if status_filter:
        query = query.filter(Incident.status == status_filter)
    if severity:
        query = query.filter(Incident.severity == severity)
    rows = query.order_by(Incident.detected_at.desc()).offset(offset).limit(limit).all()
    return [IncidentOut.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an incident manually",
)
def create_incident(payload: IncidentCreate, db: DBSession) -> IncidentOut:
    incident = Incident(**payload.model_dump())
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return IncidentOut.model_validate(incident)


@router.get(
    "/{incident_id}",
    response_model=IncidentDetail,
    summary="Get incident detail with analysis steps",
)
def get_incident(incident_id: int, db: DBSession) -> IncidentDetail:
    incident = db.get(Incident, incident_id)
    if not incident:
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
) -> IncidentOut:
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(incident, field, value)

    db.commit()
    db.refresh(incident)
    return IncidentOut.model_validate(incident)
