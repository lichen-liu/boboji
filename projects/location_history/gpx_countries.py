#!/usr/bin/env python3
"""Print a table of countries/territories represented by recorded GPX points."""

import argparse
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
REFERENCE_VERSION = "9469f09592ced973a3448cf66b6100b741b64c0d"
REFERENCE_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/" + REFERENCE_VERSION
    + "/releaseData/gbOpen/{iso3}/ADM0/geoBoundaries-{iso3}-ADM0_simplified.geojson"
)
MAX_AUTO_COAST_METERS = 10_000


def load_countries(path, download=False, url=DATA_URL):
    if not path.exists() and download:
        print("Downloading public country boundaries; GPX coordinates stay local.", file=sys.stderr)
        path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "boboji-gpx-countries/1.0"})
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
    rows, iso3 = defaultdict(list), {}
    for feature in data["features"]:
        properties, geometry = feature["properties"], feature["geometry"]
        name = properties.get("NAME_EN") or properties.get("ADMIN") or properties.get("name")
        code = next((properties[key] for key in ("ISO_A2_EH", "ISO_A2", "ADM0_A3")
                     if properties.get(key) not in (None, "", "-99")), "—")
        if not name:
            raise ValueError("country feature is missing its name")
        iso3[(name, code)] = next((properties[key] for key in ("ISO_A3_EH", "ISO_A3", "ADM0_A3")
                                  if isinstance(properties.get(key), str) and len(properties[key]) == 3
                                  and properties[key].isascii() and properties[key].isalpha()), None)
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
    lookup.iso3 = iso3
    lookup.near = lambda lat, lon, country, radius: distance_to(lat, lon, country, radius) <= radius
    return lookup


def load_coastal_reference(country, iso3, cache_dir=None):
    """Fetch only public country geometry, then reuse the cached copy offline."""
    if iso3 is None:
        return None
    path = (cache_dir or DEFAULT_COUNTRIES.parent / "coastlines") / f"gbopen_{REFERENCE_VERSION}_{iso3}_adm0.geojson"
    try:
        data = load_countries(path, download=True, url=REFERENCE_URL.format(iso3=iso3))
        # Keep Natural Earth's names/codes; this reference supplies geometry.
        for feature in data["features"]:
            feature["properties"] = {"NAME_EN": country[0], "ISO_A2": country[1]}
        return country_lookup(data)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        print(f"Detailed coastline unavailable for {country[0]}; unsupported gaps remain unassigned.", file=sys.stderr)
        return None


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
    reference_country: Optional[tuple] = None


def distance(first, second):
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta = math.radians(second.longitude - first.longitude)
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    return 12742.0176 * math.asin(math.sqrt(min(1, max(0, value))))


def reachable(first, second, max_speed_kmh, slack_meters):
    """Necessary displacement bound, allowing slack at both recorded positions."""
    seconds = (second.time - first.time).total_seconds()
    return seconds > 0 and distance(first, second) <= max_speed_kmh * seconds / 3600 + 2 * slack_meters / 1000


@dataclass(frozen=True)
class DenoisePolicy:
    max_speed_kmh: float = 1000
    max_gap_minutes: float = 60
    position_allowance_meters: float = 10000

    def __post_init__(self):
        for name, value in (("max_speed_kmh", self.max_speed_kmh),
                            ("max_gap_minutes", self.max_gap_minutes),
                            ("position_allowance_meters", self.position_allowance_meters)):
            if not math.isfinite(value) or value < 0 or value == 0 and name != "position_allowance_meters":
                raise ValueError(f"invalid denoising policy: {name}")

    def feasible(self, first, second):
        return reachable(first, second, self.max_speed_kmh, self.position_allowance_meters)

    def gap_ok(self, first_time, second_time):
        return 0 < (second_time - first_time).total_seconds() <= self.max_gap_minutes * 60


DEFAULT_POLICY = DenoisePolicy()


def tracking_epochs(fixes):
    """One chronological unit per timestamp; duplicate records never vote."""
    epochs = defaultdict(list)
    for fix in fixes:
        if fix.time is not None and any(seq is not None for seq in fix.sequences):
            epochs[fix.time].append(fix)
    return dict(sorted(epochs.items()))


