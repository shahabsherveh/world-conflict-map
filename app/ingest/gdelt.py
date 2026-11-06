"""GDELT 2.0 raw event file downloader."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from app.ingest.normalizer import parse_export_tsv

DEFAULT_BASE_URL = "https://data.gdeltproject.org/gdeltv2"


def parse_export_zip(data: bytes, source_name: str | None = None) -> list[dict[str, str]]:
    """Unzip a `.export.CSV.zip` payload and parse its TSV contents."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as f:
            events = parse_export_tsv(f.read().decode("utf-8", "replace"))
    if source_name:
        for event in events:
            event["_source_file"] = source_name
    return events


class GDELTClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fifteen_minute_stamps(self, day: date) -> list[str]:
        stamps: list[str] = []
        current = datetime(day.year, day.month, day.day)
        for _ in range(96):
            stamps.append(current.strftime("%Y%m%d%H%M%S"))
            current += timedelta(minutes=15)
        return stamps

    def download_export(self, ts: str) -> list[dict[str, str]]:
        url = f"{self.base_url}/{ts}.export.CSV.zip"
        response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        return parse_export_zip(response.content, source_name=f"{ts}.export.CSV.zip")

    def fetch_day(self, day: date) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        for ts in self.fifteen_minute_stamps(day):
            try:
                events.extend(self.download_export(ts))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue  # no data for this 15-min slot
                raise
        return events


def read_day_from_dir(directory: Path, day: date) -> list[dict[str, str]]:
    """Read locally cached export files for one day, skipping missing/corrupt ones."""
    events: list[dict[str, str]] = []
    for ts in GDELTClient().fifteen_minute_stamps(day):
        path = directory / f"{ts}.export.CSV.zip"
        if not path.exists():
            continue
        try:
            events.extend(parse_export_zip(path.read_bytes(), source_name=path.name))
        except (OSError, zipfile.BadZipFile, IndexError):
            continue  # a partial/corrupt download can be retried on the next run
    return events
