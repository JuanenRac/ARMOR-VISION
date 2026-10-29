# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **The README follows the universal layout:** security, interfaces, configuration, testing, troubleshooting and roadmap sections and the architecture and repository-structure pictures, in the eight languages.
- **The layout of the README is checked in the CI:** the validator runs the shared `tools/universal_readme_check.py` and lists, as a warning, what differs from the universal layout of the README.
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
