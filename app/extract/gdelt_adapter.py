"""GDELT 2.0 → EventDraft adapter."""

from __future__ import annotations

from datetime import datetime

from app.extract.base import BaseSourceAdapter, EventDraft
from app.extract.intensity import derive_intensity

ARMED_CONFLICT_ROOT_CODES = {"18", "19", "20"}


def _map_event_type(event_base_code: str) -> str:
    if event_base_code.startswith("19"):
        return "battle"
    if event_base_code.startswith("18"):
        return "assault"
    if event_base_code.startswith("20"):
        return "mass_violence"
    return event_base_code


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summary(raw: dict[str, str]) -> str | None:
    actors = [name for name in (raw.get("actor1_name"), raw.get("actor2_name")) if name]
    base = " vs ".join(actors) if actors else "Armed conflict"
    place = raw.get("action_geo_fullname")
    return f"{base} — {place}" if place else base


def _confidence(raw: dict[str, str]) -> float:
    try:
        articles = int(raw.get("num_articles") or 0)
    except ValueError:
        return 0.5
    return round(min(articles / 10.0, 1.0), 2)


class GDELTAdapter(BaseSourceAdapter):
    def to_event_draft(self, raw: dict[str, str]) -> EventDraft | None:
        if raw.get("event_root_code") not in ARMED_CONFLICT_ROOT_CODES:
            return None

        sql_date = raw.get("sql_date", "")
        try:
            event_date = datetime.strptime(sql_date, "%Y%m%d").date()
        except ValueError:
            return None

        event_type = _map_event_type(raw.get("event_base_code", ""))
        goldstein = _to_float(raw.get("goldstein_scale", ""))

        return EventDraft(
            source_event_id=raw.get("global_event_id") or None,
            place_name=raw.get("action_geo_fullname") or None,
            country=raw.get("action_geo_country_code") or None,
            lat=_to_float(raw.get("action_geo_lat", "")),
            lon=_to_float(raw.get("action_geo_long", "")),
            event_date=event_date,
            event_type=event_type,
            actor_a=raw.get("actor1_name") or None,
            actor_b=raw.get("actor2_name") or None,
            fatalities=None,
            intensity=derive_intensity(event_type, None, goldstein),
            summary=_summary(raw),
            source_url=raw.get("source_url") or None,
            confidence=_confidence(raw),
        )
