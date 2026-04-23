"""Incident ORM model - a detected issue worth investigating."""

import enum
from datetime import datetime
from typing import List, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity_enum"),
        nullable=False,
        default=Severity.MEDIUM,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status_enum"),
        nullable=False,
        default=IncidentStatus.OPEN,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    analyses: Mapped[List["Analysis"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="Analysis.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Incident id={self.id} severity={self.severity} status={self.status}>"
