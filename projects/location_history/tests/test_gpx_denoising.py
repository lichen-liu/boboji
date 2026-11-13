"""Independent synthetic movement truth, errors, and abstention cases.

The generator uses forward geodesics, not the denoiser's inverse distance or
country interpolation. All locations and countries here are invented.
"""

from datetime import datetime, timedelta, timezone
import math
import random

import pytest

import gpx_countries as script


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
A, B = ("Alpha", "AA"), ("Beta", "BB")
MODES = {"walking": 5, "running": 15, "cycling": 30, "driving": 130,
         "train": 350, "flight": 1100}
ACCELERATION = {"walking": 1, "running": 2, "cycling": 1.5, "driving": 2,
                "train": .5, "flight": 2}  # m/s²; simulation settings, not classifier limits.
TURN_RATE = {"walking": 60, "running": 20, "cycling": 8, "driving": 2,
             "train": .1, "flight": .5}  # Degrees/s; avoid instantaneous vehicle U-turns.


def forward(latitude, longitude, bearing, metres):
    """Generate truth on a sphere using a destination bearing and distance."""
    lat, lon, angle = map(math.radians, (latitude, longitude, bearing))
    arc = metres / 6371008.8
    lat2 = math.asin(math.sin(lat) * math.cos(arc) + math.cos(lat) * math.sin(arc) * math.cos(angle))
    lon2 = lon + math.atan2(math.sin(angle) * math.sin(arc) * math.cos(lat),
                          math.cos(arc) - math.sin(lat) * math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2) + 180) % 360 - 180


def movement(mode, latitude, cadence, error, seed):
    """Stops, turns, returns, and irregular sampling; noise is added AFTER truth."""
    rng = random.Random(seed)
    truth, lat, lon, time, bearing, target_bearing = [], latitude, 179.8, BASE, 75, 75
    speed = MODES[mode] / 3.6
    for i in range(81):
        seconds = cadence * rng.uniform(.75, 1.25)
        if i % 12 == 0:
            target_bearing += rng.uniform(-10, 10) if mode == "flight" else rng.uniform(-120, 120)
        if i == 41 and mode in {"walking", "running", "cycling", "driving"}:
            target_bearing += 180  # An ordinary return, not an error.
        target_speed = 0 if mode != "flight" and 15 <= i < 20 else MODES[mode] / 3.6
        change = ACCELERATION[mode] * seconds
        new_speed = speed + max(-change, min(change, target_speed - speed))
        rotation = (target_bearing - bearing + 180) % 360 - 180
        rotation = max(-TURN_RATE[mode] * seconds, min(TURN_RATE[mode] * seconds, rotation))
        lat, lon = forward(lat, lon, bearing + rotation / 2, (speed + new_speed) * seconds / 2)
        bearing, speed = bearing + rotation, new_speed
        time += timedelta(seconds=seconds)
        truth.append((lat, lon, time, 1))
    observed, north, east = [], 0.0, 0.0
    for lat, lon, time, seq in truth:
        if error == "independent":
            north, east = rng.gauss(0, 20), rng.gauss(0, 20)
        elif error == "correlated":
            north = max(-200, min(200, .95 * north + rng.gauss(0, 20)))
            east = max(-200, min(200, .95 * east + rng.gauss(0, 20)))
        elif error == "bias":
            north, east = 180, -80
        lat, lon = forward(lat, lon, math.degrees(math.atan2(east, north)), math.hypot(north, east))
        observed.append((lat, lon, time, seq))
    return observed


def samples(coordinates, seconds=60, sequence=1):
    return [(lat, lon, BASE + timedelta(seconds=i * seconds), sequence)
            for i, (lat, lon) in enumerate(coordinates)]


