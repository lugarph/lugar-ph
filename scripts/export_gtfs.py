"""Write one city's jeepney network as a static GTFS zip.

Uses the checked-in network plus any approved revisions in the database that
DATABASE_URL points to (the local SQLite file by default). Without a usable
database, the checked-in network alone is exported.

    .venv/bin/python scripts/export_gtfs.py --city bacolod --out bacolod-gtfs.zip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gtfs_export import export_city
from transit_network import CITY_METADATA


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", required=True, choices=sorted(CITY_METADATA))
    parser.add_argument("--out", required=True, type=Path, help="Path of the zip file to write")
    args = parser.parse_args()
    feed = export_city(args.city)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(feed)
    print(f"Wrote {args.out} ({len(feed) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
