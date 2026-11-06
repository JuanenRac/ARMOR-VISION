# ARMOR-VISION usage

```text
python -m armor_vision simulate [--config FILE] [--mode MODE]
python -m armor_vision check-config FILE
python -m armor_vision simulate --simulate-events --activity-config FILE [--seed N] [--objects N] [--duration S] [--camera ID] [--detections-file FILE]
python -m armor_vision simulate --heatmap OUT.json|OUT.png|OUT.svg --activity-config FILE
python -m armor_vision activity-example
python -m armor_vision check-activity-config FILE
```

`simulate` runs a built-in scenario (a person crossing a driveway, a parked car in the street, movement behind a masked tree) through the rules and prints one JSON line per event, then a last line with the counters. `check-config` validates a configuration file and prints every problem it finds; any problem means no configuration is accepted. Exit codes: 0 good, 1 invalid configuration, 2 unreadable file.

## Configuration

```json
{
  "cameras": {
    "cam-front": {
      "motion_threshold": 25,
      "motion_min_cells": 2,
      "zones": [
        {"id": "drive", "name": "Driveway", "kind": "alert", "labels": ["person"],
         "min_frames": 3, "min_seconds": 1.0,
         "points": [[0.3, 0.6], [0.9, 0.6], [0.9, 1.0], [0.3, 1.0]]}
      ],
      "masks": [[[0.0, 0.0], [0.2, 0.0], [0.2, 0.4], [0.0, 0.4]]]
    }
  },
  "profiles": {"away": ["drive"], "home": []}
}
```

