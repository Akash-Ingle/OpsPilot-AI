"""Shared FastAPI dependencies."""

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.services.api_key import hash_key

DBSession = Annotated[Session, Depends(get_db)]


def require_project(
    db: DBSession,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Project:
    """Resolve the calling project from its API key.

    Accepts the key via either ``Authorization: Bearer <key>`` or the
    ``X-API-Key`` header. Raises 401 if missing or unknown.
    """
    raw_key: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization[7:].strip()
    elif x_api_key:
        raw_key = x_api_key.strip()

    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Send 'Authorization: Bearer <key>' or 'X-API-Key: <key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    project = (
        db.query(Project).filter(Project.key_hash == hash_key(raw_key)).first()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return project


CurrentProject = Annotated[Project, Depends(require_project)]
