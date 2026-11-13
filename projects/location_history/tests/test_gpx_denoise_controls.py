"""Independent denoising controls and their global override, with offline data."""

from datetime import datetime, timedelta, timezone
import json

import pytest

import gpx_countries as script


A, B = ("Alpha", "AA"), ("Beta", "BB")
BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def boundaries():
    features = []
    for label, west, south, east, north in ((A, -1, -1, 0, 1), (B, 29, 29, 31, 31)):
        features.append({"type": "Feature", "properties": {"NAME_EN": label[0], "ISO_A2": label[1]},
                         "geometry": {"type": "Polygon", "coordinates": [[
                             [west, south], [east, south], [east, north],
                             [west, north], [west, south]]]}})
    return {"type": "FeatureCollection", "features": features}


def samples():
    # One impossible named-country spike, plus an unresolved point near Alpha.
    positions = [(0, -.02), (30, 30), (0, -.01), (0, .02), (0, -.01)]
    records = [(lat, lon, BASE + timedelta(minutes=i), 1)
               for i, (lat, lon) in enumerate(positions)]
    return records[:2] + [records[1]] + records[2:]


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    country_data = tmp_path / "countries.geojson"
    country_data.write_text(json.dumps(boundaries()))
    source = tmp_path / "input.gpx"
    body = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                   for lat, lon, time, _sequence in samples())
    source.write_text('<gpx><trk><trkseg>' + body + '</trkseg></trk></gpx>')
    monkeypatch.setattr(script, "urlopen", lambda *_a, **_kw: pytest.fail("offline inputs must not fetch maps"))
    return source, country_data


def test_help_groups_all_denoising_settings(capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["--help"])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    denoising = help_text.split("\nDenoising:\n", 1)[1]
    for flag in ("--denoise", "--no-denoise", "--motion-denoise", "--no-motion-denoise",
                 "--border-denoise", "--coastal-denoise", "--visit-denoise",
                 "--remove-unassigned", "--no-remove-unassigned", "--gps-radius-meters",
                 "--max-speed-kmh", "--max-gap-minutes", "--position-allowance-meters",
                 "--motion-slack-meters", "--explain"):
        assert flag in denoising
    assert "--country-data" not in denoising
    assert "--timeline" not in denoising


@pytest.mark.parametrize("motion,remove", [(True, True), (False, True), (True, False), (False, False)])
def test_api_motion_and_unassigned_stages_are_independent(motion, remove):
    records = samples()
    fixes, report = script.denoise_samples(
        records, script.country_lookup(boundaries()), motion=motion,
        borders=False, coastal=False, visits=False, remove_unassigned=remove)
    assert report["enabled"] is True and report["motion_enabled"] is motion
    assert report["excluded"] == (2 if motion else 0)
    assert report["unassigned_removed"] == (1 if remove else 0)
    assert sum(f.count for f in fixes if f.country == B) == (0 if motion else 2)
    assert sum(f.count for f in fixes if f.country is None) == (0 if remove else 1)
    assert sum(f.count for f in fixes) + report["excluded"] + report["unassigned_removed"] == len(records)
    if not motion:
        assert report["tested"] == 0
        assert report["unresolved_motion"]  # Disabling deletion keeps movement diagnostics.
    assert f"GPX points ({'enabled' if motion else 'disabled'})" in script.format_denoising(report)


@pytest.mark.parametrize("motion_flags,motion", [([], True), (["--motion-denoise"], True),
                                                (["--no-motion-denoise"], False)])
@pytest.mark.parametrize("remove_flags,remove", [([], True), (["--no-remove-unassigned"], False)])
def test_cli_defaults_and_independent_stage_controls(inputs, capsys, motion_flags, motion, remove_flags, remove):
    source, country_data = inputs
    original = source.read_bytes()
    assert script.main([str(source), "--country-data", str(country_data), "--timeline",
                        "--no-border-denoise", "--no-coastal-denoise", "--no-visit-denoise",
                        *motion_flags, *remove_flags]) == 0
    output = capsys.readouterr().out
    assert ("| Beta" in output) is not motion
    assert ("| Unassigned" in output) is not remove
    assert "Denoising: on" in output
    assert f"Excluded as motion outliers: {2 if motion else 0}" in output
    assert f"Removed unassigned GPX points: {1 if remove else 0}" in output
    assert f"GPX points ({'enabled' if motion else 'disabled'})" in output
    assert source.read_bytes() == original


@pytest.mark.parametrize("remove_flags,removed", [([], 3), (["--no-remove-unassigned"], 0)])
def test_motion_off_leaves_far_unknowns_to_the_separate_final_removal_stage(inputs, capsys, remove_flags, removed):
    source, country_data = inputs
    data = boundaries()
    data["features"] = data["features"][:1]
    country_data.write_text(json.dumps(data))
    assert script.main([str(source), "--country-data", str(country_data), "--timeline",
                        "--no-motion-denoise", "--no-border-denoise", "--no-coastal-denoise",
                        "--no-visit-denoise", *remove_flags]) == 0
    output = capsys.readouterr().out
    assert "Excluded as motion outliers: 0 GPX points (disabled)" in output
    assert f"Removed unassigned GPX points: {removed}" in output
    assert f"GPX points represented: {6 - removed} · Unassigned: {3 - removed}" in output


@pytest.mark.parametrize("global_first", [False, True])
def test_global_off_dominates_explicit_stage_enables_regardless_of_order(inputs, capsys, global_first):
    source, country_data = inputs
    stage_flags = ["--motion-denoise", "--border-denoise", "--coastal-denoise",
                   "--visit-denoise", "--remove-unassigned"]
    flags = ["--no-denoise", *stage_flags] if global_first else [*stage_flags, "--no-denoise"]
    assert script.main([str(source), "--country-data", str(country_data), "--timeline", *flags]) == 0
    output = capsys.readouterr().out
    assert "Denoising: off" in output
    assert "GPX points represented: 6" in output
    assert "| Beta" in output and "| Unassigned" in output


@pytest.mark.parametrize("motion", [False, True])
def test_api_global_off_restores_every_raw_record_even_with_all_stage_enables(motion):
    records = list(reversed(samples()))
    lookup = script.country_lookup(boundaries())
    fixes, report = script.denoise_samples(records, lookup, enabled=False, motion=motion,
                                           borders=True, coastal=True, visits=True, remove_unassigned=True)
    assert report == {"enabled": False}
    assert [(f.latitude, f.longitude, f.time, f.country, f.count) for f in fixes] == [
        (lat, lon, time, lookup(lat, lon), 1) for lat, lon, time, _sequence in records]
