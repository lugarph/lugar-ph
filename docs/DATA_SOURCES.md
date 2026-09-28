# Data sources

Lugar.ph shows route references, not live navigation or official stops. Treat every line as a best estimate. Riders should still confirm the signboard, direction, current service, safe boarding points, and fare locally.

## Where each city's lines come from

| City | Geometry | Status value |
| --- | --- | --- |
| Bacolod | Lines 1–3, 5–11, and 16: OpenStreetMap route relations mapped street by street, one per direction, citing City Ordinance 966 and LTFRB MC 2022-010. The other lines are inferred from the LPTRP study's landmark sequence and routed along OpenStreetMap roads. | `osm_route_relation`, `inferred_from_lptrp_anchors` |
| Iloilo | 10 lines from OpenStreetMap route relations. OSM uses an older 17-route numbering, so only lines whose names clearly match were imported (OSM route n is usually our n + 1). The rest are inferred from the approved route structures and street sequences, routed along OpenStreetMap roads. | `osm_route_relation`, `inferred_from_official_route_structure` |
| Tacloban | Lines 1–5 and 7 from OpenStreetMap route relations. The rest are inferred from the rationalized PUJ routes, routed along OpenStreetMap roads. The one P2P route is excluded. | `osm_route_relation`, `inferred_from_official_route_structure` |
| Cebu | 28 codes from current OpenStreetMap route relations. The rest are archived 2017 DOTC GTFS shapes, filtered to codes in a current 74-line directory that lists both active and inactive lines. | `osm_route_relation`, `archived_dotc_gtfs_shape` |
| Baguio | 45 lines from OpenStreetMap route relations mapped by local contributors, one relation per direction (Pico-Puguis and Trancoville are single loops). Lines around Baguio and La Trinidad only. | `osm_route_relation` |
| Naga | The 8 routes of the 2025 route plan, with route 8's four downtown loops drawn separately (11 lines), traced through the streets the ordinance lists. | `inferred_from_official_route_structure` |
| Cagayan de Oro | 63 of the route plan's lines, traced through the streets it lists for each route in and out. | `inferred_from_official_route_structure` |
| Davao | 7 downtown routes traced through the streets listed on the OpenStreetMap wiki (route 4 imported from its OSM relation), plus Route 12 from its OSM relation. | `osm_route_relation`, `inferred_from_official_route_structure` |

Inferred lines follow the published landmark order, but the actual turns and one-way streets may differ.

### Raw sources and how the newer cities are drawn

Baguio, Naga, Cagayan de Oro, and Davao keep their inputs in `data/sources/<city>/`, so they can be checked or redrawn without fetching anything again:

