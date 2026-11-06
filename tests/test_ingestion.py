import io
import zipfile
from datetime import date

import httpx

from app.ingest.gdelt import GDELTClient, parse_export_zip, read_day_from_dir
from app.ingest.normalizer import COLUMNS, dedupe_new, parse_export_tsv


def make_row(**overrides: str) -> str:
    row = [""] * len(COLUMNS)
    for key, value in overrides.items():
        row[COLUMNS.index(key)] = value
    return "\t".join(row)


def test_parse_export_tsv_maps_columns() -> None:
    text = make_row(
        global_event_id="123",
        event_root_code="19",
        action_geo_lat="33.3",
        action_geo_long="44.4",
        source_url="http://example.com",
    )
    events = parse_export_tsv(text)
    assert len(events) == 1
    event = events[0]
    assert event["global_event_id"] == "123"
    assert event["event_root_code"] == "19"
    assert event["action_geo_lat"] == "33.3"
    assert event["action_geo_long"] == "44.4"
    assert event["source_url"] == "http://example.com"


def test_parse_export_tsv_skips_malformed_rows() -> None:
    good = make_row(global_event_id="1")
    bad = "only\tthree\tfields"
    events = parse_export_tsv(f"{good}\n{bad}\n")
    assert len(events) == 1


def test_parse_export_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "sample.export.CSV", make_row(global_event_id="1", event_root_code="19") + "\n"
        )
    events = parse_export_zip(buf.getvalue(), source_name="sample.export.CSV.zip")
    assert events[0]["global_event_id"] == "1"
    assert events[0]["_source_file"] == "sample.export.CSV.zip"


def test_fifteen_minute_stamps() -> None:
    client = GDELTClient()
    stamps = client.fifteen_minute_stamps(date(2024, 1, 1))
    assert len(stamps) == 96
    assert stamps[0] == "20240101000000"
    assert stamps[-1] == "20240101234500"


def test_dedupe_new() -> None:
    events = [
        {"global_event_id": "a"},
        {"global_event_id": "b"},
        {"global_event_id": "a"},
    ]
    assert [e["global_event_id"] for e in dedupe_new(events)] == ["a", "b"]


def test_dedupe_new_skips_existing() -> None:
    events = [{"global_event_id": "a"}, {"global_event_id": "b"}]
    assert [e["global_event_id"] for e in dedupe_new(events, {"a"})] == ["b"]


def test_read_day_from_dir_skips_missing_and_corrupt_files(tmp_path) -> None:
    day = date(2024, 1, 1)
    stamps = GDELTClient().fifteen_minute_stamps(day)
    with zipfile.ZipFile(tmp_path / f"{stamps[0]}.export.CSV.zip", "w") as archive:
        archive.writestr(
            "sample.export.CSV",
            make_row(global_event_id="1", event_root_code="19") + "\n",
        )
    (tmp_path / f"{stamps[1]}.export.CSV.zip").write_bytes(b"not a zip")

    events = read_day_from_dir(tmp_path, day)
    assert [event["global_event_id"] for event in events] == ["1"]
    assert events[0]["_source_file"] == f"{stamps[0]}.export.CSV.zip"


def test_fetch_day_skips_missing_files(monkeypatch) -> None:
    client = GDELTClient()

    def fake_download(ts: str) -> list[dict[str, str]]:
        if ts.endswith("001500"):
            request = httpx.Request("GET", "http://example.com")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("404", request=request, response=response)
        return [{"global_event_id": ts}]

    monkeypatch.setattr(client, "download_export", fake_download)
    events = client.fetch_day(date(2024, 1, 1))
    assert len(events) == 95
