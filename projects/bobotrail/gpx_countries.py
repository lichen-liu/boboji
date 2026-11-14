#!/usr/bin/env python3
"""Print a table of countries/territories represented by recorded GPX points."""

import argparse
from dataclasses import dataclass, field
import json
import logging
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
LOGGER = logging.getLogger("gpx_countries")


def load_countries(path, download=False, url=DATA_URL):
    if not path.exists() and download:
        LOGGER.info("Downloading boundary map: %s", path.name)
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
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        LOGGER.info("Reference map unavailable for %s: %s", country[0], error)
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


@dataclass(frozen=True)
class DenoiseConfig:
    policy: DenoisePolicy = DEFAULT_POLICY
    gps_radius_meters: Optional[float] = None
    enabled: bool = True
    motion: bool = True
    borders: bool = True
    visits: bool = True
    coastal: bool = True
    remove_unassigned: bool = True
    singletons: bool = True

    def __post_init__(self):
        radius = self.gps_radius_meters
        if self.enabled and radius is not None and (not math.isfinite(radius) or radius <= 0):
            raise ValueError("invalid coastal radius")


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



def record_removal(report, fix, reason):
    counts = report["removed_by_country"].setdefault(fix.country, {})
    counts[reason] = counts.get(reason, 0) + fix.count


def remove_unassigned_fixes(fixes, report):
    """Final output policy: drop unresolved records without inferring a country."""
    retained = []
    for fix in fixes:
        if fix.country is None:
            report["unassigned_removed"] += fix.count
            record_removal(report, fix, "unassigned")
            report["decisions"].append((fix.time, "Unassigned", "Removed", "final unassigned-removal policy", fix.count))
        else:
            retained.append(fix)
    return retained


def remove_singleton_excursions(fixes, report):
    """Filter one-timestamp A → X → A excursions against a frozen visible view.

    This is a presentation policy for all timed point types, independent of
    physical inference bounds. Simultaneous alternatives never acquire order.
    Competing proposals cannot erase the epochs supporting one another.
    """
    epochs = defaultdict(list)
    for fix in fixes:
        if fix.time is not None:
            epochs[fix.time].append(fix)
    times = sorted(epochs)
    labels = {time: {fix.country for fix in epoch} for time, epoch in epochs.items()}
    proposals = {}
    for i in range(1, len(times) - 1):
        left, time, right = times[i - 1:i + 2]
        context = labels[left]
        if len(context) != 1 or None in context or context != labels[right] or None in labels[time]:
            continue
        country = next(iter(context))
        candidates = [fix for fix in epochs[time] if fix.country != country]
        if candidates:
            proposals[time] = (left, right, country, candidates)
    removed = set()
    excursions = set()
    for time, (left, right, country, candidates) in proposals.items():
        if left in proposals or right in proposals:
            continue
        for fix in candidates:
            removed.add(fix)
            excursions.add((time, fix.country))
            record_removal(report, fix, "singleton")
            report["decisions"].append((time, fix.raw_country[0] if fix.raw_country else "Unassigned",
                                        "Removed", f"single-timestamp {fix.country[0]} excursion between "
                                        f"{country[0]} observations", fix.count))
    report["singleton_removed"] += sum(fix.count for fix in removed)
    report["singleton_excursions"] += len(excursions)
    return [fix for fix in fixes if fix not in removed]


def create_denoise_report(fixes, epochs, config, reference):
    policy = config.policy
    return {
        "enabled": True, "input": sum(f.count for f in fixes), "unique": len(fixes),
        "excluded": 0, "tested": 0, "motion_enabled": config.motion,
        "conflicting_epochs": sum(len(epoch) > 1 for epoch in epochs.values()),
        "border_corrected": 0, "borders_enabled": config.borders,
        "reference_confirmed": 0, "map_unavailable": set(),
        "coastal_enabled": config.coastal,
        "coastal_automatic": config.gps_radius_meters is None and reference is not None,
        "coastal_models": [], "coastal_unavailable": [], "coastal_effective": [],
        "inferred": 0, "max_inferred_distance_meters": 0,
        "visit_inferred": 0, "visits_enabled": config.visits,
        "unassigned_removed": 0, "remove_unassigned_enabled": config.remove_unassigned,
        "singleton_removed": 0, "singleton_excursions": 0, "singleton_enabled": config.singletons,
        "gps_radius_meters": config.gps_radius_meters,
        "max_speed_kmh": policy.max_speed_kmh, "max_gap_minutes": policy.max_gap_minutes,
        "motion_slack_meters": policy.position_allowance_meters, "decisions": [],
        "removed_by_country": {},
    }


