"""Pydantic schemas for log entries."""

from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class LogBase(BaseModel):
    timestamp: datetime
    service_name: str = Field(..., max_length=128)
    severity: str = Field(..., max_length=32)
    message: str


class LogCreate(LogBase):
    pass


class LogOut(LogBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class LogUploadResponse(BaseModel):
    ingested: int
    skipped: int = 0
    sample: List[LogOut] = Field(default_factory=list)
