# Boboji

`timeline_to_fog.py` converts Google Maps Timeline JSON into a GPX file for
Fog of World. It is a standalone Python 3.11+ script using only the standard
library. Copy it anywhere and run:

```sh
python3 timeline_to_fog.py location-history.json -o history.gpx
```

Supports Android/iPhone Timeline exports and older Google Takeout raw and
semantic history. Extract ZIPs first; multiple JSON files can share one output.
Open the resulting `.gpx` with Fog of World or use its track-import flow.

Conversion stays offline, preserves available timestamps and altitude, and
keeps separate trips/devices apart. Gaps over 30 minutes or 10 km start new
segments; `--max-gap-minutes` and `--max-distance-km` adjust those limits.
Visits and activity endpoints stay isolated rather than inventing routes.
Use `--force` to replace an existing output. Keep personal exports outside Git
or in ignored `data/` and `output/` folders. Coordinates are treated as WGS-84.

Tests: `python3 -m pip install pytest`, then `python3 -m pytest -q`.

GitHub follows `trip_dollar`: PRs to `main`, up-to-date branches, required
`pytest (Python 3.13)`, squash/rebase merges only, no bypasses, and no force
pushes or deletion of `main`. Development branches require linear history.
Add any PR label after the final push to request CI; pushes to `main` test
automatically. The matching settings are recorded under `.github/`.
