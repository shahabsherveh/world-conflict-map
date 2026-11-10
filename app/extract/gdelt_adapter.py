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


# Denominators come from observed percentiles in the armed-conflict subset (n≈2.9k):
# NumArticles p50=4 / p90=10 / p99=15, and NumSources is 1 for 94.9% of events, so /4 puts
# genuinely multi-outlet coverage at the top of the range. The weight is a convention, not a
# fitted parameter: ranking is insensitive to it (Spearman ≥0.99 for any weight in 0.2–0.8),
# so there is nothing to optimise. What it does control is where the absolute 0.5 line falls
# — a threshold nothing has validated.
ARTICLES_FOR_FULL_CONFIDENCE = 10.0
SOURCES_FOR_FULL_CONFIDENCE = 4.0
SOURCE_WEIGHT = 0.6


def _count(raw: dict[str, str], key: str) -> int:
    """Parse one corroboration count; absent, unparsable or negative means zero.

    GDELT emits both columns, so a missing one is a fixture or parse gap rather
    than evidence of a source. Treating it as zero keeps one absence mapping to
    one value, which is what makes the column filterable.
    """
    try:
        return max(int(raw.get(key) or 0), 0)
    except ValueError:
        return 0


def _confidence(raw: dict[str, str]) -> float:
    """Ordinal corroboration score, 0.0..1.0: article volume plus an outlet bonus.

    Twelve articles from one outlet is usually a single wire story reprinted; twelve
    across four outlets is independent corroboration, so the outlet term is the bonus.
    Read this as a ranking key, not a measurement — the weights are a convention (ranking
    barely moves across them) and the scale is unvalidated. When a decision matters, gate
    on the counts (`sources >= 2 and articles >= 3`), not on a threshold of this number.
    """
    articles = min(_count(raw, "num_articles") / ARTICLES_FOR_FULL_CONFIDENCE, 1.0)
    sources = min(_count(raw, "num_sources") / SOURCES_FOR_FULL_CONFIDENCE, 1.0)
    return round((1 - SOURCE_WEIGHT) * articles + SOURCE_WEIGHT * sources, 2)


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
