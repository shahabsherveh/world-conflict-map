"""Seed the DB with demo conflicts for UI testing (no network needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import date, timedelta

from app.db import get_session
from app.models import Conflict, ConflictEvent

DEMOS = [
    ("Ukraine War", "UA", 48.0, 37.5, 5),
    ("Yemen Civil War", "YE", 15.3, 44.2, 5),
    ("Sudan Conflict", "SD", 15.5, 32.5, 4),
    ("Sahel Insurgency", "ML", 16.0, -1.0, 3),
]


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
        for i in range(3):
            session.add(
                ConflictEvent(
                    conflict_id=conflict.id,
                    place_name=name,
                    country=country,
                    lat=lat,
                    lon=lon,
                    event_date=today - timedelta(days=i * 10),
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
