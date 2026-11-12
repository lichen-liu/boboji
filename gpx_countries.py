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

    def distance_to(latitude, longitude, country, limit=math.inf):
        """Approximate kilometres to a country polygon; zero inside it.

        A finite limit restricts the search; infinity means no edge was found
        within that distance. The local tangent plane is intended for nearby
        borders, not surveying or distances across continents.
        """
        for west, south, east, north, label, edges in rows.get(math.floor(latitude), ()):
            if (label == country and west <= longitude <= east and south <= latitude <= north
                    and contains(edges, latitude, longitude)):
                return 0.0
        dy = min(180, limit / 111.195)
        sx = 111.195 * math.cos(math.radians(latitude))
        seen, best = set(), math.inf
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
                    squared = (ax + fraction * ex) ** 2 + (ay + fraction * ey) ** 2
                    if squared <= limit * limit:
                        best = min(best, squared)
        return math.sqrt(best)

    def nearby(latitude, longitude, radius):
        """Countries whose actual polygons intersect the supplied tolerance."""
        dy = min(180, radius / 111.195)
        dx = min(180, radius / (111.195 * max(1e-12, math.cos(math.radians(latitude)))))
        candidates = set()
        for band in range(max(-90, math.floor(latitude - dy)), min(90, math.floor(latitude + dy)) + 1):
            for west, south, east, north, label, _edges in rows.get(band, ()):
                if south - dy <= latitude <= north + dy and any(
                    west - dx <= longitude + shift <= east + dx for shift in (-360, 0, 360)
                ):
                    candidates.add(label)
        return {label for label in candidates if distance_to(latitude, longitude, label, radius) <= radius}

    lookup.distance_to = distance_to
    lookup.nearby = nearby
    lookup.near = lambda lat, lon, country, radius: distance_to(lat, lon, country, radius) <= radius
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


def gpx_samples(source, *, motion_groups=False):
    """Read points; motion groups distinguish recorded tracks from POIs/routes."""
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
            if motion_groups and node.tag != prefix + "trkpt":
                sequence = None
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
    raw_country: Optional[tuple] = None


def distance(first, second):
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta = math.radians(second.longitude - first.longitude)
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    return 12742.0176 * math.asin(math.sqrt(min(1, max(0, value))))


def reachable(first, second, max_speed_kmh, slack_meters):
    """Necessary displacement bound, allowing slack at both recorded positions."""
    seconds = (second.time - first.time).total_seconds()
    return seconds > 0 and distance(first, second) <= max_speed_kmh * seconds / 3600 + 2 * slack_meters / 1000


def motion_chunks(paths, ambiguous_times, max_gap_seconds):
    """Never reconstruct travel through logger breaks or conflicting epochs."""
    chunks, seen = [], set()
    for path in paths.values():
        current = []
        for fix in sorted(path.values(), key=lambda item: item.time):
            if fix.time in ambiguous_times:
                if len(current) >= 2 and tuple(current) not in seen:
                    seen.add(tuple(current))
                    chunks.append(current)
                current = []
                continue
            if current and (fix.time - current[-1].time).total_seconds() > max_gap_seconds:
                if len(current) >= 2 and tuple(current) not in seen:
                    seen.add(tuple(current))
                    chunks.append(current)
                current = []
            current.append(fix)
        if len(current) >= 2 and tuple(current) not in seen:
            seen.add(tuple(current))
            chunks.append(current)
    return chunks


