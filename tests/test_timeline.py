from datetime import datetime, timezone

import pytest

from boboji.timeline import ConversionError, Point, combine, convert_history, distance_km


def raw(latitude=515000000, longitude=-1200000, time="2026-01-01T12:00:00Z", **extra):
    return {"latitudeE7": latitude, "longitudeE7": longitude, "timestamp": time, **extra}


def phone_path(points, **extra):
    return {"timelinePath": points, **extra}


def test_legacy_records_normalize_e7_utc_sort_and_deduplicate():
    first = {"latitudeE7": 515000000, "longitudeE7": -1200000, "timestampMs": "1767268800000", "altitude": 8}
    later = raw(515001000, -1201000, "2026-01-01T07:01:00-05:00")
    result = convert_history({"locations": [later, first, first.copy()]})
    assert result.point_count == 2
    assert len(result.tracks) == 1
    assert result.tracks[0][0] == Point(51.5, -0.12, datetime(2026, 1, 1, 12, tzinfo=timezone.utc), 8)
    assert result.tracks[0][1].time == datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)


def test_android_paths_raw_positions_and_metadata():
    document = {
        "semanticSegments": [phone_path([
            {"point": "51.5°, -0.12°", "time": "2026-01-01T12:00:00Z"},
            {"point": "51.501°, -0.121°", "time": "2026-01-01T12:01:00Z"},
        ])],
        "rawSignals": [
            {"wifiScan": {"timestamp": "2026-01-01T13:00:00Z"}},
            {"position": {"LatLng": "51.51°, -0.13°", "timestamp": "2026-01-01T13:00:00Z", "altitudeMeters": 23.5}},
        ],
        "userLocationProfile": {"frequentPlaces": [{"placeLocation": "0°, 0°"}]},
    }
    result = convert_history(document)
    assert [len(track) for track in result.tracks] == [2, 1]
    assert result.tracks[1][0].elevation == 23.5
    assert all(point.latitude != 0 for track in result.tracks for point in track)


def test_ios_geo_points_and_fractional_minute_offsets():
    result = convert_history([phone_path([
        {"point": "geo:51.5,-0.12", "durationMinutesOffsetFromStartTime": "0"},
        {"point": "geo:51.501,-0.121", "durationMinutesOffsetFromStartTime": "1.5"},
        {"point": "geo:51.502,-0.122", "time": "2026-01-01T12:03:00Z", "durationMinutesOffsetFromStartTime": "invalid"},
    ], startTime="2026-01-01T07:00:00-05:00", endTime="2026-01-01T12:05:00Z")])
    assert result.point_count == 3
    assert result.tracks[0][1].time == datetime(2026, 1, 1, 12, 1, 30, tzinfo=timezone.utc)
    assert result.tracks[0][2].time.minute == 3


@pytest.mark.parametrize("location", ["geo:51.5,-0.12", {"latLng": "51.5°, -0.12°"}])
def test_visits_and_activity_endpoints_are_isolated(location):
    result = convert_history([
        {"startTime": "2026-01-01T12:00:00Z", "visit": {"topCandidate": {"placeLocation": location}}},
        {"startTime": "2026-01-01T12:01:00Z", "endTime": "2026-01-01T12:02:00Z", "activity": {"start": location, "end": "geo:51.501,-0.121"}},
    ])
    assert [len(track) for track in result.tracks] == [1, 1, 1]


def test_legacy_semantic_prefers_recorded_path_and_preserves_untimed_waypoints():
    document = {"timelineObjects": [
        {"activitySegment": {
            "startLocation": {"latitudeE7": 0, "longitudeE7": 0},
            "simplifiedRawPath": {"points": [
                {"latE7": 515000000, "lngE7": -1200000, "timestampMs": "1767268800000"},
                {"latE7": 515001000, "lngE7": -1201000, "timestampMs": "1767268860000"},
            ]},
            "waypointPath": {"waypoints": [{"latE7": 0, "lngE7": 0}]},
        }},
        {"activitySegment": {"waypointPath": {"waypoints": [
            {"latE7": 515002000, "lngE7": -1202000},
            {"latE7": 515003000, "lngE7": -1203000},
        ]}}},
        {"placeVisit": {"location": {"latitudeE7": 515004000, "longitudeE7": -1204000}, "duration": {"startTimestamp": "2026-01-01T13:00:00Z"}}},
    ]}
    result = convert_history(document)
    assert [len(track) for track in result.tracks] == [2, 2, 1]
    assert result.tracks[1][0].time is None
    assert all(point.latitude > 51 for track in result.tracks for point in track)


def test_legacy_semantic_endpoints_do_not_become_a_route():
    result = convert_history({"timelineObjects": [{"activitySegment": {
        "startLocation": {"latitudeE7": 515000000, "longitudeE7": -1200000},
        "endLocation": {"latitudeE7": 515001000, "longitudeE7": -1201000},
        "duration": {"startTimestampMs": "1767268800000", "endTimestampMs": "1767268860000"},
    }}]})
    assert [len(track) for track in result.tracks] == [1, 1]


