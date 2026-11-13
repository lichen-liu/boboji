"""Final unassigned-removal policy, with invented coordinates and offline maps."""

from datetime import datetime, timedelta, timezone
from itertools import product
import json

import pytest

import gpx_countries as script


A, B = ("Alpha", "AA"), ("Beta", "BB")
BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def polygon(label, west, east):
    return {"type": "Feature", "properties": {"NAME_EN": label[0], "ISO_A2": label[1]},
            "geometry": {"type": "Polygon", "coordinates": [
                [[west, -1], [east, -1], [east, 1], [west, 1], [west, -1]]]}}


def countries(with_neighbor=False):
    features = [polygon(A, -1, 0)]
    if with_neighbor:
        features.append(polygon(B, .05, 1))
    return script.country_lookup({"type": "FeatureCollection", "features": features})


def points(longitudes):
    return [(0, longitude, BASE + timedelta(minutes=i), 1) for i, longitude in enumerate(longitudes)]


def denoise(records, lookup, **options):
    settings = {"borders": False, "coastal": False, "visits": False, "singletons": False}
    settings.update(options)
    return script.denoise_samples(records, lookup, **settings)


def assert_conserved(records, fixes, report):
    assert sum(fix.count for fix in fixes) + report["excluded"] + report["unassigned_removed"] == len(records)


def test_default_removal_handles_timed_untimed_track_poi_and_duplicate_weights():
    records = [(0, -.005, BASE, 1),
               (0, .005, BASE + timedelta(minutes=1), 1),
               (0, .005, BASE + timedelta(minutes=1), 1),
               (0, .006, BASE + timedelta(minutes=2), None),
               (0, .006, BASE + timedelta(minutes=2), None),
               (0, .007, None, 2), (0, .007, None, None)]
    fixes, report = denoise(records, countries())
    assert len(fixes) == 1 and fixes[0].country == A
    assert report["excluded"] == 0 and report["unassigned_removed"] == 6
    removed = [row for row in report["decisions"] if row[3] == "final unassigned-removal policy"]
    assert sum(row[4] for row in removed) == 6
    assert any(row[0] is None for row in removed)
    assert "final unassigned-removal policy" in script.format_decisions(report)
    assert "Removed unassigned GPX points: 6" in script.format_denoising(report)
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("stage", ["reference", "visit", "coastal_context"])
def test_final_named_country_survives_even_when_the_raw_country_was_unknown(stage):
    lookup = countries()
    options = {"coastal": True}
    if stage == "reference":
        records = [(0, .005, None, None)]
        reference = script.country_lookup({"type": "FeatureCollection", "features": [polygon(A, -1, .02)]})
        options["coastal_reference"] = lambda _country: reference
    elif stage == "visit":
        records = points([-.005, -.004, .005, -.004, -.005])
        options["visits"] = True
    else:
        records = points([-.005, .005, -.005])
        options["gps_radius_meters"] = 1000
    fixes, report = denoise(records, lookup, **options)
    formerly_unknown = [fix for fix in fixes if fix.raw_country is None]
    assert formerly_unknown and all(fix.country == A for fix in formerly_unknown)
    assert report["unassigned_removed"] == 0
    assert_conserved(records, fixes, report)


def test_unassigned_opt_out_preserves_unknowns_without_disabling_other_passes():
    records = points([-.005, .005, -.005]) + [(0, .008, None, None)]
    fixes, report = denoise(records, countries(), remove_unassigned=False)
    assert sum(fix.count for fix in fixes if fix.country is None) == 2
    assert report["unassigned_removed"] == 0
    assert not any(row[3] == "final unassigned-removal policy" for row in report["decisions"])
    assert_conserved(records, fixes, report)


def test_global_raw_opt_out_dominates_explicit_removal_and_restores_original_order():
    records = [(0, .005, None, None), *points([-.005, .005, -.005])]
    records += [records[1]]
    lookup = countries()
    def unexpected_reference(_country):
        pytest.fail("raw mode must bypass inference and removal")
    fixes, report = denoise(records, lookup, enabled=False, remove_unassigned=True,
                            borders=True, coastal=True, visits=True,
                            coastal_reference=unexpected_reference)
    assert report["enabled"] is False
    assert [(fix.latitude, fix.longitude, fix.time, fix.country) for fix in fixes] == [
        (lat, lon, time, lookup(lat, lon)) for lat, lon, time, _ in records]
    assert [fix.count for fix in fixes] == [1] * len(records)


@pytest.mark.parametrize("remove", [False, True])
def test_motion_and_final_removal_counts_are_disjoint_and_conserve_duplicate_records(remove):
    far = (30, 30, BASE + timedelta(minutes=1), 1)
    near = (0, .005, BASE + timedelta(minutes=3), 1)
    records = [(0, -.005, BASE, 1), far, far,
               (0, -.004, BASE + timedelta(minutes=2), 1), near, near, near]
    fixes, report = denoise(records, countries(), remove_unassigned=remove)
    assert report["excluded"] == 2
    assert report["unassigned_removed"] == (3 if remove else 0)
    assert sum(fix.count for fix in fixes) == (2 if remove else 5)
    assert_conserved(records, fixes, report)


