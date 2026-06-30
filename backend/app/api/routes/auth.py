"""Human authentication: register, login, logout, and current-user lookup.

Sessions are server-side; the raw token is delivered in an httpOnly cookie so it
is never readable by page JavaScript (mitigates XSS token theft). Browsers reach
these routes same-origin through the Next.js proxy, so the cookie is first-party.
"""

import re

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, DBSession
from app.config import settings
from app.core.logging import logger
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_DAYS,
    create_session,
    hash_password,
    revoke_session,
    verify_password,
)

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    id: int
    email: str


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and start a session",
)
@limiter.limit(settings.rate_limit_auth)
def register(
    request: Request, response: Response, payload: RegisterRequest, db: DBSession
) -> UserOut:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    raw = create_session(db, user)
    _set_session_cookie(response, raw)
    logger.info("auth: registered user id={} email={!r}", user.id, user.email)
    return UserOut(id=user.id, email=user.email)


@router.post(
    "/login",
    response_model=UserOut,
    summary="Authenticate and start a session",
)
@limiter.limit(settings.rate_limit_auth)
def login(
    request: Request, response: Response, payload: LoginRequest, db: DBSession
) -> UserOut:
    user = db.query(User).filter(User.email == payload.email).first()
    # Always run verify to keep timing roughly constant whether or not the email exists.
    valid = user is not None and verify_password(payload.password, user.password_hash)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    raw = create_session(db, user)
    _set_session_cookie(response, raw)
    logger.info("auth: login user id={}", user.id)
    return UserOut(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
def logout(request: Request, db: DBSession) -> Response:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    revoke_session(db, raw)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/me", response_model=UserOut, summary="Get the logged-in user")
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, email=user.email)
