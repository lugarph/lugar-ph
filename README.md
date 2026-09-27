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
| `status` | string | yes | Where the geometry came from: `inferred_from_lptrp_anchors`, `inferred_from_official_route_structure`, or `archived_dotc_gtfs_shape`. |
| `distance_km` | number | yes | Length of the drawn geometry. |
| `planned_length_km` | number or null | no | Length stated in the published route plan. |
| `source_url` | string | no | Document the line comes from. Defaults to the city's source. |
| `anchors` | array | yes | Named landmarks along the line, in riding order (see below). |

### Anchors

| Property | Type | Meaning |
| --- | --- | --- |
| `id` | string | Slug for the landmark. |
| `name` | string | Place name riders know (`Ayala`, `Burgos Market`). Names of three letters or fewer are shown in capitals (`SM`). Names containing `endpoint` are ignored. |
| `lng`, `lat` | number | Position in WGS84. |

Anchors do three things. They name stops ("Get off near SM"), they give each ride its direction ("toward Libertad" is the first or last anchor), and they feed instant search suggestions.

### Geometry rules

- Coordinates are `[lng, lat]` in WGS84 and follow the roads the jeep drives.
- Points run in riding order, starting at the first anchor. Keep consecutive points under 500 m apart.
- An open line (start and end more than 500 m apart) is assumed to run both ways along the same roads.
- A closed loop (it ends within 500 m of where it starts) is a one-way route. It is only ridden in the order the points are drawn.

### How the planner reads it

Like an OSMnx street graph, the planner turns the lines into nodes and edges when the app starts:

| Nodes (stops) | |
| --- | --- |
| `line`, `stop` | Line and position along it. A stop is placed every 100 m of geometry. |
| `x`, `y` | Longitude and latitude. |
| `km` | Distance along the line from its first point. |

| Edges | Connects | Weight |
| --- | --- | --- |
| ride | Stops on the same line, in either direction for open lines and forward only for loops. Rides are at least 250 m. | ride km |
| transfer | A stop and the nearest stop of every other line within 320 m | walk km × 3 + 2 |
| access | Each pin and the nearest stop of every line within 750 m | walk km × 2.2 |

Any line that passes within 200 m of both ends of a ride is listed as an interchangeable jeep for that ride. [docs/DETAILS.md](docs/DETAILS.md) explains the search itself.

## Contributing route data

1. **Fix or add a line.** Edit the city's GeoJSON in [geojson.io](https://geojson.io), QGIS, or JOSM. Trace the roads the jeep actually takes, in riding order, and add anchors for the landmarks riders use.
2. **Or change the anchors and regenerate.** Bacolod, Iloilo, and Tacloban geometry is generated from anchors by [`scripts/build_route_network.py`](scripts/build_route_network.py) and [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py). Change the anchors there and rerun the script. Rerunning overwrites hand edits to those cities' files.
3. **New Bacolod lines** also need an entry in `ROUTES` in [`route_catalog.py`](route_catalog.py).
4. **Run `pytest`.** If you added or removed lines, update the expected line counts in `tests/test_route_catalog.py`.
5. **Open a pull request** that says what changed and how you know: a published route plan, a photo of the signboard, or a ride you took.

Sources and known limitations are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
