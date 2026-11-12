import json
import os
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

import gpx_countries
import gpx_prune as script

NS = "{http://www.topografix.com/GPX/1/1}"


def country_data():
    def feature(name, code, west):
        return {"type": "Feature", "properties": {
            "NAME_EN": name, "ISO_A2_EH": code, "ISO_A3": code + "A",
        }, "geometry": {"type": "Polygon", "coordinates": [[
            [west, 0], [west + 10, 0], [west + 10, 10], [west, 10], [west, 0],
        ]]}}
    return {"type": "FeatureCollection", "features": [
        feature("Alpha", "AA", 0), feature("Beta", "BB", 20),
    ]}


@pytest.fixture
def files(tmp_path):
    source, boundaries = tmp_path / "history.gpx", tmp_path / "countries.geojson"
    boundaries.write_text(json.dumps(country_data()))
    points = """<{tag} lat="2" lon="22"><time>2026-01-01T12:00:00Z</time></{tag}>
      <{tag} lat="2" lon="2"><time>2026-01-02T12:00:00Z</time></{tag}>
      <{tag} lat="2" lon="22"><time>2026-01-03T12:00:00Z</time></{tag}>"""
    source.write_text(f'''<gpx xmlns="{NS[1:-1]}" xmlns:x="urn:example" version="1.1" creator="test">
      <metadata><name>Original</name><extensions><x:note>Keep metadata</x:note></extensions></metadata>
      <wpt lat="2" lon="2"><name>Selected waypoint</name><time>2026-01-02T12:00:00Z</time></wpt>
      <rte><name>Route</name>{points.format(tag="rtept")}</rte>
      <trk><name>Track</name><trkseg>{points.format(tag="trkpt")}
        <extensions><x:quality>original</x:quality></extensions>
      </trkseg></trk></gpx>''')
    return source, boundaries


def arguments(files, *extra):
    source, boundaries = files
    return [str(source), "--country-data", str(boundaries), *extra]


