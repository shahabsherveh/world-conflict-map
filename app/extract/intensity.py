"""Intensity derivation for conflict events."""

from __future__ import annotations

BASE_INTENSITY = {"battle": 4, "assault": 3, "mass_violence": 5}


def derive_intensity(event_type: str, fatalities: int | None, goldstein: float | None) -> int:
    intensity = BASE_INTENSITY.get(event_type, 3)
    if fatalities:
        intensity += 1
    if goldstein is not None and goldstein < -5.0:
        intensity += 1
    return max(1, min(5, intensity))
