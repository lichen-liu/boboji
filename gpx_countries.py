#!/usr/bin/env python3
"""Print a table of countries/territories represented by recorded GPX points."""

import argparse
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
import json
import math
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from itertools import chain
from pathlib import Path
from statistics import median
from typing import Optional
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

DATA_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_10m_admin_0_countries.geojson"
)
DEFAULT_COUNTRIES = Path(__file__).resolve().parent / "var/ne_10m_admin_0_countries_ca96624.geojson"


def load_countries(path, download=False):
    if not path.exists() and download:
        print("Downloading public country boundaries; GPX coordinates stay local.", file=sys.stderr)
        path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(DATA_URL, headers={"User-Agent": "boboji-gpx-countries/1.0"})
        temporary = None
        try:
            with urlopen(request, timeout=60) as response:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    shutil.copyfileobj(response, handle)
            # Check the download before publishing the cache file.
            with temporary.open(encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("type") != "FeatureCollection" or not data.get("features"):
                raise ValueError("download is not a country GeoJSON FeatureCollection")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def contains(edges, latitude, longitude):
    inside = False
    for x1, y1, x2, y2 in edges:
        cross = (longitude - x1) * (y2 - y1) - (latitude - y1) * (x2 - x1)
        if (
            abs(cross) < 1e-10
            and min(x1, x2) <= longitude <= max(x1, x2)
            and min(y1, y2) <= latitude <= max(y1, y2)
        ):
            return True
        if (y1 > latitude) != (y2 > latitude):
            crossing = x1 + (latitude - y1) * (x2 - x1) / (y2 - y1)
            if longitude < crossing:
                inside = not inside
    return inside


def country_lookup(data):
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise ValueError("expected a country GeoJSON FeatureCollection")
    rows = defaultdict(list)
    for feature in data["features"]:
        properties, geometry = feature["properties"], feature["geometry"]
        name = properties.get("NAME_EN") or properties.get("ADMIN") or properties.get("name")
        code = next((properties[key] for key in ("ISO_A2_EH", "ISO_A2", "ADM0_A3")
                     if properties.get(key) not in (None, "", "-99")), "—")
        if not name:
            raise ValueError("country feature is missing its name")
        if geometry["type"] == "Polygon":
            polygons = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            polygons = geometry["coordinates"]
        else:
            raise ValueError("country geometry must be Polygon or MultiPolygon")
        for polygon in polygons:
            outer = polygon[0]
            west, east = min(p[0] for p in outer), max(p[0] for p in outer)
            south, north = min(p[1] for p in outer), max(p[1] for p in outer)
            bands = defaultdict(list)
            # Restrict ray casting to edges in the point's one-degree latitude band.
            # Keeping all rings together also excludes holes such as inland lakes.
            for ring in polygon:
                for first, second in zip(ring, ring[1:] + ring[:1]):
                    x1, y1 = first[:2]
                    x2, y2 = second[:2]
                    edge = x1, y1, x2, y2
                    for row in range(math.floor(min(y1, y2)), math.floor(max(y1, y2)) + 1):
                        bands[row].append(edge)
            for row, edges in bands.items():
                rows[row].append((west, south, east, north, (name, code), edges))

    @lru_cache(maxsize=100_000)
    def lookup(latitude, longitude):
        for west, south, east, north, country, edges in rows.get(math.floor(latitude), ()):
            if west <= longitude <= east and south <= latitude <= north:
                if contains(edges, latitude, longitude):
                    return country
        return None

    def near(latitude, longitude, country, radius):
        # Only inspect edges within the fitted uncertainty radius. Distances use
        # a local tangent plane, so this is an approximate geometric distance.
        dy = radius / 111.195
        sx = 111.195 * math.cos(math.radians(latitude))
        seen = set()
        for band in range(max(-90, math.floor(latitude - dy)), min(90, math.floor(latitude + dy)) + 1):
            for _west, _south, _east, _north, label, edges in rows.get(band, ()):
                if label != country:
                    continue
                for edge in edges:
                    if edge in seen:
                        continue
                    seen.add(edge)
                    x1, y1, x2, y2 = edge
                    x1 = (x1 - longitude + 180) % 360 - 180
                    x2 = x1 + (x2 - edge[0] + 180) % 360 - 180
                    shift = 360 * round((x1 + x2) / 720)
                    ax, ay = (x1 - shift) * sx, (y1 - latitude) * 111.195
                    bx, by = (x2 - shift) * sx, (y2 - latitude) * 111.195
                    ex, ey = bx - ax, by - ay
                    fraction = max(0, min(1, -(ax * ex + ay * ey) / (ex * ex + ey * ey))) if ex or ey else 0
                    if (ax + fraction * ex) ** 2 + (ay + fraction * ey) ** 2 <= radius ** 2:
                        return True
        return False

    lookup.near = near
    return lookup


def gpx_prefix(root):
    if root.tag not in (
        "gpx", "{http://www.topografix.com/GPX/1/0}gpx", "{http://www.topografix.com/GPX/1/1}gpx"
    ):
        raise ValueError("expected a GPX document")
    return root.tag[:-3]


def point_info(node, prefix):
    try:
        latitude, longitude = float(node.attrib["lat"]), float(node.attrib["lon"])
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            raise ValueError
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError
    except (KeyError, ValueError, OverflowError):
        raise ValueError("GPX point has invalid latitude/longitude") from None
    time = node.findtext(prefix + "time")
    if time:
        try:
            time = datetime.fromisoformat(time.strip().replace("Z", "+00:00"))
            if time.tzinfo is None:
                raise ValueError
            time = time.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise ValueError("GPX point time must include a valid timezone") from None
    else:
        time = None
    return latitude, longitude, time


def gpx_samples(source):
    events = ET.iterparse(source, events=("start", "end"))
    try:
        _, root = next(events)
    except StopIteration:
        raise ValueError("GPX file is empty") from None
    prefix = gpx_prefix(root)
    point_tags = {prefix + name for name in ("trkpt", "rtept", "wpt")}
    point_paths = {
        (root.tag, prefix + "wpt"),
        (root.tag, prefix + "rte", prefix + "rtept"),
        (root.tag, prefix + "trk", prefix + "trkseg", prefix + "trkpt"),
    }
    containers = {prefix + name for name in ("trkseg", "trk", "rte")}
    stack = [root]
    sequences, serial = {}, 0
    for event, node in events:
        if event == "start":
            stack.append(node)
            if node.tag in (prefix + "trkseg", prefix + "rte"):
                serial += 1
                sequences[node] = serial
            continue
        if node.tag in point_tags and tuple(item.tag for item in stack) in point_paths:
            if node.tag == prefix + "wpt":
                serial += 1
                sequence = serial
            else:
                sequence = sequences[stack[-2]]
            yield (*point_info(node, prefix), sequence)
        sequences.pop(node, None)
        if node.tag in point_tags or node.tag in containers:
            node.clear()
            stack[-2].remove(node)
        stack.pop()


def gpx_points(source):
    for latitude, longitude, time, _sequence in gpx_samples(source):
        yield latitude, longitude, time


def summarize(points, lookup):
    return summarize_labels((lookup(lat, lon), time, 1) for lat, lon, time in points)


def summarize_labels(points):
    countries = {}
    total = unassigned = 0
    for country, time, count in points:
        total += count
        unassigned += count if country is None else 0
        row = countries.setdefault(country, [0, None, None])
        row[0] += count
        if time is not None:
            row[1] = min(row[1], time) if row[1] is not None else time
            row[2] = max(row[2], time) if row[2] is not None else time
    return countries, total, unassigned


@dataclass(eq=False)
class Fix:
    latitude: float
    longitude: float
    time: Optional[datetime]
    country: Optional[tuple]
    count: int = 0
    sequences: set = field(default_factory=set)


def distance(first, second):
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta = math.radians(second.longitude - first.longitude)
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    return 12742.0176 * math.asin(math.sqrt(min(1, max(0, value))))


def interpolate(first, second, time):
    fraction = (time - first.time).total_seconds() / (second.time - first.time).total_seconds()
    longitude = first.longitude + fraction * ((second.longitude - first.longitude + 180) % 360 - 180)
    return Fix(first.latitude + fraction * (second.latitude - first.latitude),
               (longitude + 180) % 360 - 180, time, None)


def upper_fence(values):
    """Robust empirical upper bound, without a fixed speed/distance cutoff."""
    values = sorted(values)
    def quantile(fraction):
        index = fraction * (len(values) - 1)
        lower = math.floor(index)
        return values[lower] + (values[math.ceil(index)] - values[lower]) * (index - lower)
    return max(quantile(.9), quantile(.75) + 3 * (quantile(.75) - quantile(.25)))


def motion_profile(fixes, fallback=None):
    # Conflicting locations at one timestamp cannot train a movement model.
    by_time = defaultdict(list)
    for fix in fixes:
        by_time[fix.time].append(fix)
    fixes = [items[0] for _time, items in sorted(by_time.items()) if len(items) == 1]
    if len(fixes) < 2 or (len(fixes) < 5 and fallback is None):
        return None
    base = {"fixes": fixes, "times": [fix.time for fix in fixes], "fitted": len(fixes) >= 5}
    if len(fixes) < 5:
        return {**base, **fallback}
    gaps = [(b.time - a.time).total_seconds() for a, b in zip(fixes, fixes[1:])]
    speeds = [distance(a, b) / gap for a, b, gap in zip(fixes, fixes[1:], gaps)]
    errors = [distance(b, interpolate(a, c, b.time)) for a, b, c in zip(fixes, fixes[1:], fixes[2:])]
    return {**base,
            "gap": upper_fence(gaps), "speed": upper_fence(speeds),
            "error": upper_fence(errors), "cadence": median(gaps)}


def denoise_samples(samples, lookup, enabled=True):
    """Return classified fixes and an auditable count of conservative changes.

    Models are fitted separately to GPX track segments/routes, never to country
    residence duration. Unsupported observations and sustained transit remain.
    Exact duplicate fixes retain their GPX count but contribute once to fitting.
    """
    if not enabled:
        fixes = [Fix(lat, lon, time, lookup(lat, lon), 1, {sequence})
                 for lat, lon, time, sequence in samples]
        return fixes, {"enabled": False}
    unique, paths = {}, defaultdict(dict)
    total = 0
    for latitude, longitude, time, sequence in samples:
        total += 1
        key = latitude, longitude, time
        fix = unique.get(key)
        if fix is None:
            fix = unique[key] = Fix(latitude, longitude, time, lookup(latitude, longitude))
        fix.count += 1
        fix.sequences.add(sequence)
        if time is not None:
            paths[sequence][key] = fix
    fixes = list(unique.values())
    report = {"enabled": enabled, "input": total, "unique": len(fixes),
              "isolated": 0, "spikes": 0, "adjusted": 0}
    profiles = {sequence: profile for sequence, items in paths.items()
                if (profile := motion_profile(items.values())) is not None}
    report["fitted_paths"] = len(profiles)
    if profiles:
        pooled = {key: upper_fence([p[key] for p in profiles.values()])
                  for key in ("gap", "cadence", "speed", "error")}
        for sequence, items in paths.items():
            if sequence not in profiles and (profile := motion_profile(items.values(), pooled)) is not None:
                profiles[sequence] = profile
    support, spike_votes = defaultdict(set), defaultdict(set)
    for sequence, profile in profiles.items():
        path = profile["fixes"]
        for fix in path:
            support[fix].add(sequence)
        for a, b, c in zip(path, path[1:], path[2:]):
            left, right = (b.time - a.time).total_seconds(), (c.time - b.time).total_seconds()
            if max(left, right) > profile["gap"]:
                continue
            if (distance(a, b) / left > profile["speed"] + 1e-6
                    and distance(b, c) / right > profile["speed"] + 1e-6
                    and distance(a, c) / (left + right) <= profile["speed"]
                    and distance(b, interpolate(a, c, b.time)) > profile["error"] + 1e-6):
                spike_votes[b].add(sequence)
    rejected = {fix for fix, votes in spike_votes.items() if votes == support[fix]}
    report["spikes"] = sum(fix.count for fix in rejected)

    # Compare isolated visits/endpoints with independently supported paths.
    supported = sorted(((fix.time, sequence) for sequence, p in profiles.items()
                        for fix in p["fixes"] if fix not in rejected), key=lambda item: item[0])
    times = [time for time, _sequence in supported]
    for fix in fixes:
        if fix.time is None or fix in rejected or any(len(paths[s]) > 1 for s in fix.sequences):
            continue
        index = bisect_left(times, fix.time)
        neighboring_times = {time for time, _sequence in supported[max(0, index - 2):index + 2]}
        candidates = {sequence for time in neighboring_times
                      for _time, sequence in supported[bisect_left(times, time):bisect_right(times, time)]}
        conflicts = []
        for sequence in candidates:
            p = profiles[sequence]
            index_in_path = bisect_left(p["times"], fix.time)
            local = motion_profile(p["fixes"][max(0, index_in_path - 6):index_in_path + 7]) or p
            # Use a nearby regular pair, including a short extrapolation when
            # the candidate lies just outside a path or within a sampling gap.
            neighbors = p["fixes"][max(0, index_in_path - 3):index_in_path + 3]
            pairs = [(a, b) for a, b in zip(neighbors, neighbors[1:])
                     if a not in rejected and b not in rejected
                     and (b.time - a.time).total_seconds() <= local["gap"]
                     and min(abs((fix.time - a.time).total_seconds()),
                             abs((fix.time - b.time).total_seconds())) <= local["cadence"]]
            if not pairs:
                continue
            a, b = min(pairs, key=lambda pair: max(abs((fix.time - item.time).total_seconds()) for item in pair))
            gap = min(abs((fix.time - a.time).total_seconds()), abs((fix.time - b.time).total_seconds()))
            predicted = interpolate(a, b, fix.time)
            if not -90 <= predicted.latitude <= 90:
                continue
            neighbor = min((a, b), key=lambda item: abs((fix.time - item.time).total_seconds()))
            # Account for both fitted position scatter and possible movement
            # since the closest supported timestamp (speeds are in km/second).
            conflicts.append(distance(fix, predicted) > local["error"] + 1e-6
                             and distance(fix, neighbor) > local["error"] + local["speed"] * gap + 1e-6)
        if conflicts and all(conflicts):
            rejected.add(fix)
            report["isolated"] += fix.count

    near = getattr(lookup, "near", None)
    proposals = defaultdict(dict)
    for sequence, p in profiles.items():
        if not p["fitted"]:
            continue
        path = [fix for fix in p["fixes"] if fix not in rejected]
        runs = []
        for fix in path:
            if not runs or runs[-1][0].country != fix.country:
                runs.append([fix])
            else:
                runs[-1].append(fix)
        for previous, middle, following in zip(runs, runs[1:], runs[2:]):
            a, b = previous[-1], following[0]
            country = a.country
            if country is None or b.country != country or near is None:
                continue
            if ((middle[-1].time - middle[0].time).total_seconds() > p["cadence"]
                    or (middle[0].time - a.time).total_seconds() > p["gap"]
                    or (b.time - middle[-1].time).total_seconds() > p["gap"]):
                continue
            if all(near(fix.latitude, fix.longitude, country, p["error"])
                   and lookup(predicted.latitude, predicted.longitude) == country
                   and distance(fix, predicted) <= p["error"] + 1e-6
                   for fix in middle for predicted in [interpolate(a, b, fix.time)]):
                for fix in middle:
                    proposals[fix][sequence] = country
    for fix, votes in proposals.items():
        countries = set(votes.values())
        if set(votes) == support[fix] and len(countries) == 1:
            fix.country = countries.pop()
            report["adjusted"] += fix.count
    return [fix for fix in fixes if fix not in rejected], report


def format_denoising(report):
    if not report["enabled"]:
        return "Denoising: off; original country assignments and all GPX points are shown."
    text = (f"Denoising: on · Input GPX points: {report['input']:,} · Distinct observations: {report['unique']:,}\n"
            f"Excluded GPX points: {report['isolated'] + report['spikes']:,} "
            f"(isolated conflicts: {report['isolated']:,}; path spikes: {report['spikes']:,}) · "
            f"Boundary assignments adjusted: {report['adjusted']:,}\n"
            "Limits use observed cadence, speeds, and position scatter; uncertain/offshore points remain.")
    if not report["fitted_paths"]:
        text += "\nInsufficient supported path context; observations left unchanged."
    return text


def timestamp(value):
    if value is None:
        return "—"
    text = value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return text[:-1].rstrip("0") + "Z" if "." in text else text


def text_table(headers, rows):
    widths = [max(len(row[column]) for row in [headers, *rows]) for column in range(len(headers))]

    def line(row):
        return "| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |"

    return "\n".join([line(headers), line(["-" * width for width in widths]), *(line(row) for row in rows)])


def format_table(countries, total, unassigned):
    headers = ("Country / territory", "Code", "GPX points", "First recorded (UTC)", "Last recorded (UTC)")
    rows = []
    for country, (count, first, last) in sorted(
        countries.items(), key=lambda item: (item[0] is None, item[0] or ("", ""))
    ):
        name, code = country or ("Unassigned / offshore", "—")
        rows.append((name, code, f"{count:,}", timestamp(first), timestamp(last)))
    count = sum(country is not None for country in countries)
    lines = [text_table(headers, rows), "",
             f"Countries/territories: {count} · GPX points: {total:,} · Unassigned: {unassigned:,}",
             "First/last are recorded timestamps, not continuous stays. — = no recorded timestamp."]
    return "\n".join(lines)


def group_timeline(points, lookup):
    return group_timeline_labels((lookup(lat, lon), time, 1) for lat, lon, time in points)


def group_timeline_labels(points):
    timed, undated = [], defaultdict(int)
    total = unassigned = untimed = 0
    for country, time, count in points:
        total += count
        unassigned += count if country is None else 0
        untimed += count if time is None else 0
        if time is None:
            undated[country] += count
        else:
            timed.append((time, country, count))
    timed.sort(key=lambda item: item[0])
    periods = []
    for time, country, count in timed:
        if not periods or periods[-1][0] != country:
            periods.append([country, count, time, time])
        else:
            periods[-1][1] += count
            periods[-1][3] = time
    for country, count in sorted(undated.items(), key=lambda item: (item[0] is None, item[0] or ("", ""))):
        periods.append([country, count, None, None])
    return periods, total, unassigned, untimed


def format_timeline(periods, total, unassigned, untimed):
    headers = ("Country / territory", "Code", "GPX points", "Begin (UTC)", "End (UTC)", "Recorded span")
    rows = []
    for country, count, begin, end in periods:
        name, code = country or ("Unassigned / offshore", "—")
        span = str(end - begin) if begin is not None else "—"
        if "." in span:
            span = span.rstrip("0")
        rows.append((name, code, f"{count:,}", timestamp(begin), timestamp(end), span))
    countries = {country for country, _, _, _ in periods if country is not None}
    timed_periods = sum(begin is not None for _, _, begin, _ in periods)
    lines = [text_table(headers, rows), "",
             f"Countries/territories: {len(countries)} · Recorded periods: {timed_periods:,}",
             f"GPX points represented: {total:,} · Unassigned: {unassigned:,} · Untimed: {untimed:,}",
             "Rows group consecutive countries after sorting UTC timestamps; returns start new rows.",
             "Recorded span = end minus begin, based on samples; continuous presence is not implied."]
    if any(begin is None for _, _, begin, _ in periods):
        lines.append("Untimed points are grouped by country at the end; — = no recorded timestamp.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpx", type=Path, help="input .gpx file")
    parser.add_argument("--country-data", type=Path, help="existing Natural Earth country GeoJSON (offline)")
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--timeline", dest="timeline", action="store_true",
                      help="show country periods from oldest to newest, including return visits")
    view.add_argument("--summary", dest="timeline", action="store_false",
                      help="show the alphabetical country summary (default)")
    parser.add_argument("--denoise", action=argparse.BooleanOptionalAction, default=True,
                        help="filter conflicting observations and smooth supported boundary jitter (default: enabled)")
    parser.set_defaults(timeline=False)
    args = parser.parse_args(argv)
    try:
        with args.gpx.open("rb") as source:
            points = gpx_samples(source)
            first = next(points, None)
            if first is None:
                raise ValueError("GPX contains no track points, route points, or waypoints")
            lookup = country_lookup(load_countries(
                args.country_data or DEFAULT_COUNTRIES, download=args.country_data is None
            ))
            fixes, report = denoise_samples(chain((first,), points), lookup, enabled=args.denoise)
            labels = ((fix.country, fix.time, fix.count) for fix in fixes)
            output = (format_timeline(*group_timeline_labels(labels)) if args.timeline
                      else format_table(*summarize_labels(labels)))
            output += "\n" + format_denoising(report)
        print(output)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(2, f"error: {error}\n")
    except (KeyError, TypeError, IndexError, AttributeError):
        parser.exit(2, "error: malformed country GeoJSON\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
