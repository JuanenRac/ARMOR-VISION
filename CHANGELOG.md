# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **The live service can ask for a token, and must when it is open to other machines:** the settings gain `token_file`, the path of a file that holds the token (the environment variable `ARMOR_VISION_SERVICE_TOKEN` does the same; never both, and never in the settings file, so it is never in a repository). With a token every request, `GET /health` included, needs `Authorization: Bearer <token>`, compared in constant time, and anything else is an empty `401`. With `allow_remote` true the service does not start without one. A token of fewer than 24 characters or with odd characters is refused; the token is never printed, not even by `check-service-config`, which only says whether there is one.
## [0.0.6] - A live service keeps the activity engine in memory and serves the heat map, and the heat map route can be mounted by a server

- **A live service keeps the activity engine in memory and serves the heat map:** `python -m armor_vision serve --activity-config FILE [--config FILE] [--service-config FILE]` runs the same engine the command line uses, takes detections as they happen (`POST /ingest`, one observation per request, in time order for each camera) and answers `GET /heatmap?camera=&format=&scale=` from that memory instead of replaying a file for every request (`GET /health` tells what it holds). Its settings are in a file (`service-example` prints one, `check-service-config` checks one): the address (the loopback one unless `allow_remote` is true), the port, the largest request, the most detections in one observation and the longest query; an unknown field or a value out of range means it does not start. It stores nothing on disk, keeps no secret and keeps only counted positions; a scene can be simulated at start (`simulate`). The command `heatmap-route` is unchanged.
- Tests: 112 (before 97), 15 of them for the service.
- **The heat map route can be mounted by a server:** the new command `heatmap-route` answers one `GET /heatmap` query (camera, format, scale) from the activity configuration and a file of recorded detections and prints the answer as one JSON line (`status`, `content_type`, `body_base64`). The route is still `heatmap_route`, so a pipeline that is off answers 404 and a bad query 400; a wrong configuration or a file that cannot be read exits with 1 or 2 and prints nothing, so it is never taken for an empty map. Nothing else changes: the other commands and their output are the same.
- Tests: 97 (before 90), 7 of them for the new command.

## [0.0.5] - An activity pipeline with simulated cameras, events and a heat map, off by default, and a type check in the CI

- **An activity pipeline with simulated cameras and a heat map (off by default):** the new activity configuration (`enabled` is `false` unless the file says otherwise) switches on a pipeline that turns detections into activity events (`zone_enter`, `zone_exit`, `dwell`, `loiter`, `line_cross`, with `authorizes_action: false`) and keeps a heat map of activity: counts per cell of a grid over the scene, over a configurable time window with optional decay, normalised as weight divided by the maximum, exportable as JSON, PNG or SVG (standard library only) and bounded in memory. The detections come from a pluggable source: a deterministic synthetic scene (a seed gives the same objects every time) or a file of recorded detections; a malformed, backwards-in-time or oversized file is refused whole. Only aggregated positions are kept: no picture, box or identity is stored or exported. New commands `simulate --simulate-events`, `simulate --heatmap OUT`, `activity-example` and `check-activity-config`, and the handler of `GET /heatmap` for the service that will mount it (this repository has no server of its own). With the switch off, everything behaves as before; the real camera or RTSP source is for the hardware and is not written.
- Tests: 90 (before 61), including tests that pin the existing simulation output and property tests with a fixed seed.
- **The CI type-checks the source:** the project declares its mypy configuration, so the shared workflow runs ruff and mypy on it.

## [0.0.4] - The lights of Project status follow the evidence of the manifest, the universal README and the pictures of the README from shared tools

- **The lights of Project status follow the evidence of the manifest:** the manifest says how far the repository has been shown to work (`evidence`: `host-test`, `simulator`, `bench` or `field`) and the validator fails when a light is above what that evidence and the maturity allow (`tools/status_lights.py`), so a green that never ran on real hardware cannot come back.
- **The README follows the universal layout:** security, interfaces, configuration, testing, troubleshooting and roadmap sections and the architecture and repository-structure pictures, in the eight languages.
- **The layout of the README is checked in the CI:** the validator runs the shared `tools/universal_readme_check.py` and fails when the README differs from the universal layout.
- **The pictures of the README come from shared tools:** `tools/make_architecture.py` draws `images/architecture.svg` from `docs/architecture.json` and `tools/make_structure.py` draws the Repository Structure (the text tree and the animated picture) from `docs/structure.json`; both measure every text, and `--check` fails when a picture, its description or the code it points to disagree. They are vendored from ARMOR-COMMON like the shared CI checks.

## [0.0.3] - The manifest says what the project is: a library without a service of 

- The manifest says what the project is: a library without a service of its own, that produces alert and detection events.
- The repository has a security policy, a code of conduct, a contributing guide and a support file.
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.
- The commands of the README are also given for bash (`PYTHONPATH=src python -m armor_vision ...`), in the eight languages, and the test count reads in each language.

## [0.0.2] - Loitering that is caught, one event per visit, and a configuration that cannot lie

- **Somebody who comes into a zone and stands still now fires it** once its `min_seconds` is over (before, the "did not move" rule silenced the zone before a long inertia could pass, so loitering was never reported). An object that was already standing still when it entered still makes no event.
- **A frame the detector misses does not open a new visit:** visits end when the tracker has lost the object, not when one frame lacks it, so one person gives one event, not one per blink of the detector.
- **The tracker follows a quick walker:** a detection with no overlap still continues a track when its centre is within one box size (low frame rates, close-up walkers), ranked below any real overlap.
- **Modes:** the server's `disarmed` has an explicit meaning (alert zones are not watched, detection zones record); events carry `timestamp_ms`.
- **The configuration:** `zones` or `masks` that are not lists, NaN and Infinity (in `min_seconds` and in the JSON file), bow-tie polygons and polygons with almost no area are refused with a clear line; a detection with a confidence outside 0..1 or NaN is dropped.
- The masked cells of the motion grid are worked out once per set of masks, not on every frame.
- Tests: 42 (before 38).

## [0.0.1]

- First version: the tested core of the camera analysis service, in plain Python without dependencies.
- **Zones and masks** drawn on normalised coordinates (0 to 1), so one drawing works at any resolution. A zone has a label filter, a kind (`alert` or `detection`) and an inertia of N pictures and N seconds before it counts; a mask is where movement is ignored. The configuration is checked strictly: any error gives no configuration at all, so nothing silently watches less than was drawn.
- **Motion first:** two grey pictures are compared on a 16 x 9 grid; the detector runs only when enough cells outside the masks have changed.
- **A tracker** keeps the identity of each object between pictures and notices what stands still; a parked object is remembered for minutes and makes no new events.
- **Rules:** an object counts when its feet are inside the zone, it fires once per visit, and the arming profile (for example `away` or `home`) chooses which zones are watched; an unknown mode watches everything.
- **Events** (`armor.vision.event/v1`) report what was seen and always carry `authorizes_action: false`. The message is not part of the ARMOR-COMMON contract yet.
- `armor-vision check-config FILE` validates a configuration and `armor-vision simulate` runs a built-in scenario (a person crossing the driveway, a parked car, movement behind a masked tree).
- 38 tests. There is no real detector model yet and nothing has run on a camera or on the Jetson Orin NX.
