"""Independent border-map truth and isolated recording-marker failures."""

from datetime import timedelta
import json

import pytest

import gpx_countries as script
from test_gpx_denoising import A, B, BASE, coast, feature, movement, samples


def reference_maps(country):
    # The baseline border is x=0; both reference sources agree it is x=.015.
    bounds = (-1, -1, .015, 1) if country == A else (.015, -1, 1, 1)
    return script.country_lookup({"type": "FeatureCollection", "features": [feature(*country, *bounds)]})


def test_return_blips_correct_only_when_both_country_maps_agree():
    records = samples([(.01, -.01), (.01, .003), (.01, .005), (.01, .03), (.01, -.01)])
    fixes, report = script.denoise_samples(records, coast(True), coastal_reference=reference_maps)
    assert [f.country for f in fixes] == [A, A, A, B, A]
    assert [f.raw_country for f in fixes] == [A, B, B, B, A]
    assert report["border_corrected"] == 2 and report["excluded"] == 0
    assert "reference maps agree on boundary correction" in script.format_decisions(report)


@pytest.mark.parametrize("spacing", [1, 60, 3600, 86400])
def test_border_map_correction_is_not_a_short_visit_or_sample_density_rule(spacing):
    records = samples([(.01, -.01), (.01, .003), (.01, .005), (.01, -.01)], seconds=spacing)
    fixes, report = script.denoise_samples(records, coast(True), coastal_reference=reference_maps)
    assert all(f.country == A for f in fixes) and report["border_corrected"] == 2


def test_genuine_brief_crossing_supported_by_its_country_reference_is_preserved():
    records = samples([(.01, -.01), (.01, .02), (.01, .021), (.01, .02), (.01, -.01)])
    fixes, report = script.denoise_samples(records, coast(True), coastal_reference=reference_maps)
    assert [f.country for f in fixes] == [A, B, B, B, A]
    assert report["border_corrected"] == report["excluded"] == 0


@pytest.mark.parametrize("condition", ["overlap", "neither", "source_missing", "destination_missing", "disabled"])
def test_ambiguous_or_missing_border_evidence_never_rewrites_a_named_country(condition):
    def reference(country):
        if condition == "disabled":
            pytest.fail("disabled border stage must not load references")
        if condition == "source_missing" and country == B or condition == "destination_missing" and country == A:
            return None
        if condition == "overlap":
            return lambda *_: country
        if condition == "neither":
            return lambda *_: None
        return reference_maps(country)
    records = samples([(.01, -.01), (.01, .003), (.01, -.01)])
    fixes, report = script.denoise_samples(records, coast(True), coastal=False,
                                         borders=condition != "disabled", coastal_reference=reference)
    assert [f.country for f in fixes] == [A, B, A]
    assert report["border_corrected"] == 0


def test_a_one_way_country_transition_does_not_become_a_return_excursion():
    records = samples([(.01, -.01), (.01, .003), (.01, .005)])
    fixes, report = script.denoise_samples(records, coast(True), coastal_reference=reference_maps)
    assert [f.country for f in fixes] == [A, B, B] and report["border_corrected"] == 0


def marker_records():
    # Two preceding fixes and one following fix corroborate ordinary motion.
    # Every record has a separate logger segment, like isolated Timeline endpoints.
    return [(lat, lon, time, i) for i, (lat, lon, time, _) in enumerate(
        samples([(0, 0), (0, .001), (30, 30), (0, .002)]))]


@pytest.mark.parametrize("copies", [1, 2, 100])
def test_impossible_isolated_marker_is_excluded_across_logging_breaks(copies):
    records = marker_records()
    records += [records[2]] * (copies - 1)
    fixes, report = script.denoise_samples(records, lambda *_: A)
    assert report["excluded"] == copies
    assert sum(f.count for f in fixes) + report["excluded"] == len(records)
    assert all(f.time != BASE + timedelta(minutes=2) for f in fixes)
    assert "isolated marker contradicts surrounding tracking" in script.format_decisions(report)


def test_a_later_real_trip_to_the_markers_country_is_preserved():
    records = marker_records()
    later = [(30, 30 + i * .001, BASE + timedelta(hours=5, minutes=i), 50) for i in range(13)]
    fixes, report = script.denoise_samples(records + later, lambda lat, _: B if lat > 20 else A)
    assert report["excluded"] == 1
    assert sum(f.country == B for f in fixes) == 13


