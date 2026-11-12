#!/usr/bin/env python3
"""Convert Google Maps Timeline JSON to Fog of World GPX, entirely offline."""

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple, Optional
from xml.etree import ElementTree as ET


class Point(NamedTuple):
    latitude: float
    longitude: float
    time: Optional[datetime] = None
    elevation: Optional[float] = None


def number(value):
    try:
        result = float(value)
        if isinstance(value, bool) or not math.isfinite(result):
            raise ValueError
        return result
    except (TypeError, ValueError, OverflowError):
        raise ValueError("expected a finite number") from None


def objects(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("expected an array of objects")
    return value


def record_time(record, *keys):
    for key in keys or ("timestamp", "time", "timestampMs"):
        if key not in record:
            continue
        try:
            if key.endswith("Ms"):
                return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                    milliseconds=number(record[key])
                )
            result = datetime.fromisoformat(record[key].replace("Z", "+00:00"))
            if result.tzinfo is None:
                raise ValueError
            return result.astimezone(timezone.utc)
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise ValueError("expected a valid timestamp with a timezone") from None
    return None


def point(location, time=None):
    elevation = None
    if isinstance(location, dict):
        for key in ("altitudeMeters", "altitude"):
            if key in location:
                elevation = number(location[key])
                break
        if "latLng" in location or "LatLng" in location:
            location = location.get("latLng", location.get("LatLng"))
    if isinstance(location, str):
        parts = location.strip().removeprefix("geo:").replace("°", "").split(",")
        if len(parts) != 2:
            raise ValueError("expected latitude,longitude")
        latitude, longitude = map(number, parts)
    elif isinstance(location, dict):
        for lat_key, lon_key, scale in (
            ("latitudeE7", "longitudeE7", 10_000_000),
            ("latE7", "lngE7", 10_000_000),
            ("latitude", "longitude", 1),
        ):
            if lat_key in location or lon_key in location:
                latitude = number(location.get(lat_key)) / scale
                longitude = number(location.get(lon_key)) / scale
                break
        else:
            raise ValueError("missing latitude or longitude")
    else:
        raise ValueError("invalid location")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("coordinates outside latitude/longitude bounds")
    return Point(latitude, -180.0 if longitude == 180 else longitude, time, elevation)


def raw_tracks(records):
    devices = defaultdict(list)
    for record in objects(records):
        time = record_time(record)
        if time is None:
            raise ValueError("raw location is missing a timestamp")
        device = record.get("deviceTag", "default")
        if isinstance(device, bool) or not isinstance(device, (str, int)):
            raise ValueError("invalid deviceTag")
        devices[str(device)].append(point(record, time))
    return [sorted(points, key=lambda item: item.time) for points in devices.values()]


def phone_tracks(segments):
    for segment in objects(segments):
        start, end = record_time(segment, "startTime"), record_time(segment, "endTime")
        if "timelinePath" in segment:
            path = []
            for item in objects(segment["timelinePath"]):
                time = record_time(item, "time")
                if time is None and "durationMinutesOffsetFromStartTime" in item:
                    offset = number(item["durationMinutesOffsetFromStartTime"])
                    if start is None or offset < 0:
                        raise ValueError("path offset requires startTime and nonnegative minutes")
                    try:
                        time = start + timedelta(minutes=offset)
                    except OverflowError:
                        raise ValueError("path timestamp offset is too large") from None
                if time is not None and (
                    (start is not None and time < start) or (end is not None and time > end)
                ):
                    raise ValueError("point time is outside its segment")
                path.append(point(item["point"], time))
            yield path
        elif "visit" in segment:
            location = segment["visit"].get("topCandidate", {}).get("placeLocation")
            if location is not None:
                yield [point(location, start)]
        elif "activity" in segment:
            for key, time in (("start", start), ("end", end)):
                if key in segment["activity"]:
                    yield [point(segment["activity"][key], time)]
        elif "timelineMemory" not in segment:
            raise ValueError("expected timelinePath, visit, or activity")


def takeout_tracks(items):
    for item in objects(items):
        if "placeVisit" in item:
            visit = item["placeVisit"]
            if "location" in visit:
                yield [point(visit["location"], record_time(
                    visit.get("duration", {}), "startTimestamp", "startTimestampMs"
                ))]
        elif "activitySegment" in item:
            activity = item["activitySegment"]
            path = activity.get("simplifiedRawPath", {}).get("points", [])
            path = path or activity.get("waypointPath", {}).get("waypoints", [])
            if path:
                yield [point(record, record_time(record)) for record in objects(path)]
            else:
                for key, times in (
                    ("startLocation", ("startTimestamp", "startTimestampMs")),
                    ("endLocation", ("endTimestamp", "endTimestampMs")),
                ):
                    if key in activity:
                        yield [point(activity[key], record_time(activity.get("duration", {}), *times))]
        else:
            raise ValueError("expected activitySegment or placeVisit")


