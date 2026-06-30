"""Project management tests, focused on deletion.

Deleting a project must:
  * require an authenticated owner (401 anonymous, 404 cross-tenant / unknown),
  * remove the project from the owner's list,
  * cascade-delete the project's logs, incidents, and the incidents' analyses.
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
from app.models.analysis import Analysis
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


def _seed_children(session_factory, project_id: int) -> dict:
    """Attach a log + incident (with an analysis) to `project_id`."""
    db = session_factory()
    try:
        now = datetime.now(timezone.utc)
        db.add(
            Log(
                project_id=project_id,
                timestamp=now,
                service_name="svc",
                severity="error",
                message="boom",
            )
        )
        incident = Incident(title="inc", severity=Severity.HIGH, project_id=project_id)
        db.add(incident)
        db.flush()
        db.add(Analysis(incident_id=incident.id, llm_output="{}", step_index=0))
        db.commit()
        return {"incident_id": incident.id}
    finally:
        db.close()


def test_delete_requires_auth(session_factory):
    anon = TestClient(app)
    assert anon.delete(f"{API}/projects/1").status_code == 401


def test_owner_can_delete_and_children_cascade(session_factory):
    owner = TestClient(app)
    login(owner, "owner@example.com")
    proj = create_project(owner, "to-delete")
    pid = proj["id"]
    children = _seed_children(session_factory, pid)

    res = owner.delete(f"{API}/projects/{pid}")
    assert res.status_code == 204, res.text

    # Gone from the owner's list.
    listed = owner.get(f"{API}/projects")
    assert listed.status_code == 200
    assert all(p["id"] != pid for p in listed.json())

    # Logs, incident, and the incident's analysis are all removed.
    db = session_factory()
    try:
        assert db.query(Log).filter(Log.project_id == pid).count() == 0
        assert db.query(Incident).filter(Incident.project_id == pid).count() == 0
        assert (
            db.query(Analysis)
            .filter(Analysis.incident_id == children["incident_id"])
            .count()
            == 0
        )
    finally:
        db.close()


def test_cross_tenant_delete_is_404(session_factory):
    owner = TestClient(app)
    login(owner, "a@example.com")
    proj = create_project(owner, "tenant-a")

    other = TestClient(app)
    login(other, "b@example.com")

    res = other.delete(f"{API}/projects/{proj['id']}")
    assert res.status_code == 404

    # The real owner still sees their project intact.
    listed = owner.get(f"{API}/projects")
    assert any(p["id"] == proj["id"] for p in listed.json())


def test_delete_unknown_project_is_404(session_factory):
    owner = TestClient(app)
    login(owner, "owner@example.com")
    assert owner.delete(f"{API}/projects/999999").status_code == 404


def test_test_alert_requires_webhook(session_factory):
    owner = TestClient(app)
    login(owner, "owner@example.com")
    proj = create_project(owner, "no-slack")
    res = owner.post(f"{API}/projects/{proj['id']}/test-alert")
    assert res.status_code == 400


def test_test_alert_posts_when_configured(session_factory, monkeypatch):
    sent = {}

    def fake_send(url: str) -> bool:
        sent["url"] = url
        return True

    monkeypatch.setattr(
        "app.services.alerting.send_slack_test_message", fake_send
    )

    owner = TestClient(app)
    login(owner, "owner@example.com")
    proj = create_project(owner, "with-slack")
    hook = "https://hooks.slack.com/services/T/B/x"
    assert (
        owner.patch(
            f"{API}/projects/{proj['id']}", json={"slack_webhook_url": hook}
        ).status_code
        == 200
    )

    res = owner.post(f"{API}/projects/{proj['id']}/test-alert")
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert sent["url"] == hook


def test_test_alert_cross_tenant_is_404(session_factory):
    owner = TestClient(app)
    login(owner, "a@example.com")
    proj = create_project(owner, "tenant-a")

    other = TestClient(app)
    login(other, "b@example.com")
    res = other.post(f"{API}/projects/{proj['id']}/test-alert")
    assert res.status_code == 404
