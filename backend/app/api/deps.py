"""Shared FastAPI dependencies."""

from typing import Annotated, Optional

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.services.api_key import hash_key
from app.services.auth import SESSION_COOKIE_NAME, get_user_for_token

DBSession = Annotated[Session, Depends(get_db)]


def optional_user(
    db: DBSession,
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Optional[User]:
    """Resolve the logged-in user from the session cookie, or None."""
    return get_user_for_token(db, session_token)


OptionalUser = Annotated[Optional[User], Depends(optional_user)]


def current_user(user: OptionalUser) -> User:
    """Require a logged-in user; 401 otherwise."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


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


def accessible_project_ids(
    db: DBSession, user: OptionalUser, project: OptionalProject
) -> Optional[list[int]]:
    """Project ids the caller may read, or ``None`` for the anonymous sandbox.

    Resolution order:
      * logged-in user (session cookie) -> all project ids they own (a list,
        possibly empty if they haven't created a project yet)
      * else API key -> that single project's id
      * else -> ``None``, meaning the caller is anonymous and may read only the
        public sandbox rows (``project_id IS NULL``)
    """
    if user is not None:
        rows = db.query(Project.id).filter(Project.user_id == user.id).all()
        return [row[0] for row in rows]
    if project is not None:
        return [project.id]
    return None


AccessibleProjectIds = Annotated[Optional[list[int]], Depends(accessible_project_ids)]
