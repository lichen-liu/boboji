# Boboji

Local Python tools for travel data.

## Google Maps Timeline to Fog of World

`timeline_to_fog.py` converts a Google Maps location-history JSON export into
a GPX 1.1 file for [Fog of World](https://fogofworld.app/en/).
It runs entirely on your computer and has no third-party runtime dependencies.

Use Python 3.11 or newer, from this checkout:

```sh
python3 timeline_to_fog.py /path/to/location-history.json -o output/history.gpx
```

No package installation is required. The script uses the `src/boboji/` package
in this checkout, so keep those files together. On a Mac where `python3` is
Apple's older system Python, invoke your installed Python 3.11+ explicitly,
for example `python3.14`.

Try the included synthetic example:

```sh
python3 timeline_to_fog.py examples/timeline_example.json -o output/example.gpx
```

Multiple exported JSON files can share one output; each file's tracks remain
separate. Extract Takeout archives first, then pass the relevant JSON files:

```sh
python3 timeline_to_fog.py /path/to/Records.json -o output/legacy.gpx
python3 timeline_to_fog.py /path/to/2023_*.json -o output/2023.gpx
```

| Supported export | Recognized structure |
| --- | --- |
| Android phone Timeline | `semanticSegments` and/or positional `rawSignals` |
| iPhone phone Timeline | Top-level array of paths, visits, and activities |
| Older Google Takeout raw history | `locations`, including E7 coordinates and ISO timestamps or `timestampMs` |
| Older Google Takeout semantic history | `timelineObjects`, including `simplifiedRawPath` and `waypointPath` |

Both `geo:latitude,longitude` and degree-marked `latLng` strings are supported.
Phone path timestamps may be absolute `time` fields or minute offsets from
`startTime`. Times are converted to UTC; untimed path points stay untimed.
Altitude is retained when present on a location record.

### Import the result

Save the generated `.gpx` file to your phone and open/share it with Fog of World,
or use the app's track-import flow with a supported connected cloud storage.
See the [developer's import guide](https://medium.com/fogofworld/how-to-add-tracks-to-fog-of-world-manually-1541c6ae8d8d).
The output is standard GPX, with track segments rather than waypoint markers.
The automated checks validate the GPX structure and content; importing into
the phone app itself still requires your device.

### Track boundaries and sparse history

The script preserves recorded path geometry and source boundaries. Raw fixes
are sorted by timestamp separately for each device. Identical consecutive fixes
are collapsed. A gap over 30 minutes, a jump over 10 km, or a non-increasing
timestamp starts a new segment. Separate source files never become one route.

Visits and activities with only start/end locations are emitted as isolated,
zero-length tracks. The serializer repeats an isolated point once so it is
represented by two identical track points. It does not draw a route between
endpoints, interpolate long gaps, or use stored home/work profiles as visits.
Sparse exports therefore produce sparse coverage.

The 10 km limit follows Fog of World's documented import restriction. You can
lower that threshold or change the time gap:

```sh
python3 timeline_to_fog.py data/Timeline.json -o output/history.gpx \
  --max-gap-minutes 15 --max-distance-km 5
```

Coordinates are treated as WGS-84; no coordinate-system conversion is inferred.
For data known to use mainland China's GCJ-02 system, the developer's guide
describes its `@GCJ02.gpx` filename convention. Do not apply that suffix to
mixed-coordinate-system data.

### File handling and errors

An existing output requires `--force`. The script validates every input before
writing, writes the GPX atomically, and refuses to replace an input file.
Invalid location fields or unsupported JSON stop conversion with exit code 2.
Errors identify the file/field without printing location values or JSON bodies.
New GPX files have owner-only permissions on POSIX systems.

Keep personal files in ignored `data/` and `output/` directories, or outside the
checkout. Only synthetic examples belong in Git. The converter loads each JSON
export in memory; it does not stream multi-gigabyte archives.

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

Installing the package also provides `timeline_to_fog`; `python -m boboji` uses
the same converter. See [installation](installation/README.md),
[architecture and formats](docs/README.md), and [repository/CI guidelines](.github/README.md).

## Repository conventions

This repository follows the applicable conventions of
[`lichen-liu/trip_dollar`](https://github.com/lichen-liu/trip_dollar) at commit
[`e5e14f8`](https://github.com/lichen-liu/trip_dollar/tree/e5e14f81a219ae2d4c0606f2a5f8070a7f0cf190):
Python 3.11+, Hatchling packaging, a `src/` layout, a dependency-free core,
offline pytest tests, documented examples, manual PR-label CI on Python 3.13,
automatic tests after `main` changes, and matching GitHub merge protections.

```text
timeline_to_fog.py     Directly runnable Python script
src/boboji/           Conversion core, GPX serializer, command-line adapter
tests/                Offline regression tests
examples/             Synthetic input
docs/                 Architecture, formats, and design choices
installation/         Local installation instructions
deployment/           Execution and future-service conventions
.github/              CI, merge settings, and branch rulesets
```
