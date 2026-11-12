# Local installation

Python 3.11 or newer is required. To use the script directly, keep the checkout
together and run:

```sh
python3 timeline_to_fog.py /path/to/location-history.json -o output/history.gpx
```

For an installed package in a dedicated virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m boboji /path/to/location-history.json -o output/history.gpx
```

Hatchling is a build-time dependency. The installed converter itself uses only
Python's standard library. Development installation adds pytest:

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Installation is an explicit local action. Personal exports and generated files
stay in ignored directories or outside the checkout. No credentials are needed.
