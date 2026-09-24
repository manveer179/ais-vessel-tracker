"""Collect AIS vessel positions every two hours and append them to a CSV file."""

from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

import requests


DEFAULT_MMSI = "566942000"
DEFAULT_VESSEL_URL = (
    "https://aisvesseltracker.com/vessel/"
    "wan-hai-517-mmsi-566942000-imo-9457660"
)
DEFAULT_OUTPUT = Path("vessel_positions.csv")
REQUEST_TIMEOUT_SECONDS = 30
COLLECTION_INTERVAL_SECONDS = 2 * 60 * 60
CSV_FIELDS = (
    "collected_at_utc",
    "mmsi",
    "vessel_name",
    "latitude",
    "longitude",
    "source_url",
)


class TextExtractor(HTMLParser):
    """Extract visible text while ignoring page markup."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def page_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return parser.text()


def extract_value(text: str, label: str) -> str:
    match = re.search(
        rf"{label}\s*([+-]?\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Could not find {label} in the vessel page")
    return match.group(1)


def extract_vessel_name(text: str) -> str:
    match = re.search(
        r"About\s+([A-Z0-9][A-Z0-9 ]+?)\s+\1\s+is\s+a\s+",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


def fetch_position(url: str, mmsi: str) -> dict[str, str]:
    response = requests.get(
        url,
        headers={"User-Agent": "sales-ais-position-scraper/1.0"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = page_text(response.text)
    return {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mmsi": mmsi,
        "vessel_name": extract_vessel_name(text),
        "latitude": extract_value(text, "Latitude"),
        "longitude": extract_value(text, "Longitude"),
        "source_url": url,
    }


def append_row(output: Path, row: dict[str, str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output.exists() and output.stat().st_size > 0
    with output.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def scrape_once(url: str, mmsi: str, output: Path) -> None:
    row = fetch_position(url, mmsi)
    append_row(output, row)
    print(
        f"{row['collected_at_utc']} | {row['vessel_name'] or mmsi} | "
        f"{row['latitude']}, {row['longitude']} -> {output}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmsi", default=DEFAULT_MMSI)
    parser.add_argument("--url", default=DEFAULT_VESSEL_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--once",
        dest="continuous",
        action="store_false",
        help="Collect one position and exit",
    )
    parser.set_defaults(continuous=True)
    args = parser.parse_args()

    next_collection = time.monotonic()
    while True:
        try:
            scrape_once(args.url, args.mmsi, args.output)
        except (OSError, requests.RequestException, ValueError) as exc:
            print(f"Scrape failed: {exc}")
            if not args.continuous:
                raise SystemExit(1) from exc
        if not args.continuous:
            return
        next_collection += COLLECTION_INTERVAL_SECONDS
        time.sleep(max(0, next_collection - time.monotonic()))


if __name__ == "__main__":
    main()