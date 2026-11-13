# Denoising audit and QA — 2026-11-13

The scripts use a standalone, standard-library pipeline. This document records
its phase boundaries, filtering rules, accounting, and validation. Rules contain
no country-specific exceptions; test fixtures use invented locations and dates.
Denoising leaves the input GPX and the pruner's original-point selection unchanged.

## Code structure

`DenoiseConfig` is the immutable configuration for one run. It contains stage
switches and the context-radius override, plus a nested `DenoisePolicy` for
movement bounds. The CLI builds it once and calls `run_denoising`.
`denoise_samples` retains its existing keyword interface as an adapter for
callers and tests.

`run_denoising` calls phase helpers in this order:

| Phase | Implementation | Boundary |
| --- | --- | --- |
| Prepare | `normalize_samples`, `tracking_epochs`, `create_denoise_report` | Establish canonical observations, weights, and tracking epochs. |
| Screen | `screen_motion` | Remove motion proposals against the prepared evidence. |
| Map | `refine_map_labels` | Adjudicate coordinates and collect geometry-offset diagnostics. |
| Context | `infer_country_labels` | Freeze map-backed labels once for both visit and coastal inference. |
| Diagnose | `diagnose_tracking`, `country_conflicts` | Measure conflicts before output filtering. |
| Output | `filter_analysis` | Remove unassigned points, then singleton excursions; measure the remaining conflicts. |

The report dictionary holds counts, diagnostics, and decision rows; formatting
functions read it without changing observations. Its existing keys remain
available to callers. The code stays in one copyable script using the standard
library.

Global raw mode returns every original record in original order, with baseline
map labels. It bypasses normalization and all later phases. Optional stage
switches apply only while denoising is enabled.

## Assumptions and sources

