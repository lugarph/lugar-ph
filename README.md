# Lugar.ph MVP

A mobile-first Bacolod transit preview built with FastAPI, Jinja2, Alpine.js, Tailwind CSS, Leaflet, SQLAlchemy, and Alembic.

## Run with Docker

```sh
docker compose up --build
```

Open <http://localhost:8000>. Compose starts PostgreSQL, applies the initial migration, and serves the app.

## Run locally

Use Python 3.12 or newer. Without `DATABASE_URL`, the app and migrations use a local SQLite file.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python seed_routes.py
uvicorn main:app --reload
```

The `/api/jeepney-routes` endpoint returns the 24 routes listed in the published Bacolod Local Public Transport Route Plan (LPTRP). `/api/routes` accepts `origin_lat`, `origin_lng`, `destination_lat`, and `destination_lng`. It recommends a jeepney only for researched landmark connections around Ayala Malls Capitol Central, SM City Bacolod, and University of St. La Salle. When a researched connection exists, jeepney is the sole recommendation and the map highlights its landmark guide. For other coordinate pairs, it says the jeepney itinerary is unverified and offers walking first, with tricycle as an optional, availability- and fare-variable local ride.

`seed_routes.py` also inserts the published line names and endpoints into the SQLAlchemy `routes` table without duplicating rows on later runs.

The supported trip corridors now use road-aligned GeoJSON in [`data/road_segments.geojson`](data/road_segments.geojson). The supplied LPTRP diagram establishes the line and landmark sequence; OpenStreetMap road geometry was traced through those landmarks for **North Terminal → Ayala → SM on Bata–Libertad** and **SM → La Salle on Shopping–Libertad via La Salle**. The North Terminal trace follows Lacson Street, North Capitol Road, and Gatuslao Street to Ayala; the Shopping trace passes San Sebastian Cathedral, Burgos Market, Triangle Island Plaza, and La Salle Avenue. A two-ride trip combines both lines at SM. The origin picker includes Bacolod North Terminal so this corridor can be previewed. The map shows short dotted access guides between the searched place and the inferred line.

These are **inferred road alignments**, not surveyed jeepney tracks, live navigation, or designated stops. The map marks this clearly. Actual driving direction, road restrictions, service, safe boarding points, and fares still need local confirmation. The remaining 22 published lines are listed in the catalog but do not have street geometry. Jeepney and tricycle fares are left unknown because no current fare for these specific trips is verified. Travel times are estimates. GPS requires HTTPS or localhost in most browsers.

Route sources:

- [Bacolod LPTRP study, Table 1 and Figure 2](https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf) — 24 route names, planned lengths, and schematic line map. The figure itself says detailed roads and one-way streets are omitted. The user also supplied a readable copy of this route map and confirmed the Ayala boarding area and Shopping–La Salle landmark sequence.
- [OpenStreetMap](https://www.openstreetmap.org/copyright) — street geometry for the two inferred trip traces, routed through the map's landmarks with the public OSRM service and saved locally as GeoJSON.
- [Bacolod City route notice](https://bacolodcity.gov.ph/updated-routes-under-the-local-public-transport-route-plan-lptrp/) — the 2023 simulation routes; the notice calls the exercise temporary.
- [Bacolod City's 2025 LPTRP consultation](https://bacolodcity.gov.ph/bacolod-city-holds-local-public-transport-route-plan-lptrp-public-consultation-2025/) — evidence the plan continues to be reviewed.
- [Local Ayala–SM–La Salle trip account](https://www.reddit.com/r/LasalleBacolod/comments/1vsc3k8/jeep_to_ride_from_ayala/) — corroborates the Bata–Libertad and Shopping–La Salle transfer used by the limited trip matcher.

## Next data step

Survey active services and riding directions, validate the two road traces, then map the remaining LPTRP lines. Add PostGIS geometry columns with GeoAlchemy2 and query routes near both endpoints. Expand the matcher only after validating each direction and transfer point.
