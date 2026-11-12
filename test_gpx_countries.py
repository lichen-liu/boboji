from datetime import datetime, timezone
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
