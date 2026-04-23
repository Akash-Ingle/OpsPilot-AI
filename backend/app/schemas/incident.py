"""Pydantic schemas for incidents."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.incident import IncidentStatus, Severity
from app.schemas.analysis import AnalysisOut


class IncidentBase(BaseModel):
    title: str = Field(..., max_length=255)
    severity: Severity = Severity.MEDIUM
    root_cause: Optional[str] = None
    suggested_fix: Optional[str] = None
    status: IncidentStatus = IncidentStatus.OPEN


class IncidentCreate(IncidentBase):
    pass


class IncidentUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    severity: Optional[Severity] = None
    root_cause: Optional[str] = None
    suggested_fix: Optional[str] = None
    status: Optional[IncidentStatus] = None


class IncidentOut(IncidentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentOut):
    analyses: List[AnalysisOut] = Field(default_factory=list)