def feature(name, code, west, south, east, north):
    return {"properties": {"NAME_EN": name, "ISO_A2": code},
            "geometry": {"type": "Polygon", "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]] ]}}


def coast(neighbor=False):
    features = [feature(*A, -1, -1, 0, 1)]
    if neighbor:
        features.append(feature(*B, 0, -1, 1, 1))
    return script.country_lookup({"type": "FeatureCollection", "features": features})


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("latitude", [-70, 0, 70])
@pytest.mark.parametrize("cadence", [1, 5, 60, 300])
@pytest.mark.parametrize("error", ["none", "independent", "correlated", "bias"])
@pytest.mark.parametrize("seed", [11, 97])
def test_normal_movement_is_preserved(mode, latitude, cadence, error, seed):
    route = movement(mode, latitude, cadence, error, seed)
    fixes, report = script.denoise_samples(route, lambda *_: None)
    assert report["excluded"] == report["inferred"] == 0
    assert sum(f.count for f in fixes) == len(route)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("latitude", [-70, 0, 70])
@pytest.mark.parametrize("cadence", [1, 5, 60, 300])
def test_gross_isolated_errors_are_detected_without_erasing_real_movement(mode, latitude, cadence):
    route = movement(mode, latitude, cadence, "correlated", seed=421)
    lat, lon, time, seq = route[40]
    bad_lat, bad_lon = forward(lat, lon, 180, 1_000_000)
    route[40] = (bad_lat, bad_lon, time, seq)
    fixes, report = script.denoise_samples(route, lambda *_: None)
    assert report["excluded"] == 1
    assert [(f.latitude, f.longitude, f.time) for f in fixes] == [p[:3] for i, p in enumerate(route) if i != 40]


def test_clean_car_pickup_and_return_is_not_a_spike():
    route = samples([(2, 1 + i * .00001) for i in range(51)], seconds=300)
    route[25] = (2, 1.05, route[25][2], 1)  # About 5.5 km in five minutes each way.
    fixes, report = script.denoise_samples(route, lambda *_: A)
    assert len(fixes) == 51 and report["excluded"] == 0


@pytest.mark.parametrize("radius", [None, 1000])
def test_clean_winding_road_and_genuine_brief_border_visit_are_preserved(radius):
    coords = [(.1 + .003 * (i % 2), x) for i, x in enumerate([-.01, -.002, -.009, -.001, -.008, -.002])]
    coords += [(.101, .003), (.1015, .004), (.102, .003)]
    coords += [(.1 + .003 * (i % 2), x) for i, x in enumerate([-.002, -.008, -.001, -.009, -.002, -.01, -.003])]
    fixes, report = script.denoise_samples(samples(coords), coast(True), gps_radius_meters=radius)
    assert report["excluded"] == report["inferred"] == 0
    assert sum(f.country == B for f in fixes) == 3
    assert [p[0] for p in script.group_timeline_labels((f.country, f.time, f.count) for f in fixes)[0]] == [A, B, A]


def test_changes_of_transport_mode_are_normal():
    route, lat, lon, time, speed = [], 0, 0, BASE, 0
    for target in [0, 5, 130, 0, 350, 5, 1100, 0, 30]:
        for _ in range(8):
            new_speed = speed + max(-60, min(60, target / 3.6 - speed))
            lat, lon = forward(lat, lon, 90, (speed + new_speed) * 30)
            speed = new_speed
            time += timedelta(minutes=1)
            route.append((lat, lon, time, 1))
    fixes, report = script.denoise_samples(route, lambda *_: None)
    assert len(fixes) == len(route) and report["excluded"] == 0


def spike_route():
    route = samples([(0, i * .001) for i in range(13)])
    route[6] = (30, 30, route[6][2], 1)
    return route


def test_duplicate_records_do_not_supply_independent_evidence_or_change_decisions():
    route = spike_route()
    for copies in [1, 2, 100]:
        for separate_segments in [False, True]:
            repeated = [(lat, lon, time, seq + j if separate_segments else seq)
                        for j in range(copies) for lat, lon, time, seq in route]
            fixes, report = script.denoise_samples(repeated, lambda *_: None)
            assert report["excluded"] == copies
            assert sum(f.count for f in fixes) + report["excluded"] == len(repeated)
            assert len(fixes) == 12


def test_other_days_and_input_order_do_not_train_a_different_answer():
    route = spike_route()
    other = [(lat, lon, time + timedelta(days=1), 40) for lat, lon, time, _ in samples([(0, 0)] * 31)]
    inputs = [route, route + other, list(reversed(route + other))]
    for records in inputs:
        fixes, report = script.denoise_samples(records, lambda *_: None)
        assert report["excluded"] == 1
        assert all(f.time != route[6][2] for f in fixes if f.time < BASE + timedelta(days=1))


def test_impossible_isolated_conflict_uses_motion_evidence_without_duplicate_voting():
    route = samples([(0, i * .001) for i in range(13)])
    other = (30, 30, route[6][2], 2)
    fixes, report = script.denoise_samples(route + [other] * 100, lambda *_: None)
    assert report["conflicting_epochs"] == 1 and report["excluded"] == 100
    assert sum(f.count for f in fixes) == 13


def test_distinct_overlapping_recordings_are_not_resolved_by_density():
    route = spike_route()
    other = [(lat, lon, time + timedelta(seconds=10), 2)
             for lat, lon, time, _ in samples([(30, 30)] * 13)]
    fixes, report = script.denoise_samples(route + other, lambda *_: None)
    assert len(fixes) == 26 and report["excluded"] == 0


def test_waypoint_duplicate_of_a_rejected_track_fix_is_still_a_poi():
    route = spike_route()
    lat, lon, time, _ = route[6]
    fixes, report = script.denoise_samples(route + [(lat, lon, time, None)], lambda *_: None)
    assert report["excluded"] == 1
    assert any(f.time == time and f.sequences == {None} for f in fixes)


@pytest.mark.parametrize("sparse", ["endpoint", "gap", "untimed", "route", "burst"])
def test_insufficient_context_abstains(sparse):
    route = spike_route()
    if sparse == "endpoint":
        route = route[6:]
    elif sparse == "four":
        route = route[4:8]
    elif sparse == "gap":
        route = [(lat, lon, time + timedelta(hours=i), seq) for i, (lat, lon, time, seq) in enumerate(route)]
    elif sparse == "split":
        route = [(lat, lon, time, 1 if i < 6 else 2) for i, (lat, lon, time, _) in enumerate(route)]
    elif sparse == "untimed":
        route = [(lat, lon, None, seq) for lat, lon, _, seq in route]
    elif sparse == "route":
        route = [(lat, lon, time, None) for lat, lon, time, _ in route]
    elif sparse == "burst":
        route[7] = (30, 30, route[7][2], 1)
    fixes, report = script.denoise_samples(route, lambda *_: None)
    assert report["excluded"] == 0 and sum(f.count for f in fixes) == len(route)


def test_infeasible_bypass_prevents_an_isolated_deletion():
    route = samples([(0, 0), (0, 0), (40, 40), (0, 1), (0, 1)])
    fixes, report = script.denoise_samples(route, lambda *_: None)
    assert len(fixes) == 5 and report["excluded"] == 0


def test_user_movement_bounds_and_gap_limits_control_the_decision():
    route = samples([(0, 0), (0, 0), (0, .1), (0, 0), (0, 0)])
    assert script.denoise_samples(route, lambda *_: None)[1]["excluded"] == 0  # Plausible flight.
    assert script.denoise_samples(route, lambda *_: None, max_speed_kmh=130,
                                  motion_slack_meters=1000)[1]["excluded"] == 1
    assert script.denoise_samples(route, lambda *_: None, max_speed_kmh=130,
                                  motion_slack_meters=6000)[1]["excluded"] == 0
    assert script.denoise_samples(route, lambda *_: None, max_speed_kmh=130,
                                  max_gap_minutes=.5)[1]["excluded"] == 0


@pytest.mark.parametrize("seconds", [1, 60, 300])
def test_reachability_bound_includes_uncertainty_at_both_positions(seconds):
    first = script.Fix(0, 0, BASE, None)
    allowed = 1500 * seconds / 3.6 + 2000
    for factor, expected in [(.999, True), (1.001, False)]:
        lat, lon = forward(0, 0, 90, allowed * factor)
        second = script.Fix(lat, lon, BASE + timedelta(seconds=seconds), None)
        assert script.reachable(first, second, 1500, 1000) == expected


def test_different_positions_are_not_a_country_conflict_when_they_agree_on_country():
    route = samples([(.1, -.001), (.1, .002), (.1, -.001)])
    route.append((.1, -.002, route[1][2], 2))
    fixes, report = script.denoise_samples(route, coast(), gps_radius_meters=500)
    assert report["inferred"] == 1 and report["conflicting_epochs"] == 1
    assert report["excluded"] == 0 and all(f.country == A for f in fixes)


def test_slow_or_persistent_error_is_not_identifiable_from_movement_alone():
    # These data could equally be a boat, a coastal hotel with bias, or map error.
    route = samples([(.2, -.001), (.2, .002), (.2, .003), (.2, .002), (.2, -.001)])
    fixes, report = script.denoise_samples(route, coast())
    assert [f.country for f in fixes] == [A, None, None, None, A]
    assert report["excluded"] == report["inferred"] == 0


@pytest.mark.parametrize("seconds", [60, 3600, 86400])
def test_explicit_coastal_tolerance_uses_actual_points_not_duration_or_segment_count(seconds):
    # Days and GPX segment boundaries cannot change distance to a map polygon.
    route = [(lat, lon, time, i) for i, (lat, lon, time, _) in enumerate(
        samples([(.1, -.001), (.1, .002), (.2, .003), (.3, .002), (.4, -.001)], seconds))]
    fixes, report = script.denoise_samples(route, coast(), gps_radius_meters=500)
    assert report["excluded"] == 0 and report["inferred"] == 3
    assert all(f.country == A for f in fixes)
    assert sum(f.raw_country is None for f in fixes) == 3
    assert report["max_inferred_distance_meters"] == pytest.approx(333.58, abs=1)
    assert len(script.group_timeline_labels((f.country, f.time, f.count) for f in fixes)[0]) == 1


def test_coastal_tolerance_has_an_actual_distance_cutoff():
    route = samples([(.1, -.001), (.1, .002), (.1, .02), (.1, .002), (.1, -.001)])
    fixes, report = script.denoise_samples(route, coast(), gps_radius_meters=500)
    assert report["inferred"] == 2
    assert [f.country for f in fixes] == [A, A, None, A, A]


def test_nearby_foreign_polygon_prevents_a_unique_coastal_assignment():
    data = {"type": "FeatureCollection", "features": [feature(*A, -1, -1, 0, 1), feature(*B, .005, -1, 1, 1)]}
    route = samples([(.1, -.001), (.1, .002), (.1, -.001)])
    fixes, report = script.denoise_samples(route, script.country_lookup(data), gps_radius_meters=500)
    assert report["inferred"] == 0 and fixes[1].country is None


@pytest.mark.parametrize("context", ["no_return", "different_country", "conflict", "only_pois"])
def test_coastal_inference_requires_unambiguous_raw_tracking_references(context):
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        feature(*A, -1, -1, 0, 1), feature(*B, 2, -1, 3, 1)]})
    route = samples([(.1, -.001), (.1, .002), (.1, -.001)])
    if context == "no_return":
        route.pop()
    elif context == "different_country":
        route[-1] = (.1, 2.5, route[-1][2], 2)
    elif context == "conflict":
        route.append((.1, 2.5, route[-1][2], 2))
    else:
        route = [(lat, lon, time, None) if i != 1 else (lat, lon, time, seq)
                 for i, (lat, lon, time, seq) in enumerate(route)]
    fixes, report = script.denoise_samples(route, lookup, gps_radius_meters=500)
    assert report["inferred"] == 0 and fixes[1].country is None