def screen_motion(fixes, epochs, policy, report):
    rejected, checked = motion_outliers(epochs, policy)
    report["excluded"] = sum(f.count for f in rejected)
    report["tested"] = len(checked)
    for fix in rejected:
        record_removal(report, fix, "motion")
    report["decisions"].extend(
        (f.time, f.raw_country[0] if f.raw_country else "Unassigned", "Excluded",
         "both legs exceed configured movement bound", f.count) for f in rejected)
    return [fix for fix in fixes if fix not in rejected]


def refine_map_labels(fixes, lookup, config, reference, report):
    if config.borders or config.coastal:
        adjudicate_maps(fixes, lookup, reference, report, config.borders, config.coastal)
    # Geometry offsets describe map disagreement; they never train a tolerance.
    covered = defaultdict(list)
    for fix in fixes:
        if fix.raw_country is None and fix.reference_country is not None:
            covered[fix.reference_country].append(fix)
    for country, points in covered.items():
        offsets = [lookup.distance_to(f.latitude, f.longitude, country, MAX_AUTO_COAST_METERS / 1000) * 1000
                   for f in points]
        locations = len({(fix.latitude, fix.longitude) for fix in points})
        report["coastal_models"].append((country[0], locations, math.ceil(max(offsets))))
        report["coastal_effective"].append(
            (country[0], min(MAX_AUTO_COAST_METERS, config.policy.position_allowance_meters)))


def infer_country_labels(fixes, lookup, config, reference, report):
    """Both context passes read the same frozen map-backed evidence."""
    evidence = {fix: fix.country for fix in fixes}
    if config.visits:
        infer_single_epoch_visits(fixes, lookup, evidence, config.policy, report,
                                 config.gps_radius_meters, include_unassigned=config.coastal)
    if config.coastal:
        infer_coastal_countries(fixes, lookup, config.gps_radius_meters, report, reference,
                               config.policy.position_allowance_meters, evidence=evidence)


def diagnose_tracking(fixes, policy):
    epochs = tracking_epochs(fixes)
    conflicts = sum(len({fix.country for fix in epoch}) > 1 for epoch in epochs.values())
    movement = []
    times = list(epochs)
    for left, right in zip(times, times[1:]):
        if policy.gap_ok(left, right) and not any(
            policy.feasible(a, b) for a in epochs[left] for b in epochs[right]
        ):
            movement.append((left, right))
    return conflicts, movement


def country_conflicts(fixes):
    labels = defaultdict(set)
    for fix in fixes:
        if fix.time is not None:
            labels[fix.time].add(fix.country)
    return [(time, sorted(countries, key=lambda country: (country is None, country or ("", ""))))
            for time, countries in sorted(labels.items()) if len(countries) > 1]


def filter_analysis(fixes, config, report):
    """Apply output policies once, after inference and its diagnostics."""
    if config.remove_unassigned:
        fixes = remove_unassigned_fixes(fixes, report)
    if config.singletons:
        fixes = remove_singleton_excursions(fixes, report)
    report["represented"] = sum(fix.count for fix in fixes)
    report["remaining_country_alternatives"] = country_conflicts(fixes)
    report["remaining_country_epochs"] = len(report["remaining_country_alternatives"])
    _, report["remaining_motion"] = diagnose_tracking(fixes, config.policy)
    return fixes


def run_denoising(samples, lookup, config, reference=None):
    """Prepare → Screen → Map → Context → Diagnose → Output."""
    if not config.enabled:
        fixes = []
        for lat, lon, time, sequence in samples:
            country = lookup(lat, lon)
            fixes.append(Fix(lat, lon, time, country, 1, {sequence}, country))
        return fixes, {"enabled": False}

    fixes = normalize_samples(samples, lookup)
    epochs = tracking_epochs(fixes)
    report = create_denoise_report(fixes, epochs, config, reference)
    if config.motion:
        fixes = screen_motion(fixes, epochs, config.policy, report)
    refine_map_labels(fixes, lookup, config, reference, report)
    infer_country_labels(fixes, lookup, config, reference, report)
    report["unresolved_country_epochs"], report["unresolved_motion"] = diagnose_tracking(fixes, config.policy)
    report["before_output_country_epochs"] = len(country_conflicts(fixes))
    fixes = filter_analysis(fixes, config, report)
    report["decisions"].sort(key=decision_sort_key)
    report["map_unavailable"] = sorted(report["map_unavailable"])
    return fixes, report


