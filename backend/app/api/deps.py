"""Shared FastAPI dependencies."""

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.services.api_key import hash_key

DBSession = Annotated[Session, Depends(get_db)]


def _extract_api_key(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    """Pull the raw API key from either header, or None if absent."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    if x_api_key:
        return x_api_key.strip() or None
    return None


def require_project(
    db: DBSession,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Project:
    """Resolve the calling project from its API key.

    Accepts the key via either ``Authorization: Bearer <key>`` or the
    ``X-API-Key`` header. Raises 401 if missing or unknown.
    """
    raw_key = _extract_api_key(authorization, x_api_key)
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Send 'Authorization: Bearer <key>' or 'X-API-Key: <key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    project = db.query(Project).filter(Project.key_hash == hash_key(raw_key)).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return project


def optional_project(
    db: DBSession,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Optional[Project]:
    """Resolve the calling project if a key is supplied, else None.

    Used by read endpoints that serve the public sandbox (no key -> only
    ``project_id IS NULL`` rows) but switch to a tenant's private view when a
    valid key is present. A *supplied but invalid* key is rejected with 401 so
    bad credentials never silently fall back to the public view.
    """
    raw_key = _extract_api_key(authorization, x_api_key)
    if not raw_key:
        return None
    project = db.query(Project).filter(Project.key_hash == hash_key(raw_key)).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return project


CurrentProject = Annotated[Project, Depends(require_project)]
OptionalProject = Annotated[Optional[Project], Depends(optional_project)]
