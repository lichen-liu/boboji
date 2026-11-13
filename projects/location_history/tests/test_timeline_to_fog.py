import json
import os
import shutil
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

import timeline_to_fog as script

NS = {"g": "http://www.topografix.com/GPX/1/1"}


def raw(latitude=515000000, time="2026-01-01T12:00:00Z", **extra):
    return {"latitudeE7": latitude, "longitudeE7": -1200000, "timestamp": time, **extra}


def test_raw_history_coordinates_timestamps_sorting_and_duplicates():
    first = {"latitudeE7": 515000000, "longitudeE7": -1200000,
             "timestampMs": "1767268800000", "altitude": 8}
    tracks = script.convert({"locations": [raw(515001000, "2026-01-01T07:01:00-05:00"), first, first]})
    assert [len(track) for track in tracks] == [2]
    assert tracks[0][0].latitude == 51.5
    assert tracks[0][0].longitude == -0.12
    assert tracks[0][0].elevation == 8
    assert tracks[0][1].time.isoformat() == "2026-01-01T12:01:00+00:00"


@pytest.mark.parametrize("wrapped", [False, True])
def test_phone_exports_absolute_and_offset_times(wrapped):
    segments = [{"startTime": "2026-01-01T07:00:00-05:00", "timelinePath": [
        {"point": "geo:51.5,-0.12", "durationMinutesOffsetFromStartTime": "0"},
        {"point": "51.501°, -0.121°", "durationMinutesOffsetFromStartTime": "1.5"},
        {"point": "51.502°, -0.122°", "time": "2026-01-01T12:03:00Z",
         "durationMinutesOffsetFromStartTime": "ignored"},
    ]}]
    tracks = script.convert({"semanticSegments": segments} if wrapped else segments)
    assert [len(track) for track in tracks] == [3]
    assert tracks[0][1].time.isoformat() == "2026-01-01T12:01:30+00:00"


def test_android_raw_positions_ignore_metadata_and_profiles():
    tracks = script.convert({
        "rawSignals": [{"wifiScan": {}}, {"position": {
            "LatLng": "51.5°, -0.12°", "timestamp": "2026-01-01T12:00:00Z",
            "altitudeMeters": 23.5,
        }}],
        "userLocationProfile": {"frequentPlaces": [{"placeLocation": "0°, 0°"}]},
    })
    assert len(tracks) == len(tracks[0]) == 1
    assert tracks[0][0].elevation == 23.5


def test_takeout_semantic_paths_and_isolated_endpoints():
    location = {"latitudeE7": 515000000, "longitudeE7": -1200000}
    waypoints = [{"latE7": 515000000, "lngE7": -1200000},
                 {"latE7": 515001000, "lngE7": -1201000}]
    tracks = script.convert({"timelineObjects": [
        {"activitySegment": {"simplifiedRawPath": {"points": [
            {**record, "timestampMs": str(1767268800000 + index * 60000)}
            for index, record in enumerate(waypoints)
        ]}, "waypointPath": {"waypoints": [{"latE7": 0, "lngE7": 0}]}}},
        {"activitySegment": {"waypointPath": {"waypoints": waypoints}}},
        {"activitySegment": {"startLocation": location, "endLocation": location}},
        {"placeVisit": {"location": location}},
    ]})
    assert [len(track) for track in tracks] == [2, 2, 1, 1, 1]
    assert tracks[1][0].time is None
    assert all(item.latitude > 51 for track in tracks for item in track)


@pytest.mark.parametrize("location", ["geo:51.5,-0.12", {"latLng": "51.5°, -0.12°"}])
def test_phone_visits_and_endpoints_remain_isolated(location):
    tracks = script.convert([
        {"visit": {"topCandidate": {"placeLocation": location}}},
        {"activity": {"start": location, "end": "geo:51.501,-0.121"}},
    ])
    assert [len(track) for track in tracks] == [1, 1, 1]


def test_gaps_jumps_conflicting_times_and_devices_stay_separate():
    tracks = script.convert({"locations": [
        raw(deviceTag=1), raw(515001000, "2026-01-01T12:01:00Z", deviceTag=1),
        raw(515002000, "2026-01-01T13:00:00Z", deviceTag=1),
        raw(505002000, "2026-01-01T13:01:00Z", deviceTag=1),
        raw(505003000, "2026-01-01T13:01:00Z", deviceTag=1), raw(deviceTag=2),
    ]})
    assert [len(track) for track in tracks] == [2, 1, 1, 1, 1]
    data = {"locations": [raw(), raw(515100000, "2026-01-01T12:10:00Z")]}
    assert len(script.convert(data, max_gap_minutes=5)) == 2
    assert len(script.convert(data, max_distance_km=1)) == 2
    assert 2 < script.distance_km(script.Point(0, 179.99), script.Point(0, -179.99)) < 3