def denoise_samples(samples, lookup, enabled=True, *, gps_radius_meters=None,
                    max_speed_kmh=DEFAULT_POLICY.max_speed_kmh,
                    max_gap_minutes=DEFAULT_POLICY.max_gap_minutes,
                    motion_slack_meters=DEFAULT_POLICY.position_allowance_meters,
                    coastal=True, coastal_reference=None, borders=True, visits=True,
                    remove_unassigned=True, motion=True, singletons=True):
    """Keyword adapter for callers; the CLI uses DenoiseConfig directly."""
    policy = DenoisePolicy(max_speed_kmh, max_gap_minutes, motion_slack_meters) if enabled else DEFAULT_POLICY
    config = DenoiseConfig(policy=policy, gps_radius_meters=gps_radius_meters, enabled=enabled,
                           motion=motion, borders=borders, visits=visits, coastal=coastal,
                           remove_unassigned=remove_unassigned, singletons=singletons)
    return run_denoising(samples, lookup, config, coastal_reference)


def decision_sort_key(row):
    return row[0] is None, row[0] or datetime.max.replace(tzinfo=timezone.utc), row[1], row[2], row[3], row[4]


def format_denoising(report, verbose=False):
    if not report["enabled"]:
        return "Denoising: off."
    removed = report["excluded"] + report["unassigned_removed"] + report["singleton_removed"]
    kept = report.get("represented", report["input"] - removed)
    excursions = report["singleton_excursions"]
    excursion_label = "excursion" if excursions == 1 else "excursions"
    lines = [
        f"Denoising: on · Input: {report['input']:,} · Kept: {kept:,} · Removed: {removed:,}",
        f"Removed points: motion {report['excluded']:,} · unassigned {report['unassigned_removed']:,} · "
        f"singletons {report['singleton_removed']:,} ({excursions:,} {excursion_label})",
        f"Country labels (per stage): border {report['border_corrected']:,} · reference {report['reference_confirmed']:,} · "
        f"visit {report['visit_inferred']:,} · coastal {report['inferred']:,}",
    ]
    disabled = [name for name, key in (
        ("motion", "motion_enabled"), ("border", "borders_enabled"),
        ("visit", "visits_enabled"), ("coastal", "coastal_enabled"),
        ("unassigned removal", "remove_unassigned_enabled"), ("singletons", "singleton_enabled"),
    ) if not report[key]]
    if disabled:
        lines.append("Disabled: " + ", ".join(disabled) + ".")
    conflicts = report.get("remaining_country_epochs", 0)
    movement = len(report.get("remaining_motion", []))
    if conflicts or movement:
        issues = [f"{count:,} {name}{'' if count == 1 else 's'}" for count, name in
                  ((conflicts, "country conflict"), (movement, "movement conflict")) if count]
        lines.append("Review: " + " · ".join(issues) + ". Use --explain for timestamps.")
    removals = format_removal_summary(report)
    if removals:
        lines.extend(("", removals))
    if verbose:
        lines.extend(("", format_denoising_details(report)))
    return "\n".join(lines)


def format_removal_summary(report):
    countries = report.get("removed_by_country", {})
    if not countries:
        return ""
    reasons = ("motion", "unassigned", "singleton")
    rows = []
    totals = [0, 0, 0]
    for country, counts in sorted(countries.items(), key=lambda item: (item[0] is None, item[0] or ("", ""))):
        name, code = country or ("Unassigned", "—")
        values = [counts.get(reason, 0) for reason in reasons]
        totals = [total + value for total, value in zip(totals, values)]
        rows.append((name, code, *(f"{value:,}" for value in values), f"{sum(values):,}"))
    rows.append(("Total", "—", *(f"{value:,}" for value in totals), f"{sum(totals):,}"))
    return "Removed points by country\n" + text_table(
        ("Country / territory", "Code", "Motion", "Unassigned", "Singletons", "Total"), rows)