def normalize_samples(samples, lookup):
    unique = {}
    for lat, lon, time, sequence in samples:
        key = lat, lon, time, sequence is not None
        if key not in unique:
            country = lookup(lat, lon)
            unique[key] = Fix(lat, lon, time, country, raw_country=country)
        unique[key].count += 1
        unique[key].sequences.add(sequence)
    # Equal-time order is deterministic during denoising. Raw mode preserves
    # original order; conflicts never acquire precedence from XML ordering.
    return sorted(unique.values(), key=lambda f: (f.time is None,
                  f.time or datetime.max.replace(tzinfo=timezone.utc), f.latitude, f.longitude,
                  any(seq is not None for seq in f.sequences)))


def epoch_pair_feasible(first, second, policy):
    return all(policy.feasible(a, b) for a in first for b in second)


def motion_outliers(epochs, policy):
    """One isolated-epoch rule for all recorded tracks, independent of segments.

    Both legs must fail against every neighboring position alternative while
    every bypass alternative is feasible. Decisions use the original epochs;
    removals never manufacture support for another removal.
    """
    times, proposed, checked = list(epochs), set(), set()
    for i in range(1, len(times) - 1):
        left, time, right = times[i - 1:i + 2]
        if not policy.gap_ok(left, time) or not policy.gap_ok(time, right):
            continue
        if not epoch_pair_feasible(epochs[left], epochs[right], policy):
            continue
        for fix in epochs[time]:
            checked.add(fix)
            if (all(not policy.feasible(a, fix) for a in epochs[left])
                    and all(not policy.feasible(fix, b) for b in epochs[right])):
                proposed.add(fix)
    # Competing hypotheses must not delete the observations supporting each
    # other's bypass (e.g. two interleaved, individually coherent recordings).
    rejected = set()
    for i in range(1, len(times) - 1):
        if not any(f in proposed for t in (times[i - 1], times[i + 1]) for f in epochs[t]):
            rejected.update(f for f in epochs[times[i]] if f in proposed)
    return rejected, checked


def adjudicate_maps(fixes, lookup, reference, report, named_enabled=True, unknown_enabled=True):
    """Adjudicate coordinates, independent of visit duration or row ordering.

    A named original's reference must exclude the coordinate; an unassigned
    coordinate has no source reference to check. All nearby alternatives must
    be available, and exactly one may include it. This is geographic evidence,
    not visit proof. Domain flags control named and unassigned refinement.
    """
    nearby = getattr(lookup, "nearby", None)
    if reference is None or nearby is None:
        return
    for fix in fixes:
        original = fix.raw_country
        if original is None and not unknown_enabled or original is not None and not named_enabled:
            continue
        alternatives = nearby(fix.latitude, fix.longitude, MAX_AUTO_COAST_METERS / 1000) - {original}
        if not alternatives:
            continue
        if original is not None:
            source = reference(original)
            if source is None:
                report["map_unavailable"].add(original[0])
                continue
            if source(fix.latitude, fix.longitude) is not None:
                continue
        covered, complete = [], True
        for country in sorted(alternatives):
            boundary = reference(country)
            if boundary is None:
                report["map_unavailable"].add(country[0])
                complete = False
                break
            if boundary(fix.latitude, fix.longitude) == country:
                covered.append(country)
        if complete and len(covered) == 1:
            country = covered[0]
            fix.country = fix.reference_country = country
            if original is None:
                report["reference_confirmed"] += fix.count
            else:
                report["border_corrected"] += fix.count
            report["decisions"].append((fix.time, original[0] if original else "Unassigned", country[0],
                                        "reference country polygon" if original is None else
                                        "reference maps agree on boundary correction", fix.count))


