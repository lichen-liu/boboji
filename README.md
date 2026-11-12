# Boboji

`timeline_to_fog.py` converts Google Maps Timeline JSON into a GPX file for
Fog of World. It is a standalone Python 3.9+ script using only the standard
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
python3 gpx_countries.py history.gpx --summary
python3 gpx_countries.py history.gpx --timeline
python3 gpx_countries.py history.gpx --timeline --denoise
python3 gpx_countries.py history.gpx --timeline --gps-radius-meters 1000
python3 gpx_countries.py history.gpx --timeline --no-denoise
python3 gpx_countries.py history.gpx > var/visited_countries.md
```

The default view and `--summary` show one row per country in alphabetical order.
`--timeline` sorts observations by UTC timestamp, then groups consecutive
countries into rows with begin, end, recorded span, and point count. Returns
start new rows: Canada → Peru → Canada produces three rows. Unassigned
points remain visible and also split periods; there is no blanket offshore
exclusion, and `--show-offshore` is no longer needed. Untimed points are grouped
by country at the end.
Spans run from the first to last recorded point in each period and can include
sampling gaps. The timeline flag replaces `--chronological`.
Equal-time conflicts retain input order; rows do not resolve which position is true.

`--denoise` is enabled by default in both views. It screens **isolated, gross
motion outliers** in recorded tracks. A point is excluded only if both incoming
and outgoing displacements exceed the configured movement bound, the bypass
is feasible, and two surrounding observations on each side provide consistent
context. Turns, stops, detours, changes of transport, short visits, and water
travel are normal; their shape or duration alone does not justify removal.

The defaults allow **1,500 km/h**, plus **1,000 m per position**, to accommodate
mixed travel including flights. These are conservative policy assumptions,
not learned GPS accuracy. `--max-speed-kmh`, `--motion-slack-meters`, and
`--max-gap-minutes` (default 30) expose them. Lowering the speed bound can erase
real faster travel. No motion test crosses a GPX segment boundary or a gap over
the limit. Endpoints, sparse tracks, conflicting simultaneous locations, and
distinct overlapping recordings are retained when context is insufficient.
Waypoints and route points remain in the table but are not motion evidence.
Exact duplicate tracking records preserve counts without adding evidence.

No coastal radius is estimated from road curvature. Optionally supply
`--gps-radius-meters 1000` to allow approximate country assignment within
1 km of a polygon. This **mapping tolerance** applies only to unassigned,
timed tracking points bracketed by the same raw country, with that country the
only polygon within the radius. Named countries are never rewritten merely
because a visit is brief. Actual points are checked; no straight route is
invented, inferred labels never become evidence, and duration/point-count
cutoffs do not apply. This optional mapping policy can span logging breaks;
it does not establish continuous presence or prove that a point was on land.

The footer distinguishes excluded motion outliers from inferred country labels,
states the bounds, and reports how many tracking fixes could be checked.
`--explain` lists each changed record with its timestamp, original country,
result, and reason. `--no-denoise` shows every raw record and geometric label,
including when a coastal tolerance was supplied. Small glitches, plausible
jumps, persistent bias, and unknown accuracy remain unresolved. See the
[denoising audit](DENOISING_AUDIT.md) for assumptions, counterexamples, tests,
and limits. The old `--gps-max-points` / `--gps-max-minutes` heuristics were
removed because short visits and sparse sampling are not evidence of error.

Denoising changes only the displayed analysis; it never writes or modifies
GPX files. The pruner's selection and removal preview always use original
points and geometric country assignments.

The first run downloads public [Natural Earth country boundaries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/)
into the ignored `var/` folder beside the script; later runs work offline.
Use `--country-data countries.geojson` for an existing local copy. Coordinates
stay local. The table reflects recorded points, including transit; it does not
infer countries between samples. Unmatched points are counted separately; “Unassigned” does not prove offshore.
Country/territory definitions and approximate borders follow Natural Earth;
`10m` denotes a 1:10 million map scale, not ten-metre positional accuracy.

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

All scripts support Python 3.9+. Tests: `python3 -m pip install pytest`, then
`python3 -m pytest -q`. CI tests Python 3.9 and 3.13.

GitHub follows `trip_dollar`: PRs to `main`, up-to-date branches, required
`pytest (Python 3.13)`, squash/rebase merges only, no bypasses, and no force
pushes or deletion of `main`. Development branches require linear history.
Add any PR label after the final push to request CI; pushes to `main` test
automatically. The matching settings are recorded under `.github/`.