@pytest.mark.parametrize("data", [
    {}, {"locations": []}, {"locations": {}}, {"rawSignals": [{"wifiScan": {}}]},
    {"locations": [raw(910000000)]}, {"locations": [raw(float("nan"))]},
    {"locations": [raw(True)]}, {"locations": [raw(time="2026-01-01T12:00:00")]},
    {"locations": [{"latitudeE7": 0, "longitudeE7": 0}]}, [{"unknown": {}}],
    [{"timelinePath": [{"point": "geo:0,0", "durationMinutesOffsetFromStartTime": -1}]}],
    [{"startTime": "2026-01-01T12:00:00Z", "timelinePath": [
        {"point": "geo:0,0", "durationMinutesOffsetFromStartTime": "1e300"}]}],
    [{"startTime": "2026-01-01T12:00:00Z", "endTime": "2026-01-01T12:05:00Z",
      "timelinePath": [{"point": "geo:0,0", "durationMinutesOffsetFromStartTime": 60}]}],
])
def test_invalid_exports_fail(data):
    with pytest.raises(ValueError):
        script.convert(data)


@pytest.mark.parametrize("options", [
    {"max_gap_minutes": 0}, {"max_gap_minutes": float("inf")},
    {"max_distance_km": 11}, {"max_distance_km": float("nan")},
])
def test_invalid_thresholds_fail(options):
    with pytest.raises(ValueError):
        script.convert({"locations": [raw()]}, **options)


def test_gpx_namespace_decimals_times_and_stationary_tracks():
    tracks = script.convert({"locations": [raw(altitude=8)]})
    root = ET.fromstring(script.to_gpx(tracks))
    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"
    assert root.attrib["version"] == "1.1"
    points = root.findall("g:trk/g:trkseg/g:trkpt", NS)
    assert len(points) == 2 and points[0].attrib == points[1].attrib
    assert points[0].find("g:time", NS).text == "2026-01-01T12:00:00Z"
    assert points[0].find("g:ele", NS).text == "8.0"
    root = ET.fromstring(script.to_gpx([[script.Point(1e-7, 179.99999999999997, elevation=1e-7)]]))
    point = root.find("g:trk/g:trkseg/g:trkpt", NS)
    assert point.attrib["lat"] == point.find("g:ele", NS).text == "0.0000001"
    assert float(point.attrib["lon"]) < 180


def test_script_runs_when_copied_alone_without_installation(tmp_path):
    standalone = tmp_path / "timeline_to_fog.py"
    shutil.copyfile(script.__file__, standalone)
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    source.write_bytes(b"\xef\xbb\xbf" + json.dumps({"locations": [raw()]}).encode())
    result = subprocess.run(
        [sys.executable, "-I", str(standalone), str(source), "-o", str(output)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(ET.parse(output).findall(".//g:trkpt", NS)) == 2


def test_existing_output_and_input_are_protected(tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    source.write_text(json.dumps({"locations": [raw()]}))
    output.write_text("original")
    with pytest.raises(SystemExit):
        script.main([str(source), "-o", str(output)])
    assert output.read_text() == "original"
    assert script.main([str(source), "-o", str(output), "--force"]) == 0
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        script.main([str(output), "-o", str(output), "--force"])
    assert output.read_bytes() == before
    linked = tmp_path / "linked.gpx"
    os.link(source, linked)
    with pytest.raises(SystemExit):
        script.main([str(source), "-o", str(linked), "--force"])
    assert linked.read_bytes() == source.read_bytes()


def test_multiple_files_validate_before_writing_and_keep_boundaries(tmp_path):
    first, second, output = (tmp_path / name for name in ("first.json", "second.json", "output.gpx"))
    first.write_text(json.dumps({"locations": [raw()]}))
    second.write_text("invalid JSON")
    with pytest.raises(SystemExit):
        script.main([str(first), str(second), "-o", str(output)])
    assert not output.exists()
    second.write_text(first.read_text())
    assert script.main([str(first), str(second), "-o", str(output)]) == 0
    assert len(ET.parse(output).findall("g:trk/g:trkseg", NS)) == 2


@pytest.mark.parametrize("content", [b"{invalid JSON}", b"\xff\xfe", json.dumps({
    "locations": [raw("PRIVATE_LOCATION")],
}).encode()])
def test_errors_do_not_expose_private_input_or_overwrite_files(tmp_path, capsys, content):
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    source.write_bytes(content)
    output.write_text("original")
    with pytest.raises(SystemExit) as raised:
        script.main([str(source), "-o", str(output), "--force"])
    assert raised.value.code == 2
    assert output.read_text() == "original"
    stderr = capsys.readouterr().err
    assert "PRIVATE_LOCATION" not in stderr and "Traceback" not in stderr
