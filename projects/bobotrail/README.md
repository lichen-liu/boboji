# BoboTrail

Convert, inspect, and clean your travel trails. Standalone Python 3.9+ tools
using only the standard library. Run examples from
this project directory:

```sh
cd projects/bobotrail
```

## Convert Timeline JSON

`timeline_to_fog.py` converts Google Maps Timeline exports to GPX for Fog of World.
It supports Android/iPhone exports and older Google Takeout raw and semantic
history. Extract ZIPs first; multiple JSON inputs can share one output.

```sh
python3 timeline_to_fog.py location-history.json -o history.gpx
```

Conversion stays offline and preserves available timestamps and altitude.
Separate trips/devices stay apart. Gaps over 30 minutes or 10 km start new
segments; `--max-gap-minutes` and `--max-distance-km` adjust these limits.
Visits and activity endpoints stay isolated. Use `--force` to replace an existing
output. Coordinates are treated as WGS-84.

## Summarize countries

`gpx_countries.py` shows country/territory counts and recorded timestamps in UTC.

```sh
python3 gpx_countries.py history.gpx --summary
python3 gpx_countries.py history.gpx --timeline
python3 gpx_countries.py history.gpx --timeline --verbose
python3 gpx_countries.py history.gpx --timeline --explain
python3 gpx_countries.py history.gpx --timeline --no-singleton-denoise
python3 gpx_countries.py history.gpx --timeline --no-denoise
python3 gpx_countries.py history.gpx > var/visited_countries.md
```

The default `--summary` view has one row per country in alphabetical order.
`--timeline` sorts points by UTC timestamp and groups consecutive countries after
filtering. Returns start new rows. Retained untimed points appear at the end.
Recorded spans can include sampling gaps; they do not establish continuous stays.
Different countries at the same timestamp remain alternatives. The timeline flag
replaces `--chronological`.

The default footer shows input/kept/removed point counts, removal categories,
label counts by stage, disabled stages, and any conflicts in the displayed points.
When points are removed, a brief country/code table breaks their counts down by
motion exclusion, unassigned removal, and singleton filtering, with a total row.
Countries reflect labels at removal time; earlier label corrections are not
counted as removals. Duplicate records retain their weights.
Label counts can overlap; removal categories are disjoint. `--verbose` adds phase
results, settings, diagnostics before and after output filtering, and reference-map
details. Download attempts and optional reference failures are logged to stderr
only in verbose CLI runs. `--explain` lists individual decisions and timestamps of
country and movement conflicts remaining in the displayed points. The two flags can be combined.

## Denoising

Denoising changes the displayed analysis without writing GPX files. The pipeline
has six ordered phases:

| Phase | Work |
| --- | --- |
| Prepare | Normalize exact copies while retaining record counts; build chronological tracking epochs. |
| Screen | Exclude isolated motion outliers using bounded travel and a feasible bypass. |
| Map | Refine country labels with reference polygons; collect map-disagreement diagnostics. |
| Context | Infer visit/coastal labels from one frozen snapshot of map-backed evidence. |
| Diagnose | Record country and movement conflicts before output filtering. |
| Output | Remove unassigned points, then singleton excursions; review the remaining points before grouping. |

The master switch and each optional stage default to **on** in both views.
All controls are grouped under **Denoising** in `--help`.

| Disable flag | Effect |
| --- | --- |
| `--no-denoise` | Bypass the whole pipeline; restore raw records, order, and baseline labels. |
| `--no-motion-denoise` | Skip motion exclusion; other stages still use movement bounds. |
| `--no-border-denoise` | Skip reference-map refinement of named countries. |
| `--no-visit-denoise` | Skip single-epoch visit-context inference. |
| `--no-coastal-denoise` | Skip reference refinement and contextual inference for raw-unassigned points. |
| `--no-remove-unassigned` | Keep remaining unassigned points. |
| `--no-singleton-denoise` | Keep one-timestamp country excursions. |