def infer_single_epoch_visits(fixes, lookup, evidence, policy, report, country_radius_meters=None,
                             include_unassigned=True):
    """Resolve unconfirmed country excursions within the declared uncertainty.

    Two distinct confirming epochs on EACH side must support the same country.
    A single differing epoch (named or unassigned) needs to be within that
    country's polygon allowance and have feasible movement throughout. Apply
    all proposals together against a frozen post-map snapshot; no cascading.
    """
    distance_to = getattr(lookup, "distance_to", None)
    allowance = policy.position_allowance_meters if country_radius_meters is None else country_radius_meters
    if distance_to is None or allowance <= 0:
        return
    epochs = tracking_epochs(fixes)
    times = list(epochs)
    labels = {time: {evidence[f] for f in epoch} for time, epoch in epochs.items()}
    proposals = []
    for i in range(2, len(times) - 2):
        window = times[i - 2:i + 3]
        candidate = window[2]
        if len(labels[candidate]) != 1:
            continue  # Conflicting simultaneous country evidence is a barrier.
        if labels[candidate] == {None} and not include_unassigned:
            continue
        anchors = [labels[window[j]] for j in (0, 1, 3, 4)]
        country = next(iter(anchors[0])) if len(anchors[0]) == 1 else None
        if country is None or any(label != {country} for label in anchors) or labels[candidate] == {country}:
            continue
        if not all(policy.gap_ok(a, b) and epoch_pair_feasible(epochs[a], epochs[b], policy)
                   for a, b in zip(window, window[1:])):
            continue
        if not epoch_pair_feasible(epochs[window[1]], epochs[window[3]], policy):
            continue
        radius = allowance / 1000
        if all(distance_to(f.latitude, f.longitude, country, radius) <= radius for f in epochs[candidate]):
            proposals.extend((f, country) for f in epochs[candidate])
    for fix, country in proposals:
        original = evidence[fix]
        fix.country = country
        report["visit_inferred"] += fix.count
        report["decisions"].append((fix.time, original[0] if original else "Unassigned", country[0],
                                    "unconfirmed one-epoch excursion within position allowance", fix.count))


def infer_coastal_countries(fixes, lookup, radius_meters, report, reference=None, position_allowance=0, evidence=None):
    """Resolve remaining unknown gaps against frozen geographic evidence.

    Use immutable raw tracking labels as references. Assign only when the same
    country is observed on both sides and is the sole polygon within the
    tolerance of the actual point. Direct reference coverage was already
    adjudicated before freezing evidence. The declared positional allowance
    or manual override is the only context radius; sample offsets never train it.
    """
    nearby = getattr(lookup, "nearby", None)
    if nearby is None or (radius_meters is None and reference is None):
        return
    epochs = defaultdict(list)
    for fix in fixes:
        if fix.time is not None and any(sequence is not None for sequence in fix.sequences):
            epochs[fix.time].append(fix)
    times = sorted(epochs)
    evidence = evidence if evidence is not None else {f: f.reference_country or f.raw_country for f in fixes}
    states = {time: {evidence[f] for f in epochs[time] if evidence[f] is not None} for time in times}
    previous, following, country = {}, {}, None
    for time in times:
        labels = states[time]
        if labels:
            country = next(iter(labels)) if len(labels) == 1 else None
        previous[time] = country
    country = None
    for time in reversed(times):
        labels = states[time]
        if labels:
            country = next(iter(labels)) if len(labels) == 1 else None
        following[time] = country
    candidates = defaultdict(list)
    for time in times:
        country = previous[time]
        if country is None or country != following[time]:
            continue
        for fix in epochs[time]:
            if evidence[fix] is None and fix.country is None:
                candidates[country].append(fix)
    for country, points in candidates.items():
        radius = radius_meters
        if radius is None:
            points = [fix for fix in points if nearby(fix.latitude, fix.longitude,
                                                     MAX_AUTO_COAST_METERS / 1000) == {country}]
            if not points:
                continue
            if reference(country) is None:
                report["coastal_unavailable"].append(country[0])
                continue
            radius = min(MAX_AUTO_COAST_METERS, position_allowance)
            if radius <= 0:
                continue
            if country[0] not in dict(report["coastal_effective"]):
                report["coastal_effective"].append((country[0], radius))
        for fix in points:
            if nearby(fix.latitude, fix.longitude, radius / 1000) == {country}:
                fix.country = country
                report["inferred"] += fix.count
                depth = lookup.distance_to(fix.latitude, fix.longitude, country, radius / 1000)
                report["max_inferred_distance_meters"] = max(report["max_inferred_distance_meters"], depth * 1000)
                reason = ("coastal continuity within position/map allowance" if radius_meters is None else "explicit coastal tolerance")
                report["decisions"].append((fix.time, "Unassigned", country[0], reason, fix.count))



def remove_unassigned_fixes(fixes, report):
    """Final output policy: drop unresolved records without inferring a country."""
    retained = []
    for fix in fixes:
        if fix.country is None:
            report["unassigned_removed"] += fix.count
            report["decisions"].append((fix.time, "Unassigned", "Removed", "final unassigned-removal policy", fix.count))
        else:
            retained.append(fix)
    return retained


