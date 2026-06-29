"""Tenant isolation tests for the public-sandbox + private-project read model.

No key  -> caller sees only public sandbox rows (project_id IS NULL).
Valid key -> caller sees only that project's rows.
Cross-tenant or anonymous access to a private incident -> 404 (not 403, so the
existence of another tenant's incident isn't leaked).
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

API = settings.api_v1_prefix


@pytest.fixture
def client():
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
        yield TestClient(app), TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)


def _new_project(tc, name):
    res = tc.post(f"{API}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    body = res.json()
    return body["api_key"], body["id"]


@pytest.fixture
def seeded(client):
    tc, session_factory = client
    key_a, id_a = _new_project(tc, "tenant-a")
    key_b, id_b = _new_project(tc, "tenant-b")

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
        "tc": tc,
        "key_a": key_a,
        "key_b": key_b,
        "ids": ids,
        "auth_a": {"Authorization": f"Bearer {key_a}"},
        "auth_b": {"Authorization": f"Bearer {key_b}"},
    }


def test_anonymous_list_sees_only_public(seeded):
    res = seeded["tc"].get(f"{API}/incidents")
    assert res.status_code == 200
    titles = {i["title"] for i in res.json()}
    assert titles == {"public-sandbox"}


def test_keyed_list_sees_only_own(seeded):
    res = seeded["tc"].get(f"{API}/incidents", headers=seeded["auth_a"])
    assert res.status_code == 200
    titles = {i["title"] for i in res.json()}
    assert titles == {"a-incident"}


def test_public_incident_readable_by_anyone(seeded):
    res = seeded["tc"].get(f"{API}/incidents/{seeded['ids']['public']}")
    assert res.status_code == 200


def test_private_incident_hidden_from_anonymous(seeded):
    res = seeded["tc"].get(f"{API}/incidents/{seeded['ids']['a']}")
    assert res.status_code == 404


def test_cross_tenant_detail_is_404(seeded):
    # Tenant A must not be able to read tenant B's incident.
    res = seeded["tc"].get(
        f"{API}/incidents/{seeded['ids']['b']}", headers=seeded["auth_a"]
    )
    assert res.status_code == 404


def test_owner_can_read_own_incident(seeded):
    res = seeded["tc"].get(
        f"{API}/incidents/{seeded['ids']['a']}", headers=seeded["auth_a"]
    )
    assert res.status_code == 200
    assert res.json()["title"] == "a-incident"


def test_cross_tenant_patch_is_404(seeded):
    res = seeded["tc"].patch(
        f"{API}/incidents/{seeded['ids']['b']}",
        headers=seeded["auth_a"],
        json={"status": "resolved"},
    )
    assert res.status_code == 404


def test_invalid_key_is_rejected(seeded):
    res = seeded["tc"].get(
        f"{API}/incidents", headers={"Authorization": "Bearer opsp_not_a_real_key"}
    )
    assert res.status_code == 401


def test_logs_are_scoped_too(seeded):
    anon = seeded["tc"].get(f"{API}/logs")
    assert anon.status_code == 200
    assert {l["message"] for l in anon.json()} == {"public log"}

    keyed = seeded["tc"].get(f"{API}/logs", headers=seeded["auth_a"])
    assert keyed.status_code == 200
    assert {l["message"] for l in keyed.json()} == {"a log"}
