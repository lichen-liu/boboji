"""Coastline disagreement and visit continuity, using invented map geometry.

Calibration-only cases set position allowance to zero. Separate cases exercise
the user's positive allowance and the default CLI behavior.
"""

import io
import json
from urllib.error import URLError

import pytest

import gpx_countries as script
from test_gpx_denoising import A, B, coast, feature, samples


def reference_data():
    # The reference shoreline extends farther east in the southern half.
    data = {"type": "FeatureCollection", "features": [feature(*A, -1, -1, .02, 1)]}
    data["features"][0]["geometry"]["coordinates"] = [
        [[-1, -1], [.02, -1], [.02, 0], [.005, 0], [.005, 1], [-1, 1], [-1, -1]]]
    return data


def reference(country):
    assert country == A
    return script.country_lookup(reference_data())


def route(far=True):
    coords = [(-.01, -.001), (-.01, .018), (.01, .015)]
    if far:
        coords.append((.01, .06))
    return samples([*coords, (.01, -.001)])


def test_map_calibration_without_position_allowance_preserves_open_water():
    fixes, report = script.denoise_samples(route(), coast(), coastal_reference=reference, motion_slack_meters=0, borders=False, remove_unassigned=False)
    assert [f.country for f in fixes] == [A, A, None, None, A]
    assert [f.raw_country for f in fixes] == [A, None, None, None, A]
    assert report["excluded"] == 0 and report["inferred"] == 0
    assert report["reference_confirmed"] == 1
    assert report["coastal_models"] == [("Alpha", 1, 2002)]
    text = script.format_decisions(report)
    assert "reference country polygon" in text
    assert "coastal continuity within position/map allowance" not in text


@pytest.mark.parametrize("copies", [1, 20, 100])
def test_open_water_and_duplicate_records_do_not_inflate_the_mapping_band(copies):
    records = route()
    records = [*records, *([records[3]] * copies)]
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=reference, motion_slack_meters=0, borders=False, remove_unassigned=False)
    assert report["coastal_models"] == [("Alpha", 1, 2002)]
    assert sum(f.count for f in fixes if f.country is None) == copies + 2
    assert report["excluded"] + sum(f.count for f in fixes) == len(records)


def test_no_reference_confirmed_land_means_no_invented_radius():
    records = samples([(.01, -.001), (.01, .015), (.01, .06), (.01, -.001)])
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=reference, motion_slack_meters=0, borders=False, remove_unassigned=False)
    assert report["coastal_models"] == [] and report["inferred"] == 0
    assert [f.country for f in fixes] == [A, None, None, A]


@pytest.mark.parametrize("spacing", [1, 60, 3600, 86400])
def test_calibration_uses_geographic_evidence_across_sampling_rates_and_logging_breaks(spacing):
    records = [(lat, lon, time, i) for i, (lat, lon, time, _) in enumerate(samples(
        [p[:2] for p in route(far=False)], seconds=spacing))]
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=reference, motion_slack_meters=0, borders=False, remove_unassigned=False)
    assert report["coastal_models"] == [("Alpha", 1, 2002)]
    assert [f.country for f in fixes] == [A, A, None, A]


def test_direct_map_evidence_needs_no_visit_anchors_but_contextual_guesses_do():
    records = route(far=False)[:-1]
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=reference, motion_slack_meters=0, borders=False, remove_unassigned=False)
    assert report["inferred"] == 0
    assert [f.country for f in fixes] == [A, A, None]


@pytest.mark.parametrize("mode", ["off", "raw"])
def test_opt_outs_and_explicit_override_do_not_fetch_reference_data(mode):
    def unwanted(_country):
        pytest.fail("reference fetch must be bypassed")
    options = {"coastal": False} if mode == "off" else {"enabled": False} if mode == "raw" else {"gps_radius_meters": 500}
    fixes, report = script.denoise_samples(route(), coast(), coastal_reference=unwanted, **options, remove_unassigned=False)
    assert [f.country for f in fixes] == [A, None, None, None, A]


def test_named_foreign_visit_is_preserved_even_inside_an_automatic_band():
    coarse = script.country_lookup({"type": "FeatureCollection", "features": [
        feature(*A, -1, -1, 0, 1), feature(*B, .009, .5, .01, .6)]})
    records = samples([(-.01, -.001), (-.01, .018), (-.01, -.001), (.55, .0095), (.55, -.001)])
    fixes, report = script.denoise_samples(records, coarse, coastal_reference=reference, motion_slack_meters=0,
                                         borders=False, remove_unassigned=False, singletons=False)
    assert fixes[3].country == B and fixes[3].raw_country == B
    assert report["excluded"] == 0


def test_multiple_unassigned_positions_at_one_epoch_do_not_fragment_a_country_visit():
    records = route(far=False)
    records.append((.01, .014, records[2][2], 2))
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=reference, motion_slack_meters=5000, borders=False, remove_unassigned=False)
    assert all(f.country == A for f in fixes)
    assert report["conflicting_epochs"] == 1 and report["excluded"] == 0
    periods = script.group_timeline_labels((f.country, f.time, f.count) for f in fixes)[0]
    assert len(periods) == 1


