"""SQLAlchemy models for the Global Conflict Map."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes; avoids deprecated utcnow)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Conflict(Base):
    __tablename__ = "conflict"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(120), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    events: Mapped[list[ConflictEvent]] = relationship(back_populates="conflict")


class ConflictEvent(Base):
    __tablename__ = "conflict_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_event_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    conflict_id: Mapped[int | None] = mapped_column(ForeignKey("conflict.id"))
    place_name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(120), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_type: Mapped[str | None] = mapped_column(String(80))
    actor_a: Mapped[str | None] = mapped_column(String(255))
    actor_b: Mapped[str | None] = mapped_column(String(255))
    fatalities: Mapped[int | None] = mapped_column(Integer)
    intensity: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[str] = mapped_column(String(16), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    conflict: Mapped[Conflict | None] = relationship(back_populates="events")


class RawEvent(Base):
    """Parsed GDELT row persisted before extraction/filtering."""

    __tablename__ = "raw_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(64), unique=True)
    source_day: Mapped[date] = mapped_column(Date, index=True)
    event_date: Mapped[date | None] = mapped_column(Date, index=True)
    event_root_code: Mapped[str | None] = mapped_column(String(8), index=True)
    source_file: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    outcome: Mapped[str | None] = mapped_column(String(32))


class EditLog(Base):
    __tablename__ = "edit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(80))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    edited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_day: Mapped[date | None] = mapped_column(Date, index=True)
    mode: Mapped[str | None] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
