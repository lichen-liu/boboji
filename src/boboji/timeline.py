"""Normalize Google Timeline exports without reading files or using the network."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


class ConversionError(ValueError):
    """An unsupported export or an invalid location field."""


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float
    time: datetime | None = None
    elevation: float | None = None


Track = tuple[Point, ...]


@dataclass(frozen=True)
class Conversion:
    tracks: tuple[Track, ...]

    @property
    def point_count(self) -> int:
        return sum(len(track) for track in self.tracks)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConversionError(f"{field}: expected an object")
    return value


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConversionError(f"{field}: expected an array")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConversionError(f"{field}: expected a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ConversionError(f"{field}: expected a finite number") from None
    if not math.isfinite(number):
        raise ConversionError(f"{field}: expected a finite number")
    return number


def _time(value: Any, field: str, *, milliseconds: bool = False) -> datetime:
    try:
        if milliseconds:
            return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                milliseconds=_number(value, field)
            )
        if not isinstance(value, str):
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ConversionError(f"{field}: expected a valid timestamp with a timezone") from None


def _record_time(record: dict[str, Any], field: str) -> datetime:
    for key in ("timestamp", "time", "timestampMs"):
        if key in record:
            return _time(record[key], f"{field}.{key}", milliseconds=key == "timestampMs")
    raise ConversionError(f"{field}: missing timestamp or timestampMs")


def _optional_time(record: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        if key in record:
            return _time(record[key], key, milliseconds=key.endswith("Ms"))
    return None


def _coordinates(value: Any, field: str) -> tuple[float, float]:
    if isinstance(value, str):
        text = value.strip().removeprefix("geo:").replace("\N{DEGREE SIGN}", "")
        parts = text.split(",")
        if len(parts) != 2:
            raise ConversionError(f"{field}: expected latitude,longitude")
        latitude, longitude = (_number(part.strip(), field) for part in parts)
    else:
        location = _object(value, field)
        for key in ("latLng", "LatLng"):
            if key in location:
                return _coordinates(location[key], f"{field}.{key}")
        if "latitudeE7" in location or "longitudeE7" in location:
            lat_key, lon_key, scale = "latitudeE7", "longitudeE7", 10_000_000
        elif "latE7" in location or "lngE7" in location:
            lat_key, lon_key, scale = "latE7", "lngE7", 10_000_000
        else:
            lat_key, lon_key, scale = "latitude", "longitude", 1
        if lat_key not in location or lon_key not in location:
            raise ConversionError(f"{field}: missing latitude or longitude")
        latitude = _number(location[lat_key], f"{field}.{lat_key}") / scale
        longitude = _number(location[lon_key], f"{field}.{lon_key}") / scale
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ConversionError(f"{field}: coordinates outside latitude/longitude bounds")
    # GPX 1.1's longitude type excludes +180; -180 is the same meridian.
    return latitude, -180.0 if longitude == 180 else longitude


def _point(value: Any, field: str, time: datetime | None = None) -> Point:
    latitude, longitude = _coordinates(value, field)
    elevation = None
    if isinstance(value, dict):
        for key in ("altitudeMeters", "altitude"):
            if key in value:
                elevation = _number(value[key], f"{field}.{key}")
                break
    return Point(latitude, longitude, time, elevation)


def _raw_tracks(records: Any, field: str, *, signals: bool = False) -> list[Track]:
    by_device: dict[str, list[Point]] = defaultdict(list)
    for index, value in enumerate(_array(records, field)):
        context = f"{field}[{index}]"
        record = _object(value, context)
        if signals:
            # Wi-Fi scans and activity readings are metadata, not GPS fixes.
            if "position" not in record:
                continue
            record = _object(record["position"], f"{context}.position")
            context += ".position"
        device = record.get("deviceTag", "default")
        if isinstance(device, bool) or not isinstance(device, (str, int)):
            raise ConversionError(f"{context}.deviceTag: expected a string or integer")
        by_device[str(device)].append(_point(record, context, _record_time(record, context)))
    return [tuple(sorted(points, key=lambda point: point.time)) for points in by_device.values()]


def _phone_tracks(segments: Any, field: str) -> list[Track]:
    tracks: list[Track] = []
    for index, value in enumerate(_array(segments, field)):
        context = f"{field}[{index}]"
        segment = _object(value, context)
        if "timelinePath" in segment:
            path: list[Point] = []
            for point_index, item in enumerate(_array(segment["timelinePath"], f"{context}.timelinePath")):
                point_context = f"{context}.timelinePath[{point_index}]"
                record = _object(item, point_context)
                if "point" not in record:
                    raise ConversionError(f"{point_context}: missing point")
                time = None
                if "time" in record:
                    time = _time(record["time"], f"{point_context}.time")
                elif "durationMinutesOffsetFromStartTime" in record:
                    offset = _number(
                        record["durationMinutesOffsetFromStartTime"], f"{point_context}.offset"
                    )
                    if offset < 0 or "startTime" not in segment:
                        raise ConversionError(f"{point_context}: offset requires a startTime and nonnegative minutes")
                    try:
                        time = _time(segment["startTime"], f"{context}.startTime") + timedelta(minutes=offset)
                    except OverflowError:
                        raise ConversionError(f"{point_context}: timestamp offset is too large") from None
                if time is not None:
                    start = _optional_time(segment, "startTime")
                    end = _optional_time(segment, "endTime")
                    if (start is not None and time < start) or (end is not None and time > end):
                        raise ConversionError(f"{point_context}: point time is outside the segment")
                path.append(_point(record["point"], point_context, time))
            if path:
                tracks.append(tuple(path))
        elif "visit" in segment:
            visit = _object(segment["visit"], f"{context}.visit")
            candidate = _object(visit.get("topCandidate", {}), f"{context}.visit.topCandidate")
            if "placeLocation" in candidate:
                tracks.append((_point(candidate["placeLocation"], f"{context}.placeLocation", _optional_time(segment, "startTime")),))
        elif "activity" in segment:
            activity = _object(segment["activity"], f"{context}.activity")
            # Endpoints prove presence at two places, not the route between them.
            for key, time_key in (("start", "startTime"), ("end", "endTime")):
                if key in activity:
                    tracks.append((_point(activity[key], f"{context}.activity.{key}", _optional_time(segment, time_key)),))
        elif "timelineMemory" not in segment:
            raise ConversionError(f"{context}: expected timelinePath, visit, or activity")
    return tracks


def _takeout_tracks(objects: Any) -> list[Track]:
    tracks: list[Track] = []
    for index, value in enumerate(_array(objects, "timelineObjects")):
        context = f"timelineObjects[{index}]"
        item = _object(value, context)
        if "placeVisit" in item:
            visit = _object(item["placeVisit"], f"{context}.placeVisit")
            if "location" in visit:
                duration = _object(visit.get("duration", {}), f"{context}.duration")
                tracks.append((_point(visit["location"], f"{context}.location", _optional_time(duration, "startTimestamp", "startTimestampMs")),))
        elif "activitySegment" in item:
            activity = _object(item["activitySegment"], f"{context}.activitySegment")
            path = None
            for path_key, points_key in (("simplifiedRawPath", "points"), ("waypointPath", "waypoints")):
                if path_key in activity:
                    container = _object(activity[path_key], f"{context}.{path_key}")
                    candidates = _array(container.get(points_key, []), f"{context}.{path_key}.{points_key}")
                    if candidates:
                        path = []
                        for point_index, point in enumerate(candidates):
                            point_context = f"{context}.{path_key}.{points_key}[{point_index}]"
                            record = _object(point, point_context)
                            time = _optional_time(record, "timestamp", "timestampMs")
                            path.append(_point(record, point_context, time))
                        break
            if path:
                tracks.append(tuple(path))
            else:
                duration = _object(activity.get("duration", {}), f"{context}.duration")
                for key, time_keys in (
                    ("startLocation", ("startTimestamp", "startTimestampMs")),
                    ("endLocation", ("endTimestamp", "endTimestampMs")),
                ):
                    if key in activity:
                        tracks.append((_point(activity[key], f"{context}.{key}", _optional_time(duration, *time_keys)),))
        else:
            raise ConversionError(f"{context}: expected activitySegment or placeVisit")
    return tracks


def _parse_history(document: Any) -> list[Track]:
    if isinstance(document, list):
        return _phone_tracks(document, "timeline")
    root = _object(document, "export")
    tracks: list[Track] = []
    recognized = False
    for key in ("locations", "timelineObjects", "semanticSegments", "rawSignals"):
        if key not in root:
            continue
        recognized = True
        if key == "locations":
            tracks.extend(_raw_tracks(root[key], key))
        elif key == "timelineObjects":
            tracks.extend(_takeout_tracks(root[key]))
        elif key == "semanticSegments":
            tracks.extend(_phone_tracks(root[key], key))
        else:
            tracks.extend(_raw_tracks(root[key], key, signals=True))
    if not recognized:
        raise ConversionError(
            "unsupported export: expected a Timeline array or locations, timelineObjects, "
            "semanticSegments, or rawSignals"
        )
    return tracks


def distance_km(first: Point, second: Point) -> float:
    """Great-circle distance, including tracks crossing the date line."""
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(second.longitude - first.longitude)
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def convert_history(
    document: Any, *, max_gap_minutes: float = 30, max_distance_km: float = 10
) -> Conversion:
    """Convert one export, preserving source boundaries and splitting discontinuities.

    Invalid positional data fails the whole conversion; unrelated metadata is
    ignored. No coordinate, route, or timestamp is invented.
    """
    max_gap_minutes = _number(max_gap_minutes, "max_gap_minutes")
    max_distance_km = _number(max_distance_km, "max_distance_km")
    if max_gap_minutes <= 0 or not 0 < max_distance_km <= 10:
        raise ConversionError("gap must be positive; distance must be greater than 0 and at most 10 km")
    tracks: list[Track] = []
    for source in _parse_history(document):
        current: list[Point] = []
        for point in source:
            if current:
                previous = current[-1]
                if point == previous:
                    continue
                elapsed = None
                if point.time is not None and previous.time is not None:
                    elapsed = (point.time - previous.time).total_seconds()
                if (
                    distance_km(previous, point) > max_distance_km
                    or (elapsed is not None and (elapsed <= 0 or elapsed > max_gap_minutes * 60))
                ):
                    tracks.append(tuple(current))
                    current = []
            current.append(point)
        if current:
            tracks.append(tuple(current))
    if not tracks:
        raise ConversionError("export contains no usable location points")
    return Conversion(tuple(tracks))


def combine(conversions: Iterable[Conversion]) -> Conversion:
    """Keep input-file boundaries when merging several exports."""
    return Conversion(tuple(track for conversion in conversions for track in conversion.tracks))