- All coordinates are normalised: `[0, 0]` is the top-left corner of the picture and `[1, 1]` the bottom-right.
- A **zone** counts an object when its feet (the bottom centre of its box) are inside the polygon, its label is accepted (an empty `labels` list accepts every label), and it has been there for `min_frames` pictures and `min_seconds` seconds. It fires once per visit; leaving and coming back is a new visit. An object that has stopped moving makes no new event.
- `kind` is `alert` (worth waking someone) or `detection` (only recorded).
- A **mask** is a polygon where movement is ignored: no motion is counted under it and detections whose **centre** is inside it are dropped (a zone, on the other hand, looks at the **feet**: a person whose centre is under the masked crown of a tree and whose feet are in the zone is dropped).
- `motion_threshold` (1 to 255) is the grey difference that counts as change; `motion_min_cells` is how many cells of the 16 x 9 grid must change before the detector is asked.
- A zone or a mask can also be written as a **rectangle**, `"rect": {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.5}` (in a mask list, the object itself), the form Studio draws and the server keeps for the zones to ignore; it is the same as its four corners, and a zone gives `points` or `rect`, not both.
- The **limits** of a pipeline are in the configuration: `"limits": {"max_detections": 100, "max_tracks": 200}` (whole numbers from 1 to 10000). A frame with more detections than `max_detections` keeps the most certain ones, and a camera that already follows `max_tracks` things starts no new track until one expires; what is left out is counted as a dropped detection.
- A pipeline that cannot serve a call raises `UnknownCameraError` (a camera that is not in the configuration) or `NoDetectorError` (`process_frame` without a detector), both a `VisionError`, so a service can tell them from a bug; they are still a `KeyError` and a `RuntimeError` for code written before.
- A **profile** lists the zones that are watched in an arming mode. With no mode, or a mode without a profile, every zone is watched - except for `disarmed` (the server's own word): without a profile of that name its `alert` zones are not watched and only the `detection` zones record. The server's modes are `armed` and `disarmed`; `away` and `home` are profile names for a house that has them.
- Unknown fields are errors, on purpose.

## Event

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

`authorizes_action` is always `false`: the event reports what was seen, and the server decides what to do. The message is not part of the ARMOR-COMMON contract yet.

The event is versioned in its `schema`. The first version (`armor.vision.event/v1`) is the one above. The second (`armor.vision.event/v2`) has the same fields plus `radar_tracks`, a whole number (zero or more) with the radar tracks that agree with what the camera saw; `make_event(..., radar_tracks=N)` writes it. The consumer (the policy worker of ARMOR-SERVER-AI) accepts both: a first-version event takes the radar count the worker was started with, a second-version event brings its own, and any other `schema` is refused.

## As a library

```python
from armor_vision.config import parse_config
from armor_vision.pipeline import Pipeline
from armor_vision.tracker import Detection

config, errors = parse_config(raw)            # config is None when errors is not empty
pipeline = Pipeline(config, mode="away")
events = pipeline.process_detections("cam-front", timestamp, [Detection("person", 0.9, (x0, y0, x1, y1))])
```

`process_frame(camera_id, timestamp, frame)` takes a grey `Frame` and a detector, and asks the detector only when the picture moved. The only detector in this version is `ScriptedDetector`; asking `load_detector("tensorrt")` raises `DetectorUnavailable` because the model for the Jetson Orin NX is not written yet.

## Replaying recorded detections

`python -m armor_vision replay FILE [--config FILE] [--mode MODE]` runs a file of recorded detections (one JSON object per line: `camera_id`, `timestamp`, `detections`) through the zone rules and prints one event per line followed by `{"stats", "events_per_zone"}`. With `--mode` only the zones of that arming mode are watched, as in the service. The exit code is 2 for a file that cannot be used (the whole file is refused) and for a camera of the file that is not in the configuration.

## The ONNX detector (library, off unless built)

`parse_onnx_settings({"model": "model.onnx", "labels": ["person", "car"], "input_size": 640, "min_confidence": 0.4, "merge_iou": 0.5, "max_detections": 50})` checks the settings whole; `load_detector("onnx", settings)` opens the model with `onnxruntime` (install it yourself; it is not a dependency). The model has one input `[1, 3, S, S]` (float32, RGB 0..1; the grey frame is repeated on three channels) and one output `[N, 6]` or `[1, N, 6]` with rows `x1, y1, x2, y2, score, class` in pixels of the input.

## Activity events and heat map (off by default)

A separate pipeline turns detections into activity events and a heat map. It is **off** unless the activity configuration says `"enabled": true`: without it `--simulate-events` and `--heatmap` exit with 3 and write nothing, and everything above behaves exactly as before. `activity-example` prints a configuration to start from.

```json
{
  "enabled": true,
  "heatmap": {"cols": 32, "rows": 18, "window_seconds": 300, "half_life_seconds": null,
              "slices": 60, "max_cells": 4096, "position": "foot", "labels": []},
  "events": {"dwell_seconds": 3.0, "loiter_seconds": 6.0, "loiter_radius": 0.05, "lost_seconds": 2.0, "labels": [],
             "lines": [{"id": "gate", "a": [0.3, 0.7], "b": [0.9, 0.7]}]}
}
```

- **Sources** (anything with `observations()`): `SyntheticSource(camera_id, seed, objects, duration, fps)` walks people about the scene, stopping now and then, and gives the same detections for the same seed; `FileSource(path)` reads recorded detections, one JSON object per line: `{"camera_id": "cam", "timestamp": 1.5, "detections": [{"label": "person", "confidence": 0.9, "box": [x0, y0, x1, y1]}]}`. A line that is not valid, a time that goes backwards, an unknown field or a file over 16 MiB refuses the whole file. A real camera or RTSP source is for the hardware and is not written.
- **Events** (`armor.vision.activity/v1`, always `authorizes_action: false`), worked out from the feet of each tracked object and the zones of the vision configuration: `zone_enter`; `dwell` once the object has been inside `dwell_seconds`; `loiter` once it has been inside `loiter_seconds` without leaving a box of `loiter_radius`; `zone_exit` when it leaves or has not been seen for `lost_seconds`; `line_cross` (with `direction` `to_left` or `to_right` of the line from `a` to `b`) when the feet cross a counting line. Detections that are malformed or whose centre is inside a mask are dropped and counted.
- **Heat map** (`armor.vision.heatmap/v1`): one count per cell of a `cols` x `rows` grid laid over the scene, taken at the feet (or the `centre`) of each accepted detection. With `window_seconds` the map remembers the last window, cut in `slices` slices (exact to one slice); with `half_life_seconds` older slices weigh `0.5 ** (age / half_life)`; with neither it keeps everything. `weights` are the raw sums (their total equals the number of accepted positions when nothing decays or leaves the window) and `normalized` is `weight / max_weight` (all zero when the maximum is zero). Positions outside the scene, or older than the window, are rejected and counted. Memory is bounded: at most `slices` slices of `cols x rows` cells, and `cols x rows` never above `max_cells` (65536 at most). The PNG and the SVG draw the normalised map from blue (little) to red (the most).
- **Privacy:** only aggregated positions are kept. No picture, box, track or identity is stored or exported, and the export says `"contains_images": false`.
- **As a library:** `ActivityEngine(vision_config, activity_config).process(camera_id, timestamp, detections)` or `.run(source)`; `engine.heatmap(camera_id).snapshot()` gives the map. `heatmap_route(engine, query)` is the handler of `GET /heatmap?camera=ID&format=json|png|svg&scale=N` for the service that mounts it: it returns `(status, content type, body)`, 404 when the pipeline is off (`engine` is `None`) and 400 for a bad query.
- **As a live service:** `python -m armor_vision serve --activity-config FILE [--config FILE] [--service-config FILE]` keeps the engine in memory. `POST /ingest` takes one observation (`{"camera_id", "timestamp", "detections": [...]}`, the format of the recorded file) and answers `200` with the number of events, `400` for one that is not understood, `404` for a camera that is not in the configuration, `409` when time goes backwards for that camera and `503` while the pipeline is off; `GET /heatmap` takes the same query as the command and `GET /health` says what the service holds. `python -m armor_vision service-example` prints the settings (address, port, `allow_remote`, `max_body_bytes`, `max_detections`, `max_query_bytes`, `request_timeout_s`, `max_connections`, `render_cache_entries`, `simulate`) and `check-service-config FILE` checks a file. It listens on 127.0.0.1 only, unless the file says `allow_remote`, and then it does not start without a token. The token is optional on the loopback address: `token_file` in the settings names a file that holds it (or the environment variable `ARMOR_VISION_SERVICE_TOKEN`; 24 to 200 characters of letters, digits and `. _ ~ + / = -`), and with one every request needs `Authorization: Bearer <token>` (an empty `401` otherwise). The token is never in the settings file, never printed and never written; the server that mounts the route owns the sign-in of people. The service writes nothing to disk. Its limits are in the settings file: `request_timeout_s` (1 to 300 seconds, 15: a client that goes quiet in the middle of a request is dropped), `max_connections` (1 to 1024, 64: requests handled at the same time; the next one is answered `503` with `Retry-After`) and `render_cache_entries` (0 to 256, 16: drawn maps kept for reuse while no observation has been counted since; 0 draws every time). A map is drawn after the engine has been released, so a large PNG never holds up the observations that come in.
- **As a command, for a server that mounts the route:** `python -m armor_vision heatmap-route --activity-config FILE [--detections-file FILE] [--camera ID] [--format json|png|svg] [--scale N]` builds the engine from the activity configuration and the recorded detections (a file of the format above; without it the map is empty), answers that one query with `heatmap_route` and prints one JSON line: `{"status", "content_type", "body_base64"}`. The exit code is 0 for every answer of the route (also the 404 of a pipeline that is off and the 400 of a bad query, with a body that says nothing about the machine), 1 for a wrong configuration and 2 for a file that cannot be read: a server must never take a failure for an empty map. The command keeps no state between calls, so the map is the one of the file at that moment.
- **The counting lines of each camera, from the server:** `python -m armor_vision sync-context --server URL --ai-token-file FILE [--service URL] [--service-token-file FILE] [--interval SECONDS]` asks `GET /api/v1/ai/context` of ARMOR-SERVER (with the token of the observation service, or the variable `ARMOR_AI_TOKEN`) and hands the answer to the running service with `POST /context`, so the lines drawn in Studio are counted without a restart. With the default `--interval 0` it does one round, prints the answer of the service as one JSON line and stops; with an interval of 5 to 86400 seconds it repeats until it is stopped, saying only the first round that works and each change after a failure. It runs only when started (nothing in the service reaches out by itself), never follows a redirect, takes at most `--max-bytes` (262144 by default) from an answer, uses `--ca-file` for a server on https with its own certificate, and never prints a token. Exit 1 for a wrong option, 2 when the one round cannot be done (the server or the service does not answer, or the pipeline of the service is off).