def interactive(monkeypatch, response="yes"):
    monkeypatch.setattr(script.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    if isinstance(response, BaseException):
        def answer(_):
            raise response
    else:
        answer = lambda _: response
    monkeypatch.setattr("builtins.input", answer)


def test_filters_are_required_before_any_file_access(capsys):
    with pytest.raises(SystemExit) as raised:
        script.main(["missing.gpx"])
    assert raised.value.code == 2
    assert "at least one filter" in capsys.readouterr().err


def test_date_bounds_and_country_filters_intersect():
    lookup = gpx_countries.country_lookup(country_data())
    start = script.time_bound("2026-01-02")
    end = script.time_bound("2026-01-02", end=True)
    countries = script.resolve_countries(["aa", "Alpha", "AAA"], country_data())
    assert countries == {("Alpha", "AA")}
    assert script.matches((2, 2, start), lookup, start, end, countries)
    assert script.matches((2, 2, end), lookup, start, end, countries)
    assert not script.matches((2, 22, start), lookup, start, end, countries)
    assert not script.matches((2, 2, script.time_bound("2026-01-03")), lookup, start, end, countries)
    assert not script.matches((2, 2, None), lookup, start, end, countries)
    assert script.matches((2, 2, None), lookup, countries=countries)
    assert not script.matches((50, 50, start), lookup, countries=countries)
    assert script.resolve_countries(["aa, bb"], country_data()) == {("Alpha", "AA"), ("Beta", "BB")}
    assert script.time_bound("2026-01-02T07:00:00-05:00").hour == 12


def test_quoted_country_name_with_comma_is_not_split():
    data = country_data()
    data["features"][0]["properties"]["NAME_EN"] = "Alpha, Islands"
    assert script.resolve_countries(["Alpha, Islands"], data) == {("Alpha, Islands", "AA")}
    assert script.resolve_countries(["AA,BB"], data) == {("Alpha, Islands", "AA"), ("Beta", "BB")}


@pytest.mark.parametrize("value", ["2026-01-02T12:00:00", "2026-02-31", "PRIVATE_BAD_TIMESTAMP"])
def test_invalid_bounds_do_not_echo_values(value):
    with pytest.raises(ValueError) as raised:
        script.time_bound(value)
    assert "PRIVATE_BAD_TIMESTAMP" not in str(raised.value)


def test_invalid_filters_fail_without_output(files):
    for extra in (("--start", "2026-01-03", "--end", "2026-01-02"), ("--countries", "Unknown")):
        with pytest.raises(SystemExit) as raised:
            script.main(arguments(files, *extra))
        assert raised.value.code == 2
    assert not files[0].with_name("history_pruned.gpx").exists()


def test_preview_uses_country_summary_timestamps_and_never_prompts_or_writes(files, tmp_path, monkeypatch, capsys):
    def unexpected_prompt(_):
        pytest.fail("dry run must not prompt")
    monkeypatch.setattr("builtins.input", unexpected_prompt)
    output = tmp_path / "new-directory" / "pruned.gpx"
    before = files[0].read_bytes()
    assert script.main(arguments(files, "--start", "2026-01-02", "--end", "2026-01-02",
                                 "--countries", "AA", "--dry-run", "-o", str(output))) == 0
    report = capsys.readouterr().out
    assert "Matching points to remove: 3 of 7" in report
    assert "Alpha" in report and "2026-01-02T12:00:00Z" in report
    assert "AND" in report and "Preview only" in report
    assert not output.parent.exists()
    assert files[0].read_bytes() == before


def test_pruner_previews_original_points_even_when_country_report_denoises_them(files, capsys):
    source, boundaries = files
    track = ''.join(
        f'<trkpt lat="2" lon="{1 + index * .001}"><time>2026-01-01T00:{index:02}:00Z</time></trkpt>'
        for index in range(13))
    original = (f'<gpx xmlns="{NS[1:-1]}"><wpt lat="2" lon="22">'
                '<time>2026-01-01T00:06:00Z</time></wpt>'
                f'<trk><trkseg>{track}</trkseg></trk></gpx>')
    source.write_text(original)
    assert gpx_countries.main([str(source), "--country-data", str(boundaries)]) == 0
    assert "| Beta" not in capsys.readouterr().out
    assert script.main(arguments(files, "--countries", "BB", "--dry-run")) == 0
    report = capsys.readouterr().out
    assert "Matching points to remove: 1 of 14" in report and "| Beta" in report
    assert source.read_text() == original
    assert not source.with_name("history_pruned.gpx").exists()


@pytest.mark.parametrize("answer", ["no", "", "y", EOFError(), KeyboardInterrupt()])
def test_decline_or_interruption_creates_no_output(files, monkeypatch, answer):
    interactive(monkeypatch, answer)
    assert script.main(arguments(files, "--countries", "AA")) == 0
    assert not files[0].with_name("history_pruned.gpx").exists()


def test_noninteractive_execution_cannot_confirm(files, monkeypatch):
    monkeypatch.setattr(script.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit) as raised:
        script.main(arguments(files, "--countries", "AA"))
    assert raised.value.code == 2
    assert not files[0].with_name("history_pruned.gpx").exists()


def test_time_only_preview_includes_unassigned_and_skips_untimed(files, capsys):
    source, _ = files
    source.write_text(f'''<gpx xmlns="{NS[1:-1]}">
      <wpt lat="2" lon="2"/>
      <wpt lat="50" lon="50"><time>2026-01-02T12:00:00Z</time></wpt>
    </gpx>''')
    assert script.main(arguments(files, "--start", "2026-01-02", "--dry-run")) == 0
    report = capsys.readouterr().out
    assert "Matching points to remove: 1 of 2" in report
    assert "Unassigned" in report and "2026-01-02T12:00:00Z" in report
    assert "Untimed points excluded from time filter: 1" in report
    assert not source.with_name("history_pruned.gpx").exists()


def test_no_matches_never_prompts_or_creates_output(files, monkeypatch, capsys):
    def unexpected_prompt(_):
        pytest.fail("an empty removal must not prompt")
    monkeypatch.setattr("builtins.input", unexpected_prompt)
    assert script.main(arguments(files, "--start", "2027-01-01", "--countries", "AA")) == 0
    assert "Nothing matches" in capsys.readouterr().out
    assert not files[0].with_name("history_pruned.gpx").exists()


def test_confirmation_writes_new_file_preserving_source_metadata_and_track_gaps(files, monkeypatch):
    source, _ = files
    before = source.read_bytes()
    interactive(monkeypatch)
    assert script.main(arguments(files, "--countries", "Alpha")) == 0
    output = source.with_name("history_pruned.gpx")
    assert source.read_bytes() == before
    root = ET.parse(output).getroot()
    assert root.findtext(NS + "metadata/" + NS + "name") == "Original"
    assert root.findtext(".//{urn:example}note") == "Keep metadata"
    assert root.findall(NS + "wpt") == []
    segments = root.findall(NS + "trk/" + NS + "trkseg")
    routes = root.findall(NS + "rte")
    assert [len(segment.findall(NS + "trkpt")) for segment in segments] == [1, 1]
    assert [len(route.findall(NS + "rtept")) for route in routes] == [1, 1]
    assert [segment.findtext(".//{urn:example}quality") for segment in segments] == ["original", "original"]
    assert len(list(script.tracking_nodes(root, NS))) == 4


def test_all_points_can_only_be_removed_after_confirmation(files, monkeypatch, capsys):
    interactive(monkeypatch)
    assert script.main(arguments(files, "--start", "2026-01-01")) == 0
    root = ET.parse(files[0].with_name("history_pruned.gpx")).getroot()
    assert list(script.tracking_nodes(root, NS)) == []
    assert "All recorded points match" in capsys.readouterr().out
    assert root.findtext(NS + "metadata/" + NS + "name") == "Original"


def test_existing_output_input_and_hardlinks_are_protected(files, tmp_path):
    source, _ = files
    existing, linked = tmp_path / "existing.gpx", tmp_path / "linked.gpx"
    existing.write_text("original")
    os.link(source, linked)
    before = source.read_bytes()
    for output in (source, linked, existing):
        with pytest.raises(SystemExit):
            script.main(arguments(files, "--countries", "AA", "-o", str(output)))
    assert existing.read_text() == "original"
    assert source.read_bytes() == linked.read_bytes() == before


def test_dry_run_can_preview_with_existing_output_but_never_input_aliases(files, tmp_path, capsys):
    source, _ = files
    output = source.with_name("history_pruned.gpx")
    output.write_text("existing output")
    assert script.main(arguments(files, "--countries", "AA", "--dry-run")) == 0
    assert output.read_text() == "existing output"
    assert "Output already exists" in capsys.readouterr().out
    linked = tmp_path / "alias.gpx"
    os.link(source, linked)
    for alias in (source, linked):
        with pytest.raises(SystemExit):
            script.main(arguments(files, "--countries", "AA", "--dry-run", "-o", str(alias)))
    assert linked.read_bytes() == source.read_bytes()


def test_output_created_while_confirming_is_not_overwritten(files, monkeypatch):
    source, _ = files
    output = source.with_name("history_pruned.gpx")
    before_names = {path.name for path in source.parent.iterdir()}
    interactive(monkeypatch)
    def answer(_):
        output.write_text("other process")
        return "yes"
    monkeypatch.setattr("builtins.input", answer)
    with pytest.raises(SystemExit):
        script.main(arguments(files, "--countries", "AA"))
    assert output.read_text() == "other process"
    assert {path.name for path in source.parent.iterdir()} == before_names | {output.name}
