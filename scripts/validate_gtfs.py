"""Check every city's GTFS feed with the MobilityData GTFS validator.

Downloads the validator's command-line jar (about 40 MB) into scripts/.cache/
on first use; it is not kept in Git. The validator needs Java 17 or newer: set
JAVA to a java binary if the one on PATH is older.

    .venv/bin/python scripts/validate_gtfs.py              # every city
    .venv/bin/python scripts/validate_gtfs.py --city naga

Prints each feed's notices by severity and exits with status 1 if any feed has
an ERROR notice. Full HTML and JSON reports are left in scripts/.cache/gtfs/.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gtfs_export import export_city
from transit_network import CITY_METADATA


VALIDATOR_VERSION = "8.0.1"
VALIDATOR_URL = (
    f"https://github.com/MobilityData/gtfs-validator/releases/download/v{VALIDATOR_VERSION}/"
    f"gtfs-validator-{VALIDATOR_VERSION}-cli.jar"
)
CACHE = ROOT / "scripts" / ".cache"
JAR = CACHE / f"gtfs-validator-{VALIDATOR_VERSION}-cli.jar"
MIN_JAVA = 17


def _java_version(java: str) -> int:
    output = subprocess.run([java, "-version"], capture_output=True, text=True).stderr
    match = re.search(r'version "(\d+)(?:\.(\d+))?', output)
    if not match:
        return 0
    major, minor = int(match[1]), int(match[2] or 0)
    return minor if major == 1 else major  # Java 8 reports itself as 1.8


def find_java() -> str:
    candidates = [os.environ.get("JAVA"), "java"]
    if os.environ.get("JAVA_HOME"):
        candidates.insert(1, str(Path(os.environ["JAVA_HOME"]) / "bin" / "java"))
    if platform.system() == "Darwin":
        home = subprocess.run(["/usr/libexec/java_home", "-v", f"{MIN_JAVA}+"], capture_output=True, text=True)
        if home.returncode == 0:
            candidates.append(str(Path(home.stdout.strip()) / "bin" / "java"))
    for java in filter(None, candidates):
        try:
            if _java_version(java) >= MIN_JAVA:
                return java
        except OSError:
            continue
    sys.exit(f"The GTFS validator needs Java {MIN_JAVA} or newer. Set JAVA to its java binary.")


def validate(city: str, java: str) -> dict[str, list[tuple[str, int]]]:
    """Notice codes and counts by severity for one city's feed."""
    work = CACHE / "gtfs"
    work.mkdir(parents=True, exist_ok=True)
    feed, report = work / f"{city}.zip", work / f"{city}-report"
    feed.write_bytes(export_city(city))
    subprocess.run(
        [java, "-jar", str(JAR), "--input", str(feed), "--output_base", str(report),
         "--country_code", "ph", "--skip_validator_update"],
        check=True, capture_output=True,
    )
    notices: dict[str, list[tuple[str, int]]] = {"ERROR": [], "WARNING": [], "INFO": []}
    for notice in json.loads((report / "report.json").read_text())["notices"]:
        notices[notice["severity"]].append((notice["code"], notice["totalNotices"]))
    return notices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", action="append", choices=sorted(CITY_METADATA), help="Repeat for several; default every city")
    args = parser.parse_args()
    java = find_java()
    if not JAR.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {VALIDATOR_URL}")
        urlretrieve(VALIDATOR_URL, JAR)
    failed = False
    for city in args.city or CITY_METADATA:
        notices = validate(city, java)
        failed |= bool(notices["ERROR"])
        summary = "; ".join(
            f"{severity} " + ", ".join(f"{code} ×{count}" for code, count in found)
            for severity, found in notices.items() if found
        )
        print(f"{city}: {summary or 'no notices'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