def test_conflicting_named_countries_still_block_country_context():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        feature(*A, -1, -1, 0, 1), feature(*B, 2, -1, 3, 1)]})
    records = route(far=False)
    records.append((.01, 2.5, records[-1][2], 2))
    fixes, report = script.denoise_samples(records, lookup, coastal_reference=lambda _country: coast(), motion_slack_meters=0, borders=False, remove_unassigned=False)
    assert report["inferred"] == 0
    assert fixes[1].country is None and fixes[2].country is None


def test_far_reference_land_cannot_enlarge_the_automatic_discovery_ceiling():
    def huge_reference(_country):
        return script.country_lookup({"type": "FeatureCollection", "features": [feature(*A, -1, -1, 2, 1)]})
    records = samples([(-.01, -.001), (-.01, .018), (-.01, .5), (-.01, -.001)], seconds=300)
    fixes, report = script.denoise_samples(records, coast(), coastal_reference=huge_reference, remove_unassigned=False)
    assert report["coastal_models"] == [("Alpha", 1, 2002)]
    assert fixes[2].country is None


def test_other_nearby_country_prevents_unique_coastal_assignment():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        feature(*A, -1, -1, 0, 1), feature(*B, .025, -1, 1, 1)]})
    def unused(country):
        return lambda *_: country  # Overlapping references cannot adjudicate an unknown.
    fixes, report = script.denoise_samples(route(), lookup, coastal_reference=unused, borders=False, remove_unassigned=False)
    assert report["inferred"] == 0


def test_reference_download_is_cached_and_keeps_the_original_country_identity(tmp_path, monkeypatch):
    requests = []
    def download(request, **_kwargs):
        requests.append(request.full_url)
        return io.BytesIO(json.dumps(reference_data()).encode())
    monkeypatch.setattr(script, "urlopen", download)
    first = script.load_coastal_reference(A, "AAA", tmp_path)
    assert first(-.01, .018) == A
    monkeypatch.setattr(script, "urlopen", lambda *_a, **_k: pytest.fail("cached lookup must work offline"))
    assert script.load_coastal_reference(A, "AAA", tmp_path)(-.01, .018) == A
    assert requests == [script.REFERENCE_URL.format(iso3="AAA")]


@pytest.mark.parametrize("failure", [URLError("offline"), ValueError("bad JSON")])
def test_missing_reference_preserves_unknowns_and_reports_the_limit(tmp_path, monkeypatch, capsys, failure):
    def unavailable(*_args, **_kwargs):
        raise failure
    monkeypatch.setattr(script, "urlopen", unavailable)
    fixes, report = script.denoise_samples(route(), coast(), coastal_reference=lambda country:
                                         script.load_coastal_reference(country, "AAA", tmp_path), remove_unassigned=False)
    assert report["inferred"] == 0 and report["coastal_unavailable"] == ["Alpha"]
    assert "unavailable" in capsys.readouterr().err
    assert [f.country for f in fixes] == [A, None, None, None, A]


def test_normal_cli_enables_automatic_coastal_handling_without_an_extra_flag(tmp_path, monkeypatch, capsys):
    base = {"type": "FeatureCollection", "features": [feature(*A, -1, -1, 0, 1)]}
    base["features"][0]["properties"]["ISO_A3"] = "AAA"
    countries = tmp_path / "base.geojson"
    countries.write_text(json.dumps(base))
    monkeypatch.setattr(script, "DEFAULT_COUNTRIES", countries)
    monkeypatch.setattr(script, "urlopen", lambda *_a, **_k: io.BytesIO(json.dumps(reference_data()).encode()))
    source = tmp_path / "input.gpx"
    body = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                   for lat, lon, time, _ in route(far=False))
    original = '<gpx><trk><trkseg>' + body + '</trkseg></trk></gpx>'
    source.write_text(original)
    assert script.main([str(source), "--timeline", "--no-remove-unassigned"]) == 0
    output = capsys.readouterr().out
    rows = [line for line in output.splitlines() if line.startswith('|')][2:]
    assert len(rows) == 1 and "| Alpha" in rows[0]
    assert "automatic from reference country polygons and the position allowance" in output
    assert "10,000 m effective; map disagreement 2,002 m from 1 reference-confirmed locations" in output
    assert source.read_text() == original
    for flag in ["--no-coastal-denoise", "--no-denoise"]:
        assert script.main([str(source), "--timeline", flag, "--no-remove-unassigned"]) == 0
        assert "| Unassigned" in capsys.readouterr().out
    assert script.main([str(source), "--timeline", "--country-data", str(countries), "--no-remove-unassigned"]) == 0
    assert "| Unassigned" in capsys.readouterr().out  # Custom boundaries stay offline.