Each flag has a positive form, such as `--motion-denoise`. Individual stage
switches apply while the master is enabled; they cannot override `--no-denoise`.
Normalization is part of the enabled pipeline. Disabling one stage does not
exempt a point from the others.

| Setting | Default |
| --- | --- |
| `--max-speed-kmh` | 1,000 km/h |
| `--position-allowance-meters` | 10,000 m per position; `--motion-slack-meters` is an alias. |
| `--max-gap-minutes` | 60 minutes between adjacent required observations. |
| `--gps-radius-meters` | Use the position allowance for context; an explicit value overrides visit/coastal context radii. |

These are configured assumptions, not measured GPS accuracy. A manual context
radius does not change motion bounds or direct map evidence. Zero position
allowance disables uncertainty-based visit smoothing; direct reference geometry
can still establish a country label.

Output filtering runs once, after inference. Unassigned removal uses the final
country label. Singleton filtering then removes one-timestamp `A → X → A`
excursions, including simultaneous alternatives, when neighboring epochs support
A. It preserves endpoints, untimed points, and consecutive multi-timestamp visits.
Retained unknowns are barriers; removing them can expose a singleton pattern.
Neither filter relabels points or reruns inference.

Singleton filtering is a presentation policy without a distance or elapsed-gap
limit. It can hide a sparse real visit. The converter keeps only the start of a
Google semantic visit, so zero GPX span does not establish zero source-visit
duration. Use `--no-singleton-denoise` to retain such observations.
See the [denoising audit](docs/denoising_audit.md) for exact rules, phase boundaries,
accounting, and test coverage.

## Boundary data

The first run downloads public [Natural Earth country boundaries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/)
to ignored `var/` storage beside the script. Cached maps work offline.
`--country-data countries.geojson` uses local boundaries without fetching
reference maps. Requests for public maps contain country codes, never GPX
coordinates or timestamps.

Natural Earth supplies baseline names and geometry. `10m` means a 1:10 million
map scale, not ten-metre accuracy. Unmatched points are unassigned; that label
does not prove offshore. Administrative polygons can include water, and the
analysis does not infer countries between recorded samples.

Reference polygons come from [geoBoundaries gbOpen](https://www.geoboundaries.org/api.html),
produced by William & Mary geoLab and contributing boundary providers, pinned to
commit `9469f09592ced973a3448cf66b6100b741b64c0d`. The collection is CC BY 4.0 compliant;
[country metadata](https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM0/)
identifies original sources and licenses. References are cached under
`var/coastlines/`. Map refinement preserves baseline labels when a required
reference is unavailable; `--verbose` reports the fallback and affected map names.

## Prune GPX points

`gpx_prune.py` previews selected original points and requires an interactive
terminal and explicit `yes` before writing a new file. Keep `gpx_countries.py`
beside it for the shared country/time summary. Pruner selection and preview use
original geometric assignments, independently of denoising.

```sh
python3 gpx_prune.py history.gpx --countries CA US --start 2026-01-01 --end 2026-01-31 --dry-run
python3 gpx_prune.py history.gpx --countries CA US --start 2026-01-01 --end 2026-01-31 -o cleaned.gpx
```

At least one of `--start`, `--end`, or `--countries` is required. Supplied filters
intersect: these examples select CA/US points within the time window. Country
names or ISO codes are accepted; quote names with spaces. Bounds are inclusive.
Date-only bounds cover whole UTC days; full timestamps require a timezone.
Untimed points never match a time filter.

`--dry-run` never prompts or writes. The default output is `INPUT_pruned.gpx`;
`-o` selects another new filename. Existing files are never overwritten, and the
input stays unchanged. Remaining tracks/routes are split at removed gaps.

## Local files and tests

Keep private exports, generated files, and map caches outside Git or under ignored
`var/` storage. Existing checkouts may use the project `var` link to reuse the
repository-root private data and caches. New checkouts create `var/` beside the
scripts. Input/output paths resolve from the current working directory.

Install pytest with `python3 -m pip install pytest`, then run
`python3 -m pytest -q` from the project or repository root. CI uses Python 3.9
and 3.13. The scripts remain usable when copied out of the repository.
