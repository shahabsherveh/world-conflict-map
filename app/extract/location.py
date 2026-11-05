"""Detect and repair inconsistent event coordinates.

GDELT sometimes produces place strings whose components contradict each other
(e.g. "Qeshm, Kordestan, Iran" — Qeshm is an island, not in Kordestan), which
lands the marker hundreds of kilometres away. We re-geocode the most reliable
form of the name, "city, country", and accept the result only when the
geocoder confirms it lies in that country.
"""

from __future__ import annotations

import math
import time

import httpx

DEFAULT_DISTANCE_KM = 100.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def split_place(place_name: str) -> tuple[str | None, str | None]:
    """Return (city, country) from a GDELT-style "City, Region, Country" string."""
    parts = [p.strip() for p in place_name.split(",") if p.strip()]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[-1]


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


class NominatimGeocoder:
    """Rate-limited Nominatim client returning coordinates plus country."""

    def __init__(
        self,
        base_url: str = "https://nominatim.openstreetmap.org/search",
        user_agent: str = "global-conflict-map/1.0",
        min_interval: float = 1.1,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self._cache: dict[str, tuple[float, float, str] | None] = {}
        self._last = 0.0

    def lookup(self, query: str) -> tuple[float, float, str] | None:
        """Return (lat, lon, country_name) or None."""
        if query in self._cache:
            return self._cache[query]
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        result: tuple[float, float, str] | None = None
        try:
            response = httpx.get(
                self.base_url,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 1,
                    "accept-language": "en",
                },
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Language": "en",
                },
                timeout=self.timeout,
            )
            self._last = time.monotonic()
            response.raise_for_status()
            data = response.json()
            if data:
                country = (data[0].get("address") or {}).get("country", "")
                result = (float(data[0]["lat"]), float(data[0]["lon"]), country)
        except Exception:  # noqa: BLE001 — geocoding is best-effort
            result = None
        self._cache[query] = result
        return result


def resolve_coordinates(
    place_name: str | None,
    lat: float | None,
    lon: float | None,
    geocoder: NominatimGeocoder,
    threshold_km: float = DEFAULT_DISTANCE_KM,
) -> tuple[float | None, float | None, bool]:
    """Return (lat, lon, was_corrected).

    Only overrides source coordinates when "city, country" resolves somewhere
    materially different *and* the geocoder places it in the stated country.
    """
    if not place_name or lat is None or lon is None:
        return lat, lon, False

    city, country = split_place(place_name)
    if not city or not country:
        return lat, lon, False

    resolved = geocoder.lookup(f"{city}, {country}")
    if resolved is None:
        return lat, lon, False

    new_lat, new_lon, resolved_country = resolved
    if _norm(country) not in _norm(resolved_country):
        return lat, lon, False  # geocoder landed outside the stated country

    if haversine_km(lat, lon, new_lat, new_lon) > threshold_km:
        return new_lat, new_lon, True
    return lat, lon, False
