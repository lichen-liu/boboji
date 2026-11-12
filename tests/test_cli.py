import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from boboji.cli import main
from boboji.gpx import NAMESPACE
from boboji.gpx import to_gpx
from boboji.timeline import Conversion, Point

REPO = Path(__file__).resolve().parents[1]
NS = {"g": NAMESPACE}


def write_export(path, *, latitude=515000000):
    path.write_text(json.dumps({"locations": [{
        "latitudeE7": latitude, "longitudeE7": -1200000,
        "timestamp": "2026-01-01T07:00:00-05:00", "altitude": 8,
    }]}), encoding="utf-8")


def test_script_runs_without_install_or_pythonpath_from_another_directory(tmp_path):
    output = tmp_path / "tracks.gpx"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", str(REPO / "timeline_to_fog.py"), str(REPO / "examples/timeline_example.json"), "-o", str(output)],
        cwd=tmp_path, env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    root = ET.parse(output).getroot()
    assert root.tag == f"{{{NAMESPACE}}}gpx"
    assert root.attrib["version"] == "1.1"
    segments = root.findall("g:trk/g:trkseg", NS)
    assert [len(segment.findall("g:trkpt", NS)) for segment in segments] == [3, 2]
    assert "4 recorded points" in result.stdout


def test_isolated_locations_are_zero_length_tracks_with_utc_time_and_elevation(tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "nested" / "output.gpx"
    write_export(source)
    assert main([str(source), "-o", str(output)]) == 0
    points = ET.parse(output).findall("g:trk/g:trkseg/g:trkpt", NS)
    assert len(points) == 2
    assert points[0].attrib == points[1].attrib == {"lat": "51.5", "lon": "-0.12"}
    assert points[0].find("g:ele", NS).text == "8.0"
    assert points[0].find("g:time", NS).text == "2026-01-01T12:00:00Z"
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600


def test_gpx_decimals_preserve_small_values_and_do_not_round_longitude_to_180():
    document = to_gpx(Conversion(((Point(1e-7, 179.99999999999997, elevation=1e-7),),)))
    point = ET.fromstring(document).find("g:trk/g:trkseg/g:trkpt", NS)
    assert point.attrib["lat"] == "0.0000001"
    assert float(point.attrib["lon"]) < 180
    assert point.find("g:ele", NS).text == "0.0000001"


def test_existing_output_requires_force_and_failed_conversion_preserves_it(tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    write_export(source)
    output.write_text("original", encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        main([str(source), "-o", str(output)])
    assert raised.value.code == 2
    assert output.read_text() == "original"
    assert main([str(source), "-o", str(output), "--force"]) == 0
    valid_output = output.read_bytes()
    source.write_text('{"locations": [', encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(source), "-o", str(output), "--force"])
    assert output.read_bytes() == valid_output


def test_all_inputs_are_validated_before_output_is_created(tmp_path):
    first, second, output = tmp_path / "first.json", tmp_path / "second.json", tmp_path / "output.gpx"
    write_export(first)
    second.write_text("not json", encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        main([str(first), str(second), "-o", str(output)])
    assert raised.value.code == 2
    assert not output.exists()
    write_export(second, latitude=515001000)
    assert main([str(first), str(second), "-o", str(output)]) == 0
    assert len(ET.parse(output).findall("g:trk/g:trkseg", NS)) == 2


def test_input_cannot_be_replaced_even_with_force_or_hardlink(tmp_path):
    source = tmp_path / "input.gpx"
    write_export(source)
    before = source.read_bytes()
    with pytest.raises(SystemExit):
        main([str(source), "-o", str(source), "--force"])
    linked = tmp_path / "linked.gpx"
    os.link(source, linked)
    with pytest.raises(SystemExit):
        main([str(source), "-o", str(linked), "--force"])
    assert source.read_bytes() == linked.read_bytes() == before


@pytest.mark.parametrize("content", [
    b"{not json}", b"\xff\xfe", b'{"locations": [NaN]}',
    b'{"locations": [{"latitudeE7": "PRIVATE_LOCATION", "longitudeE7": 0, "timestampMs": 0}]}',
])
def test_errors_do_not_create_files_or_echo_private_payloads(tmp_path, capsys, content):
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    source.write_bytes(content)
    with pytest.raises(SystemExit) as raised:
        main([str(source), "-o", str(output)])
    assert raised.value.code == 2
    assert not output.exists()
    stderr = capsys.readouterr().err
    assert "error:" in stderr
    assert "PRIVATE_LOCATION" not in stderr
    assert "Traceback" not in stderr


def test_utf8_bom_is_supported(tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    write_export(source)
    source.write_bytes(b"\xef\xbb\xbf" + source.read_bytes())
    assert main([str(source), "-o", str(output)]) == 0


def test_write_failure_keeps_existing_output_and_removes_temporary_file(tmp_path, monkeypatch):
    source, output = tmp_path / "input.json", tmp_path / "output.gpx"
    write_export(source)
    output.write_text("original", encoding="utf-8")

    def fail_replace(*_):
        raise OSError("simulated write failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(SystemExit):
        main([str(source), "-o", str(output), "--force"])
    assert output.read_text() == "original"
    assert list(tmp_path.glob(".output.gpx.*")) == []
