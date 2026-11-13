"""Country-level removal accounting and its default footer, using offline maps."""

from datetime import datetime, timedelta, timezone
import json

import pytest

import gpx_countries as script


A, B, C = ("Alpha", "AA"), ("Beta", "BB"), ("Gamma", "CC")
BASE = datetime(2036, 1, 1, tzinfo=timezone.utc)
REASONS = ("motion", "unassigned", "singleton")


def polygon(country, west, east):
    return {"type": "Feature", "properties": {"NAME_EN": country[0], "ISO_A2": country[1]},
            "geometry": {"type": "Polygon", "coordinates": [[
                [west, -1], [east, -1], [east, 1], [west, 1], [west, -1]]]}}


def boundaries(named_spike=True):
    features = [polygon(A, -2, 0), polygon(B, 0, 2)]
    if named_spike:
        features.append(polygon(C, 29, 31))
    return {"type": "FeatureCollection", "features": features}


def records():
    track = [(0, lon, BASE + timedelta(minutes=i), 1)
             for i, lon in enumerate([-.005, 30, -.005, .005, -.005])]
    return [track[0], track[1], track[1], track[2], *([track[3]] * 3), track[4],
            *([(0, 35, None, None)] * 4)]


def run(points, named_spike=True, **options):
    settings = {"borders": False, "coastal": False, "visits": False}
    settings.update(options)
    return script.denoise_samples(points, script.country_lookup(boundaries(named_spike)), **settings)


def buckets(report):
    return {country: tuple(counts.get(reason, 0) for reason in REASONS)
            for country, counts in report["removed_by_country"].items()}


def table_rows(text):
    lines = [line for line in text.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.split("|")[1:-1]] for line in lines[2:]]


def assert_accounted(points, fixes, report):
    totals = [sum(counts.get(reason, 0) for counts in report["removed_by_country"].values())
              for reason in REASONS]
    assert totals == [report["excluded"], report["unassigned_removed"], report["singleton_removed"]]
    assert sum(fix.count for fix in fixes) + sum(totals) == len(points)
    return totals


@pytest.mark.parametrize("named_spike", [False, True])
def test_country_summary_partitions_duplicate_weights_by_the_actual_removal_stage(named_spike):
    points = records()
    fixes, report = run(points, named_spike=named_spike)
    expected = {B: (0, 0, 3), None: (0, 4, 0), C: (2, 0, 0)} if named_spike else {
        B: (0, 0, 3), None: (2, 4, 0)}
    assert buckets(report) == expected
    assert assert_accounted(points, fixes, report) == [2, 4, 3]
    summary = script.format_removal_summary(report)
    rows = table_rows(summary)
    assert [row[0] for row in rows] == (["Beta", "Gamma", "Unassigned", "Total"] if named_spike
                                      else ["Beta", "Unassigned", "Total"])
    assert rows[-1] == ["Total", "—", "2", "4", "3", "9"]
    assert next(row for row in rows if row[0] == "Unassigned") == [
        "Unassigned", "—", "0" if named_spike else "2", "4", "0", "4" if named_spike else "6"]
    assert summary in script.format_denoising(report)
    assert script.format_denoising(report, verbose=True).count("Removed points by country") == 1


def test_summary_uses_the_final_removed_country_without_losing_raw_decision_provenance():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        polygon(A, -2, .01), polygon(B, .01, 2)]})
    references = {country: script.country_lookup({"type": "FeatureCollection", "features": [feature]})
                  for country, feature in ((A, polygon(A, -2, -.01)), (B, polygon(B, -.01, 2)))}
    points = [(0, -1.5, BASE, 1), *([(0, .005, BASE + timedelta(minutes=1), 1)] * 3),
              (0, -1.5, BASE + timedelta(minutes=2), 1)]
    fixes, report = script.denoise_samples(points, lookup, motion=False, visits=False, coastal=False,
                                           coastal_reference=references.get)
    assert report["border_corrected"] == 3 and buckets(report) == {B: (0, 0, 3)}
    removed = [decision for decision in report["decisions"] if decision[2] == "Removed"]
    assert removed[0][1] == "Alpha" and "Beta excursion" in removed[0][3]
    assert table_rows(script.format_removal_summary(report)) == [
        ["Beta", "BB", "0", "0", "3", "3"], ["Total", "—", "0", "0", "3", "3"]]
    assert_accounted(points, fixes, report)