def test_time_gaps_jumps_equal_times_and_devices_split_tracks():
    result = convert_history({"locations": [
        raw(deviceTag=1),
        raw(515001000, -1201000, "2026-01-01T12:01:00Z", deviceTag=1),
        raw(515002000, -1202000, "2026-01-01T13:00:00Z", deviceTag=1),
        raw(505002000, -1202000, "2026-01-01T13:01:00Z", deviceTag=1),
        raw(505003000, -1203000, "2026-01-01T13:01:00Z", deviceTag=1),
        raw(515000010, -1200010, deviceTag=2),
    ]})
    assert [len(track) for track in result.tracks] == [2, 1, 1, 1, 1]


def test_path_order_is_preserved_and_backwards_time_starts_a_new_track():
    result = convert_history([phone_path([
        {"point": "geo:51.5,-0.12", "time": "2026-01-01T12:02:00Z"},
        {"point": "geo:51.501,-0.121", "time": "2026-01-01T12:01:00Z"},
        {"point": "geo:51.502,-0.122", "time": "2026-01-01T12:03:00Z"},
    ])])
    assert [len(track) for track in result.tracks] == [1, 2]
    assert result.tracks[0][0].latitude == 51.5


def test_distance_handles_dateline_and_gpx_longitude_boundary():
    assert 2 < distance_km(Point(0, 179.99), Point(0, -179.99)) < 3
    result = convert_history([phone_path([{"point": "geo:90,180"}])])
    assert result.tracks[0][0].longitude == -180


def test_input_files_keep_their_boundaries():
    first = convert_history({"locations": [raw()]})
    second = convert_history({"locations": [raw(515001000, -1201000, "2026-01-01T12:01:00Z")]})
    assert [len(track) for track in combine([first, second]).tracks] == [1, 1]


@pytest.mark.parametrize("document, message", [
    ({"unrelated": []}, "unsupported export"),
    ({"locations": []}, "no usable location"),
    ({"rawSignals": [{"wifiScan": {}}]}, "no usable location"),
    ({"locations": {}}, "expected an array"),
    ({"locations": [raw(latitude=910000000)]}, "outside latitude"),
    ({"locations": [raw(longitude=-1810000000)]}, "outside latitude"),
    ({"locations": [raw(latitude=True)]}, "finite number"),
    ({"locations": [raw(latitude=float("nan"))]}, "finite number"),
    ({"locations": [raw(latitude="PRIVATE_INVALID_COORDINATE")]}, "finite number"),
    ({"locations": [raw(time="2026-01-01T12:00:00")]}, "timezone"),
    ({"locations": [{"latitudeE7": 0, "longitudeE7": 0}]}, "missing timestamp"),
    ({"locations": [raw(altitude=float("inf"))]}, "finite number"),
    ([{"unknown": {}}], "expected timelinePath"),
    ([phone_path([{"point": "geo:51.5,-0.12", "durationMinutesOffsetFromStartTime": -1}], startTime="2026-01-01T12:00:00Z")], "nonnegative"),
    ([phone_path([{"point": "geo:51.5,-0.12", "durationMinutesOffsetFromStartTime": 1}])], "requires a startTime"),
    ([phone_path([{"point": "geo:51.5,-0.12", "durationMinutesOffsetFromStartTime": "1e300"}], startTime="2026-01-01T12:00:00Z")], "too large"),
    ([phone_path([{"point": "geo:51.5,-0.12", "durationMinutesOffsetFromStartTime": 60}], startTime="2026-01-01T12:00:00Z", endTime="2026-01-01T12:05:00Z")], "outside the segment"),
])
def test_invalid_locations_and_shapes_fail_without_echoing_private_data(document, message):
    with pytest.raises(ConversionError, match=message) as raised:
        convert_history(document)
    assert "PRIVATE_INVALID_COORDINATE" not in str(raised.value)


@pytest.mark.parametrize("options", [
    {"max_gap_minutes": 0}, {"max_gap_minutes": float("inf")},
    {"max_distance_km": 0}, {"max_distance_km": 11}, {"max_distance_km": float("nan")},
])
def test_invalid_split_options_fail(options):
    with pytest.raises(ConversionError):
        convert_history({"locations": [raw()]}, **options)


def test_custom_gap_and_distance_thresholds():
    document = {"locations": [raw(), raw(515100000, -1200000, "2026-01-01T12:10:00Z")]}
    assert len(convert_history(document).tracks) == 1
    assert len(convert_history(document, max_gap_minutes=5).tracks) == 2
    assert len(convert_history(document, max_distance_km=1).tracks) == 2
