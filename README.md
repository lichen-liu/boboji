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
python3 gpx_countries.py history.gpx --timeline --explain
python3 gpx_countries.py history.gpx --timeline --no-coastal-denoise
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

`--denoise` is enabled by default in both views. It checks physical movement,
independent border maps, and coastal country-visit continuity before grouping.
Turns, stops, detours, transport changes, brief visits, and boat travel are
normal; duration or sampling density alone never proves noise.

The defaults are **1,000 km/h**, **10 km allowance per position**, and a maximum
recording gap of **one hour**. Configure them with `--max-speed-kmh`,
`--position-allowance-meters` (alias `--motion-slack-meters`), and
`--max-gap-minutes` (default 60). The position allowance now also applies to
automatic coastal country inference; it is a policy budget, not measured GPS
accuracy. The Python API keeps the keyword `motion_slack_meters` for compatibility.

Within a continuous track, an isolated motion outlier needs impossible incoming
and outgoing legs, a feasible bypass, and two supporting observations on each
side. Isolated markers in their own GPX segments are additionally checked against
the surrounding chronological tracking log: the bypass must be feasible, both
legs to the marker impossible, and either an actual continuous track must bracket
it or another neighboring epoch must corroborate the track. All surrounding
position alternatives must agree physically. Logging breaks alone do not justify
an impossible teleport. This cross-segment check assumes one traveler's history;
coherent competing recordings remain unresolved. Waypoints and planned routes
are not motion evidence, and exact duplicates do not add evidence.

Border-map verification is **on by default**. For a return excursion A → B → A
within 10 km of A's polygon, a B point is relabeled only when A's independent
reference polygon includes it **and B's reference polygon excludes it**. Missing
or overlapping reference evidence preserves the original named country. There
is no short-duration or point-count cutoff; a genuine brief B visit supported
by its own reference map stays visible. `--no-border-denoise` disables this stage.

Coastal handling is also **on by default**. For unassigned points bracketed by
the same country, reference-covered locations reveal the baseline coastline's
observed disagreement. The automatic band is the larger of that observed map
budget and the configured position allowance, capped at **10 km**. Unverified
points never train the map budget. A reference must be available; without any
covered calibration locations, only the explicitly configured position allowance
can supply the budget. No competing country may be within the discovery band.
A manual `--gps-radius-meters N` instead uses exactly N metres for coastal
inference and overrides the position allowance for that stage.

Country context uses original map labels plus independent, verified border-map
corrections. Guessed coastal labels never become anchors. Distinct coordinates
at one timestamp do not imply different countries; conflicting named countries
still block country continuity. There is no coastal duration or sample-count
cutoff. `--no-coastal-denoise` disables coastal inference, and `--no-denoise`
restores all raw points and labels. Manual coastal radii bypass coastal
calibration; the separate border stage can still load reference maps.

These labels describe approximate visit context, including possible nearshore
water excursions. They do not prove land presence, measured GPS accuracy, or
an immigration visit. Reference administrative polygons can include water.
Coordinates in the input file remain unchanged.

The footer distinguishes excluded motion outliers from inferred country labels,
states the bounds, and reports how many tracking fixes could be checked.
`--explain` lists each changed record with its timestamp, original country,
result, and reason. `--no-denoise` shows every raw record and geometric label,
including when a coastal tolerance was supplied. Small glitches, plausible
jumps, persistent bias, and offshore points outside a supported mapping band
remain unresolved. See the
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

Country-map verification downloads smaller per-country reference polygons
from [geoBoundaries gbOpen](https://www.geoboundaries.org/api.html), produced by
William & Mary geoLab and contributing boundary providers, pinned to commit
`9469f09592ced973a3448cf66b6100b741b64c0d`. The collection is CC BY 4.0 compliant;
[country metadata](https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM0/)
identifies original sources and licenses. Cached files live under ignored
`var/coastlines/`, and subsequent runs work offline. Requests contain country
codes, never GPX coordinates or timestamps. Unavailable references leave
unsupported gaps visible with a diagnostic. `--country-data` keeps using only
your local boundaries and never automatically fetches reference data.

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
