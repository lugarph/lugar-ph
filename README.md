# Lugar.ph MVP

A mobile-first Bacolod transit preview built with FastAPI, Jinja2, Alpine.js, Tailwind CSS, Leaflet, SQLAlchemy, and Alembic.

## Run with Docker

```sh
docker compose up --build
```

Open <http://localhost:8000>. Compose starts PostgreSQL, applies the migrations, and serves the app.

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

The **Jeepney routes** tab displays all 24 planned LPTRP corridors dynamically on a geographic Leaflet map. Each colored line can be selected from the map or searchable directory. Each line has public community notes stored in the `route_comments` table. Notes are explicitly unverified; the MVP has no moderation dashboard or user accounts. The comment API is `GET/POST /api/jeepney-routes/{route_slug}/comments`; posting has basic length checks, a honeypot, and a short per-client cooldown. Public deployment should add moderation, stronger abuse controls, and a privacy policy.

Users can tap the Leaflet map to pin either the origin or destination. Recent places remain as one-tap shortcuts. The map uses the [OSM tile service](https://operations.osmfoundation.org/policies/tiles/) and its required attribution; pinning does not call a geocoder.

`/api/jeepney-routes` returns the 24 planned lines, and `/api/jeepney-network` returns their road-aligned GeoJSON. `/api/routes` accepts `origin_lat`, `origin_lng`, `destination_lat`, and `destination_lng`. It searches the complete inferred network, walks up to 750 meters from each pin to the nearest useful corridor, and can plan either one ride or two rides with one short walking transfer. The selected itinerary draws its walking access links, jeepney geometry, and transfer on the map. When no useful corridor is close enough, the app offers walking first and tricycle as an optional, availability- and fare-variable local ride.

`seed_routes.py` also inserts the published line names and endpoints into the SQLAlchemy `routes` table without duplicating rows on later runs.

The network is stored in [`data/jeepney_network.geojson`](data/jeepney_network.geojson). The supplied LPTRP diagram establishes each line's topology and named landmark sequence. Those places were triangulated against OpenStreetMap, then [`scripts/build_route_network.py`](scripts/build_route_network.py) routed the anchor sequences over OSM roads with OSRM and cached the result locally. Runtime route planning does not depend on OSRM or a geocoder. The earlier hand-reviewed corridor fragments remain in [`data/road_segments.geojson`](data/road_segments.geojson) as research provenance.

These are **inferred road alignments**, not surveyed jeepney tracks, live navigation, or designated stops. The map marks this clearly. Actual turns, driving direction, service, safe boarding points, and fares still need local confirmation. Jeepney and tricycle fares are left unknown because no current fare for these specific trips is verified. Travel times are estimates. GPS requires HTTPS or localhost in most browsers.

Route sources:

- [Bacolod LPTRP study, Table 1 and Figure 2](https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf) — 24 route names, planned lengths, and schematic line map. The figure itself says detailed roads and one-way streets are omitted. The user also supplied a readable copy of this route map and confirmed the Ayala boarding area and Shopping–La Salle landmark sequence.
- [OpenStreetMap](https://www.openstreetmap.org/copyright) — landmark positions, map tiles, and road geometry for the inferred network; OSRM was used at build time and the result is saved locally as GeoJSON.
- [Bacolod City route notice](https://bacolodcity.gov.ph/updated-routes-under-the-local-public-transport-route-plan-lptrp/) — the 2023 simulation routes; the notice calls the exercise temporary.
- [Bacolod City's 2025 LPTRP consultation](https://bacolodcity.gov.ph/bacolod-city-holds-local-public-transport-route-plan-lptrp-public-consultation-2025/) — evidence the plan continues to be reviewed.
- [Local Ayala–SM–La Salle trip account](https://www.reddit.com/r/LasalleBacolod/comments/1vsc3k8/jeep_to_ride_from_ayala/) — corroborates the Bata–Libertad and Shopping–La Salle connection around the city center.

## Next data step

Survey active services and riding directions, then correct each inferred line from community evidence. Add PostGIS geometry columns with GeoAlchemy2 and replace the in-memory nearest-line search with `ST_DWithin` and indexed route-segment queries. Add moderation before enabling community notes in a public deployment.
