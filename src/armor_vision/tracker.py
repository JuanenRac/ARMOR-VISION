"""Follows detections from one frame to the next and notices what stands still."""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Box, centre, iou

MATCH_IOU = 0.3
MATCH_REACH = 1.0                # a detection that does not overlap still follows a track if its centre is within this many box sizes (a quick walker at a low frame rate)
MISSING_SECONDS = 2.0            # a moving track that is not seen this long is dropped
STATIONARY_MISSING_SECONDS = 300.0   # a parked car is remembered much longer
STATIONARY_WINDOW = 3.0          # seconds over which "did not move" is judged
STATIONARY_DISTANCE = 0.01       # normalised distance the centre may drift


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: Box


@dataclass
class Track:
    track_id: int
    label: str
    box: Box
    confidence: float
    first_seen: float
    last_seen: float
    history: list[tuple[float, tuple[float, float]]] = field(default_factory=list)
    stationary: bool = False


class Tracker:
    def __init__(self) -> None:
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> list[Track]:
        return sorted(self._tracks.values(), key=lambda t: t.track_id)

    def update(self, timestamp: float, detections: list[Detection]) -> list[Track]:
        """Matches detections to tracks (best overlap first, same label only) and
        returns the tracks seen in this update."""
        pairs = []
        for track in self._tracks.values():
            for index, detection in enumerate(detections):
                if detection.label == track.label:
                    overlap = iou(track.box, detection.box)
                    if overlap >= MATCH_IOU:
                        pairs.append((overlap, track.track_id, index))
                        continue
                    # no overlap worth the name: the distance between centres, against the size of the boxes, ranks below every real overlap
                    size = max(track.box[2] - track.box[0], track.box[3] - track.box[1], detection.box[2] - detection.box[0], detection.box[3] - detection.box[1])
                    (tx, ty), (dx, dy) = centre(track.box), centre(detection.box)
                    distance = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5
                    if size > 0 and distance <= MATCH_REACH * size:
                        pairs.append((0.1 * (1.0 - distance / (MATCH_REACH * size)), track.track_id, index))
        pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
        used_tracks: set[int] = set()
        used_detections: set[int] = set()
        seen: list[Track] = []
        for _, track_id, index in pairs:
            if track_id in used_tracks or index in used_detections:
                continue
            used_tracks.add(track_id)
            used_detections.add(index)
            track = self._tracks[track_id]
            detection = detections[index]
            track.box, track.confidence, track.last_seen = detection.box, detection.confidence, timestamp
            self._remember(track, timestamp)
            seen.append(track)
        for index, detection in enumerate(detections):
            if index in used_detections:
                continue
            track = Track(self._next_id, detection.label, detection.box, detection.confidence, timestamp, timestamp)
            self._next_id += 1
            self._tracks[track.track_id] = track
            self._remember(track, timestamp)
            seen.append(track)
        self._expire(timestamp)
        return sorted(seen, key=lambda t: t.track_id)

    def _remember(self, track: Track, timestamp: float) -> None:
        track.history.append((timestamp, centre(track.box)))
        horizon = timestamp - STATIONARY_WINDOW
        while len(track.history) > 2 and track.history[1][0] <= horizon:
            track.history.pop(0)
        oldest_time, oldest = track.history[0]
        if timestamp - oldest_time >= STATIONARY_WINDOW:
            drift = max(abs(c[0] - oldest[0]) + abs(c[1] - oldest[1]) for _, c in track.history)
            track.stationary = drift <= STATIONARY_DISTANCE
        else:
            track.stationary = False

    def _expire(self, timestamp: float) -> None:
        for track_id in [t.track_id for t in self._tracks.values()
                         if timestamp - t.last_seen > (STATIONARY_MISSING_SECONDS if t.stationary else MISSING_SECONDS)]:
            del self._tracks[track_id]
