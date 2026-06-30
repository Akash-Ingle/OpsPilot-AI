"""Project helpers shared across routes."""

from sqlalchemy.orm import Session as DBSession

from app.models.project import Project
from app.models.user import User
from app.services.api_key import generate_key

_DEFAULT_PROJECT_NAME = "My App"


def get_or_create_default_project(db: DBSession, user: User) -> Project:
    """Return the user's oldest project, creating a default one if they have none.

    Used by session-authenticated convenience flows (Simulate / manual analyze)
    that need a project to attach incidents to. The generated API key isn't
    surfaced here; the user can create explicit keyed projects on the Connect page.
    """
    project = (
        db.query(Project)
        .filter(Project.user_id == user.id)
        .order_by(Project.id.asc())
        .first()
    )
    if project is not None:
        return project

    key = generate_key()
    project = Project(
        name=_DEFAULT_PROJECT_NAME,
        key_hash=key.key_hash,
        key_prefix=key.display_prefix,
        user_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project
