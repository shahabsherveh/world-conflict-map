from app.config import DEFAULTS, load_config


def test_unsafe_location_repair_is_off_by_default() -> None:
    """Regression: auto-repair corrupts good coordinates, so it must default off."""
    assert DEFAULTS["repair_locations"] is False


def test_config_merges_file_over_defaults() -> None:
    cfg = load_config()
    assert cfg["lookback_days"] == 1
    assert isinstance(cfg["zero_shot_threshold"], float)
    assert cfg["base_url"].startswith("http")
