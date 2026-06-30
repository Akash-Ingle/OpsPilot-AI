"""Routes for log ingestion and retrieval."""

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.deps import AccessibleProjectIds, OptionalUser, DBSession
from app.models.log import Log
from app.schemas.log import LogCreate, LogOut, LogUploadResponse
from app.services.log_parser import parse_log_payload
from app.services.projects import get_or_create_default_project

router = APIRouter()


@router.post(
    "/upload",
    response_model=LogUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload logs (raw text or JSON). Logged in -> your project; else sandbox.",
)
async def upload_logs(
    db: DBSession,
    user: OptionalUser,
    file: UploadFile = File(..., description="Log file: plain text or JSON array"),
) -> LogUploadResponse:
    try:
        raw = (await file.read()).decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Unable to read file: {exc}")

    parsed: List[LogCreate] = parse_log_payload(raw, filename=file.filename or "")

    if not parsed:
        raise HTTPException(status_code=400, detail="No valid log entries parsed from file")

    # Logged in -> your project; anonymous -> the public sandbox (project_id NULL).
    project_id = get_or_create_default_project(db, user).id if user else None
    rows = [Log(project_id=project_id, **entry.model_dump()) for entry in parsed]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)

    return LogUploadResponse(
        ingested=len(rows),
        sample=[LogOut.model_validate(r) for r in rows[:5]],
    )


@router.get(
    "",
    response_model=List[LogOut],
    summary="List ingested logs (filterable, scoped to the caller)",
)
def list_logs(
    db: DBSession,
    project_ids: AccessibleProjectIds,
    service_name: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> List[LogOut]:
    query = db.query(Log)
    if project_ids is None:
        query = query.filter(Log.project_id.is_(None))  # anonymous sandbox
    else:
        query = query.filter(Log.project_id.in_(project_ids or [-1]))
    if service_name:
        query = query.filter(Log.service_name == service_name)
    if severity:
        query = query.filter(Log.severity == severity)
    rows = query.order_by(Log.timestamp.desc()).offset(offset).limit(limit).all()
    return [LogOut.model_validate(r) for r in rows]
