# Technical details

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/cities` | Supported cities with map centre and zoom. |
| `GET /api/routes?city&origin_lat&origin_lng&destination_lat&destination_lng` | Trip options (see below). |
| `GET /api/places?city&q` | City-bounded place search through Nominatim. Runs only on an explicit search. |
| `GET /api/landmarks?city` | Named anchors along a city's lines, used for instant search suggestions. |
| `GET /api/walking-route?from_lat&from_lng&to_lat&to_lng` | Turn-by-turn walking directions for one walk. |
| `GET /api/jeepney-routes?city` | Line catalogue for the routes tab. |
| `GET /api/jeepney-network?city` | The city's GeoJSON network. |
| `GET/POST /api/jeepney-routes/{id}/comments` | Community notes for a line. |

`/api/routes` returns `options`, with the recommended trip first:

- The recommended trip has a `highlight`, such as `Fastest`, when there are alternatives to compare against.
- Up to two alternatives follow, quickest first. Each has `tags` and a `compared_to_best` breakdown of minutes, walking, transfers, and fare.
- Each ride in `itinerary.legs` gives the `signboard`, the `heading`, and the `board` and `alight` stops with a landmark or street label, plus `ride_minutes`, the `fare_php` estimate, and `also`: other jeeps that serve the same ride.
- When nothing is found, `no_route` says why (`origin_far`, `destination_far`, `both_far`, `no_connection`, or `too_close`) and gives the nearest mapped line to each pin.

## Trip planning

[`transit_network.py`](../transit_network.py) runs a round-based search in the style of RAPTOR over the stop graph described in the README. Round *r* finds the cheapest way to reach every stop using exactly *r* rides, up to three. Each line is scanned once per round in each allowed direction, keeping a running minimum. Jeepneys run by frequency rather than timetable, so the cost is in ride-km equivalents rather than time:

`ride km + 2.2 × walk to and from the pins + 3 × walk between lines + 2 per extra ride`

- A second search that weights walking four times as heavily finds alternatives with less walking.
- Candidates are compared on street walking distances. These come from a single OSRM table request, capped at 3 seconds, with a fallback of straight-line distance × 1.25.
- The recommended trip is the one with the fewest rides whose cost is within 30% of the cheapest.
- An alternative is shown only if it is:
  - faster, has less walking, or has fewer transfers;
  - costs no more than 1.8 × the recommended trip;
  - is not beaten on rides, walking, and time together by an option already shown;
  - is not just the same trip on an interchangeable jeep.
- Time estimates assume 12 km/h riding, 4.8 km/h walking, 6 minutes to board, and 8 minutes per transfer.

## External services

Lugar.ph uses the public [Nominatim](https://operations.osmfoundation.org/policies/nominatim/) geocoder and the FOSSGIS [OSM routing service](https://routing.openstreetmap.de/about.html) for walking. Both adapters send at most one request per second and keep a small in-process cache.

Nominatim forbids search-as-you-type, so the search box filters recent places, popular places, and landmarks locally, and only calls the geocoder when you press Search. These public services suit low-volume evaluation only. Use a self-hosted or contracted geocoder and walking router before real traffic.

Planning trips needs no external service. If the walking router is slow or down, the app falls back to estimates.

## Community notes

Notes are stored in the `route_comments` table. Posting has length checks, a honeypot field, and a short per-client cooldown. There is no moderation dashboard or user accounts yet, so a public deployment needs moderation, stronger abuse controls, and a privacy policy.

## Adding a city

1. Add the GeoJSON file.
2. Add the city to `CITY_METADATA` and `NETWORK_FILES` in `transit_network.py`.
3. Add its search bounding box to `CITY_VIEWBOXES` in `osm_services.py`.
4. Add its default start and popular places to `cityProfiles` and `cities` in `templates/index.html`.

## Next steps

- Survey active services and riding directions, and correct inferred lines from community evidence.
- Move geometry into PostGIS with GeoAlchemy2 and use indexed `ST_DWithin` queries.
- Add moderation before opening community notes publicly.
