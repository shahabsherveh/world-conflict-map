"""Rebuild conflicts from the stored events with the current grouping rule.

Usage:
    python scripts/regroup.py            # report only (runs inside a rolled-back transaction)
    python scripts/regroup.py --apply    # write the new grouping

Only needed to repair data grouped by an older rule (see the autoflush bug in
app/extract/grouping.py: conflicts created during a run used to fall back to
city-name matching, splitting one theatre into one conflict per city). The daily
run links new events only and never needs this.

This rewrites `conflict` rows and every event's `conflict_id`; event coordinates
are untouched, so no marker moves. Conflict ids restart from 1, so a bookmark to
?conflict=ID will point at a different conflict afterwards. Back up conflicts.db
first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.db import get_session
from app.extract.grouping import regroup_all
from app.models import Conflict, ConflictEvent, EditLog


def main(apply: bool = False) -> None:
    session = get_session()
    try:
        before = session.scalar(select(func.count()).select_from(Conflict)) or 0
        curated = session.scalar(
            select(func.count()).select_from(EditLog).where(EditLog.target_type == "conflict")
        )
        events = session.scalar(select(func.count()).select_from(ConflictEvent)) or 0
        unlinked = session.scalar(
            select(func.count())
            .select_from(ConflictEvent)
            .where(ConflictEvent.conflict_id.is_(None))
        )

        created = regroup_all(session)
        session.flush()  # autoflush is off: make the new links visible to the counts below
        orphaned = session.scalar(
            select(func.count())
            .select_from(ConflictEvent)
            .where(ConflictEvent.conflict_id.is_(None))
        )
        sizes = session.execute(
            select(Conflict.name, func.count(ConflictEvent.id))
            .join(ConflictEvent, ConflictEvent.conflict_id == Conflict.id)
            .group_by(Conflict.id)
            .order_by(func.count(ConflictEvent.id).desc())
            .limit(5)
        ).all()

        mode = "applied" if apply else "dry-run (rolled back)"
        print(f"{before} conflicts -> {created} from {events} events ({unlinked} unlinked before)")
        print("largest: " + ", ".join(f"{name} ({count})" for name, count in sizes))
        print(f"unlinked after regrouping: {orphaned}", flush=True)
        if curated:
            print(
                f"WARNING: {curated} conflict edit(s) in edit_log will be dropped "
                f"(conflict ids are reassigned)",
                flush=True,
            )
        if apply:
            session.commit()
        else:
            session.rollback()
        print(mode)
    finally:
        session.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
