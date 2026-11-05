"""Inspect suspicious event coordinates (dry-run only by default).

Usage:
    python scripts/repair_locations.py            # report only
    python scripts/repair_locations.py --apply    # write changes

WARNING: automatic repair is unreliable. Re-geocoding "city, country" drops the
region token that GDELT used, which can move an already-correct marker hundreds
of kilometres (verified against Dnipro/Komyshuvakha/Kagera). Prefer editing the
few genuinely wrong points by hand in the UI.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import get_session
from app.extract.location import NominatimGeocoder, resolve_coordinates
from app.models import ConflictEvent


def main(apply: bool = False) -> None:
    session = get_session()
    geocoder = NominatimGeocoder()
    events = list(session.scalars(select(ConflictEvent)))
    flagged = 0
    try:
        for event in events:
            new_lat, new_lon, changed = resolve_coordinates(
                event.place_name, event.lat, event.lon, geocoder
            )
            if not changed:
                continue
            flagged += 1
            print(
                f"[suspect {event.id}] {event.place_name}: "
                f"({event.lat:.3f},{event.lon:.3f}) vs city-level ({new_lat:.3f},{new_lon:.3f})",
                flush=True,
            )
            if apply:
                event.lat, event.lon = new_lat, new_lon
                session.commit()
    finally:
        session.commit()
        session.close()
    mode = "applied" if apply else "reported (dry-run)"
    print(f"\n{mode}: {flagged} of {len(events)} events")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