def format_denoising_details(report):
    rows = [
        ("Prepare", "Normalize", "on", f"{report['unique']:,} distinct records"),
        ("Screen", "Motion", "on" if report["motion_enabled"] else "off", f"{report['excluded']:,} removed"),
        ("Map", "Borders", "on" if report["borders_enabled"] else "off", f"{report['border_corrected']:,} corrected"),
        ("Map", "Reference coverage", "on" if report["coastal_enabled"] else "off", f"{report['reference_confirmed']:,} assigned"),
        ("Context", "Visits", "on" if report["visits_enabled"] else "off", f"{report['visit_inferred']:,} assigned"),
        ("Context", "Coastal", "on" if report["coastal_enabled"] else "off", f"{report['inferred']:,} assigned"),
        ("Output", "Unassigned", "on" if report["remove_unassigned_enabled"] else "off", f"{report['unassigned_removed']:,} removed"),
        ("Output", "Singletons", "on" if report["singleton_enabled"] else "off", f"{report['singleton_removed']:,} removed, {report['singleton_excursions']:,} excursions"),
    ]
    radius = report["gps_radius_meters"]
    context_radius = report["motion_slack_meters"] if radius is None else radius
    radius_source = "position allowance" if radius is None else "manual override"
    lines = [
        "Denoising stages",
        text_table(("Phase", "Stage", "State", "Result"), rows),
        "",
        f"Bounds: speed {report['max_speed_kmh']:g} km/h · "
        f"position {report['motion_slack_meters'] / 1000:g} km · gap {report['max_gap_minutes']:g} min.",
        f"Country context radius: {context_radius:g} m ({radius_source}).",
        "Bounds are configured assumptions, not measured GPS accuracy.",
        f"Tracking: {report['tested']:,} checked fixes · {report['conflicting_epochs']:,} timestamps with multiple positions.",
        f"Diagnostics before output filters: {report.get('before_output_country_epochs', report['unresolved_country_epochs']):,} country conflicts · "
        f"{len(report['unresolved_motion']):,} movement conflicts.",
        f"Diagnostics after output filters: {report.get('remaining_country_epochs', 0):,} country conflicts · "
        f"{len(report.get('remaining_motion', [])):,} movement conflicts.",
        "Removal and label-change counts include duplicates; label changes can overlap.",
    ]
    if report["coastal_enabled"] and report["coastal_automatic"]:
        lines.append(f"Automatic coastal inference is capped at {MAX_AUTO_COAST_METERS:,} m.")
    unavailable = sorted(set(report["map_unavailable"]) | set(report["coastal_unavailable"]))
    if unavailable:
        lines.append("Unavailable reference maps: " + ", ".join(unavailable) + ".")
    maps = format_reference_details(report)
    if maps:
        lines.extend(("", maps))
    return "\n".join(lines)


def format_reference_details(report):
    effective = dict(report["coastal_effective"]) if report["coastal_automatic"] else {}
    observed = {name: (locations, offset) for name, locations, offset in report["coastal_models"]}
    if not effective and not observed:
        return ""
    rows = []
    for name in sorted(set(effective) | set(observed)):
        locations, offset = observed.get(name, (None, None))
        rows.append((name, f"{effective[name]:,}" if name in effective else "—",
                     f"{offset:,}" if offset is not None else "—",
                     f"{locations:,}" if locations is not None else "—"))
    return "Reference map details\n" + text_table(
        ("Country / territory", "Auto allowance (m)", "Map offset (m)", "Locations"), rows
    )


