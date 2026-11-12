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
start new rows: Canada → Peru → Canada produces three rows. Unassigned/offshore
points remain visible and also split periods; there is no blanket offshore
exclusion, and `--show-offshore` is no longer needed. Untimed points are grouped
by country at the end.
Spans run from the first to last recorded point in each period and can include
sampling gaps. The timeline flag replaces `--chronological`.

`--denoise` is enabled by default in both views. It fits movement limits to each
GPX track segment or route using its sampling cadence, speeds, and deviations
from locally interpolated positions. Nearby path windows refine comparisons
with isolated fixes. Robust upper fences (the larger of the
90th percentile or upper quartile plus three interquartile ranges) provide
empirical movement and scatter limits.
Exact duplicate fixes retain their GPX counts but contribute only once to
fitting. Isolated visits/endpoints that contradict a supported path, and
isolated path spikes with implausible movement on both sides, can be excluded
from the report.

The GPS border filter considers a short switch A → B → A within a track
segment/route, including an unassigned B. By default, the samples in A
surrounding the switch must be at most **10 minutes** apart, and B must contain
at most **5 distinct timestamps**. Every B point must be within the estimated
GPS radius of A's **polygon**, rather than its centroid. For switches into a
named country B, a majority of interpolated positions between the surrounding
A samples must also support A; coherent crossings supported by that bridge
remain visible. For an unassigned coastal gap, the bridge may itself be
unassigned if both it and every actual point stay within A's distance budget.
A bridge that crosses another named country prevents the coastal correction.
After a correction, neighboring unassigned gaps are checked again before
grouping. These later passes only assign unassigned points; they do not change
known country labels, and inferred points do not train the new radius fit.

The new short/sparse rule's automatic radius uses the same robust upper fence,
fitted to time-weighted interpolation residuals in stable A observations on
each side of the switch.
The suspect run and the bridge across it do not train this threshold. At least
three eligible residuals are needed for an automatic radius. With an explicit
radius, a surrounding country run with five distinct timestamps can supply
context even when a GPX segment has too few local residuals. The earlier
one-sampling-interval rule also remains, using its per-path scatter bound when
at least one surrounding country run has five timestamps and every bridge
position agrees. Unsupported alternating country labels remain uncertain.
This estimates trajectory scatter, not measured device accuracy or
a calibrated probability. It can also reflect road curvature and map error.

Use `--gps-radius-meters 1000` to set an explicit 1 km polygon-distance cutoff.
`--gps-max-minutes` and `--gps-max-points` adjust the time and independent-point
limits; all conditions must hold. These options affect border reassignment,
while the existing isolated-conflict and path-spike filters keep their fitted
movement limits. Corrections happen before both summary and timeline grouping.
The footer shows the inferred radius range (or override), corrected counts,
and the farthest corrected point's distance to its previous country polygon.
An isolated marker can also be reassigned, rather than discarded, when a
supported path brackets its timestamp in the same country and the polygon
distance passes this threshold. Other supported paths must agree; a path
supporting the marker's original country vetoes the correction.
Duplicate points in a short GPX segment do not veto a correction merely because
that segment lacks enough context to fit its own radius. Nearby observations
of a different country in another source still veto it.

Sustained offshore travel, long gaps, and untimed observations remain visible
without sufficient evidence for a change. A real brief visit near a border can
also resemble jitter; compare `--no-denoise` when reviewing uncertain cases.
Paths with fewer than five distinct timestamps can use pooled limits learned
from longer paths to detect gross movement conflicts;
they do not supply their own boundary-uncertainty fit. With no longer paths,
sparse data stays unchanged. Disagreement between supported sources prevents
an automatic change. These are conservative empirical rules, not calibrated
probabilities or proof of a visit. GPX segment context is available; original
Google activity labels and
confidence values cannot be recovered from an ordinary GPX file.

The footer reports input counts, excluded points by reason, and adjusted
country assignments. `--no-denoise` shows every original point and country
assignment. Denoising changes only the displayed analysis; it never writes or
modifies GPX files. The pruner's selection and removal preview always use the
original points and geometric country assignments.

The first run downloads public [Natural Earth country boundaries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/)
into the ignored `var/` folder beside the script; later runs work offline.
Use `--country-data countries.geojson` for an existing local copy. Coordinates
stay local. The table reflects recorded points, including transit; it does not
infer countries between samples. Offshore/unmatched points are counted separately.
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