def infer_coastal_countries(fixes, lookup, radius_meters, report):
    """Optional mapping tolerance; never erase an observed named country.

    Use immutable raw tracking labels as references. Assign only when the same
    country is observed on both sides and is the sole polygon within the
    supplied tolerance of the actual point. No hypothetical route is invented.
    """
    nearby = getattr(lookup, "nearby", None)
    if radius_meters is None or nearby is None:
        return
    epochs = defaultdict(list)
    for fix in fixes:
        if fix.time is not None and any(sequence is not None for sequence in fix.sequences):
            epochs[fix.time].append(fix)
    times = sorted(epochs)
    previous, following, country = {}, {}, None
    for time in times:
        if len(epochs[time]) > 1:
            country = None
        elif epochs[time][0].raw_country is not None:
            country = epochs[time][0].raw_country
        previous[time] = country
    country = None
    for time in reversed(times):
        if len(epochs[time]) > 1:
            country = None
        elif epochs[time][0].raw_country is not None:
            country = epochs[time][0].raw_country
        following[time] = country
    for time in times:
        country = previous[time]
        if country is None or country != following[time]:
            continue
        for fix in epochs[time]:
            if fix.raw_country is not None:
                continue
            if nearby(fix.latitude, fix.longitude, radius_meters / 1000) == {country}:
                fix.country = country
                report["inferred"] += fix.count
                depth = lookup.distance_to(fix.latitude, fix.longitude, country, radius_meters / 1000)
                report["max_inferred_distance_meters"] = max(report["max_inferred_distance_meters"], depth * 1000)
                report["decisions"].append((fix.time, "Unassigned", country[0], "explicit coastal tolerance", fix.count))


def denoise_samples(samples, lookup, enabled=True, *, gps_radius_meters=None,
                    max_speed_kmh=1500, max_gap_minutes=30, motion_slack_meters=1000):
    """Conservative screening of timed tracking observations.

    Ordinary movement can turn, stop, change mode, cross a border briefly, fly,
    or travel on water. Neither shape, dwell duration nor sample density proves
    GPS error. Exclude only isolated fixes requiring excessive speed on BOTH
    sides, with two corroborating observations on each side and a feasible
    bypass. Do not select a truth among overlapping/conflicting recordings.
    """
    if not enabled:
        fixes = [Fix(lat, lon, time, lookup(lat, lon), 1, {sequence}, lookup(lat, lon))
                 for lat, lon, time, sequence in samples]
        return fixes, {"enabled": False}
    unique, paths, epochs = {}, defaultdict(dict), defaultdict(set)
    total = 0
    for latitude, longitude, time, sequence in samples:
        total += 1
        # A waypoint/route point is not an independent tracking observation.
        key = latitude, longitude, time, sequence is not None
        fix = unique.get(key)
        if fix is None:
            country = lookup(latitude, longitude)
            fix = unique[key] = Fix(latitude, longitude, time, country, raw_country=country)
        fix.count += 1
        fix.sequences.add(sequence)
        if time is not None and sequence is not None:
            paths[sequence][key] = fix
            epochs[time].add(fix)
    fixes = list(unique.values())
    ambiguous_times = {time for time, items in epochs.items() if len(items) > 1}
    chunks = motion_chunks(paths, ambiguous_times, max_gap_minutes * 60)
    starts, ends = sorted(chunk[0].time for chunk in chunks), sorted(chunk[-1].time for chunk in chunks)
    tested, rejected, decisions = set(), set(), []
    for path in chunks:
        for index in range(2, len(path) - 2):
            before, first, fix, last, after = path[index - 2:index + 3]
            # Two overlapping tracks may be different devices/people, or two
            # competing estimates. More copies do not make one of them true.
            if bisect_right(starts, fix.time) - bisect_left(ends, fix.time) != 1:
                continue
            tested.add(fix)
            if (reachable(before, first, max_speed_kmh, motion_slack_meters)
                    and reachable(last, after, max_speed_kmh, motion_slack_meters)
                    and reachable(first, last, max_speed_kmh, motion_slack_meters)
                    and not reachable(first, fix, max_speed_kmh, motion_slack_meters)
                    and not reachable(fix, last, max_speed_kmh, motion_slack_meters)):
                rejected.add(fix)
                decisions.append((fix.time, fix.raw_country[0] if fix.raw_country else "Unassigned",
                                  "Excluded", "both legs exceed configured movement bound", fix.count))
    report = {"enabled": True, "input": total, "unique": len(fixes),
              "excluded": sum(fix.count for fix in rejected), "tested": len(tested),
              "conflicting_epochs": len(ambiguous_times), "inferred": 0,
              "max_inferred_distance_meters": 0, "gps_radius_meters": gps_radius_meters,
              "max_speed_kmh": max_speed_kmh, "max_gap_minutes": max_gap_minutes,
              "motion_slack_meters": motion_slack_meters, "decisions": decisions}
    retained = [fix for fix in fixes if fix not in rejected]
    infer_coastal_countries(retained, lookup, gps_radius_meters, report)
    return retained, report


