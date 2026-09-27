# Data sources

Lugar.ph shows route references, not live navigation or official stops. Treat every line as a best estimate. Riders should still confirm the signboard, direction, current service, safe boarding points, and fare locally.

## Where each city's lines come from

| City | Geometry | Status value |
| --- | --- | --- |
| Bacolod | Inferred: route names and landmark sequence from the LPTRP study, routed along OpenStreetMap roads | `inferred_from_lptrp_anchors` |
| Iloilo | Inferred: approved route structures and street sequences, routed along OpenStreetMap roads | `inferred_from_official_route_structure` |
| Tacloban | Inferred: rationalized PUJ routes, routed along OpenStreetMap roads. The one P2P route is excluded. | `inferred_from_official_route_structure` |
| Cebu | Archived 2017 DOTC GTFS shapes, filtered to codes in a current 74-line directory that lists both active and inactive lines | `archived_dotc_gtfs_shape` |

Inferred lines follow the published landmark order, but the actual turns and one-way streets may differ. The Bacolod route map itself notes that detailed roads and one-way streets are omitted.

## Sources

- [Bacolod LPTRP study, Table 1 and Figure 2](https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf): 24 route names, planned lengths, and the schematic line map. A readable copy of the route map was also supplied, confirming the Ayala boarding area and the Shopping–La Salle landmark sequence.
- [Bacolod City route notice](https://bacolodcity.gov.ph/updated-routes-under-the-local-public-transport-route-plan-lptrp/): the 2023 simulation routes. The notice calls the exercise temporary.
- [Bacolod City 2025 LPTRP consultation](https://bacolodcity.gov.ph/bacolod-city-holds-local-public-transport-route-plan-lptrp-public-consultation-2025/): evidence that the plan is still under review.
- [Local Ayala–SM–La Salle trip account](https://www.reddit.com/r/LasalleBacolod/comments/1vsc3k8/jeep_to_ride_from_ayala/): corroborates the Bata–Libertad and Shopping–La Salle connection around the city centre.
- [Iloilo LTFRB Memorandum Circular 2023-036](https://ilonggoengineer.com/wp-content/uploads/2025/04/mc-2023-036.pdf): 25 approved PUJ route structures and street sequences.
- [Tacloban LTFRB Memorandum Circular 2024-035](https://www.scribd.com/document/780942237/LTFRB-MC-2024-035) and the [Tacloban ordinance directory](https://tacloban.gov.ph/ordinance/page/5/): 19 rationalized PUJ routes plus one P2P route.
- [Transitland Cebu DOTC feed](https://www.transit.land/feeds/f-wcb4-cebu~dotc): archived Cebu GTFS route shapes. Service dates end in 2017.
- [Cebu Bus Spotters route directory](https://sites.google.com/view/cebubusspotters/cbs-virtual-library/cebu-jeepney-route-guide/cebu-city-jeepney-routes): 74 documented codes used to filter the archived GTFS.
- [OpenStreetMap](https://www.openstreetmap.org/copyright): road geometry for inferred lines, landmark positions, place search, map tiles, and walking directions.
- [LTFRB fare increase, September 2026](https://www.philstar.com/headlines/2026/09/27/2559277/jeepney-fares-p14-starting-sept-28-buses-taxis-tnvs-also-hike-rates): the traditional jeepney fare used for estimates is ₱14 for the first 4 km plus ₱2 per km after, effective 28 September 2026. Students, seniors, and PWDs pay 20% less.

## Known gaps

- Riding direction is unknown for open lines, so they are assumed to run both ways on the same roads.
- Cebu's anchors are route endpoints only, so Cebu stops are named by street, when the walking router answers.
- Community notes are public and unverified.