def denoise_samples(samples, lookup, enabled=True, *, gps_radius_meters=None,
                    max_speed_kmh=DEFAULT_POLICY.max_speed_kmh,
                    max_gap_minutes=DEFAULT_POLICY.max_gap_minutes,
                    motion_slack_meters=DEFAULT_POLICY.position_allowance_meters,
                    coastal=True, coastal_reference=None, borders=True, visits=True,
                    remove_unassigned=True, motion=True):
    """Normalize → motion → map evidence → visit/coast context → output policy.

    Every stage uses immutable observation evidence. Only geometry-backed map
    corrections can become evidence for country context; inferred visits and
    coastal labels never become anchors or calibration observations.
    enabled=False bypasses every stage, regardless of individual stage switches.
    """
    if not enabled:
        fixes = [Fix(lat, lon, time, lookup(lat, lon), 1, {sequence}, lookup(lat, lon))
                 for lat, lon, time, sequence in samples]
        return fixes, {"enabled": False}
    policy = DenoisePolicy(max_speed_kmh, max_gap_minutes, motion_slack_meters)
    if gps_radius_meters is not None and (not math.isfinite(gps_radius_meters) or gps_radius_meters <= 0):
        raise ValueError("invalid coastal radius")
    fixes = normalize_samples(samples, lookup)
    epochs = tracking_epochs(fixes)
    rejected, checked = motion_outliers(epochs, policy) if motion else (set(), set())
    decisions = [(f.time, f.raw_country[0] if f.raw_country else "Unassigned", "Excluded",
                  "both legs exceed configured movement bound", f.count) for f in rejected]
    report = {"enabled": True, "input": sum(f.count for f in fixes), "unique": len(fixes),
              "excluded": sum(f.count for f in rejected), "tested": len(checked), "motion_enabled": motion,
              "conflicting_epochs": sum(len(epoch) > 1 for epoch in epochs.values()), "inferred": 0,
              "coastal_enabled": coastal, "coastal_automatic": gps_radius_meters is None and coastal_reference is not None,
              "coastal_models": [], "coastal_unavailable": [], "reference_confirmed": 0,
              "coastal_effective": [], "border_corrected": 0, "borders_enabled": borders,
              "visit_inferred": 0, "visits_enabled": visits,
              "unassigned_removed": 0, "remove_unassigned_enabled": remove_unassigned,
              "map_unavailable": set(),
              "max_inferred_distance_meters": 0, "gps_radius_meters": gps_radius_meters,
              "max_speed_kmh": max_speed_kmh, "max_gap_minutes": max_gap_minutes,
              "motion_slack_meters": motion_slack_meters, "decisions": decisions}
    retained = [f for f in fixes if f not in rejected]
    if borders or coastal:
        adjudicate_maps(retained, lookup, coastal_reference, report, borders, coastal)
    # Observed geometry offsets are diagnostic only. They never supply a
    # tolerance or depend on a context guess.
    covered = defaultdict(list)
    for fix in retained:
        if fix.raw_country is None and fix.reference_country is not None:
            covered[fix.reference_country].append(fix)
    for country, points in covered.items():
        offsets = [lookup.distance_to(f.latitude, f.longitude, country, MAX_AUTO_COAST_METERS / 1000) * 1000 for f in points]
        report["coastal_models"].append((country[0], len({(f.latitude, f.longitude) for f in points}), math.ceil(max(offsets))))
        report["coastal_effective"].append((country[0], min(MAX_AUTO_COAST_METERS, motion_slack_meters)))
    evidence = {f: f.country for f in retained}
    if visits:
        infer_single_epoch_visits(retained, lookup, evidence, policy, report, gps_radius_meters,
                                 include_unassigned=coastal)
    if coastal:
        infer_coastal_countries(retained, lookup, gps_radius_meters, report, coastal_reference,
                               motion_slack_meters, evidence=evidence)
    final_epochs = tracking_epochs(retained)
    report["unresolved_country_epochs"] = sum(len({f.country for f in epoch}) > 1 for epoch in final_epochs.values())
    report["unresolved_motion"] = []
    times = list(final_epochs)
    for left, right in zip(times, times[1:]):
        if policy.gap_ok(left, right) and not any(policy.feasible(a, b) for a in final_epochs[left] for b in final_epochs[right]):
            report["unresolved_motion"].append((left, right))
    # Diagnose the evidence before filtering so removal cannot hide a retained
    # contradiction or create a new inference/anchor across the removed gap.
    if remove_unassigned:
        retained = remove_unassigned_fixes(retained, report)
    report["decisions"].sort(key=decision_sort_key)
    report["map_unavailable"] = sorted(report["map_unavailable"])
    return retained, report


