"""Download raw GDELT 2.0 export files for a date range.

This is a fetch-only helper: it never touches the database. Use it when the
daily pipeline's built-in fetch is too slow or when you want to inspect/cache
the raw data before extracting.

Examples:
    python scripts/fetch_gdelt.py --days 7
    python scripts/fetch_gdelt.py --start 2026-10-29 --end 2026-11-04
    python scripts/fetch_gdelt.py --days 7 --dry-run
    python scripts/fetch_gdelt.py --days 7 --workers 8 --overwrite

Files are written as `{YYYYMMDDHHMMSS}.export.CSV.zip` and existing complete
files are skipped, so an interrupted run can simply be restarted.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.ingest.gdelt import GDELTClient


def parse_args() -> argparse.Namespace:
    cfg = load_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="fetch the last N complete UTC days")
    parser.add_argument("--start", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (YYYY-MM-DD)")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/gdelt"),
        help="output directory (default: data/gdelt)",
    )
    parser.add_argument("--workers", type=int, default=8, help="parallel downloads (default: 8)")
    parser.add_argument("--timeout", type=float, default=120.0, help="per-request timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="retries per failed file")
    parser.add_argument("--overwrite", action="store_true", help="re-download existing files")
    parser.add_argument("--base-url", default=cfg["base_url"], help="GDELT base URL")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without downloading")
    args = parser.parse_args()

    if args.days is not None and (args.start or args.end):
        parser.error("use either --days or --start/--end, not both")
    if args.days is None and (args.start is None or args.end is None):
        parser.error("provide --days, or both --start and --end")
    if args.days is not None and args.days < 1:
        parser.error("--days must be >= 1")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    return args


def resolve_days(args: argparse.Namespace) -> list[date]:
    """Return the inclusive list of UTC days to fetch."""
    if args.days is not None:
        end = datetime.now(UTC).date() - timedelta(days=1)  # last complete UTC day
        start = end - timedelta(days=args.days - 1)
    else:
        start, end = args.start, args.end
    if end < start:
        raise ValueError(f"end date {end} is before start date {start}")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def format_duration(seconds: float) -> str:
    """Format seconds as `m:ss` or `h:mm:ss`."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def progress_line(
    done: int, total: int, counts: dict[str, int], started: float, width: int = 30
) -> str:
    """Build a compact, single-line progress bar."""
    ratio = done / total if total else 1.0
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    elapsed = time.time() - started
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    return (
        f"[{bar}] {done}/{total} {ratio * 100:5.1f}% "
        f"| ok {counts['downloaded']} skip {counts['skipped']} "
        f"miss {counts['missing']} fail {counts['failed']} "
        f"| {format_duration(elapsed)} ETA {format_duration(eta)}"
    )


def fetch_one(
    client: httpx.Client,
    base_url: str,
    stamp: str,
    out_dir: Path,
    overwrite: bool,
    retries: int,
) -> tuple[str, str]:
    """Download one 15-minute file. Returns (status, detail)."""
    path = out_dir / f"{stamp}.export.CSV.zip"
    if not overwrite and path.exists() and path.stat().st_size > 0:
        return "skipped", str(path)

    url = f"{base_url.rstrip('/')}/{stamp}.export.CSV.zip"
    last_error = ""
    for attempt in range(retries + 1):
        try:
            with client.stream("GET", url) as response:
                if response.status_code == 404:
                    return "missing", stamp
                response.raise_for_status()
                tmp = path.with_name(path.name + ".part")
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(65536):
                        handle.write(chunk)
                if tmp.stat().st_size == 0:
                    tmp.unlink(missing_ok=True)
                    raise OSError("empty response body")
                tmp.replace(path)
                return "downloaded", str(path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return "missing", stamp
            last_error = f"HTTP {exc.response.status_code}"
        except (httpx.HTTPError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(2**attempt)
    return "failed", f"{stamp} ({last_error})"


def main() -> int:
    args = parse_args()
    try:
        days = resolve_days(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    stamps = [stamp for day in days for stamp in GDELTClient().fifteen_minute_stamps(day)]
    print(
        f"days: {days[0]} .. {days[-1]} ({len(days)}), files: {len(stamps)}, out: {args.out}",
        flush=True,
    )
    if args.dry_run:
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    counts = {"downloaded": 0, "skipped": 0, "missing": 0, "failed": 0}
    failures: list[str] = []
    limits = httpx.Limits(max_connections=args.workers, max_keepalive_connections=args.workers)
    timeout = httpx.Timeout(args.timeout)
    started = time.time()
    is_tty = sys.stdout.isatty()
    term_width = max(20, shutil.get_terminal_size(fallback=(100, 24)).columns - 1)
    progress_every = max(1, len(stamps) // 20)  # non-TTY: ~5% milestones
    last_milestone = 0
    initial = progress_line(0, len(stamps), counts, started)
    if is_tty:
        print("\r" + initial[:term_width].ljust(term_width), end="", flush=True)
    else:
        print(initial, flush=True)

    with (
        httpx.Client(timeout=timeout, follow_redirects=True, limits=limits) as client,
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        futures = {
            pool.submit(
                fetch_one,
                client,
                args.base_url,
                stamp,
                args.out,
                args.overwrite,
                args.retries,
            ): stamp
            for stamp in stamps
        }
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                status, detail = future.result()
            except Exception as exc:  # noqa: BLE001 — keep the fetch going
                status, detail = "failed", f"{futures[future]} ({type(exc).__name__}: {exc})"
            counts[status] += 1
            if status == "failed":
                failures.append(detail)
                if is_tty:
                    print(f"\r[{' ' * term_width}]", end="\r", flush=True)
                print(f"[{done}/{len(stamps)}] failed {detail}", flush=True)

            line = progress_line(done, len(stamps), counts, started)
            if is_tty:
                print("\r" + line[:term_width].ljust(term_width), end="", flush=True)
            elif done == len(stamps) or done - last_milestone >= progress_every:
                print(line, flush=True)
                last_milestone = done

    if is_tty:
        print(flush=True)  # finish the progress line
    elapsed = time.time() - started
    print(
        f"done in {elapsed:.0f}s: {counts['downloaded']} downloaded, "
        f"{counts['skipped']} skipped, {counts['missing']} missing, "
        f"{counts['failed']} failed",
        flush=True,
    )
    if failures:
        failure_file = args.out / "fetch_failures.txt"
        failure_file.write_text("\n".join(failures) + "\n")
        print(f"failures written to {failure_file}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
