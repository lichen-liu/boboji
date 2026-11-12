from datetime import datetime, timedelta, timezone
import io
import json
import shutil
import subprocess
import sys

import pytest

import gpx_countries as script


def ring(west, south, east, north):
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def country_data():
    return {"type": "FeatureCollection", "features": [
        {"properties": {"NAME_EN": "Alpha", "ISO_A2_EH": "-99", "ISO_A2": "AA"},
         "geometry": {"type": "Polygon", "coordinates": [ring(0, 0, 10, 10), ring(4, 4, 6, 6)]}},
        {"properties": {"ADMIN": "Beta", "ISO_A2_EH": "BB"},
         "geometry": {"type": "MultiPolygon", "coordinates": [
             [ring(20, 0, 22, 2)], [ring(179, -1, 180, 1)], [ring(-180, -1, -179, 1)],
         ]}},
    ]}


def gpx(body, namespace="http://www.topografix.com/GPX/1/1"):
    attribute = f' xmlns="{namespace}"' if namespace else ""
    return f"<gpx{attribute}>{body}</gpx>".encode()


def test_polygon_holes_islands_boundaries_and_date_line():
    lookup = script.country_lookup(country_data())
    assert lookup(2, 2) == ("Alpha", "AA")
    assert lookup(0, 0) == lookup(10, 5) == ("Alpha", "AA")
    assert lookup(5, 5) is None  # The interior hole is not part of Alpha.
    assert lookup(1, 21) == lookup(0, 179.5) == lookup(0, -179.5) == ("Beta", "BB")
    assert lookup(50, 50) is None  # Offshore points are not assigned to the nearest country.


@pytest.mark.parametrize("namespace", ["", "http://www.topografix.com/GPX/1/0",
                                       "http://www.topografix.com/GPX/1/1"])
def test_track_route_waypoints_and_utc_timestamps(namespace):
    points = list(script.gpx_points(io.BytesIO(gpx('''
        <wpt lat="2" lon="2"><time>2026-01-02T00:30:00+02:00</time></wpt>
        <rte><rtept lat="1" lon="21"/></rte>
        <trk><trkseg><trkpt lat="2" lon="3"><time>2026-01-03T01:02:03.456Z</time></trkpt></trkseg></trk>
        <extensions xmlns:x="urn:foreign"><x:trkpt lat="50" lon="50"/></extensions>
        <extensions><trkpt lat="50" lon="50"/></extensions>
    ''', namespace))))
    assert len(points) == 3
    assert points[0] == (2, 2, datetime(2026, 1, 1, 22, 30, tzinfo=timezone.utc))
    assert points[1] == (1, 21, None)
    assert points[2][2].microsecond == 456000


def test_summary_exact_utc_bounds_unknown_times_and_unassigned_row():
    points = list(script.gpx_points(io.BytesIO(gpx('''
        <wpt lat="2" lon="2"><time>2026-01-03T02:03:04Z</time></wpt>
        <wpt lat="2" lon="3"><time>2026-01-02T00:30:00+02:00</time></wpt>
        <wpt lat="1" lon="21"/>
        <wpt lat="50" lon="50"><time>2026-01-05T12:00:00Z</time></wpt>
    '''))))
    stats, total, unassigned = script.summarize(points, script.country_lookup(country_data()))
    assert total == 4 and unassigned == 1
    assert stats[("Alpha", "AA")][0] == 2
    assert stats[("Beta", "BB")] == [1, None, None]
    assert stats[None][0] == 1
    table = script.format_table(stats, total, unassigned)
    assert "2026-01-01T22:30:00Z" in table and "2026-01-03T02:03:04Z" in table
    assert "2026-01-05T12:00:00Z" in table and "Unassigned / offshore" in table
    assert "Countries/territories: 2" in table and "GPX points: 4" in table
    assert "not continuous stays" in table


def test_table_keeps_fractional_precision_and_groups_large_counts():
    time = datetime(2026, 1, 1, 12, 34, 56, 123400, tzinfo=timezone.utc)
    table = script.format_table({("Alpha", "AA"): [1234, time, time]}, 1234, 0)
    assert "1,234" in table and "2026-01-01T12:34:56.1234Z" in table


def test_timeline_sorts_points_and_gives_each_return_its_own_period():
    countries = {1: ("Canada", "CA"), 2: ("Peru", "PE"), 3: ("United States", "US"),
                 4: ("Japan", "JP"), 5: ("China", "CN")}
    sequence = [1, 2, 1, 3, 4, 1, 5, 4, 5]
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = []
    for index, country in enumerate(sequence):
        begin = base + timedelta(days=index * 4)
        points += [(country, 0, begin), (country, 0, begin + timedelta(days=1, hours=3, minutes=15))]
    periods, total, unassigned, untimed = script.group_timeline(
        reversed(points), lambda latitude, _longitude: countries[latitude]
    )
    assert [period[0] for period in periods] == [countries[value] for value in sequence]
    assert [period[1] for period in periods] == [2] * 9
    assert periods[0][2] == base
    assert periods[0][3] == base + timedelta(days=1, hours=3, minutes=15)
    assert total == 18 and unassigned == untimed == 0
    table = script.format_timeline(periods, total, unassigned, untimed)
    assert table.count("| Canada") == 3 and table.count("| China") == 2
    assert "Begin (UTC)" in table and "End (UTC)" in table
    assert "1 day, 3:15:00" in table and "Recorded periods: 9" in table