def decision_sort_key(row):
    return row[0] is None, row[0] or datetime.max.replace(tzinfo=timezone.utc), row[1], row[2], row[3], row[4]


def format_denoising(report):
    if not report["enabled"]:
        return "Denoising: off; original country assignments and all GPX points are shown."
    tolerance = ("none supplied; geometric country labels retained" if report["gps_radius_meters"] is None
                 else f"{report['gps_radius_meters']:g} m (explicit mapping assumption, not measured GPS accuracy)")
    if not report["coastal_enabled"]:
        tolerance = "off"
    elif report["coastal_automatic"]:
        effective = dict(report["coastal_effective"])
        observed = {name: (locations, radius) for name, locations, radius in report["coastal_models"]}
        models = "; ".join((f"{name}: {effective[name]:,} m effective; map disagreement {observed[name][1]:,} m "
                            f"from {observed[name][0]:,} reference-confirmed locations") if name in observed else
                           f"{name}: {effective[name]:,} m position allowance; no observed map offset"
                           for name in sorted(effective))
        tolerance = "automatic from reference country polygons and the position allowance"
        tolerance += ". " + (models or "No supported mapping band found")
        if report["coastal_unavailable"]:
            tolerance += ". Reference unavailable: " + ", ".join(report["coastal_unavailable"])
    return (f"Denoising: on · Input GPX points: {report['input']:,} · Distinct records: {report['unique']:,}\n"
            f"Excluded as motion outliers: {report['excluded']:,} GPX points "
            f"({'enabled' if report['motion_enabled'] else 'disabled'}) · "
            f"Distinct tracking fixes checked: {report['tested']:,} · "
            f"Conflicting timestamp groups observed: {report['conflicting_epochs']:,}\n"
            f"Movement bounds: {report['max_speed_kmh']:g} km/h; "
            f"{report['motion_slack_meters']:g} m allowance per position; "
            f"{report['max_gap_minutes']:g} min maximum gap. These are assumptions, not fitted GPS accuracy.\n"
            f"Coastal tolerance: {tolerance}.\n"
            f"Country assignments inferred: {report['inferred']:,} · "
            f"Reference-covered GPX points: {report['reference_confirmed']:,} · "
            f"Farthest inferred polygon distance: {report['max_inferred_distance_meters']:.1f} m.\n"
            f"Visit-context inferences: {report['visit_inferred']:,} "
            f"({'enabled' if report['visits_enabled'] else 'disabled'}).\n"
            f"Border-map corrections: {report['border_corrected']:,} "
            f"({'enabled' if report['borders_enabled'] else 'disabled'}).\n"
            f"Unassigned removal: {'on' if report['remove_unassigned_enabled'] else 'off'} · "
            f"Removed unassigned GPX points: {report['unassigned_removed']:,}.\n"
            "Diagnostics below describe evidence before final unassigned removal.\n"
            f"Unresolved simultaneous country alternatives: {report['unresolved_country_epochs']:,} · "
            f"Unresolved movement transitions: {len(report['unresolved_motion']):,}.\n"
            f"Unavailable border references: {', '.join(report['map_unavailable']) or 'none'}.\n"
            "Duration alone does not erase a named country. Coastal labels are approximate visit context, not proof of land presence.")


