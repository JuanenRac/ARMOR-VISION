# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **The movement check decides per pixel, like the one of the server:** a pixel has changed when it differs from the previous picture by more than `motion_threshold` after the typical change of the whole picture is taken away, so a camera's automatic exposure, a cloud or the switch to infrared no longer wakes the detector; the grid is only used to say where it moved (a cell moves when a tenth of its pixels changed) and the masks are left out of the median.

## [0.1.1] - The vision event is versioned and can carry the radar tracks, a frame only looks at the visits of its own camera and a pipe inside a code span no longer splits a table cell in the README

- **The vision event is versioned and can carry the radar tracks:** `make_event(..., radar_tracks=N)` writes the second version (`armor.vision.event/v2`, the same fields plus `radar_tracks`); without it the event stays the first version. Three tests pin both versions and the refusal of a bad count. Tests: 138 (before 135).
- **A frame only looks at the visits of its own camera:** the rules keep the open visits of each camera apart, so ending the visits of an object that left no longer walks through the visits of every other camera (the events are the same).
- **A pipe inside a code span no longer splits a table cell in the README:** the command that answers one heatmap query shows its output formats escaped, in the eight languages.

## [0.1.0] - Zones and masks can be written as rectangles, a flood of detections cannot slow the tracker down and the errors of the pipeline can be told from a bug

- **A zone or a mask can be written as a rectangle:** `"rect": {"x", "y", "w", "h"}` is read as its four corners, so the zones to ignore that the server keeps and the ones Studio draws can be used as they are; a zone gives `points` or `rect`, not both.
- **A flood of detections cannot slow the tracker down:** the new `limits` of the configuration (`max_detections`, default 100, and `max_tracks`, default 200) keep the most certain detections of a frame and stop a camera from following more than that at once; what is left out is counted as a dropped detection.
- **The errors of the pipeline can be told from a bug:** `UnknownCameraError` and `NoDetectorError`, both a `VisionError` (and still a `KeyError` and a `RuntimeError`), replace the bare ones.

## [0.0.9] - Recorded detections can be run through the zone rules and an ONNX detector on the CPU that stays off unless it is built

- **Recorded detections can be run through the zone rules:** the new command `replay FILE [--config FILE] [--mode MODE]` reads a file of recorded detections (the JSON-lines format of the activity pipeline) and prints the alerts and detections each zone would have raised, with their count per zone, so the zones, the masks and the inertia can be tuned offline on what the cameras really saw. Nothing is sent anywhere. A file that cannot be used, or a camera that is not in the configuration, exits with 2 and prints nothing: a recording of another house must not look like a quiet one.
- **An ONNX detector that runs on the CPU, off unless it is built:** `OnnxDetector` (with `parse_onnx_settings`, and `load_detector("onnx", settings)`) runs a model with one image input and rows `x1, y1, x2, y2, score, class` as output, applies the confidence threshold, merges overlapping boxes of the same class and limits the count. `onnxruntime` is not a dependency: without it the detector says so. The model path, the labels and the thresholds are in a settings object that is checked whole. It has only been tested with a stand-in for the session; no real model has been run.
- Tests: 129 (before 119).

## [0.0.8] - The live service bounds what its clients can cost it, draws a map after the engine is released and keeps exact counters of accepted and refused requests under many threads

- **The live service bounds what clients can cost it:** the settings gain `request_timeout_s` (a client that goes quiet in the middle of a request is dropped instead of holding a thread), `max_connections` (at most that many requests are handled at once; the next one gets `503` with `Retry-After`) and `render_cache_entries` (the drawing of a map that has not changed is kept and handed out again; 0 turns it off). All three are checked at start-up like the other settings.
- **A map is drawn after the engine has been released:** the route is split in two halves, `heatmap_plan` (checks the query and reads the map) and `heatmap_draw`, so a large PNG or SVG no longer holds the lock that the observations need; `heatmap_route` gives the same answers as before.
- **The counters of accepted and refused requests are exact under many threads.**
- Tests: 119 (before 112), 7 of them for the service under load.

## [0.0.7] - The live service can ask for a token, and must when it is open to other machines

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
