"""Single-timestamp excursion presentation policy, using invented offline data."""

from datetime import datetime, timedelta, timezone
import json

import pytest

import gpx_countries as script


A, B, C = ("Alpha", "AA"), ("Beta", "BB"), ("Gamma", "CC")
BASE = datetime(2035, 1, 1, tzinfo=timezone.utc)
LONGITUDE = {A: -1.5, B: 1.5, C: 4.5, None: 8}


def polygon(label, west, east):
    return {"type": "Feature", "properties": {"NAME_EN": label[0], "ISO_A2": label[1]},
            "geometry": {"type": "Polygon", "coordinates": [[
                [west, -1], [east, -1], [east, 1], [west, 1], [west, -1]]]}}


def boundaries():
    return {"type": "FeatureCollection", "features": [
        polygon(A, -2, -1), polygon(B, 1, 2), polygon(C, 4, 5)]}


def samples(labels, *, sequence=1, gap_minutes=5):
    return [(0, LONGITUDE[label], BASE + timedelta(minutes=i * gap_minutes), sequence)
            for i, label in enumerate(labels)]


def denoise(records, **options):
    settings = {"motion": False, "borders": False, "coastal": False,
                "visits": False, "remove_unassigned": False}
    settings.update(options)
    return script.denoise_samples(records, script.country_lookup(boundaries()), **settings)


def assert_conserved(records, fixes, report):
    assert (sum(f.count for f in fixes) + report["excluded"] + report["unassigned_removed"]
            + report["singleton_removed"]) == len(records)


@pytest.mark.parametrize("copies", [1, 2, 50])
def test_default_singleton_policy_counts_duplicates_once_without_relabeling(copies):
    original = samples([A, B, A])
    records = [original[0], *([original[1]] * copies), original[2]]
    fixes, report = denoise(records)
    assert [(f.country, f.count) for f in fixes] == [(A, 1), (A, 1)]
    assert report["singleton_enabled"] is True
    assert report["singleton_removed"] == copies and report["singleton_excursions"] == 1
    assert report["visit_inferred"] == report["inferred"] == 0
    assert "single-timestamp Beta excursion between Alpha observations" in script.format_decisions(report)
    assert f"Removed GPX points: {copies}" in script.format_denoising(report)
    periods, total, unassigned, untimed = script.group_timeline_labels(
        (f.country, f.time, f.count) for f in fixes)
    assert periods == [[A, 2, original[0][2], original[2][2]]]
    assert (total, unassigned, untimed) == (2, 0, 0)
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("sequence", [1, None])
def test_policy_applies_to_timed_tracking_and_nontracking_records(sequence):
    records = samples([A, B, A], sequence=sequence)
    fixes, report = denoise(records)
    assert all(f.country == A for f in fixes) and report["singleton_removed"] == 1
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("middle", [(B,), (A, B), (B, C), (A, B, C)])
def test_simultaneous_alternatives_are_order_independent_and_count_country_epochs(middle):
    records = samples([A, A, A])
    records = [records[0], *[(0, LONGITUDE[c], records[1][2], 1) for c in middle], records[2]]
    expected_removed = sum(c != A for c in middle)
    snapshots = []
    for ordered in (records, list(reversed(records)), records[1:] + records[:1]):
        fixes, report = denoise(ordered)
        assert all(f.country == A for f in fixes)
        assert report["singleton_removed"] == expected_removed
        assert report["singleton_excursions"] == expected_removed
        assert_conserved(ordered, fixes, report)
        snapshots.append(([(f.country, f.time, f.count) for f in fixes], report["decisions"]))
    assert snapshots[0] == snapshots[1] == snapshots[2]


def test_multiple_positions_for_one_country_at_one_timestamp_are_one_excursion():
    records = samples([A, B, A])
    records.insert(2, (0, 1.6, records[1][2], 99))
    fixes, report = denoise(records)
    assert report["singleton_removed"] == 2 and report["singleton_excursions"] == 1
    assert sum(f.count for f in fixes) == 2
    assert_conserved(records, fixes, report)


def test_source_ids_and_segment_splits_do_not_change_singleton_eligibility():
    records = samples([A, B, A])
    split = [(*record[:3], i + 40) for i, record in enumerate(records)]
    snapshots = []
    for log in (records, split):
        fixes, report = denoise(log)
        snapshots.append(([(f.country, f.time, f.count) for f in fixes], report["singleton_removed"]))
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("labels", [[B], [B, A], [A, B], [B, A, A], [A, A, B],
                                    [A, B, B, A], [A, B, C], [A, B, A, B, A]])
def test_endpoints_multiepoch_visits_oneway_transitions_and_competing_support_survive(labels):
    records = samples(labels)
    fixes, report = denoise(records)
    assert [f.country for f in fixes] == labels
    assert report["singleton_removed"] == report["singleton_excursions"] == 0
    assert_conserved(records, fixes, report)


def test_separate_excursions_can_share_a_retained_anchor_without_cascading():
    records = samples([A, B, A, C, A])
    fixes, report = denoise(records)
    assert [f.country for f in fixes] == [A, A, A]
    assert report["singleton_removed"] == report["singleton_excursions"] == 2
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("unknown_position", ["between", "candidate", "anchor"])
@pytest.mark.parametrize("remove_unassigned", [False, True])
def test_unassigned_policy_runs_first_and_retained_unknowns_are_barriers(unknown_position, remove_unassigned):
    records = samples([A, B, A])
    if unknown_position == "between":
        records = samples([A, None, B, A])
    elif unknown_position == "candidate":
        records.append((0, LONGITUDE[None], records[1][2], 1))
    else:
        records.append((0, LONGITUDE[None], records[0][2], 1))
    fixes, report = denoise(records, remove_unassigned=remove_unassigned)
    assert report["unassigned_removed"] == int(remove_unassigned)
    assert report["singleton_removed"] == int(remove_unassigned)
    assert any(f.country == B for f in fixes) is not remove_unassigned
    assert_conserved(records, fixes, report)


