# Denoising audit and QA — 2026-11-12

The prior implementation failed consistency checks. The replacement is a
standalone, standard-library rule pipeline with a single immutable policy,
canonical observations, explicit evidence, and decisions made before mutation.
There are no country-specific names, private dates, or user coordinates in the
rules or tests. The input GPX and pruner's raw selection remain unchanged.

## Findings corrected

| Finding | Correction and regression coverage |
| --- | --- |
| Maps were treated as evidence that a visit occurred. A coordinate inside a country can still be one uncertain observation. | Separate geometry adjudication from temporal visit confirmation. A one-epoch return excursion within the declared allowance needs corroborated surrounding context; duplicate records do not confirm a visit. |
| Motion eligibility depended on segment length and singleton membership. Splitting or merging identical logs changed results. | One chronological-epoch motion rule for all timed tracking points. Source IDs cannot determine eligibility. |
| Partially copied tracks prevented exclusions, although full duplicates did not. | Canonicalize coordinate/time/type evidence once. No overlap interval voting or copied-path veto. |
| Equal-time input order changed map correction through invented return runs. | Coordinate-only geometry adjudication; deterministic canonical order and explicit epoch conflicts. |
| Alternating plausible trajectories could each nominate the other's observations as spikes. | Simultaneous proposal-conflict guard: a rejection cannot use another proposed rejection as its anchor. |
| Country-wide maxima learned from GPX locations expanded unrelated coastal tolerances. | Reference coverage is per-point evidence. Observed map offsets are diagnostic; unverified points use only the declared allowance. |
| A manual radius or coastal opt-out could be bypassed by an earlier context pass. | One country-radius precedence rule for visits/coasts; coastal opt-out excludes raw-unassigned inference across passes. |
| Inferred labels could manufacture later support; actual user failures became singleton epochs only after map corrections. | Freeze post-map evidence before contextual passes. Never use guessed visits/coasts as anchors. |
| Same-time explanation rows could change order because rejection sets were unordered. | Stable decision ordering includes timestamp, labels, reason, and multiplicity. |
| Success reports hid unresolved contradictions and focused on test counts. | Full-file acceptance includes specific regressions, preserved visits, count conservation, input hash, unresolved simultaneous countries, and one-way movement contradictions. |

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
rejecting mutually competing trajectories. Never retrain after removal.

Sparse two-ended observations lack bracketing context and remain. Coherent bursts,
plausible-speed drift, long gaps, and unresolved competing alternatives may
remain. Changing GPX segmentation, source IDs, duplicate multiplicity, or input
ordering cannot change physical eligibility.

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
in that case. It does not diagnose GPS error or disprove a real visit. Genuine
multi-epoch brief visits and observations outside the allowance remain visible.
`--no-visit-denoise` and `--no-denoise` expose the underlying evidence.

### 5. Coastal context

Use the same frozen map-backed labels, never visit guesses. Remaining unassigned
timed track points need matching country context on both sides and unique nearby
geometry. Automatic discovery is limited to 10 km and requires an available
reference. Contextual guesses use only the declared per-point allowance; direct
reference coverage was already adjudicated in the geometry stage. Observed offsets are reported but do not
extrapolate a tolerance to other observations. A manual country radius uses the
supplied distance instead of reference coverage and automatic allowance.

`--no-coastal-denoise` prevents both raw-unassigned reference refinement and
contextual inference in every pass. `--no-border-denoise` controls named-country geometry refinement.
Increasing positional allowance permits more movement and more country-context
inference; it is not a single monotonic noise-removal aggressiveness setting.

### 6. Explicit final unassigned removal

`--remove-unassigned` is enabled by default after inference and diagnostics,
before summary/timeline grouping. It removes only records whose **final**
country is `None`, including untimed/nontracking observations and weighted
copies. Raw-unassigned records resolved to a named country survive. This is an
explicit presentation policy and never declares the discarded positions to be
GPS errors or changes the input GPX.

`--no-remove-unassigned` retains unresolved observations. Global `--no-denoise`
bypasses every pass, including removal, and restores raw records/order. Earlier
stage opt-outs do not disable this independent final policy. Motion exclusions
and unassigned removals are disjoint; represented + motion-excluded +
unassigned-removed equals input count. All-removed input is a successful empty
analysis. Diagnostics remain based on evidence before removal; no inference is
rerun and no new anchors are manufactured. Grouping the retained points can
join the same country across removed gaps; recorded spans still do not imply
continuous presence.

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

Full local-export acceptance additionally checks both reported singleton
regressions after map adjudication, the earlier impossible isolated marker,
genuine multi-day trips, a supported multi-epoch border crossing, coastal
continuity, represented-plus-motion-excluded-plus-unassigned-removed count conservation, and input SHA-256.
Private dates, coordinates, and export hashes are intentionally excluded here.
The full output is checked for unresolved anomalies as well as corrected cases.

Run `python3 -m pytest -q`. Required CI uses Python 3.9 and3.13; local verification
also exercises Python 3.14 and3.15. Cached real-file QA blocks network access and
checks safe fallback for unavailable references. Synthetic results validate this
contract; they do not prove every real country observation correct.

## Remaining limits and diagnostics

A one-way impossible transition cannot identify which endpoint or timestamp is
wrong; it is reported for review. Simultaneous different countries are unresolved
alternatives, not a proven travel sequence, and output warns about tie ordering.
Low-speed drift, coherent error bursts, systematic bias, missing reference detail,
and genuine one-sample border visits remain fundamentally ambiguous. Context
inference may group nearshore water travel with the surrounding country visit.

No rule establishes continuous presence, immigration entry, territorial waters,
or a calibrated probability. `--explain` exposes each decision and retained
movement contradiction. Raw mode remains available, and no denoising pass writes
or prunes the input GPX.