@pytest.mark.parametrize("copies", [1, 1250])
def test_summary_is_deterministic_under_input_order_and_formats_weighted_counts(copies):
    middle = (0, .005, BASE + timedelta(minutes=1), 1)
    points = [(0, -.005, BASE, 1), *([middle] * copies), (0, -.005, BASE + timedelta(minutes=2), 1)]
    summaries = []
    for ordered in (points, list(reversed(points))):
        fixes, report = run(ordered)
        assert buckets(report) == {B: (0, 0, copies)}
        assert_accounted(ordered, fixes, report)
        summaries.append(script.format_removal_summary(report))
    assert summaries[0] == summaries[1]
    assert table_rows(summaries[0])[-1][-1] == f"{copies:,}"


@pytest.mark.parametrize("motion,unassigned,singletons,expected", [
    (False, False, False, {}),
    (True, False, False, {C: (2, 0, 0)}),
    (False, True, False, {None: (0, 4, 0)}),
    (False, False, True, {B: (0, 0, 3), C: (0, 0, 2)}),
])
def test_summary_records_enabled_stages_without_attributing_later_removals_to_a_disabled_stage(
        motion, unassigned, singletons, expected):
    points = records()
    fixes, report = run(points, motion=motion, remove_unassigned=unassigned, singletons=singletons)
    assert buckets(report) == expected
    assert_accounted(points, fixes, report)
    assert bool(script.format_removal_summary(report)) == bool(expected)


def test_raw_and_no_removal_runs_do_not_add_an_empty_footer_table():
    points = records()
    fixes, report = run(points, enabled=False)
    assert len(fixes) == len(points) and report == {"enabled": False}
    assert script.format_removal_summary(report) == ""
    assert script.format_denoising(report) == "Denoising: off."
    kept = [(0, -.005, BASE + timedelta(minutes=i), 1) for i in range(3)]
    fixes, report = run(kept)
    assert buckets(report) == {} and assert_accounted(kept, fixes, report) == [0, 0, 0]
    assert script.format_removal_summary(report) == ""
    assert "Removed points by country" not in script.format_denoising(report)


@pytest.mark.parametrize("view", ["--summary", "--timeline"])
def test_both_cli_views_include_the_country_removal_table_without_changing_the_input(
        tmp_path, monkeypatch, capsys, view):
    source, country_data = tmp_path / "input.gpx", tmp_path / "countries.geojson"
    country_data.write_text(json.dumps(boundaries()))
    track = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                    for lat, lon, time, sequence in records() if sequence is not None)
    original = ('<gpx>' + '<wpt lat="0" lon="35"/>' * 4 + '<trk><trkseg>' + track
                + '</trkseg></trk></gpx>').encode()
    source.write_bytes(original)
    monkeypatch.setattr(script, "urlopen", lambda *_a, **_kw: pytest.fail("local boundaries must stay offline"))
    assert script.main([str(source), "--country-data", str(country_data), view,
                        "--no-border-denoise", "--no-coastal-denoise", "--no-visit-denoise"]) == 0
    output = capsys.readouterr().out
    retained = output.split("\n\n", 1)[0]
    assert "| Alpha" in retained and "| Beta" not in retained and "| Gamma" not in retained
    summary = output.split("Removed points by country\n", 1)[1]
    assert table_rows(summary) == [
        ["Beta", "BB", "0", "0", "3", "3"], ["Gamma", "CC", "2", "0", "0", "2"],
        ["Unassigned", "—", "0", "4", "0", "4"], ["Total", "—", "2", "4", "3", "9"]]
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == {source, country_data}
