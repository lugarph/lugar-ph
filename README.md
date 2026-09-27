# Lugar.ph MVP

A mobile-first jeepney route preview for Bacolod, Iloilo, Cebu, and Tacloban, built with FastAPI, Jinja2, Alpine.js, Tailwind CSS, Leaflet, SQLAlchemy, and Alembic.

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

The city switcher loads 24 Bacolod lines, 25 Iloilo lines, 64 Cebu route-code shapes, or 19 Tacloban PUJ lines. The **Jeepney routes** tab draws the selected city's network dynamically on Leaflet. Each colored line can be selected from the map or searchable directory. Each line has public community notes stored in the `route_comments` table. Notes are explicitly unverified; the MVP has no moderation dashboard or user accounts. The comment API is `GET/POST /api/jeepney-routes/{route_slug}/comments`; posting has basic length checks, a honeypot, and a short per-client cooldown. Public deployment should add moderation, stronger abuse controls, and a privacy policy.

Users can search for both their origin and destination or tap the Leaflet map to place either pin. Place search uses a deliberate submit action rather than autocomplete, is bounded to the selected city, and is cached and rate limited through the backend. Recent places remain as one-tap shortcuts.

`/api/cities` lists supported cities. `/api/places` performs city-bounded place search. `/api/jeepney-routes` and `/api/jeepney-network` accept a `city` query parameter. `/api/routes` accepts `city`, `origin_lat`, `origin_lng`, `destination_lat`, and `destination_lng`. It searches that city's jeepney network, walks up to 750 meters from each pin to a useful corridor, and can plan one ride or two rides with one short walking transfer. `/api/walking-route` adds street-level pedestrian geometry and turn steps between the pins and jeepney corridors. The directions view combines those walking legs with the jeepney legs and reports total minutes and kilometers. Lugar.ph recommends jeepneys only; an unmapped trip returns no substitute transport mode.

The MVP uses the public [Nominatim search API](https://operations.osmfoundation.org/policies/nominatim/) and the FOSSGIS [OSM routing service](https://routing.openstreetmap.de/about.html). Both adapters enforce a one-request-per-second interval and keep a small in-process cache. These public services are suitable only for low-volume evaluation; deploy a self-hosted or contracted geocoder and pedestrian router before production traffic.

`seed_routes.py` also inserts the published line names and endpoints into the SQLAlchemy `routes` table without duplicating rows on later runs.

Generated networks are stored in `data/*_jeepney_network.geojson`. [`scripts/build_route_network.py`](scripts/build_route_network.py) builds Bacolod, while [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py) builds Iloilo and Tacloban from official route-structure anchors and converts Cebu's archived DOTC GTFS shapes. Runtime route planning does not depend on OSRM, GTFS servers, or a geocoder.

These are route references, not live navigation or guaranteed designated stops. Bacolod, Iloilo, and Tacloban street geometry is inferred from published route structures and OSM roads. Cebu geometry comes from an archived 2017 DOTC GTFS feed and is filtered to codes in a current 74-line directory that explicitly includes active and inactive lines. Actual turns, driving direction, active service, safe boarding points, and fares still need local confirmation. GPS requires HTTPS or localhost in most browsers.

Route sources:

- [Bacolod LPTRP study, Table 1 and Figure 2](https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf) — 24 route names, planned lengths, and schematic line map. The figure itself says detailed roads and one-way streets are omitted. The user also supplied a readable copy of this route map and confirmed the Ayala boarding area and Shopping–La Salle landmark sequence.
- [Iloilo LTFRB Memorandum Circular 2023-036](https://ilonggoengineer.com/wp-content/uploads/2025/04/mc-2023-036.pdf) — 25 approved PUJ route structures and street sequences.
- [Tacloban LTFRB Memorandum Circular 2024-035](https://www.scribd.com/document/780942237/LTFRB-MC-2024-035) and [Tacloban ordinance directory](https://tacloban.gov.ph/ordinance/page/5/) — 19 rationalized PUJ routes plus one non-PUJ P2P route; the P2P route is excluded.
- [Transitland Cebu DOTC feed record](https://www.transit.land/feeds/f-wcb4-cebu~dotc) — archived Cebu GTFS route shapes, with service dates ending in 2017.
- [Cebu Bus Spotters route directory](https://sites.google.com/view/cebubusspotters/cbs-virtual-library/cebu-jeepney-route-guide/cebu-city-jeepney-routes) — 74 documented codes used to filter the archived GTFS; the directory notes that active and inactive routes are both included.
- [OpenStreetMap](https://www.openstreetmap.org/copyright) — landmark positions, place search, map tiles, pedestrian directions, and road geometry for the inferred network; jeepney corridor geometry is saved locally as GeoJSON.
- [Bacolod City route notice](https://bacolodcity.gov.ph/updated-routes-under-the-local-public-transport-route-plan-lptrp/) — the 2023 simulation routes; the notice calls the exercise temporary.
- [Bacolod City's 2025 LPTRP consultation](https://bacolodcity.gov.ph/bacolod-city-holds-local-public-transport-route-plan-lptrp-public-consultation-2025/) — evidence the plan continues to be reviewed.
- [Local Ayala–SM–La Salle trip account](https://www.reddit.com/r/LasalleBacolod/comments/1vsc3k8/jeep_to_ride_from_ayala/) — corroborates the Bata–Libertad and Shopping–La Salle connection around the city center.

## Next data step

Survey active services and riding directions, then correct each inferred line from community evidence. Add PostGIS geometry columns with GeoAlchemy2 and replace the in-memory nearest-line search with `ST_DWithin` and indexed route-segment queries. Add moderation before enabling community notes in a public deployment.
