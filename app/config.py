"""Shared configuration loading (path-independent)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "gdelt.yaml"

DEFAULTS = {
    "base_url": "https://data.gdeltproject.org/gdeltv2",
    "lookback_days": 1,
    "zero_shot_threshold": 0.7,
    "repair_locations": False,
    "raw_retention_days": 30,
    # Daily cron has 24h between runs; two days of slack keeps one transient
    # failure (retried on the next run) from paging, while still catching a
    # pipeline that has genuinely stopped updating the map.
    "pipeline_stale_hours": 48,
    # A `running` ingestion_run older than this is a dead process, not a live
    # run; the pipeline settles it to `failed` before adding its own rows.
    "stale_run_hours": 12,
}


@lru_cache(maxsize=1)
def _loaded_config() -> dict:
    """Read and merge the YAML once; callers never see this dict."""
    values: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            values = yaml.safe_load(f) or {}
    return {**DEFAULTS, **values}


def load_config() -> dict:
    """Return merged config (file values over defaults).

    A fresh copy every call: callers treat the result as their own dict, and
    handing out the cached object let one mutation poison every later read for
    the life of the process.
    """
    return dict(_loaded_config())
