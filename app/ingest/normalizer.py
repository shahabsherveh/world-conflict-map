"""Positional column mapping and TSV parsing for GDELT 2.0 event exports."""

from __future__ import annotations

# GDELT 2.0 `.export.CSV` files are tab-separated with NO header row.
# Columns are positional; this list is the canonical 61-column schema.
COLUMNS: list[str] = [
    "global_event_id",
    "sql_date",
    "month_year",
    "year",
    "fraction_date",
    "actor1_code",
    "actor1_name",
    "actor1_country_code",
    "actor1_known_group_code",
    "actor1_ethnic_code",
    "actor1_religion1_code",
    "actor1_religion2_code",
    "actor1_type1_code",
    "actor1_type2_code",
    "actor1_type3_code",
    "actor2_code",
    "actor2_name",
    "actor2_country_code",
    "actor2_known_group_code",
    "actor2_ethnic_code",
    "actor2_religion1_code",
    "actor2_religion2_code",
    "actor2_type1_code",
    "actor2_type2_code",
    "actor2_type3_code",
    "is_root_event",
    "event_code",
    "event_base_code",
    "event_root_code",
    "quad_class",
    "goldstein_scale",
    "num_mentions",
    "num_sources",
    "num_articles",
    "avg_tone",
    "actor1_geo_type",
    "actor1_geo_fullname",
    "actor1_geo_country_code",
    "actor1_geo_adm1_code",
    "actor1_geo_adm2_code",
    "actor1_geo_lat",
    "actor1_geo_long",
    "actor1_geo_feature_id",
    "actor2_geo_type",
    "actor2_geo_fullname",
    "actor2_geo_country_code",
    "actor2_geo_adm1_code",
    "actor2_geo_adm2_code",
    "actor2_geo_lat",
    "actor2_geo_long",
    "actor2_geo_feature_id",
    "action_geo_type",
    "action_geo_fullname",
    "action_geo_country_code",
    "action_geo_adm1_code",
    "action_geo_adm2_code",
    "action_geo_lat",
    "action_geo_long",
    "action_geo_feature_id",
    "date_added",
    "source_url",
]


def parse_export_tsv(text: str) -> list[dict[str, str]]:
    """Parse a GDELT 2.0 export TSV (no header) into a list of field dicts."""
    events: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != len(COLUMNS):
            continue
        events.append(dict(zip(COLUMNS, fields)))
    return events


def dedupe_new(
    events: list[dict[str, str]], existing_ids: set[str] | None = None
) -> list[dict[str, str]]:
    """Drop events whose `global_event_id` was already seen or already stored."""
    existing = existing_ids or set()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for event in events:
        gid = event.get("global_event_id", "")
        if not gid or gid in existing or gid in seen:
            continue
        seen.add(gid)
        out.append(event)
    return out
