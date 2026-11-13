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
    assert "2026-01-05T12:00:00Z" in table and "Unassigned" in table
    assert "Countries/territories: 2" in table and "GPX points: 4" in table
    assert "do not establish continuous stays" in table


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
    assert "Untimed points follow the timeline" in table


def test_timeline_keeps_unassigned_before_grouping_same_country_points():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = script.group_timeline([
        (1, 0, base), (0, 0, base + timedelta(hours=1)),
        (1, 0, base + timedelta(hours=2)), (0, 0, None),
    ], lambda latitude, _longitude: ("Alpha", "AA") if latitude == 1 else None)
    table = script.format_timeline(*result)
    rows = [line.split("|") for line in table.splitlines()[2:] if line.startswith("|")]
    assert [row[1].strip() for row in rows] == ["Alpha", "Unassigned", "Alpha", "Unassigned"]
    assert rows[0][3].strip() == "1"
    assert rows[0][4].strip() == "2026-01-01T00:00:00Z"
    assert rows[0][5].strip() == "2026-01-01T00:00:00Z"
    assert rows[0][6].strip() == "0:00:00"
    assert "Recorded periods: 3" in table and "GPX points represented: 4" in table
    assert "excluded before grouping" not in table
    assert "Untimed points follow the timeline" in table


def test_unassigned_and_other_countries_both_split_returns():
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


def test_timeline_with_only_unassigned_points_displays_them():
    time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = script.group_timeline([(0, 0, time)], lambda *_: None)
    table = script.format_timeline(*result)
    assert len([line for line in table.splitlines() if line.startswith("|")]) == 3
    assert "Countries/territories: 0" in table and "Recorded periods: 1" in table
    assert "| Unassigned" in table


@pytest.mark.parametrize("flags", [[], ["--denoise"], ["--no-denoise"]])
def test_timeline_keeps_unassigned_without_contradicting_evidence(tmp_path, capsys, flags):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    source.write_bytes(gpx('''
        <wpt lat="2" lon="2"><time>2026-01-01T00:00:00Z</time></wpt>
        <wpt lat="5" lon="5"><time>2026-01-01T01:00:00Z</time></wpt>
        <wpt lat="2" lon="2"><time>2026-01-01T02:00:00Z</time></wpt>
    '''))
    assert script.main([str(source), "--country-data", str(boundaries), "--timeline", *flags, "--no-remove-unassigned"]) == 0
    output = capsys.readouterr().out
    assert [line.split("|")[1].strip() for line in output.splitlines()[2:] if line.startswith("|")] == [
        "Alpha", "Unassigned", "Alpha"]


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
    assert script.main([str(source), "--country-data", str(boundaries), *flags,
                        "--no-remove-unassigned", "--no-singleton-denoise"]) == 0
    output = capsys.readouterr().out
    rows = [line.split("|")[1].strip() for line in output.splitlines()[2:] if line.startswith("|")]
    assert rows == expected
    assert "2026-01-01T22:30:00Z" in output
    assert "Countries/territories: 2" in output


def test_summary_and_timeline_flags_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", "--summary", "--timeline", "--no-remove-unassigned"])
    assert error.value.code == 2
    assert "not allowed" in capsys.readouterr().err


def test_chronological_flag_has_been_renamed(capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", "--chronological", "--no-remove-unassigned"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


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
        script.main([str(source), "--no-remove-unassigned"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out and "no track points" in captured.err


def test_download_once_then_reuse_cache_offline(tmp_path, monkeypatch, capsys):
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
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


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


def test_only_tracking_points_supply_motion_groups():
    body = '''<wpt lat="2" lon="2"/><wpt lat="2" lon="2"/>
        <rte><rtept lat="2" lon="2"/><rtept lat="2" lon="3"/></rte>
        <trk><trkseg><trkpt lat="2" lon="2"/><trkpt lat="2" lon="3"/></trkseg>
        <trkseg><trkpt lat="2" lon="2"/></trkseg></trk>'''
    assert [p[3] for p in script.gpx_samples(io.BytesIO(gpx(body)))] == [1, 2, 3, 3, 4, 4, 5]
    assert [p[3] for p in script.gpx_samples(io.BytesIO(gpx(body)), motion_groups=True)] == [
        None, None, None, None, 4, 4, 5]


@pytest.mark.parametrize("flags, filtered", [([], True), (["--denoise"], True), (["--no-denoise"], False)])
@pytest.mark.parametrize("view", [[], ["--timeline"]])
def test_denoising_default_and_opt_out_in_both_views(tmp_path, capsys, flags, filtered, view):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    points = []
    for index in range(13):
        lat, lon = (1, 21) if index == 6 else (2, 1 + index * .001)
        point = f'<trkpt lat="{lat}" lon="{lon}"><time>2026-01-01T00:{index:02}:00Z</time></trkpt>'
        points.extend([point, point] if index == 6 else [point])
    original = gpx('<trk><trkseg>' + ''.join(points) + '</trkseg></trk>')
    source.write_bytes(original)
    assert script.main([str(source), "--country-data", str(boundaries), *view, *flags, "--no-remove-unassigned"]) == 0
    output = capsys.readouterr().out
    country_table = output.split("\n\n", 1)[0]
    assert ("| Beta" not in country_table) == filtered
    assert f"Denoising: {'on' if filtered else 'off'}" in output
    if filtered:
        assert "Input: 14" in output and "Kept: 12" in output and "Removed: 2" in output
        assert "Removed points: motion 2" in output
    assert source.read_bytes() == original


@pytest.mark.parametrize("flag", ["--gps-radius-meters", "--max-speed-kmh", "--max-gap-minutes", "--motion-slack-meters"])
@pytest.mark.parametrize("value", ["-1", "nan", "inf", "-inf"])
def test_invalid_movement_limits_fail_before_file_access(flag, value, capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", flag + "=" + value, "--no-remove-unassigned"])
    assert error.value.code == 2
    assert "must be finite" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--gps-radius-meters", "--max-speed-kmh", "--max-gap-minutes"])
def test_zero_positive_limits_fail_before_file_access(flag, capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", flag, "0", "--no-remove-unassigned"])
    assert error.value.code == 2
    assert "positive" in capsys.readouterr().err


def test_zero_motion_slack_is_allowed(tmp_path, capsys):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    source.write_bytes(gpx('<wpt lat="2" lon="2"/>'))
    assert script.main([str(source), "--country-data", str(boundaries), "--motion-slack-meters", "0",
                        "--no-remove-unassigned", "--verbose"]) == 0
    assert "position 0 km" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--gps-max-points", "--gps-max-minutes"])
def test_unsupported_short_visit_rules_are_removed(flag, capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["missing.gpx", flag, "5", "--no-remove-unassigned"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_waypoints_and_planned_routes_are_preserved_without_motion_screening(tmp_path, capsys):
    boundaries, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    boundaries.write_text(json.dumps(country_data()))
    body = '<wpt lat="1" lon="21"><time>2026-01-01T00:06:00Z</time></wpt>'
    body += '<rte>' + ''.join(
        f'<rtept lat="2" lon="{21 if i == 6 else 1}"><time>2026-01-01T00:{i:02}:00Z</time></rtept>'
        for i in range(13)) + '</rte>'
    source.write_bytes(gpx(body))
    assert script.main([str(source), "--country-data", str(boundaries), "--verbose", "--explain",
                        "--no-remove-unassigned", "--no-singleton-denoise"]) == 0
    output = capsys.readouterr().out
    assert "| Beta" in output.split("\n\n", 1)[0] and "Tracking: 0 checked fixes" in output
    assert "Removed points: motion 0" in output
