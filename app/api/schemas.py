"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Intensity = Annotated[int, Field(ge=1, le=5)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
ConflictStatus = Literal["active", "ended"]


class ConflictEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_event_id: str | None
    conflict_id: int | None
    place_name: str | None
    country: str | None
    lat: float | None
    lon: float | None
    event_date: date
    event_type: str | None
    actor_a: str | None
    actor_b: str | None
    fatalities: int | None
    intensity: int
    summary: str | None
    source_url: str | None
    confidence: float | None
    provenance: str
    headline: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country: str | None
    start_date: date
    end_date: date | None
    status: str


class ConflictSummary(ConflictOut):
    intensity: int
    lat: float | None
    lon: float | None
    event_count: int
    headline: str | None


class ConflictDetail(ConflictSummary):
    events: list[ConflictEventOut]


class ConflictUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: ConflictStatus | None = None


class ConflictCreate(BaseModel):
    name: str
    country: str | None = None
    start_date: date
    end_date: date | None = None
    status: ConflictStatus = "active"


class EventUpdate(BaseModel):
    place_name: str | None = None
    country: str | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None
    event_date: date | None = None
    event_type: str | None = None
    actor_a: str | None = None
    actor_b: str | None = None
    fatalities: Annotated[int, Field(ge=0)] | None = None
    intensity: Intensity | None = None
    summary: str | None = None
    source_url: str | None = None


class EventCreate(BaseModel):
    place_name: str | None = None
    country: str | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None
    event_date: date
    event_type: str | None = None
    actor_a: str | None = None
    actor_b: str | None = None
    fatalities: Annotated[int, Field(ge=0)] | None = None
    intensity: Intensity = 1
    summary: str | None = None
    source_url: str | None = None
    conflict_id: int | None = None
