# ARMOR-VISION usage

```text
python -m armor_vision simulate [--config FILE] [--mode MODE]
python -m armor_vision check-config FILE
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
- A **mask** is a polygon where movement is ignored: no motion is counted under it and detections whose centre is inside it are dropped.
- `motion_threshold` (1 to 255) is the grey difference that counts as change; `motion_min_cells` is how many cells of the 16 x 9 grid must change before the detector is asked.
- A **profile** lists the zones that are watched in an arming mode. With no mode, or a mode without a profile, every zone is watched.
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
