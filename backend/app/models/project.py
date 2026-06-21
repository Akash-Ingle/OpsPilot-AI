"""Project ORM model - a tenant that ships logs to OpsPilot via an API key.

Each project owns an API key (stored only as a salted-free SHA-256 hash; the raw
key is shown to the user exactly once at creation) and optional alerting config
(a Slack incoming-webhook URL). Ingested logs and the incidents derived from them
are scoped to a project.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # SHA-256 hex of the raw API key. The raw key is never stored.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Short, non-secret prefix shown in the UI so users can identify a key.
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)

    # Optional Slack incoming-webhook URL; alerts are posted here when set.
    slack_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Throttles event-driven auto-analysis so a log flood can't spam the LLM.
    last_auto_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project id={self.id} name={self.name!r} prefix={self.key_prefix}>"
