# Technical details

## Pages

| Address | Page |
| --- | --- |
| `/` | Splash page: what Lugar.ph does, and a city picker grouped by island. "Find my city" jumps to the nearest supported city; the last city used is offered first. |
| `/{city}` | The trip planner opened on one city, such as `/bacolod` or `/cdo`. Switching cities in the app updates the address, and back and forward move between cities. Other spellings in `CITY_ALIASES` in `main.py` (`/cagayan-de-oro`, `/CDO`) redirect to the canonical address; an unknown city shows the picker with a 404. |

The city route is declared last in `main.py`, so it never shadows `/api/…`, `/health`, or `/docs`.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/cities` | Supported cities with region, map centre, zoom, source, and line count. |
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

The algorithm is described in the README under [How trips are planned](../README.md#how-trips-are-planned).

## External services

Lugar.ph uses the public [Nominatim](https://operations.osmfoundation.org/policies/nominatim/) geocoder and the FOSSGIS [OSM routing service](https://routing.openstreetmap.de/about.html) for walking. Both adapters send at most one request per second and keep a small in-process cache.

Nominatim forbids search-as-you-type, so the search box filters recent places, popular places, and landmarks locally, and only calls the geocoder when you press Search. These public services suit low-volume evaluation only. Use a self-hosted or contracted geocoder and walking router before real traffic.

Planning trips needs no external service. If the walking router is slow or down, the app falls back to estimates.

## Community notes

Notes are stored in the `route_comments` table. Posting has length checks, a honeypot field, and a short per-client cooldown. There is no moderation dashboard or user accounts yet, so a public deployment needs moderation, stronger abuse controls, and a privacy policy.

## Adding a city

See [Run it for your city](../README.md#run-it-for-your-city) in the README.

## Next steps

- Survey active services and riding directions, and correct inferred lines from community evidence.
- Move geometry into PostGIS with GeoAlchemy2 and use indexed `ST_DWithin` queries.
- Add moderation before opening community notes publicly.
