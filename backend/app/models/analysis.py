"""Analysis ORM model - one LLM reasoning step tied to an incident."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.incident import Incident


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Raw LLM output (free-form text) plus the parsed structured JSON if available.
    llm_output: Mapped[str] = mapped_column(Text, nullable=False)
    structured_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # End-to-end agent telemetry (iterations, tools, timing, confidence progression).
    # Stored as JSON so we can evolve the shape without a migration.
    observability: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    incident: Mapped["Incident"] = relationship(back_populates="analyses")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Analysis id={self.id} incident_id={self.incident_id} "
            f"step={self.step_index} confidence={self.confidence_score}>"
        )
