"""SQLAlchemy engine, session factory, and declarative base."""

from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# Managed Postgres providers (e.g. Render, Heroku) hand out URLs with the legacy
# `postgres://` scheme, which SQLAlchemy 2.0 no longer recognizes. Normalize it.
_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

# SQLite needs a special connect arg when used with multiple threads (e.g. FastAPI).
_connect_args = {}
_engine_kwargs = {}
if _db_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    # Recycle connections so a Postgres server that drops idle conns doesn't
    # surface stale-connection errors on the next request.
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(
    _db_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
    **_engine_kwargs,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. For production use Alembic migrations instead."""
    # Import models so they are registered with the Base metadata before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Lightweight, idempotent add-column migration for additive schema changes.

    `create_all` creates *new* tables but never alters existing ones, so a
    pre-existing dev DB won't gain newly-added columns. This adds the few nullable
    columns we introduced (project scoping) if they're missing. Real production
    schema changes should use Alembic; this just keeps zero-setup SQLite dev DBs
    working across upgrades.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    wanted = {
        "logs": [("project_id", "INTEGER")],
        "incidents": [("project_id", "INTEGER")],
        "projects": [("user_id", "INTEGER")],
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl_type in columns:
                if name not in present:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
                    )