def test_an_actual_continuous_track_can_bracket_a_marker_without_an_extra_nearby_epoch():
    records = [(0, 0, BASE, 10), (30, 30, BASE + timedelta(seconds=8), 20),
               (0, .01, BASE + timedelta(minutes=1), 10),
               (0, .015, BASE + timedelta(minutes=1), 11)]
    fixes, report = script.denoise_samples(records, lambda *_: A)
    assert report["excluded"] == 1 and sum(f.count for f in fixes) == 3
    assert all(f.latitude == 0 for f in fixes)


@pytest.mark.parametrize("context", ["no_corroboration", "long_gap", "competing_tracks", "poi"])
def test_unsupported_isolated_marker_cases_remain_unresolved(context):
    records = marker_records()
    if context == "no_corroboration":
        records = records[1:]
    elif context == "long_gap":
        records[-1] = (0, .002, BASE + timedelta(hours=2), 4)
    elif context == "competing_tracks":
        records += [(30, 30, BASE + timedelta(minutes=i), 20) for i in [0, 1, 3]]
    else:
        lat, lon, time, _ = records[2]
        records[2] = lat, lon, time, None
    fixes, report = script.denoise_samples(records, lambda *_: A)
    assert report["excluded"] == 0 and sum(f.count for f in fixes) == len(records)


@pytest.mark.parametrize("mode", ["walking", "driving", "flight"])
@pytest.mark.parametrize("cadence", [1, 60, 300])
def test_normal_motion_logged_as_isolated_segments_is_preserved(mode, cadence):
    records = [(lat, lon, time, i) for i, (lat, lon, time, _) in enumerate(
        movement(mode, 65, cadence, "correlated", 421))]
    fixes, report = script.denoise_samples(records, lambda *_: A)
    assert report["excluded"] == 0 and sum(f.count for f in fixes) == len(records)


def test_position_allowance_also_controls_automatic_coastal_country_context():
    records = samples([(.01, -.001), (.01, .05), (.01, .07), (.01, -.001)])
    def reference(_country):
        return coast()
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=reference)
    assert all(f.country == A for f in fixes)
    assert report["coastal_models"] == [("Alpha", 0, 0)]
    assert report["coastal_effective"] == [("Alpha", 10000)]
    tight, report = script.denoise_samples(records, coast(), coastal_reference=reference, motion_slack_meters=1000)
    assert [f.country for f in tight] == [A, None, None, A]


def test_manual_coastal_radius_takes_precedence_over_the_position_allowance():
    records = samples([(.01, -.001), (.01, .05), (.01, -.001)])
    fixes, report = script.denoise_samples(records, coast(), gps_radius_meters=1000)
    assert [f.country for f in fixes] == [A, None, A]


def test_open_water_beyond_the_automatic_ceiling_is_not_merged():
    records = samples([(.01, -.001), (.01, .2), (.01, -.001)])
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=lambda _: coast())
    assert [f.country for f in fixes] == [A, None, A] and report["inferred"] == 0


def test_cli_corrects_verified_border_errors_and_can_disable_that_stage(tmp_path, monkeypatch, capsys):
    base = {"type": "FeatureCollection", "features": [
        feature(*A, -1, -1, 0, 1), feature(*B, 0, -1, 1, 1)]}
    for f, code in zip(base["features"], ["AAA", "BBB"]):
        f["properties"]["ISO_A3"] = code
    countries = tmp_path / "countries.geojson"
    countries.write_text(json.dumps(base))
    monkeypatch.setattr(script, "DEFAULT_COUNTRIES", countries)
    monkeypatch.setattr(script, "load_coastal_reference", lambda country, _iso: reference_maps(country))
    source = tmp_path / "input.gpx"
    points = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                     for lat, lon, time, _ in samples([(.01, -.01), (.01, .003), (.01, -.01)]))
    original = '<gpx><trk><trkseg>' + points + '</trkseg></trk></gpx>'
    source.write_text(original)
    assert script.main([str(source), "--timeline"]) == 0
    output = capsys.readouterr().out
    assert "| Beta" not in output and "Border-map corrections: 1" in output
    for flag in ["--no-border-denoise", "--no-denoise"]:
        assert script.main([str(source), "--timeline", flag]) == 0
        assert "| Beta" in capsys.readouterr().out
    assert source.read_text() == original
