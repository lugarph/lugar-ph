# Lugar.ph

Jeepney directions for Bacolod, Iloilo, Cebu, and Tacloban. Pick a start and a destination; Lugar.ph walks you to a nearby line and plans up to three jeepney rides, naming the signboards to look for, where to get off, and the estimated fare.

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

## Route data

Each city's jeepney network is one GeoJSON file in `data/`:

| City | File | Lines |
| --- | --- | --- |
| Bacolod | `jeepney_network.geojson` | 24 |
| Iloilo | `iloilo_jeepney_network.geojson` | 25 |
| Cebu | `cebu_jeepney_network.geojson` | 64 |
| Tacloban | `tacloban_jeepney_network.geojson` | 19 |

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

1. **Best: map it in OpenStreetMap.** Add or fix the line's public-transport route relations in OSM (one per direction, following the [PTv2 scheme](https://wiki.openstreetmap.org/wiki/Public_transport)). Then list the relation ids in `OSM_ROUTES` in [`scripts/build_route_network.py`](scripts/build_route_network.py) and rerun it with the line's id. The fix then helps every OSM-based app too. Eleven Bacolod lines already come from OSM.
2. **Or fix the GeoJSON directly.** Edit the city's file in [geojson.io](https://geojson.io), QGIS, or JOSM. Trace the roads the jeep actually takes, in riding order, and add anchors for the landmarks riders use.
3. **Or change the anchors and regenerate.** Lines without a mapped path are generated from anchors by [`scripts/build_route_network.py`](scripts/build_route_network.py) and [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py).
   - Each line is routed out through its anchors, then back.
   - By default the way back passes the same landmarks in reverse, following one-way streets. If the jeep returns through different landmarks, list them in `RETURN_VIA`.
   - Rerunning a script overwrites hand edits to those cities' files.
4. **New Bacolod lines** also need an entry in `ROUTES` in [`route_catalog.py`](route_catalog.py).
5. **Run `pytest`.** If you added or removed lines, update the expected line counts in `tests/test_route_catalog.py`.
6. **Open a pull request** that says what changed and how you know: a published route plan, a photo of the signboard, or a ride you took.

Sources and known limitations are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

### Licence of the route data

Geometry imported from OpenStreetMap is © OpenStreetMap contributors and available under the [Open Database Licence](https://opendatacommons.org/licenses/odbl/). Because `data/jeepney_network.geojson` includes it, that file is shared under the ODbL too. Keep the credit when you reuse it.
