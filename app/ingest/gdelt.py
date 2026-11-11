"""GDELT 2.0 raw event file downloader."""

from __future__ import annotations

import io
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from app.ingest.normalizer import parse_export_tsv

DEFAULT_BASE_URL = "https://data.gdeltproject.org/gdeltv2"

# One flaky 15-minute slot used to abort a whole day (and every remaining day of a
# multi-day backfill): `fetch_day` only tolerated 404s, so a single timeout or 5xx
# propagated out of `run()`. Retry the statuses that mean "try again", and let the
# caller skip the slot if they persist.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5


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
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        attempts: int = DEFAULT_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        sleep=time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.backoff_seconds = backoff_seconds
        # Injected so a retry test does not spend real seconds asleep.
        self._sleep = sleep

    def fifteen_minute_stamps(self, day: date) -> list[str]:
        stamps: list[str] = []
        current = datetime(day.year, day.month, day.day)
        for _ in range(96):
            stamps.append(current.strftime("%Y%m%d%H%M%S"))
            current += timedelta(minutes=15)
        return stamps

    def _request(self, url: str) -> httpx.Response:
        """GET with bounded, exponential-backoff retries for transient failures."""
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            except httpx.TransportError as exc:  # timeout, connect, read, protocol
                last_error = exc
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            if attempt + 1 < self.attempts:
                self._sleep(self.backoff_seconds * (2**attempt))
        assert last_error is not None
        raise last_error

    def download_export(self, ts: str) -> list[dict[str, str]] | None:
        """Download and parse one 15-minute slot.

        Returns None when the slot has no usable payload — a 404 (slot not
        published) or an empty/corrupt archive. Both are the same thing to a
        caller: nothing to add, nothing to fail the day over. A transient failure
        that survives every retry is raised instead.
        """
        url = f"{self.base_url}/{ts}.export.CSV.zip"
        response = self._request(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        try:
            return parse_export_zip(response.content, source_name=f"{ts}.export.CSV.zip")
        except (zipfile.BadZipFile, IndexError, OSError):
            return None  # empty/invalid archive: treat like a missing slot

    def fetch_day(self, day: date, failed_slots: list[str] | None = None) -> list[dict[str, str]]:
        """Fetch one day's 96 slots.

        A slot that exhausts its retries is skipped and named in `failed_slots`
        instead of aborting the day: losing one 15-minute window is a fraction of
        the data, while raising loses all 96 (and every later day of a backfill).
        A day where *nothing* was retrievable still raises, so `run()` records
        `status = failed` for the day that really failed rather than reporting an
        empty success that looks like a frozen map.
        """
        events: list[dict[str, str]] = []
        payloads = 0
        last_error: Exception | None = None
        for ts in self.fifteen_minute_stamps(day):
            try:
                batch = self.download_export(ts)
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                if failed_slots is not None:
                    failed_slots.append(ts)
                continue
            if batch is None:
                continue
            payloads += 1
            events.extend(batch)
        if payloads == 0 and last_error is not None:
            raise last_error
        return events


def read_day_from_dir(
    directory: Path, day: date, skipped: list[str] | None = None
) -> list[dict[str, str]]:
    """Read locally cached export files for one day, skipping missing/corrupt ones.

    A missing file is normal — that 15-minute slot was simply never downloaded —
    and is not reported. A corrupt one silently shortens the day's events, so a
    caller that cares passes `skipped` and gets the offending file names
    appended to it.
    """
    events: list[dict[str, str]] = []
    for ts in GDELTClient().fifteen_minute_stamps(day):
        path = directory / f"{ts}.export.CSV.zip"
        if not path.exists():
            continue
        try:
            events.extend(parse_export_zip(path.read_bytes(), source_name=path.name))
        except (OSError, zipfile.BadZipFile, IndexError):
            if skipped is not None:
                skipped.append(path.name)
            continue  # a partial/corrupt download can be retried on the next run
    return events
