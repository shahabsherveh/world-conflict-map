"""Swappable event-source adapter boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class EventDraft:
    source_event_id: str | None
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


class BaseSourceAdapter(ABC):
    @abstractmethod
    def to_event_draft(self, raw: dict[str, str]) -> EventDraft | None:
        """Map one raw source record to an EventDraft, or None to drop it."""