def format_decisions(report):
    rows = [(timestamp(time), original, result, str(count), reason)
            for time, original, result, reason, count in sorted(report.get("decisions", []), key=decision_sort_key)]
    if not rows:
        return "No denoising changes."
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
    summary = f"Countries/territories: {count} · GPX points: {total:,}"
    if unassigned:
        summary += f" · Unassigned: {unassigned:,}"
    lines = [text_table(headers, rows), "", summary,
             "First/last are recorded samples; gaps do not establish continuous stays."]
    if any(first is None for _count, first, _last in countries.values()):
        lines.append("— = no recorded timestamp.")
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
    summary = (f"Countries/territories: {len(countries)} · Recorded periods: {timed_periods:,} · "
               f"GPX points represented: {total:,}")
    if unassigned:
        summary += f" · Unassigned: {unassigned:,}"
    if untimed:
        summary += f" · Untimed: {untimed:,}"
    lines = [text_table(headers, rows), "", summary,
             "Recorded spans include gaps; they do not establish continuous stays."]
    if untimed:
        lines.append("Untimed points follow the timeline; — = no recorded timestamp.")
    if any(a[3] is not None and a[3] == b[2] and a[0] != b[0] for a, b in zip(periods, periods[1:])):
        lines.append("Countries sharing a timestamp are alternatives; row order does not establish travel.")
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
                          help="enable the whole pipeline, including final output filters (default: enabled)")
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
    denoising.add_argument("--singleton-denoise", action=argparse.BooleanOptionalAction, default=True,
                          help="filter one-timestamp A-to-X-to-A excursions in the selected view (default: enabled)")
    denoising.add_argument("--gps-radius-meters", type=float,
                          help="override the radius for contextual country inference (not direct map evidence)")
    denoising.add_argument("--max-speed-kmh", type=float, default=DEFAULT_POLICY.max_speed_kmh,
                          help=f"travel-speed bound for motion, context, and diagnostics (default: {DEFAULT_POLICY.max_speed_kmh})")
    denoising.add_argument("--max-gap-minutes", type=float, default=DEFAULT_POLICY.max_gap_minutes,
                          help=f"maximum observation gap in minutes (default: {DEFAULT_POLICY.max_gap_minutes})")
    denoising.add_argument("--position-allowance-meters", "--motion-slack-meters", dest="motion_slack_meters",
                          type=float, default=DEFAULT_POLICY.position_allowance_meters,
                          help=f"position allowance for motion and country context (default: {DEFAULT_POLICY.position_allowance_meters})")
    denoising.add_argument("--explain", action="store_true", help="show record changes and remaining country/movement conflicts")
    denoising.add_argument("--verbose", action="store_true", help="show phase results, settings, and map diagnostics")
    parser.set_defaults(timeline=False)
    args = parser.parse_args(argv)
    for flag, value in (("--gps-radius-meters", args.gps_radius_meters), ("--max-speed-kmh", args.max_speed_kmh),
                        ("--max-gap-minutes", args.max_gap_minutes), ("--position-allowance-meters", args.motion_slack_meters)):
        if value is not None and (not math.isfinite(value) or value < 0 or (value == 0 and flag != "--position-allowance-meters")):
            parser.error(f"{flag} must be finite and {'nonnegative' if flag == '--position-allowance-meters' else 'positive'}")
    config = DenoiseConfig(
        policy=DenoisePolicy(args.max_speed_kmh, args.max_gap_minutes, args.motion_slack_meters),
        gps_radius_meters=args.gps_radius_meters, enabled=args.denoise,
        motion=args.motion_denoise, borders=args.border_denoise, visits=args.visit_denoise,
        coastal=args.coastal_denoise, remove_unassigned=args.remove_unassigned,
        singletons=args.singleton_denoise)
    previous_log_level = LOGGER.level
    LOGGER.setLevel(logging.INFO if args.verbose else logging.WARNING)
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
            fixes, report = run_denoising(chain((first,), points), lookup, config, reference)
            labels = ((fix.country, fix.time, fix.count) for fix in fixes)
            output = (format_timeline(*group_timeline_labels(labels)) if args.timeline
                      else format_table(*summarize_labels(labels)))
            output += "\n\n" + format_denoising(report, verbose=args.verbose)
            if args.explain:
                output += "\n\n" + format_decisions(report)
                if report.get("remaining_country_alternatives"):
                    output += "\n\nCountry conflicts in displayed points:\n"
                    output += text_table(("Time (UTC)", "Country alternatives"), [
                        (timestamp(time), ", ".join(f"{country[0]} ({country[1]})" if country else "Unassigned"
                                                   for country in countries))
                        for time, countries in report["remaining_country_alternatives"]])
                if report.get("remaining_motion"):
                    output += "\n\nMovement conflicts in displayed points:\n"
                    output += text_table(("From (UTC)", "To (UTC)"),
                                         [(timestamp(a), timestamp(b)) for a, b in report["remaining_motion"]])
        print(output)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(2, f"error: {error}\n")
    except (KeyError, TypeError, IndexError, AttributeError):
        parser.exit(2, "error: malformed country GeoJSON\n")
    finally:
        LOGGER.setLevel(previous_log_level)
    return 0


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s")
    raise SystemExit(main())
