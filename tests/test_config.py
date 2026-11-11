from app.config import DEFAULTS, load_config


def test_unsafe_location_repair_is_off_by_default() -> None:
    """Regression: auto-repair corrupts good coordinates, so it must default off."""
    assert DEFAULTS["repair_locations"] is False


def test_config_merges_file_over_defaults() -> None:
    cfg = load_config()
    assert cfg["lookback_days"] == 1
    assert isinstance(cfg["zero_shot_threshold"], float)
    assert cfg["base_url"].startswith("http")
    assert cfg["raw_retention_days"] == 30


def test_load_config_returns_an_independent_copy() -> None:
    """Regression: mutating the result poisoned every later read (cached dict)."""
    first = load_config()
    first["lookback_days"] = 999
    first["new_key"] = True
    second = load_config()
    assert second["lookback_days"] == 1
    assert "new_key" not in second