Human travel can stop, turn, reverse, change transport, briefly cross a border,
fly, or travel on water. Shape, duration, and sample density alone do not prove
GPS error. [Microsoft GeoLife research](https://www.microsoft.com/en-us/research/project/geolife-building-social-networks-using-human-location-history/)
describes mixed transport within trips and variable speed. Our synthetic
movement generator exercises those patterns; it is not trained on GeoLife.

[GPS.gov](https://www.gps.gov/gps-accuracy) distinguishes receiver uncertainty,
environmental effects, and mapping error. Trajectory curvature cannot identify
a device accuracy radius. [Map-matching research](https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/)
uses measurement models and actual road networks; this script has neither.
It does not fabricate a straight road between recorded positions.

The [GPX specification](https://www.topografix.com/GPX/1/1/) distinguishes recorded
tracks from routes and POIs. Segment boundaries express logging continuity,
not independently identified people or devices. Timed tracks are assumed to
represent one traveler's history. Route points, POIs, and untimed records retain
coordinate-based map classification but do not provide movement/visit evidence.
HDOP is not a metre-based accuracy radius.

Natural Earth's `10m` is a 1:10 million map scale.
[Its generalized coastlines have known accuracy limitations](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/).
Pinned [geoBoundaries gbOpen geometry](https://www.geoboundaries.org/api.html)
supplies reference polygons; collection and original-source attribution are in
the README. Reference coverage is not necessarily land-only or legally
authoritative, and two agreeing datasets do not establish calibrated certainty.
No GPS coordinates or timestamps are sent in reference download requests.

## Rule contract

`DenoisePolicy` defines speed 1,000 km/h, position allowance 10,000 metres, and
maximum adjacent gap 60 minutes. These are configurable user policy assumptions,
not universal physical limits or measured accuracy. A manual country radius
supersedes the positional radius for both contextual country passes only.

CLI switches, shared thresholds, `--verbose`, and `--explain` are grouped under
`Denoising` in `--help`. `--denoise` is the default-on master control. Its negative
form bypasses every stage and restores raw records/order, regardless of individual
stage enable switches or their position in the command. Optional stages have
separate default-on controls: `--motion-denoise`, `--border-denoise`,
`--visit-denoise`, `--coastal-denoise`, `--remove-unassigned`, and
`--singleton-denoise`; each accepts a `--no-...` form. Normalization belongs to the
enabled pipeline. Disabling one stage does not disable the others or exempt an observation from their rules.

### 1. Canonical observations and epochs

Exact duplicates of coordinate, timestamp, and tracking/nontracking type retain
multiplicity in output but contribute one observation. Different positions at
the same timestamp remain alternatives. Sequence identifiers do not vote.
Denoised observations and explanation rows have deterministic ordering; raw
opt-out preserves original input records and order.

### 2. Motion consistency

For positive elapsed time, a feasible displacement satisfies:

```text
distance_km <= speed_kmh * elapsed_seconds / 3600 + 2 * position_allowance_m / 1000
```

The factor two allows uncertainty at both endpoints. Haversine distances are a
spherical approximation. For a middle epoch with bounded adjacent gaps, propose
an observation for exclusion only if both legs are infeasible against every
neighboring alternative and all bypass alternatives are feasible. All proposals
use original evidence. If a proposed exclusion uses an adjacent epoch containing
another proposed exclusion, abstain for that proposal. This avoids circularly
rejecting mutually competing trajectories. Do not recompute proposals after
removal.

Sparse two-ended observations lack bracketing context and remain. Coherent bursts,
plausible-speed drift, long gaps, and unresolved competing alternatives may
remain. Changing GPX segmentation, source IDs, duplicate multiplicity, or input
ordering cannot change physical eligibility.

`--no-motion-denoise` skips motion-outlier exclusion and reports zero motion
checks/exclusions with the stage marked disabled. Shared physical bounds remain
active for country-context inference and unresolved-movement diagnostics. The
independent final unassigned-removal stage still applies unless disabled.

### 3. Coordinate-based map evidence

For a named baseline country near another polygon, its reference must exclude
the coordinate. Every nearby alternative reference must be available, and exactly
one must include the coordinate. Unassigned coordinates need unique complete
reference coverage without source exclusion. These direct geographic labels
are resolved before freezing evidence, including unknowns supplying confirming
visit anchors. Otherwise retain the baseline label. This rule
applies identically to timed tracks, POIs/routes, and untimed coordinates. It
does not depend on visit duration, row order, or a return trip. Preserve original
and reference-backed labels separately. Missing sources are reported.

### 4. Temporal visit support

Freeze all post-map labels before generating proposals. For five consecutive
epochs `A, A, X, A, A`, infer A for X only if:

- X has one timestamp and one unambiguous label; X can be named or unassigned.
- All four anchor epochs unambiguously support the same named country A.
- Every required adjacent gap is within the configured limit; every positional
  alternative supports feasible movement, including the bypass.
- All X positions are within A's polygon allowance. The manual country radius,
  if supplied, takes precedence over the default positional allowance.

Apply proposals simultaneously. Do not use inferred labels to create further
support. Missing/intervening unknown epochs, conflicting labels, alternating
singletons, weak anchors, and one-way transitions cause conservative abstention.
The gap applies between adjacent required observations; a five-epoch context can
span several gaps and is not restricted to one hour in total.

A real one-observation near-border visit is observationally indistinguishable
from a blip under this allowance. The explicit display policy favors continuity
in that case. Genuine multi-epoch brief visits and observations outside the
allowance survive this inference rule. `--no-visit-denoise` disables the rule;
`--no-denoise` restores the original records. The independent final singleton
policy can still filter a one-timestamp excursion without relabeling it.

### 5. Coastal context

Use the same frozen map-backed labels, never visit guesses. Remaining unassigned
timed track points need matching country context on both sides and unique nearby
geometry. Automatic discovery is limited to 10 km and requires an available
reference. Contextual guesses use only the declared per-point allowance; direct
reference coverage was already adjudicated in the geometry stage. Observed
offsets are reported but do not extrapolate a tolerance to other observations. A manual country radius uses the
supplied distance instead of reference coverage and automatic allowance.

`--no-coastal-denoise` prevents both raw-unassigned reference refinement and
contextual inference in every pass. `--no-border-denoise` controls named-country
geometry refinement.
Increasing positional allowance permits more movement and more country-context
inference; it is not a single monotonic noise-removal aggressiveness setting.

### 6. Explicit final unassigned removal

`--remove-unassigned` is enabled by default after inference and diagnostics,
before singleton filtering and summary/timeline grouping. It removes records
whose **final** country is `None`, including untimed/nontracking observations and
weighted copies. Raw-unassigned records resolved to a named country survive.
This is an output policy; it does not change the GPX or classify discarded
positions as GPS errors.

`--no-remove-unassigned` retains unresolved observations. Global `--no-denoise`
bypasses every pass, including removal, and restores raw records/order. Earlier
stage opt-outs do not disable this independent final policy. Motion exclusions
and unassigned removals are disjoint. All-removed input is a successful empty
analysis. Pre-filter diagnostics retain their original evidence. A final review
also measures conflicts among the displayed points; neither review changes
labels or reruns inference. Grouping retained points can join the same country
across removed gaps, so recorded spans can include unobserved intervals.

### 7. Explicit singleton-excursion filtering

`--singleton-denoise` is a default-on presentation policy with an independent
`--no-singleton-denoise` opt-out. It applies in both views to all timed records,
including routes and POIs. Freeze the view remaining after the configured
unassigned-removal stage. This declared order means removing unknowns can expose
an A → X → A pattern; retained unknowns are barriers. No inference runs after
either output filter.

Group observations into chronological epochs before evaluating context. At an
interior epoch, the previous and next distinct timestamps must each have
exactly one label, the same named country A. The middle epoch must contain no
unassigned labels. Propose every middle-epoch named alternative X other than A,
including simultaneous `{A, X}` or `{A, X, Y}` cases. X cannot continue into
either neighboring epoch. Multiplicity and XML ordering never add timestamp
support or decide which simultaneous alternative comes first.

Generate all proposals against that frozen snapshot. Abstain when either
supporting neighbor epoch is itself proposed for removal. This preserves
competing A → B → A → B → A proposals; independent A → X → A → Y → A proposals
can be applied together when their anchors are not proposed. Do not iterate the
filter, relabel removed points, or use removals to manufacture further support.
First/last timestamps, untimed points, adjacent multi-timestamp country visits,
ambiguous neighboring epochs, and retained unassigned barriers survive.

This stage intentionally has no physical gap, speed, or polygon-distance gate.
One timestamp alone cannot establish actual visit duration, and a sparse real
visit can be filtered even across multi-day gaps. The converter emits only the
start of a semantic Google visit and duplicates isolated points for Fog of
World; a zero GPX span can therefore represent a nonzero source visit interval.
This policy controls presentation and does not diagnose GPS error.

Report removed GPX multiplicities and distinct country/timestamp excursions
separately. Removal sets are disjoint: represented + motion-excluded +
unassigned-removed + singleton-removed equals input count. Map/inference counters
describe earlier processing and may include subsequently removed points.
Explanations preserve raw labels and identify the final removed country and
surrounding context, including map-refined points.

## Reports and diagnostics

The default footer contains input, kept, and removed point totals; disjoint
removal counts; label counts per stage; any disabled stages; and conflicts in the
remaining displayed points. Zero unassigned/untimed counts and unrelated detail
are omitted from the country-view summary. Recorded-span notes remain short.

`--verbose` adds a phase table, configured movement/context bounds, tracking
statistics, diagnostics before and after output filters, unavailable reference
names, and per-country geometry details. Map offsets describe disagreement
between datasets; they do not fit a GPS error distribution or enlarge another
observation's radius. Label counts can overlap and include later-removed points.
Only the removal counts form disjoint categories.

Country conflicts count timed epochs containing more than one country label,
including retained `None` alternatives and all point types. The report stores
`before_output_country_epochs` before filtering and `remaining_country_epochs`
after filtering. The older `unresolved_country_epochs` key remains a tracking-only
pre-filter count for callers. `remaining_country_alternatives` stores the final
conflict timestamps and labels. Movement diagnostics use timed tracking epochs
within the configured adjacent-gap limit. A transition is conflicting when no
pair of alternatives supports feasible movement.
`unresolved_motion` describes pre-filter tracking; `remaining_motion` describes
the points left after filtering. Review only records contradictions; it does not
remove observations or identify a wrong endpoint.

`--explain` prints individual decisions, preserving raw labels and final-stage
reasons. It also prints simultaneous country alternatives and movement-conflict
timestamp pairs from the displayed points. It can be combined with `--verbose`.
Neither option changes filtering.

Boundary loaders use the standard-library logger for download attempts and
optional-reference failures at INFO level. The CLI enables those messages on
stderr with `--verbose`; normal runs are quiet. Missing optional reference maps
leave unsupported map refinements unchanged, and verbose output lists affected
countries. Public requests contain no user coordinates or timestamps. A missing
required baseline map still produces an error if its download fails.

## QA evidence

Tests use invented geometry and independently generated movement; no personal
export is a fixture. The movement generator uses forward geodesics, gradual
speed/heading changes, stops, turns, returns, irregular sampling, independent
noise, correlated noise, and bias. It does not call the classifier's inverse
distance or map functions. The existing 576 journeys/46,656 observations and 72
injected gross-jump cases remain useful bounded-motion checks, not real-world
precision/recall estimates.

Independent review added 72 property, adversarial, and control-matrix cases,
including all 32 combinations of stage switches and manual-radius controls.
Checks cover:

- Segment splits/merges, source-ID renaming, full and partial exact copies.
- Input and equal-time permutations, including explanation multiplicities.
- Post-map singleton formation, duplicate singletons, raw/named symmetry,
  genuine multi-epoch brief visits, and distant one-point visits.
- Overlapping/missing reference maps; consistent geometry across record types.
- Exact allowance/gap boundaries, zero radius, adjacent versus total horizon,
  manual override precedence, and domain/stage opt-outs.
- Unrelated later observations that cannot enlarge local coastal inference.
- Alternating trajectory conflicts, uncertain epochs, and no cascading anchors.
- CLI behavior, count conservation, raw restoration, offline caches/fallback,
  standalone copying, converter behavior, and original-data pruner previews.
- Singleton policy controls, all timed point types, endpoint/untimed protection,
  equal-time alternatives, duplicate/source-ID invariance, multi-epoch visits,
  competing proposals, declared unassigned-filter order, long-gap behavior,
  raw-label provenance, and disjoint removal accounting across all stages.

Full local-export acceptance additionally checks both reported singleton
regressions after map adjudication, the earlier impossible isolated marker,
genuine multi-day trips, a supported multi-epoch border crossing, coastal
continuity, represented-plus-motion-excluded-plus-unassigned-removed-plus-singleton-removed
count conservation, and input SHA-256.
Private dates, coordinates, and export hashes are intentionally excluded here.
The full output is checked for unresolved anomalies as well as corrected cases.

Run `python3 -m pytest -q`. Required CI uses Python 3.9 and 3.13; local verification
also exercises Python 3.14 and 3.15. Cached real-file QA blocks network access and
checks safe fallback for unavailable references. Synthetic results validate this
contract; they do not prove every real country observation correct.

## Remaining limits and diagnostics

A one-way impossible transition cannot identify which endpoint or timestamp is
wrong. Final unresolved transitions are reported for review. Simultaneous country
labels remain alternatives, and the timeline notes that their row order does not
establish travel.
Low-speed drift, coherent error bursts, systematic bias, missing reference detail,
and genuine one-sample border visits remain fundamentally ambiguous. Context
inference may group nearshore water travel with the surrounding country visit.

Recorded country labels do not establish continuous presence, immigration entry,
or a calibrated probability. Raw mode remains available, and no denoising pass
writes or prunes the input GPX.
