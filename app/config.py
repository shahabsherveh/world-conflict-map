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
}


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Return merged config (file values over defaults)."""
    values: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            values = yaml.safe_load(f) or {}
    return {**DEFAULTS, **values}