def test_unassigned_periods_break_runs_and_untimed_points_are_unplaced():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lookup = lambda latitude, _longitude: ("Alpha", "AA") if latitude == 1 else None
    result = script.group_timeline([
        (1, 0, base), (0, 0, base + timedelta(hours=1)),
        (1, 0, base + timedelta(hours=2)), (1, 0, None), (0, 0, None),
    ], lookup)
    periods, total, unassigned, untimed = result
    assert [row[0] for row in periods] == [("Alpha", "AA"), None, ("Alpha", "AA"), ("Alpha", "AA"), None]
    assert all(row[2] is None and row[3] is None for row in periods[-2:])
    assert (total, unassigned, untimed) == (5, 2, 2)
    table = script.format_timeline(*result)
    assert "Recorded periods: 3" in table and "Untimed: 2" in table
    assert "Untimed points are grouped by country at the end" in table


def test_timeline_keeps_offshore_before_grouping_same_country_points():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = script.group_timeline([
        (1, 0, base), (0, 0, base + timedelta(hours=1)),
        (1, 0, base + timedelta(hours=2)), (0, 0, None),
    ], lambda latitude, _longitude: ("Alpha", "AA") if latitude == 1 else None)
    table = script.format_timeline(*result)
    rows = [line.split("|") for line in table.splitlines()[2:] if line.startswith("|")]
    assert [row[1].strip() for row in rows] == ["Alpha", "Unassigned / offshore", "Alpha", "Unassigned / offshore"]
    assert rows[0][3].strip() == "1"
    assert rows[0][4].strip() == "2026-01-01T00:00:00Z"
    assert rows[0][5].strip() == "2026-01-01T00:00:00Z"
    assert rows[0][6].strip() == "0:00:00"
    assert "Recorded periods: 3" in table and "GPX points represented: 4" in table
    assert "excluded before grouping" not in table
    assert "Untimed points are grouped" in table


def test_offshore_and_other_countries_both_split_returns():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lookup = script.country_lookup(country_data())
    points = [(2, 2, base), (5, 5, base + timedelta(hours=1)),
              (2, 2, base + timedelta(hours=2)), (1, 21, base + timedelta(hours=3)),
              (5, 5, base + timedelta(hours=4)), (2, 2, base + timedelta(hours=5))]
    periods, total, unassigned, untimed = script.group_timeline(reversed(points), lookup)
    assert [period[0] for period in periods] == [("Alpha", "AA"), None, ("Alpha", "AA"), ("Beta", "BB"), None, ("Alpha", "AA")]
    assert [period[1] for period in periods] == [1] * 6
    assert periods[0][2:] == [base, base]
    assert periods[-1][2:] == [base + timedelta(hours=5), base + timedelta(hours=5)]
    assert (total, unassigned, untimed) == (6, 2, 0)


def test_timeline_with_only_offshore_points_displays_them():
    time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = script.group_timeline([(0, 0, time)], lambda *_: None)
    table = script.format_timeline(*result)
    assert len([line for line in table.splitlines() if line.startswith("|")]) == 3
    assert "Countries/territories: 0" in table and "Recorded periods: 1" in table
    assert "| Unassigned / offshore" in table


@pytest.mark.parametrize("flags", [[], ["--denoise"], ["--no-denoise"]])
def test_timeline_keeps_offshore_without_contradicting_evidence(tmp_path, capsys, flags):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    source.write_bytes(gpx('''
        <wpt lat="2" lon="2"><time>2026-01-01T00:00:00Z</time></wpt>
        <wpt lat="5" lon="5"><time>2026-01-01T01:00:00Z</time></wpt>
        <wpt lat="2" lon="2"><time>2026-01-01T02:00:00Z</time></wpt>
    '''))
    assert script.main([str(source), "--country-data", str(boundaries), "--timeline", *flags]) == 0
    output = capsys.readouterr().out
    assert [line.split("|")[1].strip() for line in output.splitlines()[2:] if line.startswith("|")] == [
        "Alpha", "Unassigned / offshore", "Alpha"]


def test_all_untimed_points_have_no_invented_period_or_span():
    result = script.group_timeline([(1, 0, None), (1, 0, None)], lambda *_: ("Alpha", "AA"))
    assert result[0] == [[("Alpha", "AA"), 2, None, None]]
    table = script.format_timeline(*result)
    assert "Recorded periods: 0" in table and "Untimed: 2" in table
    assert table.splitlines()[2].count("—") == 3