def test_nearby_polygon_search_handles_lake_holes_and_split_date_line():
    from test_gpx_countries import country_data
    lookup = script.country_lookup(country_data())
    assert lookup.nearby(5, 5, 1) == set()
    assert lookup.nearby(5, 4.001, 1) == {A}
    assert lookup.nearby(0, 178.999, 1) == {B}
    assert lookup.nearby(0, -178.999, 1) == {B}
    assert lookup.nearby(0, 180, .001) == {B}
    assert lookup.nearby(0, -180, .001) == {B}


def test_indexed_polygon_lookup_agrees_with_independent_rectangle_geometry():
    rng = random.Random(920)
    features = []
    rectangles = []
    for i in range(30):
        west, south = rng.uniform(-175, 170), rng.uniform(-85, 80)
        east, north = west + rng.uniform(.1, 5), south + rng.uniform(.1, 5)
        label = (f"Country {i}", str(i))
        features.append(feature(*label, west, south, east, north))
        rectangles.append((west, south, east, north, label))
    lookup = script.country_lookup({"type": "FeatureCollection", "features": features})
    for _ in range(3000):
        lat, lon = rng.uniform(-90, 90), rng.uniform(-180, 180)
        expected = next((label for west, south, east, north, label in rectangles
                         if west <= lon <= east and south <= lat <= north), None)
        assert lookup(lat, lon) == expected
    for west, south, east, north, label in rectangles:
        assert lookup((south + north) / 2, (west + east) / 2) == label


