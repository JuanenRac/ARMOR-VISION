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
- A **profile** lists the zones that are watched in an arming mode. With no mode, or a mode without a profile, every zone is watched - except for `disarmed` (the server's own word): without a profile of that name its `alert` zones are not watched and only the `detection` zones record. The server's modes are `armed` and `disarmed`; `away` and `home` are profile names for a house that has them.
- Unknown fields are errors, on purpose.

## Event

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

`authorizes_action` is always `false`: the event reports what was seen, and the server decides what to do. The message is not part of the ARMOR-COMMON contract yet.

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
- **As a library:** `ActivityEngine(vision_config, activity_config).process(camera_id, timestamp, detections)` or `.run(source)`; `engine.heatmap(camera_id).snapshot()` gives the map. `heatmap_route(engine, query)` is the handler of `GET /heatmap?camera=ID&format=json|png|svg&scale=N` for the service that will mount it (this repository has no server): it returns `(status, content type, body)`, 404 when the pipeline is off (`engine` is `None`) and 400 for a bad query.