@pytest.mark.parametrize("flags, expected", [
    ([], ["Alpha", "Beta"]), (["--summary"], ["Alpha", "Beta"]),
    (["--timeline"], ["Alpha", "Beta", "Alpha"]),
])
def test_output_view_flags(tmp_path, capsys, flags, expected):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    source.write_bytes(gpx('''
        <wpt lat="2" lon="2"><time>2026-01-03T00:00:00Z</time></wpt>
        <wpt lat="1" lon="21"><time>2026-01-02T00:30:00+02:00</time></wpt>
        <wpt lat="2" lon="2"><time>2026-01-01T00:00:00Z</time></wpt>
    '''))
    assert script.main([str(source), "--country-data", str(boundaries), *flags]) == 0
    output = capsys.readouterr().out
    rows = [line.split("|")[1].strip() for line in output.splitlines()[2:] if line.startswith("|")]
    assert rows == expected
    assert "2026-01-01T22:30:00Z" in output
    assert "Countries/territories: 2" in output


def test_summary_and_timeline_flags_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", "--summary", "--timeline"])
    assert error.value.code == 2
    assert "not allowed" in capsys.readouterr().err


def test_chronological_flag_has_been_renamed(capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", "--chronological"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def samples(coordinates, sequence=1, step_seconds=60):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [(lat, lon, base + timedelta(seconds=index * step_seconds), sequence)
            for index, (lat, lon) in enumerate(coordinates)]


def test_reader_retains_independent_tracks_routes_and_waypoints():
    body = '''<wpt lat="2" lon="2"/><wpt lat="2" lon="2"/>
        <rte><rtept lat="2" lon="2"/><rtept lat="2" lon="3"/></rte>
        <trk><trkseg><trkpt lat="2" lon="2"/><trkpt lat="2" lon="3"/></trkseg>
        <trkseg><trkpt lat="2" lon="2"/></trkseg></trk>'''
    result = list(script.gpx_samples(io.BytesIO(gpx(body))))
    assert [item[3] for item in result] == [1, 2, 3, 3, 4, 4, 5]


@pytest.mark.parametrize("flags, filtered", [([], True), (["--denoise"], True), (["--no-denoise"], False)])
@pytest.mark.parametrize("view", [[], ["--timeline"]])
def test_denoising_default_and_opt_out_in_both_views(tmp_path, capsys, flags, filtered, view):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    body = '<wpt lat="1" lon="21"><time>2026-01-01T00:06:00Z</time></wpt>' * 2
    body += '<trk><trkseg>' + ''.join(
        f'<trkpt lat="2" lon="{1 + index * .001}"><time>2026-01-01T00:{index:02}:00Z</time></trkpt>'
        for index in range(13)) + '</trkseg></trk>'
    original = gpx(body)
    source.write_bytes(original)
    assert script.main([str(source), "--country-data", str(boundaries), *view, *flags]) == 0
    output = capsys.readouterr().out
    assert ("| Beta" not in output) == filtered
    assert f"Denoising: {'on' if filtered else 'off'}" in output
    if filtered:
        assert "Input GPX points: 15" in output and "Distinct observations: 14" in output
        assert "isolated conflicts: 2" in output
    assert source.read_bytes() == original


def test_same_time_conflict_follows_supported_path_and_duplicates_do_not_vote():
    lookup = script.country_lookup(country_data())
    route = samples([(2, 1 + index * .001) for index in range(13)])
    conflicting = (1, 21, route[6][2], 2)
    fixes, report = script.denoise_samples([conflicting] * 100 + route, lookup)
    assert len(fixes) == 13
    assert report["isolated"] == 100
    assert all(fix.country == ("Alpha", "AA") for fix in fixes)


def test_sparse_context_can_use_pooled_limits_without_fabricating_a_local_fit():
    lookup = script.country_lookup(country_data())
    context = samples([(2, 1), (2, 1.001)], sequence=2)
    orphan = (1, 21, context[0][2] + timedelta(seconds=8), 3)
    sparse, report = script.denoise_samples([*context, orphan], lookup)
    assert len(sparse) == 3 and report["isolated"] == 0
    training = [(lat, lon, time + timedelta(days=1), seq) for lat, lon, time, seq in
                samples([(2, 1 + index * .001) for index in range(13)])]
    fixes, report = script.denoise_samples([*training, *context, orphan], lookup)
    assert len(fixes) == 15 and report["isolated"] == 1


def test_agreement_from_another_supported_path_preserves_an_isolated_observation():
    lookup = script.country_lookup(country_data())
    first = samples([(2, 1 + index * .001) for index in range(13)])
    second = samples([(1, 21 + index * .001) for index in range(13)], sequence=2)
    orphan = (1, 21.0065, first[6][2] + timedelta(seconds=30), 3)
    fixes, report = script.denoise_samples([*first, *second, orphan], lookup)
    assert len(fixes) == 27 and report["isolated"] == 0


