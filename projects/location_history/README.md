# Location history

Run the commands below from this project directory:

```sh
cd projects/location_history
```

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
python3 gpx_countries.py history.gpx --timeline --no-remove-unassigned
python3 gpx_countries.py history.gpx --timeline --no-denoise
python3 gpx_countries.py history.gpx > var/visited_countries.md
```

The default view and `--summary` show one row per country in alphabetical order.
`--timeline` sorts observations by UTC timestamp, then groups consecutive
countries into rows with begin, end, recorded span, and point count. Returns
start new rows: Canada → Peru → Canada produces three rows. A final
`--remove-unassigned` stage is enabled by default: remaining unresolved records
are removed **before** country grouping. `--no-remove-unassigned` keeps them
visible and lets them split periods. This is an explicit output policy, not a
claim that every unmatched point is noise. Untimed retained points are grouped
by country at the end.
Spans run from the first to last recorded point in each period and can include
sampling gaps. The timeline flag replaces `--chronological`.
Equal-time conflicts retain input order; rows do not resolve which position is true.

`--denoise` is enabled by default in both views. One policy object supplies
**1,000 km/h**, **10 km per-position allowance**, and a **60-minute maximum gap**.
Use `--max-speed-kmh`, `--position-allowance-meters` (legacy alias
`--motion-slack-meters`), and `--max-gap-minutes` to change them. A gap is between
adjacent required observations, not the total duration of a context window.
These are explicit policy assumptions, not measured GPS accuracy.

The standalone script applies these passes in order:

1. **Normalize:** exact duplicate fixes retain record counts but contribute one
   observation. Timed tracking records are grouped into chronological epochs.
   Denoised equal-time ordering is deterministic; raw mode preserves input order.
2. **Motion:** an isolated observation needs impossible incoming and outgoing
   legs, with every neighboring alternative supporting a feasible bypass. The
   maximum gap applies on both sides. Competing rejection proposals cannot
   delete each other's anchors. GPX segment IDs never determine eligibility.
3. **Map evidence:** refine a named coordinate only when its original country's
   reference excludes it, every nearby alternative reference is available, and
   exactly one includes it. For unassigned coordinates, exactly one fully
   checked reference must include the point; no source exclusion is needed. This coordinate-only pass also handles POIs and
   untimed points. Missing/overlapping evidence preserves the baseline label.
4. **Visit support:** freeze the map-adjudicated evidence. An isolated one-epoch
   country switch A → X → A can join A only with **two distinct confirming A
   epochs on each side**, bounded adjacent gaps, feasible movement, and every X
   position within A's polygon allowance. This same rule handles named and
   unassigned X. Multiple records at one timestamp do not confirm a visit.
   Conflicting epochs, missing intervening labels, weak anchors, deeper country
   observations, multi-epoch visits, and one-way transitions are preserved.
5. **Coastal context:** infer remaining unassigned track points bracketed by the
   same evidence-backed country only with unique nearby country geometry.
   Automatic context inference requires a reference and uses the configured
   position allowance, with discovery capped at 10 km. Direct reference
   coverage was already resolved before visit inference. Observed map disagreement is diagnostic only; a distant observation
   cannot enlarge another point's tolerance. Inferred labels never become
   anchors or calibration evidence in another pass.
6. **Remove unassigned:** remove every record whose final country is still
   unassigned, including timed/untimed tracks, routes, and POIs. Points resolved
   to a country by earlier passes are kept. This stage neither guesses a
   country nor reruns inference after removal.

Turns, stops, detours, changing transport, short visits, and water travel are
normal. The visit rule is an explicit uncertainty policy: a genuine one-sample
border visit inside the allowance is indistinguishable from a GPS blip and may
be smoothed. Coherent visits with multiple timestamps and deep-interior
singletons are preserved. The motion rule assumes one traveler's history;
competing trajectories remain unresolved. Planned routes and POIs are excluded
from motion and visit inference. Their coordinate-based map refinement remains
available.

`--gps-radius-meters N` overrides the radius for **both visit and coastal context**;
it does not change physical speed checks or independent map evidence. In manual
mode coastal inference uses exactly that radius. Increasing the position
allowance makes motion exclusion less aggressive and country-context inference
more permissive. Zero allowance disables uncertainty-based visit smoothing;
direct reference geometry can still establish country membership.

`--no-border-denoise` disables named-country map refinement. `--no-visit-denoise` disables the
single-epoch confirmation pass. `--no-coastal-denoise` disables both direct-reference refinement and contextual
inference for raw-unassigned coordinates. `--no-denoise` restores every original record
and baseline map label, including all unassigned records.
`--no-remove-unassigned` disables only the final removal stage. Custom `--country-data` stays offline and does not fetch
reference maps; an explicit manual radius remains available for local data.

The footer separates motion exclusions, map corrections, visit/coastal
inferences, and final unassigned removals. Corrections can overlap, but removal
counts are disjoint: represented + motion-excluded + unassigned-removed equals
input records. Diagnostics describe the evidence before the final removal step. `--explain` lists decisions and retained one-way movement
contradictions. Unresolved simultaneous countries are reported as alternatives;
row order at an identical timestamp does not establish travel. An impossible
one-way transition alone cannot identify which endpoint or timestamp is wrong.

All inference describes approximate recorded visit context. It establishes
neither land presence nor an immigration visit or a calibrated probability.
Reference administrative polygons can include water. See the
[denoising audit](docs/denoising_audit.md) for the contract, QA evidence, and limits.
The old short-run `--gps-max-points` / `--gps-max-minutes` rules remain removed.

Denoising changes only the displayed analysis; it never writes or modifies
GPX files. The pruner's selection and removal preview always use original
points and geometric country assignments.

The first run downloads public [Natural Earth country boundaries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/)
into the ignored `var/` folder beside the script; later runs work offline.
Use `--country-data countries.geojson` for an existing local copy. Coordinates
stay local. The table reflects recorded points, including transit; it does not
infer countries between samples. Unmatched points are counted separately; “Unassigned” does not prove offshore.
Baseline names and country geometry follow Natural Earth; reference adjudication
can refine the displayed geographic label.
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

In an existing checkout, private exports may still be in the repository-root
`var/` folder; the local project `var` link reuses those files and boundary caches.
New checkouts create an ignored `var/` directory beside these scripts. Input and
output arguments are always resolved from the current working directory.

All scripts support Python 3.9+. Tests: `python3 -m pip install pytest`, then
`python3 -m pytest -q`. CI tests Python 3.9 and 3.13.
