"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Intensity = Annotated[int, Field(ge=1, le=5)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
ConflictStatus = Literal["active", "ended"]
Name = Annotated[str, Field(min_length=1, max_length=255)]
# Bounded like the columns they land in: an unbounded string would be stored
# whole (SQLite ignores declared lengths) and then rendered in a list row.
PlaceName = Annotated[str, Field(max_length=255)]
Country = Annotated[str, Field(max_length=120)]
EventType = Annotated[str, Field(max_length=80)]
ActorName = Annotated[str, Field(max_length=255)]
Summary = Annotated[str, Field(max_length=5000)]
SourceUrl = Annotated[str, Field(max_length=1024)]


def _validate_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an absolute http(s) URL")
    return value


class ConflictEventOut(BaseModel):
    """An event, with corroboration counts and a derived headline."""

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
    # Corroboration, read from the stored GDELT row on the way out. Null means
    # unknown (a manual event, or one whose raw row has been pruned), never
    # "zero outlets". `well_corroborated` is a counts predicate computed by the
    # API: the ordinal `confidence` score has no validated threshold.
    sources: int | None = Field(default=None, description="Distinct outlets, or null if unknown.")
    articles: int | None = Field(default=None, description="Article count, or null if unknown.")
    well_corroborated: bool = Field(
        default=False, description="True when `sources >= 2` and `articles >= 3`."
    )
    headline: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConflictOut(BaseModel):
    """A conflict's core fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country: str | None
    start_date: date
    end_date: date | None
    status: str


class ConflictSummary(ConflictOut):
    """A conflict plus a summary of its newest in-range event."""

    intensity: int
    lat: float | None
    lon: float | None
    event_count: int
    headline: str | None


class ConflictDetail(ConflictSummary):
    """A conflict summary with its full, oldest-first event list."""

    events: list[ConflictEventOut]


class IngestionRunOut(BaseModel):
    """One pipeline run."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_day: date | None
    mode: str | None
    phase: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    items_seen: int
    items_new: int
    error: str | None
    degraded_reason: str | None


class PipelineHealthOut(BaseModel):
    """Freshness of the daily pipeline, for "the map stopped updating" checks."""

    last_success_at: datetime | None
    last_success_day: date | None
    age_hours: float | None
    stale: bool
    threshold_hours: int


class SourcesOut(BaseModel):
    """The data source behind the map."""

    source: str
    base_url: str
    lookback_days: int


class ConflictUpdate(BaseModel):
    """Partial update for a conflict; only the fields present are changed."""

    name: Name | None = None
    country: Country | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: ConflictStatus | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, data):
        if isinstance(data, dict):
            for field in ("name", "start_date", "status"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return data

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ConflictCreate(BaseModel):
    """A new conflict."""

    name: Name
    country: Country | None = None
    start_date: date
    end_date: date | None = None
    status: ConflictStatus = "active"

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class EventUpdate(BaseModel):
    """Partial update for an event; only the fields present are changed."""

    place_name: PlaceName | None = None
    country: Country | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None
    event_date: date | None = None
    event_type: EventType | None = None
    actor_a: ActorName | None = None
    actor_b: ActorName | None = None
    fatalities: Annotated[int, Field(ge=0)] | None = None
    intensity: Intensity | None = None
    summary: Summary | None = None
    source_url: SourceUrl | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, data):
        if isinstance(data, dict):
            for field in ("event_date", "intensity"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return data

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return _validate_source_url(value)


class EventCreate(BaseModel):
    """A new, manually created event."""

    place_name: PlaceName | None = None
    country: Country | None = None
    lat: Latitude | None = None
    lon: Longitude | None = None
    event_date: date
    event_type: EventType | None = None
    actor_a: ActorName | None = None
    actor_b: ActorName | None = None
    fatalities: Annotated[int, Field(ge=0)] | None = None
    intensity: Intensity = 1
    summary: Summary | None = None
    source_url: SourceUrl | None = None
    conflict_id: int | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return _validate_source_url(value)