def test_path_spike_is_excluded_but_sparse_data_is_left_alone():
    lookup = script.country_lookup(country_data())
    route = samples([(2, 1 + index * .001) for index in range(31)])
    spike = (30, 30, route[15][2], 1)
    route[15] = spike
    fixes, report = script.denoise_samples(route, lookup)
    assert len(fixes) == 30 and report["spikes"] == 1
    sparse, report = script.denoise_samples(route[14:18], lookup)
    assert len(sparse) == 4 and report["spikes"] == 0


def coast_data(with_neighbor=False):
    data = {"type": "FeatureCollection", "features": [
        {"properties": {"NAME_EN": "Alpha", "ISO_A2": "AA"},
         "geometry": {"type": "Polygon", "coordinates": [ring(-1, -1, 0, 1)]}},
    ]}
    if with_neighbor:
        data["features"].append(
            {"properties": {"NAME_EN": "Beta", "ISO_A2": "BB"},
             "geometry": {"type": "Polygon", "coordinates": [ring(0, -1, 1, 1)]}})
    return data


@pytest.mark.parametrize("with_neighbor", [False, True])
def test_fitted_boundary_jitter_is_adjusted_before_country_grouping(with_neighbor):
    lookup = script.country_lookup(coast_data(with_neighbor))
    longitudes = [-.0002, -.0004, -.00025, -.00045, -.0002, .00005, -.0002,
                  -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
    route = samples([(.1 + index * .0001, lon) for index, lon in enumerate(longitudes)])
    fixes, report = script.denoise_samples(route, lookup)
    periods, total, unassigned, _untimed = script.group_timeline_labels(
        (fix.country, fix.time, fix.count) for fix in fixes)
    assert report["adjusted"] == 1 and report["spikes"] == 0
    assert len(periods) == 1 and periods[0][0] == ("Alpha", "AA")
    assert total == 13 and unassigned == 0


def test_another_coherent_source_can_block_a_boundary_reassignment():
    lookup = script.country_lookup(coast_data(with_neighbor=True))
    longitudes = [-.0002, -.0004, -.00025, -.00045, -.0002, .00005, -.0002,
                  -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
    first = samples([(.1 + index * .0001, lon) for index, lon in enumerate(longitudes)])
    second = samples([(.1 + index * .0001, .00005) for index in range(13)], sequence=2)
    fixes, report = script.denoise_samples([*first, *second], lookup)
    shared = [fix for fix in fixes if fix.sequences == {1, 2}]
    assert len(shared) == 1 and shared[0].country == ("Beta", "BB")
    assert report["adjusted"] == 0


def test_boundary_uncertainty_handles_holes_and_the_date_line():
    lookup = script.country_lookup(country_data())
    assert lookup.near(5, 5, ("Alpha", "AA"), 112)
    assert not lookup.near(5, 5, ("Alpha", "AA"), 110)
    for longitude in (-178.99, 178.99):
        assert lookup.near(0, longitude, ("Beta", "BB"), 2)
        assert not lookup.near(0, longitude, ("Beta", "BB"), 1)


def test_sustained_offshore_transit_and_short_coherent_country_crossing_remain():
    lookup = script.country_lookup(coast_data())
    route = samples([(.1, lon) for lon in [-.02, -.015, -.01, -.005, .005, .01, .005, -.005, -.01, -.015, -.02]])
    fixes, report = script.denoise_samples(route, lookup)
    assert sum(fix.country is None for fix in fixes) == 3
    assert report["adjusted"] == report["spikes"] == 0
    # A narrow country crossed on a coherent path is a real supported crossing,
    # even when it has only one recorded point and a zero recorded span.
    data = coast_data(with_neighbor=True)
    data["features"][0]["geometry"] = {"type": "MultiPolygon", "coordinates": [
        [ring(-1, -1, 0, 1)], [ring(.01, -1, 1, 1)]]}
    data["features"][1]["geometry"]["coordinates"] = [ring(0, -1, .01, 1)]
    route = samples([(.1, lon) for lon in [-.05, -.04, -.03, -.02, -.01, .005, .02, .03, .04, .05]])
    fixes, report = script.denoise_samples(route, script.country_lookup(data), gps_radius_meters=2000)
    assert sum(fix.country == ("Beta", "BB") for fix in fixes) == 1
    assert report["adjusted"] == report["spikes"] == 0


def test_denoiser_does_not_bridge_large_gaps_or_move_untimed_observations():
    lookup = script.country_lookup(coast_data())
    longitudes = [-.0002, -.0004, -.00025, -.00045, -.0002, .00005, -.0002,
                  -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
    route = samples([(.1 + index * .0001, lon) for index, lon in enumerate(longitudes)])
    route = [(lat, lon, time + (timedelta(hours=1) if index >= 5 else timedelta()), seq)
             for index, (lat, lon, time, seq) in enumerate(route)]
    fixes, report = script.denoise_samples([*route, (.1, .00005, None, 2)], lookup)
    assert sum(fix.country is None for fix in fixes) == 2
    assert report["adjusted"] == 0


def test_no_denoise_preserves_equal_time_order_and_every_point():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    route = [(2, 2, base, 1), (1, 21, base, 2), (2, 2, base, 3)]
    fixes, _report = script.denoise_samples(route, script.country_lookup(country_data()), enabled=False)
    periods, total, _unassigned, _untimed = script.group_timeline_labels(
        (fix.country, fix.time, fix.count) for fix in fixes)
    assert [row[0][1] for row in periods] == ["AA", "BB", "AA"]
    assert total == 3


def test_fitted_filter_scales_with_sample_rate_and_distance():
    # Within the explicit time cap, the inferred radius scales with the data.
    results = []
    for scale, step in [(1, 60), (10, 600)]:
        data = coast_data()
        for point in data["features"][0]["geometry"]["coordinates"][0]:
            point[0] *= scale
        longitudes = [-.0002, -.0004, -.00025, -.00045, -.0002, .00005, -.0002,
                      -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
        route = samples([(.1 + index * .0001, lon * scale)
                         for index, lon in enumerate(longitudes)], step_seconds=step)
        fixes, report = script.denoise_samples(route, script.country_lookup(data), gps_max_minutes=30)
        results.append(([fix.country for fix in fixes], report["adjusted"]))
    assert results[0] == results[1]


def border_jitter_samples(depth=.00005, count=3):
    before = [-.0002, -.0004, -.00025, -.00045, -.0002, -.0004]
    after = [-.0002, -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
    return samples([(.1 + index * .0001, lon) for index, lon in
                    enumerate([*before, *([depth] * count), *after])])


@pytest.mark.parametrize("with_neighbor", [False, True])
def test_short_sparse_border_run_uses_polygon_distance_and_merges_before_grouping(with_neighbor):
    route = border_jitter_samples()
    fixes, report = script.denoise_samples(route, script.country_lookup(coast_data(with_neighbor)))
    periods, total, unassigned, _ = script.group_timeline_labels((f.country, f.time, f.count) for f in fixes)
    assert report["adjusted"] == 3 and report["spikes"] == 0
    assert len(periods) == 1 and periods[0][0] == ("Alpha", "AA")
    assert total == len(route) and unassigned == 0
    assert 5 < report["max_border_distance_meters"] < 6
    assert "GPS border filter:" in script.format_denoising(report)


def test_distance_is_to_requested_polygon_not_a_centroid_or_first_matching_country():
    data = coast_data(with_neighbor=True)
    lookup = script.country_lookup(data)
    assert .110 < lookup.distance_to(0, .001, ("Alpha", "AA")) < .112
    assert lookup.distance_to(0, -.5, ("Alpha", "AA")) == 0
    assert lookup.distance_to(0, .001, ("Alpha", "AA"), limit=.1) == float("inf")
    # Both polygons contain this point; lookup order must not change distance.
    data["features"][1]["geometry"]["coordinates"] = [ring(-.5, -1, 1, 1)]
    lookup = script.country_lookup(data)
    assert lookup(0, -.25) == ("Alpha", "AA")
    assert lookup.distance_to(0, -.25, ("Beta", "BB")) == 0


def test_radius_override_has_a_measurable_border_distance_cutoff():
    route = border_jitter_samples(depth=.005)
    lookup = script.country_lookup(coast_data(with_neighbor=True))
    small, small_report = script.denoise_samples(route, lookup, gps_radius_meters=500)
    large, large_report = script.denoise_samples(route, lookup, gps_radius_meters=600)
    assert sum(f.country == ("Beta", "BB") for f in small) == 3
    assert small_report["adjusted"] == 0
    assert all(f.country == ("Alpha", "AA") for f in large)
    assert large_report["adjusted"] == 3
    assert 550 < large_report["max_border_distance_meters"] < 560
    assert "600 m (override)" in script.format_denoising(large_report)


def test_suspect_points_do_not_inflate_the_automatic_gps_radius():
    lookup = script.country_lookup(coast_data(with_neighbor=True))
    _shallow, first = script.denoise_samples(border_jitter_samples(depth=.00005), lookup)
    deep, second = script.denoise_samples(border_jitter_samples(depth=.005), lookup)
    assert first["gps_radii"] == pytest.approx(second["gps_radii"])
    assert first["adjusted"] == 3 and second["adjusted"] == 0
    assert sum(f.country == ("Beta", "BB") for f in deep) == 3


@pytest.mark.parametrize("options", [{"gps_max_points": 2}, {"gps_max_minutes": 3}])
def test_short_time_and_few_points_are_both_required(options):
    fixes, report = script.denoise_samples(border_jitter_samples(),
                                          script.country_lookup(coast_data(with_neighbor=True)), **options)
    assert report["adjusted"] == 0
    assert sum(f.country == ("Beta", "BB") for f in fixes) == 3


def test_duplicate_gpx_points_do_not_count_as_independent_border_support():
    route = border_jitter_samples()
    repeated = [point for point in route for _ in range(100)]
    fixes, report = script.denoise_samples(repeated, script.country_lookup(coast_data(with_neighbor=True)))
    assert report["adjusted"] == 300
    assert sum(f.count for f in fixes) == len(repeated)
    assert all(f.country == ("Alpha", "AA") for f in fixes)


def test_gps_filter_requires_a_return_to_the_previous_country():
    route = border_jitter_samples()
    # Continue in Beta instead of returning; even a broad radius cannot turn
    # a new country arrival into a return to Alpha.
    route = route[:9]
    fixes, report = script.denoise_samples(route, script.country_lookup(coast_data(with_neighbor=True)),
                                          gps_radius_meters=1000)
    assert report["adjusted"] == 0
    assert sum(f.country == ("Beta", "BB") for f in fixes) == 3


def test_alternating_short_runs_do_not_swap_noise_into_the_surrounding_country():
    # Three short Beta fixes, three Alpha fixes, two Beta fixes, then Alpha.
    # The short Alpha interval must not get reassigned to Beta while the two
    # Beta bursts are being corrected to the well-supported Alpha country.
    longitudes = [-.0002, -.0004, -.00025, -.00045, -.0002, -.0004]
    longitudes += [.005] * 3 + [-.0002, -.0004, -.00025] + [.005] * 2
    longitudes += [-.0002, -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
    route = samples([(.1 + index * .0001, lon) for index, lon in enumerate(longitudes)])
    fixes, report = script.denoise_samples(route, script.country_lookup(coast_data(with_neighbor=True)),
                                          gps_radius_meters=600)
    assert report["adjusted"] == 5 and report["spikes"] == 0
    assert all(f.country == ("Alpha", "AA") for f in fixes)


def test_unsupported_alternating_countries_remain_uncertain_even_with_an_override():
    route = samples([(.1 + index * .0001, -.00005 if index % 2 else .00005)
                     for index in range(15)])
    lookup = script.country_lookup(coast_data(with_neighbor=True))
    fixes, report = script.denoise_samples(route, lookup, gps_radius_meters=1000)
    assert report["adjusted"] == report["spikes"] == 0
    assert [f.country for f in fixes] == [lookup(lat, lon) for lat, lon, _time, _seq in route]


@pytest.mark.parametrize("radius, corrected", [(None, True), (5, False), (10, True)])
def test_isolated_near_border_marker_is_reassigned_instead_of_discarded(radius, corrected):
    route = border_jitter_samples(count=0)
    orphan = (.10065, .00005, route[6][2] + timedelta(seconds=30), 2)
    fixes, report = script.denoise_samples([*route, orphan, orphan],
                                          script.country_lookup(coast_data(with_neighbor=True)),
                                          gps_radius_meters=radius, gps_max_points=1)
    marker = next(fix for fix in fixes if fix.time == orphan[2])
    assert marker.country == (("Alpha", "AA") if corrected else ("Beta", "BB"))
    assert marker.count == 2 and sum(f.count for f in fixes) == len(route) + 2
    assert report["isolated"] == report["spikes"] == 0
    assert report["adjusted"] == (2 if corrected else 0)


def test_supported_nearby_country_path_vetoes_an_isolated_border_correction():
    route = border_jitter_samples(count=0)
    other = samples([(.1 + index * .0001, .00005) for index in range(len(route))], sequence=2)
    orphan = (.10065, .00005, route[6][2] + timedelta(seconds=30), 3)
    fixes, report = script.denoise_samples([*route, *other, orphan],
                                          script.country_lookup(coast_data(with_neighbor=True)),
                                          gps_radius_meters=1000)
    marker = next(fix for fix in fixes if fix.time == orphan[2])
    assert marker.country == ("Beta", "BB")
    assert report["adjusted"] == report["isolated"] == 0


def test_isolated_border_marker_needs_observations_on_both_sides():
    route = border_jitter_samples(count=0)
    orphan = (.09995, .00005, route[0][2] - timedelta(seconds=30), 2)
    fixes, report = script.denoise_samples([*route, orphan],
                                          script.country_lookup(coast_data(with_neighbor=True)),
                                          gps_radius_meters=1000)
    marker = next(fix for fix in fixes if fix.time == orphan[2])
    assert marker.country == ("Beta", "BB")
    assert report["adjusted"] == report["isolated"] == 0


def test_radius_override_can_use_country_support_across_gpx_segment_boundaries():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    before = [(lat, lon, time - timedelta(minutes=8), seq) for lat, lon, time, seq in
              samples([(.1, -.0003)] * 8)]
    region = samples([(.1, lon) for lon in [-.0003, -.0003, .005, .005, .005,
                                          -.0003, -.0003, -.0003]], sequence=2)
    assert region[0][2] == base
    lookup = script.country_lookup(coast_data(with_neighbor=True))
    auto, auto_report = script.denoise_samples([*before, *region], lookup)
    manual, manual_report = script.denoise_samples([*before, *region], lookup, gps_radius_meters=600)
    assert auto_report["adjusted"] == 0 and sum(f.country == ("Beta", "BB") for f in auto) == 3
    assert manual_report["adjusted"] == 3
    assert all(f.country == ("Alpha", "AA") for f in manual)


def bay_data(foreign_bridge=False):
    # Land on both sides of a small bay; the straight bridge crosses water.
    data = {"type": "FeatureCollection", "features": [
        {"properties": {"NAME_EN": "Alpha", "ISO_A2": "AA"},
         "geometry": {"type": "Polygon", "coordinates": [[
             [-.01, -.01], [.01, -.01], [.01, .01], [.002, .01], [.002, 0],
             [-.002, 0], [-.002, .01], [-.01, .01], [-.01, -.01]]]}},
    ]}
    if foreign_bridge:
        data["features"].append(
            {"properties": {"NAME_EN": "Beta", "ISO_A2": "BB"},
             "geometry": {"type": "Polygon", "coordinates": [ring(-.0015, .00045, .0015, .0007)]}})
    return data


def bay_samples():
    longitudes = [-.009, -.008, -.007, -.006, -.005, -.003, -.001, .001,
                  .003, .004, .005, .006, .007, .008, .009]
    latitudes = [.0005, .0012, .0006, .0011, .0004, .0006, .0004, .0004,
                 .0005, .0012, .0006, .0011, .0004, .001, .0006]
    return samples(list(zip(latitudes, longitudes)))


@pytest.mark.parametrize("radius", [None, 100])
def test_nearshore_gap_can_merge_when_the_bridge_is_also_unassigned(radius):
    route = bay_samples()
    lookup = script.country_lookup(bay_data())
    a, b = [script.Fix(lat, lon, time, lookup(lat, lon)) for lat, lon, time, _seq in (route[5], route[8])]
    assert all(lookup(lat, lon) is None for lat, lon, _time, _seq in route[6:8])
    assert all(lookup(p.latitude, p.longitude) is None
               for p in [script.interpolate(a, b, route[index][2]) for index in (6, 7)])
    fixes, report = script.denoise_samples(route, lookup, gps_radius_meters=radius)
    assert report["adjusted"] == 2 and report["spikes"] == 0
    assert all(f.country == ("Alpha", "AA") for f in fixes)
    assert sum(f.count for f in fixes) == len(route)


def test_nearshore_gap_stays_unassigned_if_its_bridge_crosses_another_country():
    route = bay_samples()
    lookup = script.country_lookup(bay_data(foreign_bridge=True))
    fixes, report = script.denoise_samples(route, lookup, gps_radius_meters=1000)
    assert report["adjusted"] == 0
    assert sum(f.country is None for f in fixes) == 2


@pytest.mark.parametrize("options", [{"gps_max_points": 1}, {"gps_max_minutes": 2}])
def test_nearshore_bridge_still_requires_short_time_and_few_points(options):
    fixes, report = script.denoise_samples(bay_samples(), script.country_lookup(bay_data()),
                                          gps_radius_meters=100, **options)
    assert report["adjusted"] == 0
    assert sum(f.country is None for f in fixes) == 2


def test_duplicate_short_segment_without_foreign_evidence_does_not_veto_a_correction():
    route = border_jitter_samples()
    short = [(lat, lon, time, 2) for lat, lon, time, _sequence in route[6:8]]
    fixes, report = script.denoise_samples([*route, *short], script.country_lookup(coast_data()))
    assert report["adjusted"] == 5
    assert all(f.country == ("Alpha", "AA") for f in fixes)
    assert sum(f.count for f in fixes) == len(route) + len(short)


def test_adjacent_coastal_gaps_are_revisited_without_reclassifying_known_countries():
    longitudes = [-.0002, -.0004, -.00025, -.00045, -.0002, -.0004]
    longitudes += [.00005, .00005, -.0002, .00005, .00005, -.0003, .00005, .00005]
    longitudes += [-.0002, -.00045, -.00025, -.0004, -.0002, -.0004, -.0003]
    route = samples([(.1 + index * .0001, lon) for index, lon in enumerate(longitudes)])
    fixes, report = script.denoise_samples(route, script.country_lookup(coast_data()))
    assert report["adjusted"] == 6 and report["spikes"] == 0
    assert all(f.country == ("Alpha", "AA") for f in fixes)
    assert sum(f.count for f in fixes) == len(route)


@pytest.mark.parametrize("unassigned", [False, True])
def test_short_segment_with_foreign_evidence_still_vetoes_a_correction(unassigned):
    route = border_jitter_samples()
    data = coast_data(with_neighbor=True)
    if unassigned:
        data["features"][1]["geometry"]["coordinates"] = [ring(.0003, -1, 1, 1)]
    lat, lon, time, _seq = route[6]
    short = [(lat, lon, time, 2), (lat + .00005, .0004, time + timedelta(seconds=30), 2)]
    fixes, _report = script.denoise_samples([*route, *short], script.country_lookup(data), gps_radius_meters=1000)
    shared = next(f for f in fixes if f.time == time)
    assert shared.country == (None if unassigned else ("Beta", "BB"))
    assert shared.count == 2


@pytest.mark.parametrize("flags", [
    ["--gps-radius-meters", "0"], ["--gps-radius-meters", "nan"],
    ["--gps-radius-meters", "inf"], ["--gps-max-minutes", "-1"],
    ["--gps-max-minutes", "nan"], ["--gps-max-minutes", "inf"],
    ["--gps-max-points", "0"], ["--gps-max-points", "-1"],
])
def test_gps_filter_invalid_limits_fail_before_file_access(flags, capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", *flags])
    assert error.value.code == 2
    assert "positive" in capsys.readouterr().err


def test_gps_filter_cli_override_and_raw_opt_out(tmp_path, capsys):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(coast_data(with_neighbor=True)))
    route = border_jitter_samples(depth=.005)
    body = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                   for lat, lon, time, _sequence in route)
    original = gpx('<trk><trkseg>' + body + '</trkseg></trk>')
    source.write_bytes(original)
    arguments = [str(source), "--country-data", str(boundaries), "--timeline", "--gps-radius-meters", "600"]
    assert script.main(arguments) == 0
    output = capsys.readouterr().out
    assert "| Beta" not in output and "Boundary assignments adjusted: 3" in output
    assert "600 m (override)" in output
    assert script.main([*arguments, "--no-denoise"]) == 0
    output = capsys.readouterr().out
    assert "| Beta" in output and "Denoising: off" in output
    assert source.read_bytes() == original


@pytest.mark.parametrize("body", [
    '<wpt lat="PRIVATE_LOCATION" lon="2"/>', '<wpt lat="nan" lon="2"/>',
    '<wpt lat="91" lon="2"/>', '<wpt lat="2" lon="181"/>', '<wpt lon="2"/>',
    '<wpt lat="2" lon="2"><time>2026-01-01T12:00:00</time></wpt>',
    '<wpt lat="2" lon="2"><time>PRIVATE_TIME</time></wpt>',
])
def test_invalid_points_fail_without_echoing_private_values(body):
    with pytest.raises(ValueError) as error:
        list(script.gpx_points(io.BytesIO(gpx(body))))
    assert "PRIVATE" not in str(error.value)


def test_empty_gpx_fails_before_any_download(tmp_path, monkeypatch, capsys):
    source = tmp_path / "empty.gpx"
    source.write_bytes(gpx(""))
    monkeypatch.setattr(script, "urlopen", lambda *_args, **_kwargs: pytest.fail("unexpected network"))
    with pytest.raises(SystemExit) as error:
        script.main([str(source)])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out and "no track points" in captured.err


def test_download_once_then_reuse_cache_offline(tmp_path, monkeypatch):
    path = tmp_path / "cache" / "countries.geojson"
    requests = []

    def download(request, **_kwargs):
        requests.append(request.full_url)
        return io.BytesIO(json.dumps(country_data()).encode())

    monkeypatch.setattr(script, "urlopen", download)
    assert script.load_countries(path, download=True) == country_data()
    monkeypatch.setattr(script, "urlopen", lambda *_args, **_kwargs: pytest.fail("unexpected network"))
    assert script.load_countries(path, download=True) == country_data()
    assert requests == [script.DATA_URL]


def test_bad_download_does_not_leave_a_corrupt_cache(tmp_path, monkeypatch):
    path = tmp_path / "countries.geojson"
    monkeypatch.setattr(script, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"not JSON"))
    with pytest.raises(ValueError):
        script.load_countries(path, download=True)
    assert not path.exists() and list(tmp_path.iterdir()) == []


def test_custom_country_data_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "urlopen", lambda *_args, **_kwargs: pytest.fail("unexpected network"))
    with pytest.raises(FileNotFoundError):
        script.load_countries(tmp_path / "missing.geojson")


def test_script_runs_when_copied_alone_and_prints_a_timestamp_table(tmp_path):
    standalone = tmp_path / "gpx_countries.py"
    shutil.copyfile(script.__file__, standalone)
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    source.write_bytes(gpx('<wpt lat="2" lon="2"><time>2026-01-01T12:34:56Z</time></wpt>'))
    result = subprocess.run(
        [sys.executable, "-I", str(standalone), str(source), "--country-data", str(boundaries)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "| Alpha" in result.stdout and "2026-01-01T12:34:56Z" in result.stdout
    assert "Countries/territories: 1" in result.stdout and not result.stderr
