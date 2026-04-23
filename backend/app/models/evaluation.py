"""Evaluation ORM model - stores the comparison of an LLM analysis against
the ground truth for a known simulated scenario (Plan §10.2)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Evaluation(Base):
    """A single scored comparison between a predicted analysis and a known scenario."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Which scenario's ground truth we evaluated against.
    scenario_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Link back to the analyzed incident / analysis. Nullable by design so an
    # evaluation can also be recorded from a one-shot comparison in an
    # experiment (no persisted incident).
    incident_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    analysis_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Expected (ground truth) fields.
    expected_root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    expected_severity: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_fix: Mapped[str] = mapped_column(Text, nullable=False)

    # Predicted (LLM) fields.
    predicted_root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_severity: Mapped[str] = mapped_column(String(32), nullable=False)
    predicted_fix: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Per-dimension matches.
    root_cause_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    severity_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fix_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overall_correct: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )

    # Weighted score in [0.0, 1.0] blending the three dimensions.
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Fraction of expected root_cause keywords found in the prediction.
    keyword_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Bookkeeping: which keywords matched / were missing. Handy for debugging
    # and for building calibration dashboards without re-running the matcher.
    matched_keywords: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    missing_keywords: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # Raw predicted output snapshot (full dict) for traceability.
    predicted_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Evaluation id={self.id} scenario={self.scenario_name} "
            f"score={self.score:.2f} correct={self.overall_correct}>"
        )