- `route_plan.json`: the published route descriptions, verbatim where they were extracted from a page (Cagayan de Oro) and transcribed where they came from a PDF table (Naga, with the PDF's extracted text beside it) or a wiki table (Davao, with the wiki source beside it). Each keeps its source URL and retrieval date.
- `places.json`: terminals, markets, bridges, and landmarks, each with its coordinates, where they came from (a Nominatim search and what it matched, or an OpenStreetMap object), and whether it is approximate.
- `osm_relations.json` (Baguio, Davao): the OpenStreetMap relations considered, with their tags.
- `build_report.json`: written by the build. For every drawn line, its drawn and published lengths and any streets that could not be placed.

[`scripts/build_city_networks.py`](../scripts/build_city_networks.py) matches each listed street to named OpenStreetMap ways, routes through the corners where consecutive streets meet (OSRM driving profile, which respects one-way streets), and rejects same-named streets elsewhere in the city by checking that each corner lies on the way to the next known place. In Cagayan de Oro, 42 of the 63 lines come out within 10% of the plan's published length and 49 within 15%. Most of the rest start at a terminal that isn't mapped or run along unnamed barangay roads; the report lists them. A line drawn at less than 60% of its published length is missing its outer end and is left out. The Bacolod route map itself notes that detailed roads and one-way streets are omitted.

## Sources

- OpenStreetMap route relations: street-by-street paths for 11 Bacolod, 10 Iloilo, 28 Cebu, and 6 Tacloban lines. The ids are listed in `OSM_ROUTES` in the two build scripts. For Bacolod ([example](https://www.openstreetmap.org/relation/14998328)) they are one relation per direction (loops are a single relation), tagged with operators and the ordinance and circular that authorise them. Imported by `scripts/build_route_network.py`. © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/). A few relations needed care on import: small breaks between ways are bridged with a driving route, one return relation carries its outbound from/to tags, and two carry the wrong `ref`.
- [Bacolod City Ordinance No. 966 (2021)](https://bacolodcity.gov.ph/wp-content/uploads/2022/07/CO-966-2021.pdf): the adopted route plan's list of routes, modes, and authorised units. It classes 18 Granada–Burgos and 19 Alangilan–Burgos as Class 3 UV Express, not jeepneys. Its street-level plan (Correspondence No. 10-20-0277) is an attachment that is not published online.
- [LTFRB approval of the Bacolod route plan](https://www.pna.gov.ph/articles/1084457): Memorandum Circular 2022-010, which approved 24 routes. Doña Juliana–Central Market appears here but not in Ordinance 966's list of 23.
- [Bacolod LPTRP study, Table 1 and Figure 2](https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf): 24 route names, planned lengths, and the schematic line map. A readable copy of the route map was also supplied, confirming the Ayala boarding area and the Shopping–La Salle landmark sequence.
- [Bacolod City route notice](https://bacolodcity.gov.ph/updated-routes-under-the-local-public-transport-route-plan-lptrp/): the 2023 simulation routes. The notice calls the exercise temporary.
- [Bacolod City 2025 LPTRP consultation](https://bacolodcity.gov.ph/bacolod-city-holds-local-public-transport-route-plan-lptrp-public-consultation-2025/): evidence that the plan is still under review.
- [Local Ayala–SM–La Salle trip account](https://www.reddit.com/r/LasalleBacolod/comments/1vsc3k8/jeep_to_ride_from_ayala/): corroborates the Bata–Libertad and Shopping–La Salle connection around the city centre.
- [Iloilo LTFRB Memorandum Circular 2023-036](https://ilonggoengineer.com/wp-content/uploads/2025/04/mc-2023-036.pdf): 25 approved PUJ route structures and street sequences.
- [Tacloban LTFRB Memorandum Circular 2024-035](https://www.scribd.com/document/780942237/LTFRB-MC-2024-035) and the [Tacloban ordinance directory](https://tacloban.gov.ph/ordinance/page/5/): 19 rationalized PUJ routes plus one P2P route.
- [Transitland Cebu DOTC feed](https://www.transit.land/feeds/f-wcb4-cebu~dotc): archived Cebu GTFS route shapes. Service dates end in 2017.
- [Cebu Bus Spotters route directory](https://sites.google.com/view/cebubusspotters/cbs-virtual-library/cebu-jeepney-route-guide/cebu-city-jeepney-routes): 74 documented codes used to filter the archived GTFS.
- [Cagayan de Oro route plan](https://sites.google.com/view/cdo-routes-lptrp/home) (Roads and Traffic Administration, in force from June 2025): [District 1](https://sites.google.com/view/cdo-routes-lptrp/district-1) and [District 2](https://sites.google.com/view/cdo-routes-lptrp/district-2) pages, with each route's streets in and out and their lengths.
- [Naga City Ordinance No. 2025-070](https://www2.naga.gov.ph/wp-content/uploads/2025/10/Ordno-2025-070-Institutionalizing-the-Approved-LPTRP.pdf): the 8 approved PUJ routes (LTFRB-DOTr Board Resolution No. 204, s. 2025) and their streets, with [Resolution No. 2025-172](https://www2.naga.gov.ph/wp-content/uploads/2025/05/Resno-2025-172-Amending-Route-C-and-D-under-the-LPTRP.pdf) adding J. Miranda Avenue to loops C and D.
- [OpenStreetMap Wiki: Davao City/Public transportation](https://wiki.openstreetmap.org/wiki/Davao_City/Public_transportation): Davao's numbered and named downtown routes and their streets.
- OpenStreetMap route relations for Baguio: 45 lines mapped by local contributors, many tagged `hail_and_ride` where riders can flag the jeep anywhere. The city's own [jeepney route list](https://alternateroutes.baguio.gov.ph/jeepneyroutes/) is a useful check.
- [OpenStreetMap](https://www.openstreetmap.org/copyright): road geometry for inferred lines, landmark positions, place search, map tiles, and walking directions.
- [LTFRB fare increase, September 2026](https://www.philstar.com/headlines/2026/09/27/2559277/jeepney-fares-p14-starting-sept-28-buses-taxis-tnvs-also-hike-rates): the traditional jeepney fare used for estimates is ₱14 for the first 4 km plus ₱2 per km after, effective 28 September 2026. Students, seniors, and PWDs pay 20% less.

## Known gaps

- Bacolod lines 4, 12–15, and 17–24 have no mapped path yet, so they are estimated from the route plan and riders see a note saying so. The street-level plan behind Ordinance 966 could be requested from the Sangguniang Panlungsod secretariat or through an FOI request to LTFRB Region 6.
- The OpenStreetMap relation for Bacolod line 7 (via San Agustin) is 8.1 km against a published 13.5 km, so it may be incomplete.
- Six Iloilo OSM routes (OSM 2, 6, 8, 9, 11, 12) end at different terminals from the current route structure, so they were not imported; the routes may have changed between plans. OSM route 13 (our 14) has 3.5 km of breaks.
- Cebu codes 04I, 12D, 12G, 12I, 12L, 17B, 17C, and 17D only have old, one-direction, or broken relations in OSM, so they keep the 2017 GTFS shapes. OSM's 03Q and 04L carry no from/to tags, so those lines have no terminal names or "toward" direction.

- The way back on Bacolod, Iloilo, and Tacloban lines is inferred: it passes the outbound landmarks in reverse, along streets that respect one-way rules. Where a jeep actually returns through other side streets, the drawn return is a guess until someone records it in `RETURN_VIA` or redraws it. Inferred circuits can run longer than the published route length.
- Cebu's anchors are route endpoints only, so Cebu stops are named by street, when the walking router answers.
- Community notes are public and unverified.
- **Cagayan de Oro:** five routes the plan marks as not yet operational and five long upland routes (Dansolihon, Tuburan, Tagpangi, Tumpagon; 50-80 km round trips) are left out; the plan's Dansolihon R1 entry repeats Carmen R6's streets. Several barangay roads and subdivision streets are unnamed in OpenStreetMap, so those stretches follow the shortest road; Carmen R2 (San Agustin Valley), Gusa R2, and Camaman-an R3 (Macapaya) are left out because their outer ends could not be placed. Villa Verde, Kinasanghan, Kisanlu, and Buena Oro use an approximate terminal. Carmen R1 and R5 are mapped in OpenStreetMap under older codes (17 and N11), but both R5 relations are tagged Carmen to Agora, so the drawn versions are kept.
- **Naga:** route 3's Southbound Terminal variant is not drawn, and the ordinance's cell for loop A is jumbled, so loop A is drawn as the reverse of loop B. The Del Rosario terminal is placed on Maharlika Highway in Del Rosario rather than at the Pili boundary itself.
- **Davao:** only downtown routes are covered. Davao's named routes to Toril, Mintal, Calinan, Bangkal, Buhangin, Panacan, and elsewhere have no public street list yet. The OSM relations for Routes 1, 5, 8, 10, 11, and 13 have gaps of up to 2.4 km and use the older one-relation-per-route scheme, so they are not imported; Routes 1 and 5 are drawn from the wiki instead.
- **Baguio:** jeeps are identified by destination, not number, so the destination is shown where other cities show a route number. Intercity jeeps (Agoo, Rosario, Pugo, Sablan, Nangalisan, Itogon), the one-way-only Tawang mapping, and alternative return paths are left out.
