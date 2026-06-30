"""Tests for human authentication: register, login, logout, session, hashing."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.services.auth import (
    SESSION_COOKIE_NAME,
    hash_password,
    verify_password,
)

API = settings.api_v1_prefix


@pytest.fixture
def tc():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False


def test_register_sets_session_and_me_works(tc):
    res = tc.post(f"{API}/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert res.status_code == 201, res.text
    assert SESSION_COOKIE_NAME in res.cookies
    assert res.json()["email"] == "a@example.com"

    me = tc.get(f"{API}/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


def test_register_normalizes_email_and_rejects_duplicates(tc):
    tc.post(f"{API}/auth/register", json={"email": "Dup@Example.com", "password": "password123"})
    dup = tc.post(f"{API}/auth/register", json={"email": "dup@example.com", "password": "password123"})
    assert dup.status_code == 409


def test_register_rejects_short_password(tc):
    res = tc.post(f"{API}/auth/register", json={"email": "x@example.com", "password": "short"})
    assert res.status_code == 422


def test_register_rejects_bad_email(tc):
    res = tc.post(f"{API}/auth/register", json={"email": "not-an-email", "password": "password123"})
    assert res.status_code == 422


def test_login_wrong_password_is_401(tc):
    tc.post(f"{API}/auth/register", json={"email": "u@example.com", "password": "password123"})
    # Drop the session so we authenticate purely via credentials.
    tc.cookies.clear()
    bad = tc.post(f"{API}/auth/login", json={"email": "u@example.com", "password": "nope"})
    assert bad.status_code == 401


def test_login_unknown_user_is_401(tc):
    res = tc.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "whatever123"})
    assert res.status_code == 401


def test_logout_ends_session(tc):
    tc.post(f"{API}/auth/register", json={"email": "z@example.com", "password": "password123"})
    assert tc.get(f"{API}/auth/me").status_code == 200

    out = tc.post(f"{API}/auth/logout")
    assert out.status_code == 204
    # Session cookie cleared and the underlying session revoked.
    assert tc.get(f"{API}/auth/me").status_code == 401


def test_me_requires_auth(tc):
    assert tc.get(f"{API}/auth/me").status_code == 401
