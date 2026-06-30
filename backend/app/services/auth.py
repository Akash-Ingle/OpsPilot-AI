"""Authentication service: password hashing + server-side sessions.

Passwords are hashed with bcrypt. Sessions are random tokens stored only as a
SHA-256 hash in the DB; the raw token is delivered to the browser as an httpOnly
cookie and exchanged on each request.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from sqlalchemy.orm import Session as DBSession

from app.models.user import Session, User

SESSION_COOKIE_NAME = "opspilot_session"
SESSION_TTL_DAYS = 30
# bcrypt only hashes the first 72 bytes; longer inputs are truncated to match.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):  # malformed stored hash
        return False


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_session(db: DBSession, user: User, ttl_days: int = SESSION_TTL_DAYS) -> str:
    """Create a session row and return the raw token (to put in the cookie)."""
    raw = secrets.token_urlsafe(32)
    session = Session(
        user_id=user.id,
        token_hash=_hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    db.add(session)
    db.commit()
    return raw


def get_user_for_token(db: DBSession, raw_token: Optional[str]) -> Optional[User]:
    """Resolve a live (non-expired) session token to its user, or None."""
    if not raw_token:
        return None
    session = (
        db.query(Session).filter(Session.token_hash == _hash_token(raw_token)).first()
    )
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        # Expired: clean it up so the table doesn't accumulate dead sessions.
        db.delete(session)
        db.commit()
        return None
    return db.get(User, session.user_id)


def revoke_session(db: DBSession, raw_token: Optional[str]) -> None:
    if not raw_token:
        return
    session = (
        db.query(Session).filter(Session.token_hash == _hash_token(raw_token)).first()
    )
    if session is not None:
        db.delete(session)
        db.commit()


__all__ = [
    "SESSION_COOKIE_NAME",
    "SESSION_TTL_DAYS",
    "hash_password",
    "verify_password",
    "create_session",
    "get_user_for_token",
    "revoke_session",
]