@pytest.mark.parametrize("latitude", [-80, -10, 0, 45, 80])
def test_polygon_distance_is_to_edges_in_metres_including_at_high_latitudes(latitude):
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        feature(*A, -1, latitude - .5, 0, latitude + .5)]})
    expected_km = 111.195 * math.cos(math.radians(latitude)) * .001
    assert lookup.distance_to(latitude, .001, A, 1) == pytest.approx(expected_km, abs=.00001)
    assert lookup.nearby(latitude, .001, expected_km * 1.01) == {A}
    assert lookup.nearby(latitude, .001, expected_km * .99) == set()


def test_raw_opt_out_preserves_every_sample_and_equal_time_order():
    route = [(0, -.001, BASE, 1), (0, .001, BASE, 1), (0, -.001, BASE, 2)]
    fixes, report = script.denoise_samples(route, coast(True), enabled=False, gps_radius_meters=500)
    assert [f.country for f in fixes] == [A, B, A]
    assert [f.count for f in fixes] == [1, 1, 1]
    assert report == {"enabled": False}


def test_explanations_separate_exclusions_from_explicit_mapping_inference():
    fixes, report = script.denoise_samples(spike_route(), lambda *_: None)
    text = script.format_decisions(report)
    assert "Excluded" in text and "both legs exceed" in text and "2026-01-01T00:06:00Z" in text
    assert "latitude" not in text and "longitude" not in text
    fixes, report = script.denoise_samples(samples([(.1, -.001), (.1, .002), (.1, -.001)]), coast(), gps_radius_meters=500)
    text = script.format_decisions(report)
    assert "explicit coastal tolerance" in text and "Unassigned" in text and "Alpha" in text
    assert "not measured GPS accuracy" in script.format_denoising(report)