def test_untimed_points_are_preserved_and_do_not_supply_temporal_support():
    records = samples([A, B, A]) + [(0, LONGITUDE[B], None, 1), (0, LONGITUDE[C], None, None)]
    fixes, report = denoise(records)
    assert [(f.country, f.time) for f in fixes if f.time is None] == [(B, None), (C, None)]
    assert report["singleton_removed"] == 1
    assert_conserved(records, fixes, report)


def test_singleton_policy_is_independent_of_gap_speed_and_polygon_allowance():
    records = samples([A, B, A], gap_minutes=7200)
    fixes, report = denoise(records, motion=True, max_speed_kmh=1, max_gap_minutes=1,
                            motion_slack_meters=0)
    assert [f.country for f in fixes] == [A, A]
    assert report["excluded"] == 0 and report["singleton_removed"] == 1
    assert_conserved(records, fixes, report)


def test_removal_explains_final_country_while_preserving_raw_map_provenance():
    baseline = script.country_lookup({"type": "FeatureCollection", "features": [
        polygon(A, -2, .01), polygon(B, .01, 2)]})
    references = {country: script.country_lookup({"type": "FeatureCollection", "features": [feature]})
                  for country, feature in ((A, polygon(A, -2, -.01)), (B, polygon(B, -.01, 2)))}
    records = [(0, -1.5, BASE, 1), (0, .005, BASE + timedelta(minutes=1), 1),
               (0, -1.5, BASE + timedelta(minutes=2), 1)]
    fixes, report = script.denoise_samples(records, baseline, motion=False, visits=False,
                                           coastal=False, borders=True, coastal_reference=references.get)
    assert report["border_corrected"] == report["singleton_removed"] == 1
    decision = next(row for row in report["decisions"] if row[2] == "Removed")
    assert decision[1] == "Alpha" and "Beta excursion between Alpha" in decision[3]
    assert [f.country for f in fixes] == [A, A]
    assert_conserved(records, fixes, report)


def test_singleton_opt_out_preserves_records_and_keeps_unassigned_removal_active():
    records = samples([A, B, None, A])
    fixes, report = denoise(records, singletons=False, remove_unassigned=True)
    assert report["singleton_enabled"] is False
    assert report["singleton_removed"] == report["singleton_excursions"] == 0
    assert report["unassigned_removed"] == 1 and [f.country for f in fixes] == [A, B, A]
    assert_conserved(records, fixes, report)


def test_motion_unassigned_and_singleton_removals_are_disjoint_and_weighted():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        polygon(A, -2, 0), polygon(B, 0, 2), polygon(C, 29, 31)]})
    track = [(0, lon, BASE + timedelta(minutes=i), 1)
             for i, lon in enumerate([-.005, 30, -.005, .005, -.005])]
    records = [track[0], track[1], track[1], track[2], *([track[3]] * 3), track[4]]
    records.extend([(0, 35, None, None)] * 4)
    fixes, report = script.denoise_samples(records, lookup, borders=False, coastal=False, visits=False)
    assert report["excluded"] == 2 and report["unassigned_removed"] == 4
    assert report["singleton_removed"] == 3 and report["singleton_excursions"] == 1
    assert [(f.country, f.count) for f in fixes] == [(A, 1)] * 3
    assert_conserved(records, fixes, report)


@pytest.mark.parametrize("singletons", [False, True])
def test_master_off_restores_raw_order_duplicates_and_all_countries(singletons):
    records = list(reversed(samples([A, B, A])))
    records.insert(1, records[1])
    fixes, report = denoise(records, enabled=False, singletons=singletons)
    assert report == {"enabled": False}
    assert [(f.longitude, f.time, f.count) for f in fixes] == [(lon, time, 1) for _, lon, time, _ in records]


@pytest.mark.parametrize("view", ["--summary", "--timeline"])
@pytest.mark.parametrize("flags,removed", [([], True), (["--singleton-denoise"], True),
                                           (["--no-singleton-denoise"], False),
                                           (["--no-denoise", "--singleton-denoise"], False),
                                           (["--singleton-denoise", "--no-denoise"], False)])
def test_cli_default_and_stage_master_controls_preserve_input(tmp_path, capsys, monkeypatch, view, flags, removed):
    country_data, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    country_data.write_text(json.dumps(boundaries()))
    body = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                   for lat, lon, time, _ in samples([A, B, A]))
    original = ('<gpx><trk><trkseg>' + body + '</trkseg></trk></gpx>').encode()
    source.write_bytes(original)
    monkeypatch.setattr(script, "urlopen", lambda *_a, **_kw: pytest.fail("local boundaries must stay offline"))
    assert script.main([str(source), "--country-data", str(country_data), view, "--no-motion-denoise",
                        "--no-visit-denoise", "--no-border-denoise", "--no-coastal-denoise", *flags]) == 0
    output = capsys.readouterr().out
    assert ("| Beta" not in output) is removed
    if "--no-denoise" not in flags:
        assert f"Singleton-excursion removal: {'on' if removed else 'off'}" in output
        assert f"Removed GPX points: {int(removed)}" in output
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == {source, country_data}


def test_cli_help_keeps_both_singleton_switches_in_the_denoising_group(capsys):
    with pytest.raises(SystemExit) as error:
        script.main(["--help"])
    assert error.value.code == 0
    denoising = capsys.readouterr().out.split("\nDenoising:\n", 1)[1]
    assert "--singleton-denoise" in denoising and "--no-singleton-denoise" in denoising