def format_decisions(report):
    rows = [(timestamp(time), original, result, str(count), reason)
            for time, original, result, reason, count in sorted(report.get("decisions", []), key=decision_sort_key)]
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
    if any(a[3] is not None and a[3] == b[2] and a[0] != b[0] for a, b in zip(periods, periods[1:])):
        lines.append("Different countries at the same timestamp are unresolved alternatives; their row order does not establish travel.")
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
    denoising = parser.add_argument_group(
        "Denoising", "Enabled by default. --no-denoise bypasses the entire pipeline, "
        "regardless of individual stage switches. Stage switches apply while denoising is enabled.")
    denoising.add_argument("--denoise", action=argparse.BooleanOptionalAction, default=True,
                          help="enable the whole pipeline, including final unassigned removal (default: enabled)")
    denoising.add_argument("--motion-denoise", action=argparse.BooleanOptionalAction, default=True,
                          help="exclude isolated motion outliers; other stages still use movement bounds (default: enabled)")
    denoising.add_argument("--border-denoise", action=argparse.BooleanOptionalAction, default=True,
                          help="correct border-map disagreements using both countries' reference maps (default: enabled)")
    denoising.add_argument("--visit-denoise", action=argparse.BooleanOptionalAction, default=True,
                          help="resolve unconfirmed one-epoch excursions within the position allowance (default: enabled)")
    denoising.add_argument("--coastal-denoise", action=argparse.BooleanOptionalAction, default=True,
                          help="resolve unassigned points using reference geometry and coastal context (default: enabled)")
    denoising.add_argument("--remove-unassigned", action=argparse.BooleanOptionalAction, default=True,
                          help="remove remaining unassigned points before grouping (default: enabled)")
    denoising.add_argument("--gps-radius-meters", type=float,
                          help="override the radius for contextual country inference (not direct map evidence)")
    denoising.add_argument("--max-speed-kmh", type=float, default=DEFAULT_POLICY.max_speed_kmh,
                          help=f"travel-speed bound for motion, context, and diagnostics (default: {DEFAULT_POLICY.max_speed_kmh})")
    denoising.add_argument("--max-gap-minutes", type=float, default=DEFAULT_POLICY.max_gap_minutes,
                          help=f"maximum observation gap in minutes (default: {DEFAULT_POLICY.max_gap_minutes})")
    denoising.add_argument("--position-allowance-meters", "--motion-slack-meters", dest="motion_slack_meters",
                          type=float, default=DEFAULT_POLICY.position_allowance_meters,
                          help=f"position allowance for motion and country context (default: {DEFAULT_POLICY.position_allowance_meters})")
    denoising.add_argument("--explain", action="store_true", help="print reasons for every excluded or inferred record")
    parser.set_defaults(timeline=False)
    args = parser.parse_args(argv)
    for flag, value in (("--gps-radius-meters", args.gps_radius_meters), ("--max-speed-kmh", args.max_speed_kmh),
                        ("--max-gap-minutes", args.max_gap_minutes), ("--position-allowance-meters", args.motion_slack_meters)):
        if value is not None and (not math.isfinite(value) or value < 0 or (value == 0 and flag != "--position-allowance-meters")):
            parser.error(f"{flag} must be finite and {'nonnegative' if flag == '--position-allowance-meters' else 'positive'}")
    try:
        with args.gpx.open("rb") as source:
            points = gpx_samples(source, motion_groups=True)
            first = next(points, None)
            if first is None:
                raise ValueError("GPX contains no track points, route points, or waypoints")
            lookup = country_lookup(load_countries(
                args.country_data or DEFAULT_COUNTRIES, download=args.country_data is None
            ))
            reference = (None if args.country_data is not None else lru_cache(maxsize=8)(
                lambda country: load_coastal_reference(country, lookup.iso3.get(country))))
            fixes, report = denoise_samples(chain((first,), points), lookup, enabled=args.denoise,
                                           gps_radius_meters=args.gps_radius_meters, max_speed_kmh=args.max_speed_kmh,
                                           max_gap_minutes=args.max_gap_minutes, motion_slack_meters=args.motion_slack_meters,
                                           coastal=args.coastal_denoise, coastal_reference=reference,
                                           borders=args.border_denoise, visits=args.visit_denoise,
                                           remove_unassigned=args.remove_unassigned, motion=args.motion_denoise)
            labels = ((fix.country, fix.time, fix.count) for fix in fixes)
            output = (format_timeline(*group_timeline_labels(labels)) if args.timeline
                      else format_table(*summarize_labels(labels)))
            output += "\n" + format_denoising(report)
            if args.explain:
                output += "\n\n" + format_decisions(report)
                if report.get("unresolved_motion"):
                    output += "\n\nUnresolved movement transitions (the wrong endpoint cannot be identified):\n"
                    output += text_table(("From (UTC)", "To (UTC)"),
                                         [(timestamp(a), timestamp(b)) for a, b in report["unresolved_motion"]])
        print(output)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(2, f"error: {error}\n")
    except (KeyError, TypeError, IndexError, AttributeError):
        parser.exit(2, "error: malformed country GeoJSON\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
