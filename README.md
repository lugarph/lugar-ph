# Lugar.ph

Jeepney directions for Baguio, Naga, Bacolod, Iloilo, Cebu, Tacloban, Cagayan de Oro, and Davao. Each city has its own page, such as `/bacolod` or `/cdo`, and `/` introduces the app and lets riders pick a city. Pick a start and a destination; Lugar.ph walks you to a nearby line and plans up to three jeepney rides, naming the signboards to look for, where to get off, and the estimated fare.

Built with FastAPI, Alpine.js, Tailwind CSS, and Leaflet.

## Run it

```sh
docker compose up --build
```

Or locally with Python 3.12+ (uses SQLite unless `DATABASE_URL` is set):

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head && python seed_routes.py
uvicorn main:app --reload
```

Open <http://localhost:8000>. Run the tests with `pytest`.

## Run it for your city

Lugar.ph is free to copy for any city with jeepneys or other fixed-route transit. To make your own:

1. **Fork this repo** on GitHub.
2. **Get your city's routes** into one GeoJSON file, `data/<city>_jeepney_network.geojson`, in the [format below](#route-data).
   - **Check OpenStreetMap first.** Many Philippine cities already have jeepney routes mapped. Run this in [overpass turbo](https://overpass-turbo.eu/) over your city:
     ```text
     relation["type"="route"]["route"~"bus|share_taxi|jeepney|minibus"]({{bbox}});
     out geom;
     ```
     Export the result as GeoJSON, keep one circuit per line (out and back, in riding order), and add the line properties. Or list the relation ids in `OSM_LINES` in [`scripts/build_city_networks.py`](scripts/build_city_networks.py) to import them the way Baguio is.
   - **If your city publishes its route plan street by street** (most LPTRPs list each route's streets in order), save the descriptions in `data/sources/<city>/route_plan.json` and the terminals in `data/sources/<city>/places.json`, then add the city to `CITIES` in [`scripts/build_city_networks.py`](scripts/build_city_networks.py). It draws each line through the corners where its streets meet, as it does for Cagayan de Oro and Naga. Check `data/sources/<city>/build_report.json` for streets it couldn't place and lines whose drawn length is far from the published one.
   - **Otherwise draw them** in [geojson.io](https://geojson.io), tracing each route the way the jeep drives it.
3. **Add the city** in three places:
   - `CITY_METADATA` and `NETWORK_FILES` in [`transit_network.py`](transit_network.py): region, name, map centre, zoom, route source, and the data file. The key is the city's address: `cdo` serves `/cdo`.
   - `CITY_VIEWBOXES` in [`osm_services.py`](osm_services.py): the bounding box that place search stays inside.
   - `cityProfiles` in [`templates/index.html`](templates/index.html): the default start point and a few popular places.

   Remove cities you don't need from the same places. Other spellings of a city's address go in `CITY_ALIASES` in [`main.py`](main.py). With only one city, you can have `home()` in `main.py` redirect `/` to it.
4. **Name your app to OpenStreetMap.** Set `LUGAR_USER_AGENT` to your app's name and a contact URL or email, such as `MyCityJeeps/1.0 (https://github.com/you/your-fork)`. The free search, walking, and map-tile services ask apps to identify themselves and only allow light use.
5. **Check the local rules.** The fare estimate (`FARE_*`) and riding speeds are near the top of the planner section in [`transit_network.py`](transit_network.py). The fares follow the LTFRB regular jeepney fare.
6. **Run `pytest`,** and update the expected city and line counts in `tests/test_route_catalog.py`.
7. **Deploy.**
   - **Vercel:** [![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fandrewnyu%2Flugar-ph), or run `vercel deploy` in your fork. It finds the FastAPI app on its own.
   - **Anywhere with Docker:** `docker compose up --build`.

   Community notes need a Postgres database set in `DATABASE_URL` to be kept; without one, a Vercel deployment keeps them only temporarily. Run `alembic upgrade head` against it once.

## Community route suggestions

Open a city's **Jeepney routes** screen and select **Suggest a route**. Riders can draw a missing line, or select a mapped line and choose **Suggest correction** to edit its name, number, vehicle type, or path. The map editor lets them select and drag a point, insert one in the middle, extend the path, delete a point, undo, and reset. Submissions include an explanation and an optional evidence link. Other visitors can support or remove support for a pending suggestion once per browser. Browser cookies are used for this lightweight voting; it is not identity verification.

Suggestions are stored in the database with `pending` status and are **not** used by the route planner. Set `DATABASE_URL` to persistent Postgres for production and run `alembic upgrade head` to create the proposal and vote tables. Without persistent storage, serverless submissions and votes can disappear when an instance is recycled.

Reviewers sign in at `/admin` (also available at `/admin/routes`). There is no link to this page in public navigation. Set `ROUTE_ADMIN_USERNAME` and a private `ROUTE_ADMIN_PASSWORD_HASH` environment variable. Run `python scripts/hash_admin_password.py` locally to create a salted hash; enter the password only at the sign-in page, never in source control. The admin page shows pending suggestions, support counts, evidence links, and the proposed map path. A review note is required to accept or reject. Sessions are stored in the database and expire after eight hours; signing out revokes the session. The older `ROUTE_REVIEW_TOKEN` API option remains available for scripted reviews if configured.

Approval publishes the proposed geometry to the public map and trip planner immediately. Every route starts with a saved baseline revision; approvals and rollbacks add immutable revisions. The admin history view can restore any prior revision, including removing a newly approved route. Rejection leaves the public map alone. The editor's straight line segments are **not** automatically snapped to roads, so reviewers must inspect the path before publishing. Approved community paths are labeled as such rather than presented as official or OpenStreetMap geometry.

The database is the live source for approved revisions. To keep permanent changes in Git, run `.venv/bin/python scripts/sync_approved_routes.py --site https://www.lugarph.app --check` locally. The command prompts for the admin password and uses a protected export endpoint. Run it again without `--check` to update the city's GeoJSON file. Alternatively, load the production `DATABASE_URL` from your secret store and omit `--site` for a direct database export. Review `git diff -- data/`, run the tests, and commit the data change. The script never commits or pushes for you. A later admin rollback remains authoritative even if the now-removed route is in a checked-in file; run the sync command again to put the rollback into Git. Run Alembic migration `0005` before deploying this version to an existing database.

## Route data

Each city's jeepney network is one GeoJSON file in `data/`:

| City | File | Lines | Mapped in OpenStreetMap |
| --- | --- | --- | --- |
| Bacolod | `jeepney_network.geojson` | 24 | 11 |
| Iloilo | `iloilo_jeepney_network.geojson` | 25 | 10 |
| Cebu | `cebu_jeepney_network.geojson` | 64 | 28 |
| Tacloban | `tacloban_jeepney_network.geojson` | 19 | 6 |
| Baguio | `baguio_jeepney_network.geojson` | 45 | 45 |
| Naga | `naga_jeepney_network.geojson` | 11 | 0 |
| Cagayan de Oro | `cdo_jeepney_network.geojson` | 63 | 0 |
| Davao | `davao_jeepney_network.geojson` | 8 | 2 |

The file is a `FeatureCollection` with one `LineString` feature per jeepney line:

```json
{
  "type": "Feature",
  "geometry": { "type": "LineString", "coordinates": [[122.95053, 10.70964], [122.95061, 10.70941]] },
  "properties": {
    "id": "banago-libertad",
    "number": 1,
    "name": "Banago – Libertad Loop",
    "color": "#ef6f77",
    "status": "inferred_from_lptrp_anchors",
    "distance_km": 12.94,
    "anchors": [
      { "id": "banago_school", "name": "Banago School", "lng": 122.95053, "lat": 10.70964 },
      { "id": "libertad", "name": "Libertad", "lng": 122.94974, "lat": 10.66012 }
    ]
  }
}
```

### Line properties

| Property | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | Stable slug, unique across all cities. Community notes are stored against it, so don't rename it. |
| `number` | string or int | yes | Route number or code shown on the jeep (`1`, `04L`), unique within the city. |
| `name` | string | yes | Route name as `Terminal – Terminal`, with an en dash. The signboard shown to riders drops `via …` and a trailing `Loop`. |
| `color` | hex string | yes | The line's colour on chips, directions, and maps. Pick one distinct from lines sharing its roads. Light colours get dark text automatically. |
| `status` | string | yes | Where the geometry came from. `osm_route_relation` (mapped street by street in OpenStreetMap) and `archived_dotc_gtfs_shape` are traced paths. `inferred_from_lptrp_anchors` and `inferred_from_official_route_structure` are estimated from route plans; riders see a note on those. |
| `mode` | string | no | `jeepney` (default) or `uv_express`. UV Express rides get no fare estimate. |
| `distance_km` | number | yes | Length of the drawn geometry. |
| `planned_length_km` | number or null | no | Length stated in the published route plan. |
| `source_url` | string | no | Document the line comes from. Defaults to the city's source. |
| `anchors` | array | yes | Named landmarks from the first terminal to the far terminal, in riding order (see below). |
| `return_anchors` | array | no | Landmarks passed only on the way back, when the return uses other streets. |
| `osm_relations` | array of ints | no | OpenStreetMap route relations the geometry was imported from, in riding order. |
| `attribution` | string | no | Required credit for imported geometry, such as `© OpenStreetMap contributors, ODbL`. |

### Anchors

| Property | Type | Meaning |
| --- | --- | --- |
| `id` | string | Slug for the landmark. |
| `name` | string | Place name riders know (`Ayala`, `Burgos Market`). Names of three letters or fewer are shown in capitals (`SM`). Names containing `endpoint` are ignored. |
| `lng`, `lat` | number | Position in WGS84. |

Anchors do three things. They name stops ("Get off near SM"), they give each ride its direction, and they feed instant search suggestions. The direction reads "toward" the last anchor on the way out and "toward" the first anchor on the way back.

### Geometry rules

Jeeps don't run both ways on the same roads, so every line is drawn one way, as it is driven:

- Coordinates are `[lng, lat]` in WGS84 and follow the roads the jeep drives.
- Draw the full circuit: start at the first anchor, drive out to the far terminal, and come back to the start. The line should end within 500 m of where it begins.
- Draw the way back as it is really driven. Main roads are often shared, but side streets, one-way pairs, and detours differ.
- Keep consecutive points under 500 m apart.
- The planner only rides a line in the order its points are drawn. On a circuit, a ride may continue past the start, the way a jeep carries on through its terminal.
- A line that doesn't come back to its start is treated as one-way and ends at its last point.

### How the planner reads it

Like an OSMnx street graph, the planner turns the lines into nodes and edges when the app starts:

| Nodes (stops) | |
| --- | --- |
| `line`, `stop` | Line and position along it. A stop is placed every 100 m of geometry. |
| `x`, `y` | Longitude and latitude. |
| `km` | Distance along the line from its first point. |

| Edges | Connects | Weight |
| --- | --- | --- |
| ride | A stop and any stop after it on the same line, forward only. Rides are at least 250 m. | ride km |
| transfer | A stop and the nearest stop on each pass of every other line within 320 m | walk km × 3 + 2 |
| access | Each pin and the nearest stop on each pass of every line within 750 m | walk km × 2.2 |

A circuit often passes the same spot twice, once going and once coming back, sometimes on parallel streets. Each pass heads a different way, so each counts as its own boarding option.

## How trips are planned

The planner lives in [`transit_network.py`](transit_network.py). It runs a round-based search, a simplified version of [RAPTOR](https://www.microsoft.com/en-us/research/publication/round-based-public-transit-routing/), over the stop graph above. Jeepneys run on frequency rather than a timetable, so it minimises a cost measured in ride-kilometres rather than time:

```text
cost = ride km + 2.2 × walk to and from the pins + 3 × walk between lines + 2 per extra ride
```

1. **Board.** Walk from the start pin to the nearest stop on each pass of every line within 750 m. Each is a boarding candidate, costed by its walk.
2. **Ride (round r).** Scan each line that has candidates once, forward, keeping a running minimum. That gives the cheapest cost of getting off at every later stop with exactly *r* rides. Rides shorter than 250 m don't count. On a circuit, the scan runs a second lap so a ride can pass the terminal.
3. **Transfer.** From every stop you could get off at, walk up to 320 m to the other lines. Those become the boarding candidates for round r + 1.
4. **Finish.** After each round, walk from the nearest stops to the destination pin. That keeps the cheapest trip with one, two, and three rides.
5. **Less walking.** Run the search again with walking weighted four times as heavily. This surfaces trips that walk less.
6. **Street walking.** Replace every candidate's straight-line walks with street distances from one [OSRM](https://project-osrm.org/) table request. If the router takes more than 3 seconds, straight-line distance × 1.25 is used.
7. **Choose.**
   - **Recommended:** the trip with the fewest rides whose cost is within 30% of the cheapest.
   - **Alternatives:** up to two more, each of which must:
     - be faster, walk at least 150 m less, or have fewer transfers;
     - cost no more than 1.8 × the recommended trip;
     - not be beaten on rides, walking, and time together by a trip already shown.
8. **Group jeeps.** Any other line that passes within 200 m of both ends of a ride, going forward without a long detour, is listed as an interchangeable jeep for that ride. A trip that only swaps in one of those jeeps is not shown separately.
9. **Estimate.**
   - **Time:** rides at 12 km/h, walks at 4.8 km/h, 6 minutes to board, and 8 minutes per transfer.
   - **Fare:** the LTFRB regular jeepney fare for each ride. UV Express rides show "fare on board".

## Contributing route data

1. **Best: map it in OpenStreetMap.** Add or fix the line's public-transport route relations in OSM (one per direction, following the [PTv2 scheme](https://wiki.openstreetmap.org/wiki/Public_transport)). Then list the relation ids in `OSM_ROUTES`: in [`scripts/build_route_network.py`](scripts/build_route_network.py) for Bacolod (rerun it with the line's id), in [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py) for Iloilo, Cebu, and Tacloban (rerun it with `--osm-only`), or in `OSM_ROUTES` or `OSM_LINES` in [`scripts/build_city_networks.py`](scripts/build_city_networks.py) for Baguio, Naga, Cagayan de Oro, and Davao. The shared import code is in [`scripts/osm_routes.py`](scripts/osm_routes.py). The fix then helps every OSM-based app too.
2. **Or fix the GeoJSON directly.** Edit the city's file in [geojson.io](https://geojson.io), QGIS, or JOSM. Trace the roads the jeep actually takes, in riding order, and add anchors for the landmarks riders use.
3. **Or change the anchors or street lists and regenerate.** Lines without a mapped path are generated from anchors by [`scripts/build_route_network.py`](scripts/build_route_network.py) and [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py), and from the street lists in `data/sources/` by [`scripts/build_city_networks.py`](scripts/build_city_networks.py).
   - Each line is routed out through its anchors, then back.
   - By default the way back passes the same landmarks in reverse, following one-way streets. If the jeep returns through different landmarks, list them in `RETURN_VIA`.
   - Rerunning a script overwrites hand edits to those cities' files.
4. **New Bacolod lines** also need an entry in `ROUTES` in [`route_catalog.py`](route_catalog.py).
5. **Run `pytest`.** If you added or removed lines, update the expected line counts in `tests/test_route_catalog.py`.
6. **Open a pull request** that says what changed and how you know: a published route plan, a photo of the signboard, or a ride you took.

Sources and known limitations are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Licence

The code is free and open source under the [MIT Licence](LICENSE): use it, change it, run your own version, or build on it commercially, as long as you keep the copyright notice.

### Route data

Geometry imported from OpenStreetMap is © OpenStreetMap contributors and available under the [Open Database Licence](https://opendatacommons.org/licenses/odbl/). Because every city's file in `data/` includes it, those files are shared under the ODbL too. Keep the credit when you reuse it.