def test_all_removed_input_produces_valid_empty_summary_and_timeline_tables():
    records = points([.005, .006, .007]) + [(0, .008, None, None)]
    fixes, report = denoise(records, countries())
    assert fixes == [] and report["unassigned_removed"] == len(records)
    summary = script.format_table(*script.summarize_labels((fix.country, fix.time, fix.count) for fix in fixes))
    timeline = script.format_timeline(*script.group_timeline_labels((fix.country, fix.time, fix.count) for fix in fixes))
    assert "Country / territory" in summary and "GPX points: 0" in summary
    assert "Country / territory" in timeline and "GPX points represented: 0" in timeline
    assert not any(line.startswith('| Unassigned') for line in (summary + '\n' + timeline).splitlines())
    assert_conserved(records, fixes, report)


def test_removal_precedes_grouping_and_merges_the_surrounding_country_periods():
    records = points([-.005, .005, -.005])
    fixes, report = denoise(records, countries())
    periods, total, unassigned, untimed = script.group_timeline_labels(
        (fix.country, fix.time, fix.count) for fix in fixes)
    assert periods == [[A, 2, records[0][2], records[-1][2]]]
    assert (total, unassigned, untimed) == (2, 0, 0)
    assert report["unassigned_removed"] == 1


def test_final_removal_does_not_manufacture_confirmation_by_rerunning_inference():
    records = points([-.005, -.004, .005, .06, -.004, -.005])
    fixes, report = denoise(records, countries(with_neighbor=True), visits=True, coastal=False)
    assert report["unassigned_removed"] == 1
    assert report["visit_inferred"] == 0
    assert any(fix.country == B for fix in fixes)
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("enabled,remove,coastal,visits", tuple(product([False, True], repeat=4)))
def test_removal_control_matrix_respects_raw_mode_and_earlier_stage_opt_outs(enabled, remove, coastal, visits):
    records = points([-.005, -.004, .005, -.004, -.005])
    records.append((0, .005, records[2][2], 99))
    fixes, report = denoise(records, countries(), enabled=enabled, remove_unassigned=remove,
                            coastal=coastal, visits=visits)
    if not enabled:
        assert [fix.country for fix in fixes] == [countries()(lat, lon) for lat, lon, _, _ in records]
        assert sum(fix.count for fix in fixes) == len(records)
        return
    inferred = coastal and visits
    expected_removed = 2 if remove and not inferred else 0
    expected_unknown = 0 if inferred or remove else 2
    assert report["unassigned_removed"] == expected_removed
    assert sum(fix.count for fix in fixes if fix.country is None) == expected_unknown
    assert report["excluded"] == 0
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("flags, unknown_visible", [
    ([], False), (["--remove-unassigned"], False), (["--no-remove-unassigned"], True),
    (["--no-denoise", "--remove-unassigned"], True),
    (["--remove-unassigned", "--no-denoise"], True),
])
def test_cli_default_and_opt_outs_keep_the_input_file_unchanged(tmp_path, monkeypatch, capsys, flags, unknown_visible):
    boundaries = tmp_path / 'countries.geojson'
    boundaries.write_text(json.dumps({"type": "FeatureCollection", "features": [polygon(A, -1, 0)]}))
    source = tmp_path / 'input.gpx'
    body = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                   for lat, lon, time, _ in points([-.005, .005, -.005]))
    original = ('<gpx><wpt lat="0" lon=".008"/><trk><trkseg>' + body + '</trkseg></trk></gpx>').encode()
    source.write_bytes(original)
    monkeypatch.setattr(script, 'urlopen', lambda *_args, **_kwargs: pytest.fail('custom boundaries must stay offline'))
    assert script.main([str(source), '--country-data', str(boundaries), '--timeline', *flags]) == 0
    output = capsys.readouterr().out
    assert any(line.startswith('| Unassigned') for line in output.splitlines()) == unknown_visible
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == {source, boundaries}


def test_cli_explains_final_removal_with_the_specific_reason(tmp_path, capsys):
    boundaries = tmp_path / 'countries.geojson'
    boundaries.write_text(json.dumps({"type": "FeatureCollection", "features": [polygon(A, -1, 0)]}))
    source = tmp_path / 'input.gpx'
    source.write_text('<gpx><wpt lat="0" lon=".005"/></gpx>')
    assert script.main([str(source), '--country-data', str(boundaries), '--explain']) == 0
    output = capsys.readouterr().out
    assert 'final unassigned-removal policy' in output
    assert 'Removed unassigned GPX points: 1' in output
