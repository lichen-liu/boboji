# Denoising audit — 2026-11-12

The previous algorithm failed the audit. It could discard ordinary driving
and relabel a genuine brief border visit. Its automatic “GPS radius” was not
an identifiable measurement-error estimate. The replacement deliberately
prioritizes preserving plausible movement and resolving country-visit gaps
from independently checked map geometry. The initial audit revision left
coastal inference opt-in and consequently failed the default timeline use case.
The current revision enables reference-calibrated coastal handling by default.

Audited baseline: `fb9c05cbb5ef30b22c800c396e33b677fcadc225`.
Implementation: `gpx_countries.py`; independent synthetic movement tests:
`test_gpx_denoising.py`. No personal coordinates or exports are test fixtures.

## Findings and resolutions

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | Deviation from a time-interpolated straight line mixed actual turns, stops, detours, transport changes, GPS error, and map error. It could not estimate GPS accuracy. | Removed interpolation-residual fitting and the automatic border radius. |
| High | Locally fitted speed/scatter fences could reject a valid faster journey after a long quiet period. Unrelated tracks could train pooled limits. | Use an explicit, broad mixed-travel movement bound; unrelated journeys do not train it. |
| High | A short, sparse A → B → A sequence near a border was treated as evidence against visiting B. Ordinary border errands satisfy the same conditions. | Never rewrite a named country merely because of visit duration, sample count, or distance to A. Both reference maps must agree on a border correction; physical outliers can be excluded. |
| High | Invented straight-line bridges and successive reclassification made geography depend on hypothetical routes and earlier decisions. | Evaluate actual coordinates; country inference uses immutable raw labels and a single pass. |
| Medium | Isolated visits, planned routes, duplicate endpoints, and GPX segments were treated like independent GPS evidence. | Motion uses only timed track points. Duplicate records do not vote. Segment boundaries constrain continuity, not source identity. |
| Medium | Unmatched points were labeled offshore without a water test. The basemap is generalized and lacks a territorial-sea model. | Display “Unassigned”; separate approximate country-visit mapping from motion errors. |
| Medium | Output emphasized removed counts without explaining individual decisions or coverage. | Report the configured assumptions, checked fixes, conflicts, exclusions, and inferred labels; `--explain` lists every change. |

## Movement assumptions

Normal human travel includes stopping, reversing, following winding roads,
making a short return trip, changing transport, crossing a border briefly,
taking a ferry, and flying. Sparse observations need not fall on the route
between them. Frequent sampling does not establish a more likely country, and
repeated records are not independent observations.

Microsoft's [GeoLife research](https://www.microsoft.com/en-us/research/project/geolife-building-social-networks-using-human-location-history/)
explicitly describes transport changes within trips and speed variation with
traffic. This motivates a mixed-mode policy rather than assuming one local
speed distribution describes a whole export. We did **not** train or benchmark
against the GeoLife dataset.