def read_tracks(data):
    if isinstance(data, list):
        yield from phone_tracks(data)
        return
    keys = ("locations", "rawSignals", "semanticSegments", "timelineObjects")
    if not isinstance(data, dict) or not any(key in data for key in keys):
        raise ValueError("unsupported Timeline export")
    if "locations" in data:
        yield from raw_tracks(data["locations"])
    if "rawSignals" in data:
        positions = [item["position"] for item in objects(data["rawSignals"]) if "position" in item]
        yield from raw_tracks(positions)
    if "semanticSegments" in data:
        yield from phone_tracks(data["semanticSegments"])
    if "timelineObjects" in data:
        yield from takeout_tracks(data["timelineObjects"])


def distance_km(first, second):
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    dlon = math.radians(second.longitude - first.longitude)
    haversine = math.sin((lat2 - lat1) / 2) ** 2
    haversine += math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12742.0176 * math.asin(math.sqrt(min(1, max(0, haversine))))


def convert(data, max_gap_minutes=30, max_distance_km=10):
    max_gap_minutes, max_distance_km = number(max_gap_minutes), number(max_distance_km)
    if max_gap_minutes <= 0 or not 0 < max_distance_km <= 10:
        raise ValueError("gap must be positive; distance must be greater than 0 and at most 10 km")
    tracks = []
    for path in read_tracks(data):
        current = []
        for item in path:
            if current:
                previous = current[-1]
                if item == previous:
                    continue
                elapsed = None
                if item.time is not None and previous.time is not None:
                    elapsed = (item.time - previous.time).total_seconds()
                if distance_km(previous, item) > max_distance_km or (
                    elapsed is not None and (elapsed <= 0 or elapsed > max_gap_minutes * 60)
                ):
                    tracks.append(current)
                    current = []
            current.append(item)
        if current:
            tracks.append(current)
    if not tracks:
        raise ValueError("export contains no usable location points")
    return tracks


def to_gpx(tracks):
    ET.register_namespace("", "http://www.topografix.com/GPX/1/1")

    def tag(name):
        return "{http://www.topografix.com/GPX/1/1}" + name

    def decimal(value):
        return format(Decimal(str(value)), "f")

    root = ET.Element(tag("gpx"), version="1.1", creator="timeline_to_fog.py")
    track = ET.SubElement(root, tag("trk"))
    ET.SubElement(track, tag("name")).text = "Google Maps Timeline"
    for points in tracks:
        segment = ET.SubElement(track, tag("trkseg"))
        # Repeat isolated locations as zero-length tracks, not guessed routes.
        for item in points if len(points) > 1 else points * 2:
            node = ET.SubElement(
                segment, tag("trkpt"), lat=decimal(item.latitude), lon=decimal(item.longitude)
            )
            if item.elevation is not None:
                ET.SubElement(node, tag("ele")).text = decimal(item.elevation)
            if item.time is not None:
                ET.SubElement(node, tag("time")).text = item.time.isoformat().replace("+00:00", "Z")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def write_output(output, content, force):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.close()
            if force:
                temporary.replace(output)
            else:
                os.link(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="exported JSON files; extract ZIPs first")
    parser.add_argument("-o", "--output", type=Path, required=True, help="destination .gpx file")
    parser.add_argument("--force", action="store_true", help="replace existing output")
    parser.add_argument("--max-gap-minutes", type=float, default=30)
    parser.add_argument("--max-distance-km", type=float, default=10)
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() != ".gpx":
            raise ValueError("output filename must end in .gpx")
        if args.output.exists() and not args.force:
            raise ValueError("output already exists; use --force to replace it")
        tracks = []
        for source in args.inputs:
            if source.resolve() == args.output.resolve() or (
                source.exists() and args.output.exists() and source.samefile(args.output)
            ):
                raise ValueError("output must not replace an input file")
            with source.open(encoding="utf-8-sig") as handle:
                tracks.extend(convert(json.load(handle), args.max_gap_minutes, args.max_distance_km))
        write_output(args.output, to_gpx(tracks), args.force)
    except (json.JSONDecodeError, UnicodeError):
        parser.exit(2, f"error: {source}: expected a UTF-8 JSON export\n")
    except (KeyError, TypeError, AttributeError):
        parser.exit(2, f"error: {source}: malformed Timeline export\n")
    except (ValueError, OSError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"Wrote {len(tracks)} track segments to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
