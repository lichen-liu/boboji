# Denoising audit — 2026-11-12

The previous algorithm failed the audit. It could discard ordinary driving
and relabel a genuine brief border visit. Its automatic “GPS radius” was not
an identifiable measurement-error estimate. The replacement deliberately
prioritizes preserving plausible movement over producing a tidy timeline.

Audited baseline: `fb9c05cbb5ef30b22c800c396e33b677fcadc225`.
Implementation: `gpx_countries.py`; independent synthetic movement tests:
`test_gpx_denoising.py`. No personal coordinates or exports are test fixtures.

## Findings and resolutions

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | Deviation from a time-interpolated straight line mixed actual turns, stops, detours, transport changes, GPS error, and map error. It could not estimate GPS accuracy. | Removed interpolation-residual fitting and the automatic border radius. |
| High | Locally fitted speed/scatter fences could reject a valid faster journey after a long quiet period. Unrelated tracks could train pooled limits. | Use an explicit, broad mixed-travel movement bound; unrelated journeys do not train it. |
| High | A short, sparse A → B → A sequence near a border was treated as evidence against visiting B. Ordinary border errands satisfy the same conditions. | Never rewrite a named country because of visit duration, sample count, or distance to A. Gross motion exclusions remain possible. |
| High | Invented straight-line bridges and successive reclassification made geography depend on hypothetical routes and earlier decisions. | Evaluate actual coordinates; optional inference uses immutable raw labels and a single pass. |
| Medium | Isolated visits, planned routes, duplicate endpoints, and GPX segments were treated like independent GPS evidence. | Motion uses only timed track points. Duplicate records do not vote. Segment boundaries constrain continuity, not source identity. |
| Medium | Unmatched points were labeled offshore without a water test. The basemap is generalized and lacks a territorial-sea model. | Display “Unassigned”; separate optional approximate mapping from motion errors. |
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

Defaults are **1,500 km/h**, **1,000 m allowance per position**, and a **30-minute
maximum gap**. The speed is a deliberately broad policy for ordinary mixed
travel including commercial flights, not a universal human or vehicle limit.
The allowance is a conservative screening margin, not a measured or learned
accuracy radius. The gap limits how much continuity we assume. These values
are explicit arguments, not thresholds fitted to the user's countries.
Lowering the speed bound asserts a narrower transport model and can reject
real faster travel.

For five chronological track observations `p0, p1, x, p3, p4`, exclude `x` only
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

Endpoints, fewer than five observations, long gaps, route points, waypoints,
untimed points, conflicting epochs, and distinct overlapping recordings are
retained when the necessary context is missing. Exact copies preserve GPX
counts without increasing evidence. Exact duplicate tracks are recognized;
partially overlapping tracks are conservatively left unresolved. Conflicts
are barriers, not opportunities to pick the majority.

### Optional: approximate coastal mapping

Without an explicit `--gps-radius-meters R`, no country tolerance is assumed.
This existing argument now means a **mapping tolerance**, not a GPS accuracy
estimate. It can infer a label for a retained, timed, raw-unassigned track
point only when:

- the same raw country brackets it in chronological tracking observations;
- no conflicting timestamp interrupts that country context; and
- that country is the sole polygon within `R` of the actual point.

It never rewrites an existing named country. It does not invent a route, infer
missing positions, use inferred labels as anchors, or require a visit to be
short or sparsely sampled. Geographic proximity does not depend on GPX segment
count or whether a coastal stay lasted overnight. Context can therefore span
logging breaks, but does not establish continuous presence.

A nearshore boat and a biased coastal hotel observation can be identical in
GPX. This option may give either an approximate country label; it does not
prove land presence or classify either as noise. Raw labels remain available
with `--no-denoise` and in explanations. The old `--gps-max-points` and
`--gps-max-minutes` options were removed along with their unsupported rules.

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
The complete suite passes **805 tests** locally on Python 3.9, 3.14, and 3.15;
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
coherent error bursts, isolated inferred Google visits, and persistent bias.
It may leave a fragmented timeline rather than erase a legitimate ferry or
brief visit. Correcting those cases reliably needs additional evidence, such
as source-specific accuracy/provenance, an appropriate road model with known
transport mode, better coastline geometry, or reviewed labels.

Neither the replacement nor the optional mapping tolerance establishes a
continuous stay, legal country presence, territorial waters, or a calibrated
probability. Timestamps, source identity, basemap quality, and the selected
movement bounds remain explicit assumptions. Unknowns are retained for review.
