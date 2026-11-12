# Conversion architecture

The directly runnable `timeline_to_fog.py` script and installed entry points call
the same `boboji.cli.main`. The adapter reads UTF-8 JSON (including a BOM), validates
options, calls the core, and writes a completed GPX file atomically.

`src/boboji/timeline.py` works on decoded Python objects. It has no file access,
network calls, telemetry, background jobs, or third-party dependencies.
`src/boboji/gpx.py` serializes the resulting tracks with Python's XML library.
The CLI handles errors and reports counts; it does not implement a second parser.

## Normalization

Raw records use E7 coordinates, while phone exports can contain `geo:` strings,
degree-marked strings, or nested `latLng` objects. Coordinates must be finite and
within geographic bounds. Exactly +180 degrees longitude is represented as
-180 for GPX 1.1's exclusive upper bound. Altitude, when available, is in metres.

Milliseconds since the Unix epoch and ISO timestamps with explicit offsets
become UTC datetimes. Phone paths support absolute times and fractional minute
offsets relative to the containing segment. A present absolute time takes
precedence over the offset. Missing timestamps remain absent for path geometry;
raw GPS fixes require timestamps so they can be ordered. Offset times outside
the containing segment fail validation. The script never generates substitute
dates from the current clock.

Raw records are grouped by `deviceTag` and sorted by time. Semantic paths retain
their order, including independent `timelinePath` buckets. Legacy semantic
activities prefer nonempty `simplifiedRawPath.points`, falling back to
`waypointPath.waypoints`. Existing paths supply the geometry; start/end locations
are used only as isolated points when no path exists. Place visits are isolated.
Wi-Fi scans, activity telemetry, and `userLocationProfile` are not visited tracks.

## Segmentation and GPX

The core removes consecutive identical points and splits before a jump exceeding
the configured distance, a time gap exceeding the configured duration, or a
non-increasing timestamp between different fixes. Defaults are 10 km and
30 minutes. The distance limit cannot exceed the app's documented 10 km limit.
The great-circle calculation handles date-line crossings.

Each source path, device, and input file retains its own boundaries. Combining
multiple exports does not globally deduplicate overlapping history or infer a
route between them. Within a track, geometry follows the available recorded
samples; the converter does not map-match roads or reconstruct travel paths.

The serializer emits one GPX 1.1 `trk` containing independent `trkseg` elements.
Each segment holds `trkpt` elements, optional elevation, and optional UTC time.
Isolated points are repeated identically to represent a stationary track.
The reported recorded-point count excludes this serialization-only repetition.

## File safety

All supplied files must parse and validate before output is created. Missing
files, bad JSON/encoding, unsupported schemas, invalid locations, and empty
exports return code 2. Errors name fields rather than echoing private values.
Known non-positional metadata can be ignored; malformed positional data fails
the conversion rather than silently producing a partial history.

Output is written to a private temporary file in the destination directory.
Without `--force`, an atomic hard-link creation prevents accidental replacement;
with it, atomic replacement publishes the complete file. Both operations require
a local filesystem that supports them. A failure cleans up the temporary file.
The CLI rejects matching input/output paths, including existing hard links.

## Format references

- [Google Maps: export Timeline data on iPhone](https://support.google.com/maps/answer/6258979?co=GENIE.Platform%3DiOS&hl=en)
- [GPX 1.1 schema](https://www.topografix.com/GPX/1/1/)
- [Fog of World: GPX/KML support](https://fogofworld.app/en/)
- [Ollix: track import, 10 km limit, and GCJ-02 handling](https://medium.com/fogofworld/how-to-add-tracks-to-fog-of-world-manually-1541c6ae8d8d)

Google does not publish a stable schema for every Timeline JSON variant.
Supported structures are explicitly covered by synthetic regression fixtures.
Other export layouts need an explicit adapter rather than a recursive search
for arbitrary coordinate-like fields.
