# Flightrepo migration to Boboji

Flyji is maintained under `projects/flightrepo/`. Its Python distribution,
CLI names, FastAPI application, ingestion/publication separation, hostname,
and explicit deployment interface are retained. Project environments remain
separate from BoboWatch and BoboTrail.

## Source history

The [chronological map](../../../.github/history/flightrepo-2026-11-14.json)
interleaves all 41 public Flightrepo main commits, beginning October 9, with
the existing 49 Boboji commits. Both original author and committer headers are
preserved exactly. Ordering follows original committer time. Two neighboring
cross-project author dates overlap by a few minutes/seconds because the work
was authored in parallel and committed later; their original dates are retained.
Every historical Flightrepo subtree, blob, mode, and gitlink
matches the original source; existing Boboji component snapshots also match.
The shared parent chain is reconstructed and has no merge commits. Integration
changes are recorded at their actual new date, after those 90 source commits.

Previous Boboji main remains at
`archive/boboji-main-before-flightrepo-2026-11-14`. Earlier archive and adapter
release tags/assets remain unchanged. Full original refs, including unpublished
local branches and the open topic branch, were backed up privately and verified
by restoring both Git bundles. Private branches are not added to public main.
Source PR numbers are qualified with `lichen-liu/flightrepo` in imported messages.

Historical commits retain their original submodule pins. Build those standalone
versions from the original compatibility archives; nested historical gitlinks
are provenance, not an active monorepo submodule configuration. All three pins
are retained by the archived BoboWatch compatibility history/public PR refs.
Current code has no submodule or second editable BoboWatch source copy.

The previously open shutdown fix from
[Flightrepo #38](https://github.com/lichen-liu/flightrepo/pull/38) is ported as
integration work: stop waits for both launchd jobs to disappear before installing.
Its original topic object and discussion remain available. Existing open issues
are accounted for during archival and transferred to the canonical repository.

## Production state moved first

Private state is rooted at `boboji/var/flightrepo/`, outside tracked project code:

```text
var/flightrepo/
  hosted/flights.db                 # production serving facts
  ingestion/ingestion.db            # separate producer workspace and evidence
  ingestion/                       # associated locks, recovery state, caches
  ...                              # preserved existing private exports and outputs
projects/flightrepo/var -> ../../var/flightrepo
```

The former checkout's `var` is a compatibility symlink to that same directory.
Saved commands using the old path still resolve to the same files; new installed
settings and ingestion authority use the canonical absolute Boboji serving path.
The old source directory is no longer the storage owner. Do not delete the new
root `var/flightrepo/` when cleaning up a checkout.

Both production databases were backed up with SQLite's backup API. Each backup
was restored into a disposable file, with matching schema, every table count,
authority metadata and quotas, followed by a successful SQLite page check.
The serving snapshot contains 40,026,720 flight legs. The ingestion workspace
retains its separate candidate/evidence role and store generation.

The move stops Flyji, confirms ingestion is idle, and holds the ingestion job,
extraction, producer, and serving publication locks. A final comparison against
the backups precedes a same-filesystem rename of the whole state directory.
Database inodes are retained; live `.db`, WAL, and SHM files are not copied apart.
The runtime's `database_path` and the ingestion authority's `serving_path` are
updated together. Serving identity, ingestion store ID/generation, publication
ownership, schema, quotas, facts, credentials, port, and hostname stay intact.

Local and public acceptance checks use the same real direct flight before and
after the move. One attempted cutover automatically restored the original paths
when a public probe returned 403; the normal deployment request headers passed,
and the guarded move was retried. The verified backups remain in ignored
`var/migrations/flightrepo-2026-11-14/database-backups/` with private hashes and
restore records. Keep an independent durable copy; Git bundles do not contain
databases, caches, runtime settings, or tunnel credentials.

## Application and CI boundaries

Shared CI retains its label-triggered PR events, main push events, required
`pytest (Python 3.13)` context, and GitHub protection rules. The required matrix
waits for all four BoboWatch/Flyji job groups and fails if any fails, is cancelled,
or skips unexpectedly. It gates eight jobs: BoboTrail on Python 3.9/3.13,
BoboWatch Python 3.11/3.14 and browsers, and Flyji Python 3.13/3.14 and browsers.
Tests and browser demonstrations use fictional isolated data. No CI job deploys
production or opens production databases.

Flyji's installed adapter stays a separate, hash-pinned 0.3.1 release dependency.
This keeps the project independently installable and avoids duplicate package
ownership or a custom cross-project packaging hook. Monitoring tests use the
canonical sibling collector, so BoboWatch changes exercise the real consumer.
Update the adapter pin deliberately when its client API or protocol changes;
collector changes are tested against the maintained consumer pin on every CI run.
This supersedes the earlier proposal to embed adapter modules into Flyji wheels.

The existing installer now records repository, project path/tree, source commit,
and installed hashes and rejects private installations anywhere inside the
containing checkout. The private macOS runtime remains
`~/Library/Application Support/fyi.boboji.fly`. Its tunnel and monitoring settings
are reused. Only Flyji's explicit deploy command reinstalls/restarts Flyji;
unrelated monorepo changes restart no services.

An existing real-data restart probe attempted unrestricted route exploration and
timed out on the large archive. The migrated smoke checks request one admitted
direct itinerary and rebuild it. They still validate actual serving and routing;
interactive searches retain their existing limits and connection settings.

## Operator commands and recovery

From a clean, published Boboji checkout, ensure the project `var` alias points
to root `var/flightrepo/`, then:

```sh
cd projects/flightrepo
./deployment/flyji deploy
./deployment/flyji check
./deployment/flyji check --public
./deployment/flyji status
```

Use the existing absolute runtime path if selecting a custom runtime. Do not
initialize, reset, reseed, publish, or fetch providers as a source-migration step.
Old relative CLI commands continue through the compatibility link. Use the new
canonical paths for maintained ingestion jobs and future scheduled tasks.

For source rollback, stop both jobs and reinstall the recorded prior snapshot
while retaining the current canonical database configuration. A source rollback
does not require moving data back. Preserve the installer failure marker until
a complete installation succeeds. Keep the previous runtime/package snapshot
and exact dependency versions available until acceptance is complete.

For storage rollback, stop every affected writer and both app jobs, hold the
same producer/publication locks, change only the authority path back to its
previous location, restore the private settings, remove the legacy symlink,
and rename the whole state directory back. Preserve identities and sidecars;
do not recreate databases or copy only a live `.db`. Validate role, ownership,
counts, readiness, local/public routing, and monitoring before resuming writers.
If restoring a backup instead, restore both related stores and verify their
identity/generation/publication relationship before allowing publication.

The original repository is retained as a read-only compatibility archive after
source, CI, deployment, open work, and backup gates pass. Local source cleanup
must preserve the canonical private state and verified backups. For other
Boboji clones, follow the [history resync procedure](../../../.github/history/README.md).
