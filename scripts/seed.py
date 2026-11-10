"""Seed the DB with demo conflicts for UI testing (no network needed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import date, timedelta

from app.db import get_session
from app.models import Conflict, ConflictEvent, RawEvent, utcnow

DEMOS = [
    ("Ukraine War", "UA", 48.0, 37.5, 5),
    ("Yemen Civil War", "YE", 15.3, 44.2, 5),
    ("Sudan Conflict", "SD", 15.5, 32.5, 4),
    ("Sahel Insurgency", "ML", 16.0, -1.0, 3),
    # GDELT often cannot pin a city, and the real feed leaves ~500 such conflicts
    # per 30-day window. Seeding one keeps that path (the "No location" panel and
    # its set-location flow) exercisable without a network fetch.
    ("Unplaced Border Clashes", "XX", None, None, 4),
]

# Demo corroboration, so the popup badge is visible without a network fetch. The
# three states the API distinguishes are all covered: several outlets (green),
# one outlet with many articles (muted), and no raw row at all (no badge).
CORROBORATION: dict[str, tuple[int, int]] = {
    "Ukraine War": (4, 12),
    "Yemen Civil War": (1, 9),
}


def main() -> None:
    session = get_session()
    if session.query(Conflict).count() > 0:
        session.close()
        print("DB already has conflicts; skipping seed.")
        return

    today = date.today()
    for name, country, lat, lon, intensity in DEMOS:
        conflict = Conflict(
            name=name, country=country, start_date=today - timedelta(days=90), status="active"
        )
        session.add(conflict)
        session.flush()
        # The no-location demo gets exactly one unplaced event: with several,
        # the UI correctly stops at the conflict ("open the one to place it")
        # instead of arming the picker.
        event_total = 1 if lat is None else 3
        for i in range(event_total):
            # Offset each event slightly instead of stacking them on one point:
            # identical coordinates never separate when zooming, so Leaflet
            # spiderfies them — which jsdom cannot render in the UI smoke test.
            event_lat = None if lat is None else lat + (i - 1) * 0.04
            event_lon = None if lon is None else lon + (i - 1) * 0.04
            event_date = today - timedelta(days=i * 10)
            counts = CORROBORATION.get(name)
            # Mark the demo raw row processed: it exists to be read by the API,
            # not to be re-extracted by the next pipeline run.
            source_event_id = f"demo-{conflict.id}-{i}" if counts else None
            if counts:
                sources, articles = counts
                session.add(
                    RawEvent(
                        source_event_id=source_event_id,
                        source_day=event_date,
                        event_date=event_date,
                        event_root_code="19",
                        payload=json.dumps(
                            {"num_sources": str(sources), "num_articles": str(articles)}
                        ),
                        processed_at=utcnow(),
                        outcome="persisted",
                    )
                )
            session.add(
                ConflictEvent(
                    conflict_id=conflict.id,
                    source_event_id=source_event_id,
                    place_name=name,
                    country=country,
                    lat=event_lat,
                    lon=event_lon,
                    event_date=event_date,
                    event_type="battle",
                    intensity=intensity,
                    provenance="auto",
                    source_url="https://example.com/seed",
                )
            )
    session.commit()
    session.close()
    print("Seeded demo conflicts.")


if __name__ == "__main__":
    main()