def format_denoising(report):
    if not report["enabled"]:
        return "Denoising: off; original country assignments and all GPX points are shown."
    tolerance = ("none supplied; geometric country labels retained" if report["gps_radius_meters"] is None
                 else f"{report['gps_radius_meters']:g} m (explicit mapping assumption, not measured GPS accuracy)")
    return (f"Denoising: on · Input GPX points: {report['input']:,} · Distinct records: {report['unique']:,}\n"
            f"Excluded as motion outliers: {report['excluded']:,} GPX points · "
            f"Distinct tracking fixes checked: {report['tested']:,} · "
            f"Conflicting timestamp groups retained: {report['conflicting_epochs']:,}\n"
            f"Movement bounds: {report['max_speed_kmh']:g} km/h; "
            f"{report['motion_slack_meters']:g} m allowance per position; "
            f"{report['max_gap_minutes']:g} min maximum gap. These are assumptions, not fitted GPS accuracy.\n"
            f"Coastal tolerance: {tolerance}.\n"
            f"Country assignments inferred: {report['inferred']:,} · "
            f"Farthest inferred polygon distance: {report['max_inferred_distance_meters']:.1f} m.\n"
            "Named countries are not erased because a visit is short. Unassigned does not prove offshore.")


def format_decisions(report):
    rows = [(timestamp(time), original, result, str(count), reason)
            for time, original, result, reason, count in sorted(report.get("decisions", []), key=lambda item: item[0])]
    if not rows:
        return "No records were excluded or assigned a different country."
    return text_table(("Time (UTC)", "Raw country", "Analysis result", "GPX points", "Reason"), rows)


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
        name, code = country or ("Unassigned", "—")
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
        name, code = country or ("Unassigned", "—")
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
                        help="screen isolated tracking outliers using movement bounds (default: enabled)")
    parser.add_argument("--gps-radius-meters", type=float,
                        help="optional explicit coastal mapping tolerance; never inferred from route curvature")
    parser.add_argument("--max-speed-kmh", type=float, default=1500,
                        help="conservative travel-speed bound for isolated outliers (default: 1500)")
    parser.add_argument("--max-gap-minutes", type=float, default=30,
                        help="do not test movement across longer recording gaps (default: 30)")
    parser.add_argument("--motion-slack-meters", type=float, default=1000,
                        help="safety allowance per recorded position, not estimated accuracy (default: 1000)")
    parser.add_argument("--explain", action="store_true", help="print reasons for every excluded or inferred record")
    parser.set_defaults(timeline=False)
    args = parser.parse_args(argv)
    for flag, value in (("--gps-radius-meters", args.gps_radius_meters), ("--max-speed-kmh", args.max_speed_kmh),
                        ("--max-gap-minutes", args.max_gap_minutes), ("--motion-slack-meters", args.motion_slack_meters)):
        if value is not None and (not math.isfinite(value) or value < 0 or (value == 0 and flag != "--motion-slack-meters")):
            parser.error(f"{flag} must be finite and {'nonnegative' if flag == '--motion-slack-meters' else 'positive'}")
    try:
        with args.gpx.open("rb") as source:
            points = gpx_samples(source, motion_groups=True)
            first = next(points, None)
            if first is None:
                raise ValueError("GPX contains no track points, route points, or waypoints")
            lookup = country_lookup(load_countries(
                args.country_data or DEFAULT_COUNTRIES, download=args.country_data is None
            ))
            fixes, report = denoise_samples(chain((first,), points), lookup, enabled=args.denoise,
                                           gps_radius_meters=args.gps_radius_meters, max_speed_kmh=args.max_speed_kmh,
                                           max_gap_minutes=args.max_gap_minutes, motion_slack_meters=args.motion_slack_meters)
            labels = ((fix.country, fix.time, fix.count) for fix in fixes)
            output = (format_timeline(*group_timeline_labels(labels)) if args.timeline
                      else format_table(*summarize_labels(labels)))
            output += "\n" + format_denoising(report)
            if args.explain:
                output += "\n\n" + format_decisions(report)
        print(output)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(2, f"error: {error}\n")
    except (KeyError, TypeError, IndexError, AttributeError):
        parser.exit(2, "error: malformed country GeoJSON\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
