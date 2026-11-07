# Lugar.ph

Jeepney directions for Baguio, Naga, Bacolod, Iloilo, Cebu, Tacloban, Cagayan de Oro, and Davao. Each city has its own page, such as `/bacolod` or `/cdo`, and `/` introduces the app and lets riders pick a city. Pick a start and a destination; Lugar.ph walks you to a nearby line and plans up to three jeepney rides, naming the signboards to look for, where to get off, and the estimated fare.

Built with FastAPI, Alpine.js, Tailwind CSS, and Leaflet.

## Run it

The routes live in their own repo, [lugar-ph-routes](https://github.com/lugarph/lugar-ph-routes), which `data/` pins to an exact commit. Clone with submodules:

```sh
git clone --recurse-submodules https://github.com/lugarph/lugar-ph.git
cd lugar-ph
docker compose up --build
```

In a clone you already have, run `git submodule update --init`.

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

1. **Fork this repo and [the routes repo](https://github.com/lugarph/lugar-ph-routes)** on GitHub, and point `url` in `.gitmodules` at your routes fork.
2. **Get your city's routes** into one GeoJSON file, `data/<city>_jeepney_network.geojson`, in the [route format](https://github.com/lugarph/lugar-ph-routes#files). Commit it in your routes fork.
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

The database is the live source for approved revisions. To keep permanent changes in Git, run `.venv/bin/python scripts/sync_approved_routes.py --site https://www.lugarph.app --check` locally. The command prompts for the admin password and uses a protected export endpoint. Run it again without `--check` to update the city's GeoJSON file. Alternatively, load the production `DATABASE_URL` from your secret store and omit `--site` for a direct database export. Review the diff inside `data/`, run the tests, commit and push it in the routes repo, then commit the new `data` pointer here. The script never commits or pushes for you. A later admin rollback remains authoritative even if the now-removed route is in a checked-in file; run the sync command again to put the rollback into Git. Once a sync is deployed, load the production `DATABASE_URL` and run `.venv/bin/python scripts/sync_approved_routes.py --prune` (add `--check` first to preview). This retires the database versions the files now match. Otherwise an approved line keeps overriding the file, and a later fix to it in the routes repo won't show. Revisions are kept, so rollback still works. Run Alembic migration `0005` before deploying this version to an existing database.

## Route data

Each city's network is one GeoJSON file in `data/`, which is the [lugar-ph-routes](https://github.com/lugarph/lugar-ph-routes) repo pinned to a commit. Its README has the file format and the rules each line follows, and [SOURCES.md](https://github.com/lugarph/lugar-ph-routes/blob/main/SOURCES.md) says where each city's lines come from.

To take new routes, update the pin, run the tests, and commit it:

```sh
git -C data pull origin main
.venv/bin/pytest
git add data
git commit -m "Update routes"
```

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

## GTFS feed

Each city's network is also a static [GTFS](https://gtfs.org/documentation/schedule/reference/) feed at `/<city>/gtfs.zip`, such as `/bacolod/gtfs.zip`. The routes screen links to it. It includes routes approved since the last Git sync. To write one to a file, run `.venv/bin/python scripts/export_gtfs.py --city bacolod --out bacolod-gtfs.zip`. The code is in [`gtfs_export.py`](gtfs_export.py).

Jeepneys are hail-and-ride, with no fixed stops and no timetable. The feed models them this way instead of as scheduled buses:

- **Routes:** one route per line, `route_type` 3 (bus), with `continuous_pickup` and `continuous_drop_off` set to 0, so riders can board and get off anywhere along the route.
- **Stops:** the planner's points every 100 m along each line, plus the far terminal of a circuit. They are not signposted stops. Each stop is named after the nearest landmark ("Near SM City") or by its distance along the line. Stop IDs are `<city>-<line id>-<position>`, so they stay the same between exports unless the line's geometry changes.
- **Trips:** a circuit has one trip out to its far terminal and one back, with the same "toward" headsigns the planner shows. A loop with no known far terminal (most Cebu lines) is one trip. Each trip is timed at the planner's 12 km/h with `timepoint=0`, so times are approximate.
- **Frequencies:** every 10 minutes from 05:00 to 22:00 daily, with `exact_times=0`. **These are assumptions, not observed data.** Change `DEFAULT_HEADWAY_SECONDS` and the service hours if you have counts.
- **Fares:** GTFS fares can't express a per-kilometre fare on a hail-and-ride route without inventing fare zones. So the feed lists only the ₱14 base fare, which covers the first 4 km. Longer rides cost ₱2 more per km. `feed_info.txt` says this too. UV Express routes have no fare.
- **Geometry source:** routes have two non-standard columns. `lugar_status` holds the line's `status` from the GeoJSON: `inferred_*` lines were estimated from route plans, while the others were traced. `lugar_source_url` is the source document. `route_desc` explains the status in plain words. `feed_info.txt` has a non-standard `lugar_notes` column with the caveats above.

`scripts/validate_gtfs.py` runs every feed through the [MobilityData GTFS validator](https://github.com/MobilityData/gtfs-validator). It downloads the 40 MB jar into `scripts/.cache/` on first use, which Git ignores, and it needs Java 17 or newer. With validator 8.0.1, no feed has errors. All feeds get an info notice for the three `lugar_*` columns. Baguio and Davao get warnings for route codes longer than 12 characters, because their jeeps are named by destination. Six Cagayan de Oro routes have names that contain their code.

Lugar.ph can't put these lines on Google Maps itself. Google takes transit feeds through its [transit partner programme](https://support.google.com/transitpartners/answer/1111471), which expects the city or the operators to submit and maintain the feed. A city or operator could start from this export, confirm the routes, and replace the assumed headways and hours with real ones.

## Contributing route data

Corrections go to [lugar-ph-routes](https://github.com/lugarph/lugar-ph-routes), which has a local map editor, checks every pull request, and takes reports from people who don't use Git.

To change how routes are generated, use the build scripts here. They write to `data/`, so commit the result in that repo:

1. **Best: map it in OpenStreetMap.** Add or fix the line's public-transport route relations in OSM (one per direction, following the [PTv2 scheme](https://wiki.openstreetmap.org/wiki/Public_transport)). Then list the relation ids in `OSM_ROUTES`: in [`scripts/build_route_network.py`](scripts/build_route_network.py) for Bacolod (rerun it with the line's id), in [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py) for Iloilo, Cebu, and Tacloban (rerun it with `--osm-only`), or in `OSM_ROUTES` or `OSM_LINES` in [`scripts/build_city_networks.py`](scripts/build_city_networks.py) for Baguio, Naga, Cagayan de Oro, and Davao. The shared import code is in [`scripts/osm_routes.py`](scripts/osm_routes.py).
2. **Or change the anchors or street lists and regenerate.** Lines without a mapped path are generated from anchors by [`scripts/build_route_network.py`](scripts/build_route_network.py) and [`scripts/build_additional_city_networks.py`](scripts/build_additional_city_networks.py), and from the street lists in `data/sources/` by [`scripts/build_city_networks.py`](scripts/build_city_networks.py).
   - Each line is routed out through its anchors, then back.
   - By default the way back passes the same landmarks in reverse, following one-way streets. If the jeep returns through different landmarks, list them in `RETURN_VIA`.
   - Rebuilding keeps any line with the status `community_verified`, which is what a correction gets. To rebuild one of those from source, change its status first. Other hand edits are overwritten, and a line removed by hand comes back.
3. **New Bacolod lines** also need an entry in `ROUTES` in [`route_catalog.py`](route_catalog.py).
4. **Run `pytest`.** If lines were added or removed, update the expected line counts in `tests/test_route_catalog.py`.

## Licence

The code is free and open source under the [MIT Licence](LICENSE): use it, change it, run your own version, or build on it commercially, as long as you keep the copyright notice.

### Route data

The routes are in a separate repo, [lugar-ph-routes](https://github.com/lugarph/lugar-ph-routes), under the [Open Database Licence](https://opendatacommons.org/licenses/odbl/), because they include geometry imported from OpenStreetMap, © OpenStreetMap contributors. Keep the credit when you reuse them.
