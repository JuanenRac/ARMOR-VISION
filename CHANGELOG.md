# Changelog

All notable changes to this project are documented here.

## [0.0.1]

- First version: the tested core of the camera analysis service, in plain Python without dependencies.
- **Zones and masks** drawn on normalised coordinates (0 to 1), so one drawing works at any resolution. A zone has a label filter, a kind (`alert` or `detection`) and an inertia of N pictures and N seconds before it counts; a mask is where movement is ignored. The configuration is checked strictly: any error gives no configuration at all, so nothing silently watches less than was drawn.
- **Motion first:** two grey pictures are compared on a 16 x 9 grid; the detector runs only when enough cells outside the masks have changed.
- **A tracker** keeps the identity of each object between pictures and notices what stands still; a parked object is remembered for minutes and makes no new events.
- **Rules:** an object counts when its feet are inside the zone, it fires once per visit, and the arming profile (for example `away` or `home`) chooses which zones are watched; an unknown mode watches everything.
- **Events** (`armor.vision.event/v1`) report what was seen and always carry `authorizes_action: false`. The message is not part of the ARMOR-COMMON contract yet.
- `armor-vision check-config FILE` validates a configuration and `armor-vision simulate` runs a built-in scenario (a person crossing the driveway, a parked car, movement behind a masked tree).
- 38 tests. There is no real detector model yet and nothing has run on a camera or on the Jetson Orin NX.