[GPS.gov](https://www.gps.gov/gps-accuracy) distinguishes receiver error from
mapping error and describes environmental effects on accuracy. Its typical
open-sky smartphone accuracy is not a universal bound. GPX positions alone do
not identify which process generated a coastal offset.

The [GPX specification](https://www.topografix.com/GPX/1/1/) distinguishes
waypoints, routes, and recorded tracks; track segments describe continuity
breaks. Timestamps are optional. HDOP describes dilution of precision, not an
accuracy radius in metres. Ordinary GPX does not establish a device identity,
activity mode, original Google confidence, or calibrated measurement error.

Research such as [Newson and Krumm's map-matching work](https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/)
models measurement noise and an actual road network. We do not have a road
network or mode labels. Straight-line country interpolation cannot substitute
for that evidence.

## Replacement contract

### Default: conservative isolated motion screening

For elapsed time `dt > 0`, define a necessary reachability condition:

```text
great_circle_distance_km(p, q) <= max_speed_kmh * dt_seconds / 3600
                               + 2 * motion_slack_meters / 1000
```

The allowance appears twice because **both** positions may be uncertain.
This condition follows from a displacement bound and the triangle inequality;
it does not require straight travel, constant speed, a particular acceleration,
or a known transport mode. Distances use a spherical haversine approximation.

Current defaults, updated at the user's request, are **1,000 km/h**, **10 km
allowance per position**, and a **one-hour maximum gap**. These are configurable
travel-policy assumptions, not universal human or vehicle limits.
The allowance is a conservative screening margin, not a measured or learned
accuracy radius. The gap limits how much continuity we assume. These values
are explicit arguments, not thresholds fitted to the user's countries.
Lowering the speed bound asserts a narrower transport model and can reject
real faster travel.

Within a continuous track, for five chronological observations `p0, p1, x, p3, p4`, exclude `x` only
if **all** of the following hold:

1. They belong to the same continuous GPX segment with no intervening gap over
   the limit or conflicting timestamp group.
2. Neither overlapping distinct track chunks nor conflicting simultaneous
   positions require choosing which recording is true.
3. Both `p1 → x` and `x → p3` exceed the movement bound.
4. `p0 → p1`, `p1 → p3`, and `p3 → p4` pass the bound.

This supports an isolated bad observation better than a single large jump.
It still assumes chronological timestamps are meaningful and the surrounding
track belongs to one traveler. Passing the bound means “plausible,” not
“accurate.” Two-sided failure plus supporting context is evidence for an
isolated outlier, not proof of its physical cause. Exclusions are decided
against the original observations without iterative retraining.

An additional isolated-marker screen handles GPS records in their own segments.
A marker must have only one distinct timed fix in each of its source segments;
ordinary multi-point trips are not treated as isolated. Its nearest earlier and
later tracking epochs must have a feasible bypass, while every possible incoming
and outgoing leg to the marker fails the configured bound. Either a continuous
GPX track must connect the bracketing epochs or another adjacent epoch must
corroborate one side. Gaps to the marker and corroborating epochs cannot exceed
the maximum gap. All alternative surrounding positions must agree on feasible
movement; duplicate votes and majority country counts do not decide the result.

This cross-segment screen assumes one traveler's chronological history. A logger
segment is a continuity hint, not an independent person/device identity. It can
resolve a lone physically impossible conflict when continuous surrounding
tracking supports the bypass, while mutually incompatible anchor tracks remain
unresolved. Timestamp errors and inferred visit markers can cause the same
symptom as bad coordinates; the reason reported is a motion contradiction,
not a diagnosis of its sensor cause. No iterative deletion trains later limits.

Sparse unsupported cases, long gaps, route points, waypoints, and untimed records
remain when evidence is insufficient. Exact copies preserve counts without
adding support. `--no-denoise` preserves the complete raw analysis.

### Default: independently verified border-map correction

Preserving every named country left genuine basemap errors untouched. For a
raw return excursion A → B → A, B observations within 10 km of A's baseline
polygon can be checked against both countries' independent reference polygons.
Only **A includes the coordinate and B excludes it** permits relabeling to A.
Overlapping reference coverage, unavailable data, or a reference supporting B
preserves the original country. Neither short duration nor few samples decides
membership. Substantial legitimate trips and plausible brief border crossings
remain; the evidence can also describe real border-water activity.

The correction preserves the original raw label and records its reference-backed
label separately. Those independent map corrections can support coastal country
context, while guessed coastal labels cannot. `--no-border-denoise` disables
border-map correction. No country names or user-specific dates enter the rule.

### Default: reference-calibrated coastal visit continuity

A speed-outlier screen cannot resolve a coastline mismatch: a stationary hotel,
ordinary road, or boat can lie outside a generalized country polygon without
requiring impossible motion. Disabling coastal inference therefore did not
resolve the original fragmented timeline. The correction now uses an
independent source of geographic evidence rather than fitting road curvature.

1. Find timed, raw-unassigned tracking observations bracketed by the same evidence-backed
   named country. Only disagreement between **named country labels** breaks
   country context. Distinct coordinates at a timestamp remain a motion
   ambiguity, but can agree on country. Missing country labels are not evidence
   of a competing country.
2. Discover candidates within 10 km of that country's baseline polygon, with
   no second country within that neighborhood. This ceiling limits the scope
   of automatic mapping inference; it is not a GPS accuracy claim.
3. Load the country's pinned, cached independent
   [geoBoundaries gbOpen reference geometry](https://www.geoboundaries.org/api.html).
   This independent polygon identifies candidate locations covered by a second
   country boundary source. Administrative coverage is not necessarily land-only.
4. Compute the maximum baseline-polygon distance at those reference-covered
   locations, rounded up to a metre. This observed mapping disagreement supplies
   the observed **map** budget. The effective coastal band is the larger of
   this budget and the configured **position allowance**, capped at 10 km. If
   no location is reference-covered, the map budget is zero; only the declared
   position allowance can supply a band. Unverified offshore points and inferred
   labels never calibrate the map budget, and duplicates cannot enlarge it.
5. Assign the surrounding country only to actual points within that band and
   with no other baseline country within it. This coastal stage does not rewrite
   named countries; independent border-map correction is a separate stage.

This classifies approximate **country-visit context**, without changing or
removing coordinates. Some nearshore water excursions may join a country visit;
that is not a claim of continuous land presence or a measured GPS correction.
A substantial offshore excursion beyond the supported band remains unassigned.
The band depends on observed reference-map coverage and is not a calibrated
confidence interval. A country's maximum observed disagreement may be a broad
allowance for a more accurate part of its coastline; proximity, bracketing,
uniqueness, and the discovery ceiling constrain that inference.

The reference dataset is pinned to
`9469f09592ced973a3448cf66b6100b741b64c0d`, uses the smaller country polygons,
and caches downloads in ignored `var/coastlines/`. Country-code requests do not
include GPX coordinates or timestamps. Failed references leave unsupported gaps
visible. Custom `--country-data` stays offline. Collection and original-source
attribution links are in the README; boundary data is not committed to this repo.

`--no-coastal-denoise` disables this stage. `--gps-radius-meters R` supplies a
manual mapping band instead of coastal calibration and the position allowance.
The independent border stage can still load reference geometry. `--no-denoise` disables all analysis changes. The old
`--gps-max-points` and `--gps-max-minutes` remain removed: duration and sample
count alone do not establish country membership or sensor error.

## Geography and implementation checks

The pinned Natural Earth admin-0 layer supplies country polygons, not marine
jurisdiction. [Natural Earth documents generalized coastlines and known
accuracy limitations](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/).
Its `10m` means a 1:10 million map scale, not ten-metre accuracy. A smaller
glitch may be real receiver error, a missing island, a lake, or a map mismatch;
“Unassigned” alone cannot distinguish them.

Country lookup handles polygon holes and multipolygons using latitude-indexed
ray casting. Tests compare indexed results with independent rectangle
containment. Distance is to polygon edges, not country centroids; optional
tolerance requires checking **all** nearby countries. Distance uses a local
tangent approximation suitable for nearby borders, not survey accuracy or
large-distance geodesic buffering. Tests cover holes, latitude-band crossings,
high latitudes, and polygons split at the antimeridian. Custom GeoJSON must
split antimeridian-crossing polygons; this is not a general GIS engine.

Motion checks are independent of country names and basemap resolution. Reading,
canonicalizing, and sorting require memory proportional to the observations;
sorting and interval-overlap queries make motion screening O(N log N) overall,
without repeatedly fitting windows.
Optional polygon searches additionally depend on nearby geometry complexity.
No new runtime dependency, package structure, network upload, or GPX mutation
was introduced. The pruner still previews and selects original geometry;
denoised display labels never authorize deleting points.

## Validation and reproducibility

Run `python3 -m pytest -q`. The movement fixtures have independently generated
truth from forward geodesics. Noise is added afterward; generation does not
call the denoiser's distance, interpolation, or country rules.
The complete suite passes **861 tests** locally on Python 3.9, 3.14, and 3.15;
repository CI also requires Python 3.13.

| Synthetic experiment | Previous algorithm | Replacement |
| --- | --- | --- |
| 576 normal journeys, 46,656 genuine observations | 0 false exclusions | 0 false exclusions |
| Noise-free car pickup/return, about 5.5 km in five minutes each way | 1 genuine observation excluded | All 51 preserved |
| Noise-free winding road with a real three-point border visit | All 3 foreign-country labels lost | All 3 preserved |
| 72 journeys with one injected 1,000 km isolated jump each | All 72 errors excluded; all other observations preserved | All 72 errors excluded; all other observations preserved |

The broad normal set covers walking, running, cycling, driving, trains, and
flights; nominal speeds from 5 to 1,100 km/h; stops, turns and returns; 1/5/60/300
second cadences with jitter; three latitude bands and antimeridian crossings;
no noise, independent noise, correlated noise, and persistent bias. Seeds 11
and 97 generate the preservation set; seed 421 generates the injected-error
set. Simulation uses gradual speed/heading changes rather than instantaneous
vehicle stops or U-turns; flight traces represent airborne cruising. These
are test-generation settings, not a fitted transport classifier. No parameters
were fitted on these cases or the personal export. The two
counterexamples above demonstrate failures absent from the previous tests;
the broad normal set also fairly records where the old method already passed.

Additional tests cover transport changes, configurable speed/slack/gap bounds,
duplicate multiplicity, unrelated days, input order, simultaneous conflicts,
overlapping tracks, sparse context, error bursts, waypoint/track duplicates,
raw opt-out, optional coastal distance thresholds, ambiguous nearby countries,
long coastal stays, segment changes, and immutable raw country references.
Follow-up tests independently vary coarse and reference coastlines, preserve
unknowns beyond observed map disagreement, prevent unverified points from
training the band, handle same-time positions without inventing country
conflicts, verify download/cache failures, and exercise automatic handling via
the normal CLI without additional flags. Further tests cover mutually exclusive
border-map corrections, real brief crossings, missing/overlapping reference
coverage, cross-segment isolated markers, continuous bracketing tracks without
extra epochs, repeated markers, later genuine trips, competing trajectories, and
normal travel recorded as isolated segments. Calibration-only geometry cases
explicitly use zero position allowance to isolate the observed map budget.
Existing parsing, standalone execution, privacy, converter, and pruner checks
remain. Tests that demanded unsupported deletions/relabeling were replaced
with movement truth and explicit abstention cases.

These synthetic results verify specified behavior; they are **not** an
estimate of real-world precision or recall. The injected jumps are deliberately
gross, not a representative distribution of GPS failures. A read-only smoke
run on the local export checks execution and count conservation, not ground
truth, and is not used for tuning. No private data enters this report or CI.

## Remaining limits

The default screen will miss plausible-speed GPS drift, small border jitter,
coherent error bursts, unsupported inferred visits, and persistent bias.
Country inference can still leave gaps beyond its effective allowance; named
brief visits remain visible. Correcting those cases reliably needs additional evidence, such
as source-specific accuracy/provenance, an appropriate road model with known
transport mode, better coastline geometry, or reviewed labels.

Neither motion screening nor inferred country-visit context establishes a
continuous stay, legal country presence, territorial waters, or a calibrated
probability. Timestamps, source identity, basemap quality, and the selected
movement bounds remain explicit assumptions. Unknowns are retained for review.
