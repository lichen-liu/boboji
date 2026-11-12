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

`gpx_countries.py` prints a country/territory table with point counts and full
first/last recorded timestamps (UTC):

```sh
python3 gpx_countries.py history.gpx
python3 gpx_countries.py history.gpx > var/visited_countries.md
```

The first run downloads public [Natural Earth country boundaries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/)
into the ignored `var/` folder beside the script; later runs work offline.
Use `--country-data countries.geojson` for an existing local copy. Coordinates
stay local. The table reflects recorded points, including transit; it does not
infer countries between samples. Offshore/unmatched points are counted separately.
Country/territory definitions and approximate borders follow Natural Earth.

`gpx_prune.py` previews points selected for removal, then requires an interactive
terminal and an explicit `yes` before writing a new GPX. Keep `gpx_countries.py`
beside it for the shared country/time summary.

```sh
python3 gpx_prune.py history.gpx --countries CA US --start 2026-01-01 --end 2026-01-31 --dry-run
python3 gpx_prune.py history.gpx --countries CA US --start 2026-01-01 --end 2026-01-31 -o cleaned.gpx
```

At least one of `--start`, `--end`, or `--countries` is required. Supplied filters
intersect: the example selects only CA/US points inside the time window. Country
names or ISO codes are accepted; names with spaces should be quoted. Bounds are
inclusive and date-only bounds cover whole UTC days; full timestamps require a
timezone. Untimed points never match a time filter.

`--dry-run` never prompts or writes. The default output is `INPUT_pruned.gpx`;
`-o` chooses another new filename. Existing files are never overwritten and the
input stays unchanged. Remaining tracks/routes are split at removed gaps.

Tests: `python3 -m pip install pytest`, then `python3 -m pytest -q`.

GitHub follows `trip_dollar`: PRs to `main`, up-to-date branches, required
`pytest (Python 3.13)`, squash/rebase merges only, no bypasses, and no force
pushes or deletion of `main`. Development branches require linear history.
Add any PR label after the final push to request CI; pushes to `main` test
automatically. The matching settings are recorded under `.github/`.
