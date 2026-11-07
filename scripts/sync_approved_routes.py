"""Copy the currently published database state into checked-in GeoJSON files.

Use --site and admin login, or set DATABASE_URL for direct database access.
Review the Git diff in data/ and commit it there; this script never pushes or
changes approval history.

An approved line in the database overrides the checked-in file, so a later fix to
that line in the routes repo wouldn't show. Once the sync is committed and that
routes commit is deployed, run --prune against the database to retire the
publications the files now match. Revisions are kept, so rollback still works.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from live_network import merged_network
from models import RoutePublication, SessionLocal
from transit_network import NETWORK_FILES

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "tools"))
from routeformat import dumps_network  # noqa: E402


def prune_publications(session, cities: list[str], check: bool = False) -> tuple[list[str], list[str]]:
    """Retire publications the checked-in files have caught up with.

    Returns (retired, kept). A publication that still differs from the file is kept:
    it is either not synced yet, or a fix in the file that it is hiding.
    """
    retired, kept = [], []
    for city in cities:
        files = {feature["properties"]["id"]: feature
                 for feature in json.loads(NETWORK_FILES[city].read_text(encoding="utf-8"))["features"]}
        for item in session.scalars(select(RoutePublication).where(RoutePublication.city == city)).all():
            published = json.loads(item.feature_json) if item.feature_json else None
            label = f"{city}/{item.route_slug}"
            if files.get(item.route_slug) == published:
                retired.append(label)
                if not check:
                    session.delete(item)
            else:
                kept.append(label)
    if not check:
        session.commit()
    return retired, kept


def remote_networks(site: str, username: str, cities: list[str]):
    site = site.rstrip("/")
    parsed = urlparse(site)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise ValueError("--site must be an HTTPS site origin, such as https://lugar.ph")
    password = getpass.getpass("Admin password: ")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    login = Request(
        f"{site}/api/admin/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json", "Origin": site},
        method="POST",
    )
    with opener.open(login, timeout=30) as response:
        if json.load(response).get("username") != username:
            raise ValueError("Admin sign-in failed")
    for city in cities:
        with opener.open(f"{site}/api/admin/export-network?{urlencode({'city': city})}", timeout=30) as response:
            yield city, json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", choices=sorted(NETWORK_FILES), help="Sync only one city")
    parser.add_argument("--check", action="store_true", help="Report pending differences without writing files")
    parser.add_argument("--site", help="Export through a deployed HTTPS site instead of a direct database connection")
    parser.add_argument("--username", default="admin", help="Admin username for --site (default: admin)")
    parser.add_argument("--prune", action="store_true", help="Retire database publications the files now match. "
                        "Run only after this data is deployed. With --check, only report. Needs direct database access")
    args = parser.parse_args()
    cities = [args.city] if args.city else sorted(NETWORK_FILES)
    if args.prune:
        if args.site:
            parser.error("--prune needs direct database access; set DATABASE_URL and omit --site")
        with SessionLocal() as session:
            retired, kept = prune_publications(session, cities, check=args.check)
        for label in retired:
            print(f"{'Would retire' if args.check else 'Retired'}: {label}")
        for label in kept:
            print(f"Differs from the file, kept: {label}")
        print(f"{len(retired)} matched the files, {len(kept)} kept.")
        return 0
    changed = False
    if args.site:
        networks = remote_networks(args.site, args.username, cities)
    else:
        with SessionLocal() as session:
            publications = session.scalars(select(RoutePublication)).all()
            overlays_by_city = {
                city: tuple(sorted((item.route_slug, item.feature_json) for item in publications if item.city == city))
                for city in cities
            }
        networks = ((city, merged_network(city, overlays_by_city[city])) for city in cities)
    try:
        for city, merged in networks:
            path = NETWORK_FILES[city]
            current = json.loads(path.read_text(encoding="utf-8"))
            if current == merged:
                continue
            changed = True
            print(f"{'Pending' if args.check else 'Synced'}: {path.relative_to(Path(__file__).resolve().parents[1])}")
            if not args.check:
                path.write_text(dumps_network(merged), encoding="utf-8")
    except Exception as error:
        print(f"Route sync failed: {error}", file=sys.stderr)
        return 2
    if not changed:
        print("Route GeoJSON is in sync with approved database state.")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
