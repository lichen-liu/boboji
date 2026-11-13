"""Pipeline configuration and report contracts, with synthetic offline data."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
import logging
import math

import pytest

import gpx_countries as script


A, B = ("Alpha", "AA"), ("Beta", "BB")
BASE = datetime(2031, 1, 1, tzinfo=timezone.utc)
LONGITUDE = {A: -1.5, B: 1.5, None: 9}


def boundaries():
    features = []
    for country, west, east in ((A, -2, -1), (B, 1, 2)):
        features.append({"type": "Feature", "properties": {"NAME_EN": country[0], "ISO_A2": country[1]},
                         "geometry": {"type": "Polygon", "coordinates": [[
                             [west, -1], [east, -1], [east, 1], [west, 1], [west, -1]]]}})
    return {"type": "FeatureCollection", "features": features}


def samples(labels, sequence=1):
    return [(0, LONGITUDE[country], BASE + timedelta(minutes=i), sequence)
            for i, country in enumerate(labels)]


def run(records, **changes):
    config = replace(script.DenoiseConfig(motion=False, borders=False, visits=False, coastal=False), **changes)
    return script.run_denoising(records, script.country_lookup(boundaries()), config)


def snapshot(fixes):
    return [(f.latitude, f.longitude, f.time, f.country, f.count, f.sequences,
             f.raw_country, f.reference_country) for f in fixes]


@pytest.mark.parametrize("changes", [
    {}, {"enabled": False}, {"motion": False}, {"borders": False}, {"visits": False},
    {"coastal": False}, {"remove_unassigned": False}, {"singletons": False},
    {"policy": script.DenoisePolicy(250, 120, 3000), "gps_radius_meters": 500},
])
def test_configured_runner_preserves_the_keyword_api_contract(changes):
    records = samples([A, B, A, None, A])
    records.insert(1, records[1])
    config = replace(script.DenoiseConfig(), **changes)
    lookup = script.country_lookup(boundaries())
    configured, configured_report = script.run_denoising(records, lookup, config)
    legacy, legacy_report = script.denoise_samples(
        records, lookup, enabled=config.enabled, motion=config.motion, borders=config.borders,
        visits=config.visits, coastal=config.coastal, remove_unassigned=config.remove_unassigned,
        singletons=config.singletons, gps_radius_meters=config.gps_radius_meters,
        max_speed_kmh=config.policy.max_speed_kmh, max_gap_minutes=config.policy.max_gap_minutes,
        motion_slack_meters=config.policy.position_allowance_meters)
    assert snapshot(configured) == snapshot(legacy)
    assert configured_report == legacy_report


def test_config_and_policy_are_immutable_and_each_run_owns_its_report():
    config = script.DenoiseConfig(motion=False, borders=False, visits=False, coastal=False)
    with pytest.raises(FrozenInstanceError):
        config.motion = True
    with pytest.raises(FrozenInstanceError):
        config.policy.max_speed_kmh = 1
    records = samples([A, B, A])
    lookup = script.country_lookup(boundaries())
    first, first_report = script.run_denoising(records, lookup, config)
    second, second_report = script.run_denoising(records, lookup, config)
    assert snapshot(first) == snapshot(second)
    assert first_report == second_report
    first_report["decisions"].clear()
    assert second_report["decisions"] and second_report["singleton_removed"] == 1


@pytest.mark.parametrize("radius", [0, -1, math.inf, math.nan])
def test_active_config_rejects_invalid_context_radius_but_raw_mode_ignores_it(radius):
    with pytest.raises(ValueError, match="invalid coastal radius"):
        script.DenoiseConfig(gps_radius_meters=radius)
    records = list(reversed(samples([A, B, A])))
    config = script.DenoiseConfig(enabled=False, gps_radius_meters=radius)
    fixes, report = script.run_denoising(records, script.country_lookup(boundaries()), config)
    assert report == {"enabled": False}
    assert [(f.longitude, f.time, f.count) for f in fixes] == [(lon, time, 1) for _, lon, time, _ in records]


def test_legacy_raw_mode_still_bypasses_unused_physical_limit_validation():
    records = samples([A, B, A])
    fixes, report = script.denoise_samples(
        records, script.country_lookup(boundaries()), enabled=False, max_speed_kmh=-1,
        max_gap_minutes=0, motion_slack_meters=-1, gps_radius_meters=math.nan,
        coastal_reference=lambda _country: pytest.fail("raw mode cannot request reference maps"))
    assert [f.country for f in fixes] == [A, B, A]
    assert report == {"enabled": False}


def test_default_report_has_bounded_size_and_conserves_weighted_removal_counts():
    points = samples([A, B, A])
    records = [points[0], *([points[1]] * 3), points[2], *([(0, 9, None, None)] * 4)]
    fixes, report = run(records)
    assert report["represented"] == sum(f.count for f in fixes) == 2
    assert report["input"] == 9
    assert report["input"] == report["represented"] + report["excluded"] + report["unassigned_removed"] + report["singleton_removed"]
    compact = script.format_denoising(report)
    assert "Denoising: on · Input: 9 · Kept: 2 · Removed: 7" in compact
    assert "motion 0 · unassigned 4 · singletons 3 (1 excursion)" in compact
    assert len(compact.splitlines()) <= 5
    assert max(map(len, compact.splitlines())) <= 120
    assert "Bounds:" not in compact and "Reference map details" not in compact
    report["coastal_models"] = [(f"Country {i:02}", 100, 500) for i in range(30)]
    report["coastal_effective"] = [(name, 10000) for name, _, _ in report["coastal_models"]]
    assert script.format_denoising(report) == compact


def test_verbose_report_keeps_compact_accounting_and_separates_diagnostic_details():
    _fixes, report = run(samples([A, B, A]))
    compact = script.format_denoising(report)
    verbose = script.format_denoising(report, verbose=True)
    assert verbose.startswith(compact + "\n\n")
    assert "Denoising stages" in verbose and "| Phase" in verbose
    assert "Bounds: speed 1000 km/h · position 10 km · gap 60 min." in verbose
    assert "Diagnostics before output filters: 0 country conflicts · 2 movement conflicts." in verbose
    assert "Diagnostics after output filters: 0 country conflicts · 0 movement conflicts." in verbose
    assert report["unresolved_motion"] and report["remaining_motion"] == []
    assert "Review:" not in compact


def test_remaining_review_counts_include_only_conflicts_still_visible_after_filtering():
    records = samples([A, A, A])
    records.insert(2, (0, LONGITUDE[B], records[1][2], 1))
    fixes, report = run(records)
    assert all(f.country == A for f in fixes)
    assert report["before_output_country_epochs"] == 1 and report["remaining_country_epochs"] == 0
    assert "Review:" not in script.format_denoising(report)
    _fixes, retained_report = run(records, singletons=False)
    assert retained_report["remaining_country_epochs"] == 1
    assert "Review: 1 country conflict." in script.format_denoising(retained_report)


def test_before_and_after_country_diagnostics_use_the_same_nontracking_scope():
    records = [(0, LONGITUDE[A], BASE, None), (0, LONGITUDE[B], BASE, None)]
    _fixes, report = run(records, singletons=False)
    assert report["unresolved_country_epochs"] == 0  # Existing tracking-only API diagnostic.
    assert report["before_output_country_epochs"] == report["remaining_country_epochs"] == 1
    verbose = script.format_denoising(report, verbose=True)
    assert "Diagnostics before output filters: 1 country conflicts" in verbose
    assert "Diagnostics after output filters: 1 country conflicts" in verbose


def test_remaining_impossible_endpoint_transition_is_still_reported():
    _fixes, report = run(samples([A, B]))
    assert len(report["unresolved_motion"]) == len(report["remaining_motion"]) == 1
    assert "Review: 1 movement conflict." in script.format_denoising(report)


def test_manual_radius_is_not_reported_as_an_automatic_map_allowance():
    _fixes, report = run(samples([A, A]), gps_radius_meters=500)
    report["coastal_effective"] = [("Alpha", 10000)]
    report["coastal_models"] = [("Alpha", 1, 2002)]
    verbose = script.format_denoising(report, verbose=True)
    assert "Country context radius: 500 m (manual override)." in verbose
    map_row = next(line for line in verbose.split("Reference map details\n", 1)[1].splitlines()
                   if line.startswith("| Alpha"))
    assert [cell.strip() for cell in map_row.split("|")[1:-1]] == ["Alpha", "—", "2,002", "1"]


def test_raw_and_empty_output_have_no_irrelevant_diagnostic_footnotes():
    assert script.format_denoising({"enabled": False}) == "Denoising: off."
    assert script.format_denoising({"enabled": False}, verbose=True) == "Denoising: off."
    fixes, report = run(samples([None, None]))
    assert fixes == [] and report["represented"] == 0
    assert "Input: 2 · Kept: 0 · Removed: 2" in script.format_denoising(report)
    table = script.format_timeline(*script.group_timeline_labels([]))
    assert "GPX points represented: 0" in table
    assert "Unassigned: 0" not in table and "Untimed: 0" not in table
    assert "Untimed points" not in table


@pytest.fixture
def cli_inputs(tmp_path, monkeypatch):
    country_data, source = tmp_path / "countries.geojson", tmp_path / "input.gpx"
    country_data.write_text(json.dumps(boundaries()))
    body = ''.join(f'<trkpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></trkpt>'
                   for lat, lon, time, _ in samples([A, B, A]))
    source.write_text('<gpx><trk><trkseg>' + body + '</trkseg></trk></gpx>')
    monkeypatch.setattr(script, "urlopen", lambda *_args, **_kwargs: pytest.fail("local data must stay offline"))
    return source, country_data


def test_cli_verbose_only_adds_details_and_keeps_country_rows_unchanged(cli_inputs, capsys):
    source, country_data = cli_inputs
    original = source.read_bytes()
    base = [str(source), "--country-data", str(country_data), "--timeline"]
    assert script.main(base) == 0
    compact = capsys.readouterr()
    assert script.main([*base, "--verbose"]) == 0
    verbose = capsys.readouterr()
    assert compact.out.split("\n\n", 1)[0] == verbose.out.split("\n\n", 1)[0]
    assert "Denoising stages" not in compact.out and "Denoising stages" in verbose.out
    assert "Bounds:" not in compact.out and "Bounds:" in verbose.out
    assert not compact.err and not verbose.err
    assert source.read_bytes() == original


def test_explain_lists_retained_simultaneous_country_conflicts_without_record_changes(cli_inputs, capsys):
    source, country_data = cli_inputs
    source.write_text('<gpx>' + ''.join(
        f'<wpt lat="0" lon="{LONGITUDE[country]}"><time>{script.timestamp(BASE)}</time></wpt>'
        for country in (B, A)) + '</gpx>')
    original = source.read_bytes()
    fixes, report = run([(0, LONGITUDE[country], BASE, None) for country in (B, A)])
    assert report["decisions"] == [] and report["remaining_motion"] == []
    assert report["remaining_country_alternatives"] == [(BASE, [A, B])]
    assert len(fixes) == 2
    assert script.main([str(source), "--country-data", str(country_data), "--timeline", "--explain"]) == 0
    output = capsys.readouterr().out
    assert "No denoising changes." in output
    assert "Movement conflicts in displayed points:" not in output
    section = output.split("Country conflicts in displayed points:\n", 1)[1]
    row = next(line for line in section.splitlines() if script.timestamp(BASE) in line)
    assert [cell.strip() for cell in row.split("|")[1:-1]] == [
        script.timestamp(BASE), "Alpha (AA), Beta (BB)"]
    assert source.read_bytes() == original


def test_explain_omits_country_conflicts_removed_by_the_singleton_policy(cli_inputs, capsys):
    source, country_data = cli_inputs
    records = samples([A, A, A], sequence=None)
    records.insert(2, (0, LONGITUDE[B], records[1][2], None))
    source.write_text('<gpx>' + ''.join(
        f'<wpt lat="{lat}" lon="{lon}"><time>{script.timestamp(time)}</time></wpt>'
        for lat, lon, time, _ in records) + '</gpx>')
    original = source.read_bytes()
    _fixes, report = run(records)
    assert report["before_output_country_epochs"] == 1
    assert report["singleton_removed"] == 1 and report["remaining_country_alternatives"] == []
    assert script.main([str(source), "--country-data", str(country_data), "--timeline", "--explain"]) == 0
    output = capsys.readouterr().out
    assert "single-timestamp Beta excursion" in output
    assert "Country conflicts in displayed points:" not in output
    assert "Review:" not in output
    assert source.read_bytes() == original


@pytest.mark.parametrize("malformed", [False, True])
def test_cli_verbose_restores_logger_level_on_success_and_failure(cli_inputs, capsys, malformed):
    source, country_data = cli_inputs
    if malformed:
        source.write_text('<gpx><wpt lat="invalid" lon="0"/></gpx>')
    previous_level = script.LOGGER.level
    script.LOGGER.setLevel(logging.WARNING)
    arguments = [str(source), "--country-data", str(country_data), "--verbose"]
    try:
        if malformed:
            with pytest.raises(SystemExit) as error:
                script.main(arguments)
            assert error.value.code == 2
        else:
            assert script.main(arguments) == 0
        assert script.LOGGER.level == logging.WARNING
    finally:
        script.LOGGER.setLevel(previous_level)
    capsys.readouterr()
