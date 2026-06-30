"""Tenant isolation tests for the hybrid (public sandbox + private accounts) model.

  * anonymous -> the public sandbox only (project_id IS NULL)
  * logged-in user (session cookie) -> incidents across their own projects
  * API key -> that project only
Cross-tenant / private access returns 404 (not 403) so existence isn't leaked.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.incident import Incident, Severity
from app.models.log import Log
from tests._auth import create_project, login

API = settings.api_v1_prefix


@pytest.fixture
def session_factory():
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
        yield TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def seeded(session_factory):
    # Two distinct users, each owning one project (separate cookie jars).
    user_a = TestClient(app)
    login(user_a, "a@example.com")
    proj_a = create_project(user_a, "tenant-a")

    user_b = TestClient(app)
    login(user_b, "b@example.com")
    proj_b = create_project(user_b, "tenant-b")

    id_a, id_b = proj_a["id"], proj_b["id"]

    db = session_factory()
    try:
        public = Incident(title="public-sandbox", severity=Severity.MEDIUM, project_id=None)
        inc_a = Incident(title="a-incident", severity=Severity.HIGH, project_id=id_a)
        inc_b = Incident(title="b-incident", severity=Severity.HIGH, project_id=id_b)
        db.add_all([public, inc_a, inc_b])
        now = datetime.now(timezone.utc)
        db.add_all(
            [
                Log(project_id=None, timestamp=now, service_name="demo", severity="info", message="public log"),
                Log(project_id=id_a, timestamp=now, service_name="a", severity="error", message="a log"),
                Log(project_id=id_b, timestamp=now, service_name="b", severity="error", message="b log"),
            ]
        )
        db.commit()
        ids = {"public": public.id, "a": inc_a.id, "b": inc_b.id}
    finally:
        db.close()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "anon": TestClient(app),
        "key_a": proj_a["api_key"],
        "ids": ids,
        "auth_a": {"Authorization": f"Bearer {proj_a['api_key']}"},
    }


def test_anonymous_sees_only_public_sandbox(seeded):
    res = seeded["anon"].get(f"{API}/incidents")
    assert res.status_code == 200
    assert {i["title"] for i in res.json()} == {"public-sandbox"}


def test_anonymous_can_read_public_but_not_private(seeded):
    anon = seeded["anon"]
    assert anon.get(f"{API}/incidents/{seeded['ids']['public']}").status_code == 200
    assert anon.get(f"{API}/incidents/{seeded['ids']['a']}").status_code == 404


def test_session_list_sees_only_own(seeded):
    res = seeded["user_a"].get(f"{API}/incidents")
    assert res.status_code == 200
    assert {i["title"] for i in res.json()} == {"a-incident"}

    res_b = seeded["user_b"].get(f"{API}/incidents")
    assert {i["title"] for i in res_b.json()} == {"b-incident"}


def test_api_key_list_sees_only_own(seeded):
    # A sessionless client (machine) authenticating with project A's key sees
    # only project A's incidents.
    res = seeded["anon"].get(f"{API}/incidents", headers=seeded["auth_a"])
    assert res.status_code == 200
    assert {i["title"] for i in res.json()} == {"a-incident"}


def test_owner_can_read_own_incident(seeded):
    res = seeded["user_a"].get(f"{API}/incidents/{seeded['ids']['a']}")
    assert res.status_code == 200
    assert res.json()["title"] == "a-incident"


def test_cross_tenant_detail_is_404(seeded):
    res = seeded["user_a"].get(f"{API}/incidents/{seeded['ids']['b']}")
    assert res.status_code == 404


def test_cross_tenant_patch_is_404(seeded):
    res = seeded["user_a"].patch(
        f"{API}/incidents/{seeded['ids']['b']}", json={"status": "resolved"}
    )
    assert res.status_code == 404


def test_invalid_key_is_rejected(seeded):
    res = seeded["anon"].get(
        f"{API}/incidents", headers={"Authorization": "Bearer opsp_not_a_real_key"}
    )
    assert res.status_code == 401


def test_logs_are_scoped_too(seeded):
    res = seeded["user_a"].get(f"{API}/logs")
    assert res.status_code == 200
    assert {l["message"] for l in res.json()} == {"a log"}

    anon = seeded["anon"].get(f"{API}/logs")
    assert anon.status_code == 200
    assert {l["message"] for l in anon.json()} == {"public log"}


def test_user_sees_incidents_across_their_projects(seeded, session_factory):
    # A second project for user A; its incident should also appear for that user.
    proj_a2 = create_project(seeded["user_a"], "tenant-a-second")
    db = session_factory()
    try:
        db.add(Incident(title="a2-incident", severity=Severity.LOW, project_id=proj_a2["id"]))
        db.commit()
    finally:
        db.close()

    res = seeded["user_a"].get(f"{API}/incidents")
    assert res.status_code == 200
    assert {i["title"] for i in res.json()} == {"a-incident", "a2-incident"}
