# BoboWatch migration design

Status: completed on 2026-11-13 (America/Toronto). BoboTrail is the product
name and `projects/bobotrail/` is the directory for the former location-history
tools. The BoboWatch source repository is archived. The design below records
the accepted approach; final provenance and validation are in
[`migration.json`](migration.json).

## Executed result

- [Boboji import PR](https://github.com/lichen-liu/boboji/pull/22) was rebase-merged.
  All 22 source commits retain author identity/date and source trailers; every
  historical blob and file mode was reverified after merge. Original commit IDs
  and all 16 advertised source refs are retained in the compatibility archive
  and a restore-verified private bundle.
- The [adapter 0.3.0 release](https://github.com/lichen-liu/boboji/releases/tag/bobowatch-adapter/v0.3.0)
  passed isolated wheel install, sdist rebuild, and public download/hash checks.
  [Flightrepo](https://github.com/lichen-liu/flightrepo/pull/47) and
  [Trip Dollar](https://github.com/lichen-liu/trip_dollar/pull/16) now consume its
  hash-pinned package. Their CI derives the development-only collector fixture
  revision from the artifact, so there is no second manually maintained pin.
  Real old-wheel upgrades verify the handoff from embedded files to one adapter
  owner. The consumer application processes were not redeployed.
- Existing BoboWatch was deployed from Boboji, rolled back to the original
  revision, then restored to Boboji. Readiness, installed hashes, local/LAN URLs,
  RAM epoch/history, quota, private state hashes, and resumed producers passed
  over multiple reporting intervals. No RAM release or database relocation ran.
- CI retained its original trigger policy and required context. A deliberate
  failing project check blocked merging; final PR and post-merge checks passed.
  Live main/development rulesets still match the pre-migration audit.
- The source [migration notice](https://github.com/lichen-liu/bobowatch/pull/14)
  passed CI and merged. Flightrepo's old pin has the permanent
  `compat/flightrepo-6979491` tag, and fresh legacy builds passed before archival.
- BoboTrail: 1,063 tests; BoboWatch: 103 Python and 34 JavaScript tests plus
  Chromium/WebKit dashboard/chart suites. Both external consumers passed their
  final Python/browser/package CI. Detailed operational records and Git bundles
  stay under ignored `var/migrations/bobowatch-2026-11-13/`, outside Git.

BoboTrail's three scripts are byte-identical to the pre-rename versions. Its
ignored `var` symlink is still `../../var`, resolving to the same private data.
Flightrepo's real database remains in its original location; its full source
and data migration is separate from these adapter compatibility changes.


## Accepted design

Make Boboji the canonical monorepo for Boboji-owned projects. Keep each project
independently runnable and deployable under `projects/<name>/`. A shared source
repository does not require a shared application process, database, environment,
release version, or deployment schedule. Keep a separate repository when its
ownership, access, external users, or independent distribution justify it.

For BoboWatch, migrate the source and replay the 22 commits reachable from its
current `main` under `projects/bobowatch/`. Retain the original repository as a
read-only historical and compatibility archive after successful cutover. Do not
add BoboWatch as a Boboji submodule or maintain a bidirectional subtree sync.

Source consolidation and historical preservation are separate choices:

| Approach | History and workflow | Fit for this migration |
| --- | --- | --- |
| Git submodule | Separate repository and commits; parent records a pinned revision. Changes still need separate reviews and pointer updates. | Useful for an independently maintained dependency; retains the maintenance overhead we want to remove. |
| One source snapshot | One import commit; original history stays in an archived repository and backup. | Simplest fallback when historical import is expensive. Fully consolidates development, but loses old per-file history inside Boboji. |
| Linear history replay | Replays the source changes under a directory on top of Boboji. Preserves authorship, dates, and useful per-file history with new commit IDs. | Recommended: only 22 source commits, with no merges. |
| Merge unrelated histories / common subtree import | Can connect the old graph using merge commits. Prefix rewriting still changes IDs. | Conflicts with the existing linear development-branch policy. No ruleset exception is needed for the recommended approach. |

Do not promise original commit IDs or verified signatures in the replayed
history: changing paths and parents changes commit identities. Preserve exact
original objects in the source archive and a verified Git bundle. Preserve
source PR discussions at their original URLs; Git history does not migrate
GitHub issues, reviews, releases, settings, or secrets.

## Pre-migration audit

The pre-migration audit used local source plus GitHub metadata, not just the
READMEs. These snapshots describe the state before execution; the completed
record above supersedes repository and runtime state that changed during cutover.

| Item | Observed on 2026-11-13 |
| --- | --- |
| Boboji base | `74f99b2c13f0c1cb38035f9a989b5142f6908961` |
| BoboWatch source | `d66c9d311e40be80bc8c431c186cf7edd944ff2c` |
| BoboWatch main history | 22 commits, zero merge commits, 88 tracked files at the tip |
| Remote source branches / tags | Only `main`; no tags |
| Open source PRs / issues / releases | None |
| Source Actions secrets / variables / environments | None returned by the repository APIs |
| Source webhooks / deployment records | None returned by the repository APIs |
| Boboji Actions secrets / variables | None returned by the repository APIs |
| BoboWatch runtime | Python 3.11+, pinned `waitress==3.0.2`; no frontend build |
| BoboWatch CI | Python 3.11 and 3.14, Ruff 0.17.1, plain Node tests, Playwright 1.62.1 with Node 24 for browser checks |
| Installed BoboWatch receipt | Already records the source tip above; application snapshot is outside the checkout |
| Installed Flightrepo | Real mode; its configured database is still under the old checkout's `var/hosted/flights.db` |
| Flightrepo adapter dependency | Git submodule `vendor/bobowatch`, pinned to `6979491abfa1a794bf998d5d448226a92906c190` |
| Trip Dollar adapter dependency | Same submodule URL/path, pinned to `7a172411f3ec23fb27151724ca14236e8c999ee7`; that commit is reachable from source `main` |

Repository deployment metadata does not enumerate shell aliases, local jobs,
GitHub App installations, or external hosting integrations. Review those during
cutover. The source workflows contain checks, not production deployment jobs.
The installed macOS runtimes are the relevant deployment path for this pilot.

Flightrepo's pin is particularly important: it is retrievable from GitHub but
is **not an ancestor of today's BoboWatch `main`**, and no advertised branch or
tag currently retains it. Archiving the repo alone does not establish durable
reachability for that dependency. Add a compatibility tag to that exact source
commit before archival, and verify a fresh submodule checkout against it.
A tracked-source scan of the local repositories found Flightrepo and Trip Dollar
as consumers. Account-scoped connector code search returned no matches despite
these known integrations, so it is not evidence that no other consumers exist.

Local BoboWatch branches and a pre-GitHub history bundle also exist. Preserve and
review them separately; do not silently publish local-only work into Boboji.
The proposed replay covers public `main`, not every abandoned/local graph.
A historical filename inventory found no runtime/database/credential paths;
that is not a complete content-based secret scan.

## Directory and dependency boundaries

The final layout should preserve BoboWatch's working structure:

```text
boboji/
  README.md                         # project index and shared commands
  AGENTS.md                         # shared repository rules
  LICENSE
  .gitignore
  pytest.ini                        # explicit location-history test discovery
  .github/
    workflows/pytest.yml            # shared trigger and required check contract
    rulesets/                       # existing protection definitions
    repository-settings.json
  projects/
    bobotrail/               # existing Python 3.9+ tools
    bobowatch/
      AGENTS.md
      README.md
      pyproject.toml                # retain Python 3.11+ and project settings
      requirements-core.txt
      requirements-dev.txt
      .gitignore                    # project runtime/output exclusions
      bobowatch/                    # retain public Python import name
        migrations/
        web/
      installation/
      deployment/
      examples/
      tests/
        browser/                    # retain package.json and lockfile
      docs/
    flightrepo/                     # future migration; not part of this import
```

Do not rename BoboWatch's internal Python package, introduce a root Python
package or npm workspace, pool requirements into one environment, or reorganize
working runtime code just to make directories look uniform. Each project keeps
its own `.venv`, version constraints, tests, and documentation. The existing root
environment may still be used for location-history checks; it is not a source
artifact to migrate.

Keep the imported project `.gitignore`, including SQLite sidecars, private
tokens, local configuration, logs, and runtime folders. Root `var/` and project
`var/` remain ignored. Never copy a working directory wholesale: import tracked
Git content, not `.git`, virtualenvs, credentials, runtime snapshots, caches,
personal exports, or private databases. Preserve existing third-party notices.
BoboWatch currently has no separate license file; record its incorporation under
Boboji's MIT license with the owner's rights confirmed rather than claiming a
source license that does not exist.

Keep production adapter imports standard-library-only and free of import-time
threads. No shared `libs/` tree, package registry, task runner, or orchestration
framework is needed. The two existing external consumers do justify a small
versioned adapter distribution under this project; its proposed release path is
described below. That is a project deliverable, not a root tooling framework.

## History import and review

1. Freeze the source tip for the short cutover period. Refresh the source and
   target refs, inspect dirty worktrees and local-only branches, and recheck PRs,
   tags, consumers, and historical content. If `main` gains commits, update the
   manifest and rerun the rehearsal.
2. Create a full source backup outside tracked files, including all advertised
   refs and the exact Flightrepo pin. Verify it with `git bundle verify`, restore
   into an empty repository, and verify both commit IDs and file trees. A bundle
   made only from current `main` would miss the compatibility commit. Keep a
   durable copy outside the temporary rehearsal directory.
3. Create `codex/migrate-bobowatch` from the latest Boboji `main`. Confirm that
   the destination paths do not collide with the planning files already here.
   Keep those planning files as explicit migration additions.
4. Replay each source-main commit in order with `git format-patch --binary
   --full-index` and `git am --directory=projects/bobowatch`. Stop if source
   history is no longer linear; do not silently drop merge changes. No target
   history rewrite, force push to `main`, or protection bypass is needed.
5. Preserve author identity/date and message content, qualify old `#123` PR
   references as `lichen-liu/bobowatch#123`, and add `Source-Repository` and
   `Source-Commit` trailers to each replayed commit. These intentional message
   changes retain provenance without linking old PR numbers to Boboji PRs.
6. Verify every historical project's blob IDs and file modes against its source
   tree, accounting for the two pre-existing planning files. Then make one
   separate adaptation commit for CI, documentation, and installer boundary
   fixes. Keep that diff reviewable apart from the mechanical replay.
7. Add a public migration manifest recording source/target bases, source tree,
   imported scope, exclusions, and validation. Keep the original-to-replayed
   mapping in the rehearsal output. Reconstruct the final mapping from the
   source trailers after merge, because GitHub may recreate commit IDs.
8. Open a PR to `main`, push the final revision, then add a label to request CI.
   Keep it up to date with `main` and rerun label-triggered checks after any push
   or rebase. **Use rebase merge for this PR**; squash would discard the 22
   historical commits. Ordinary later PRs may continue to squash or rebase.

If replay fails, stop and abort it in the isolated migration checkout; keep the
source and existing main history intact. If a merged source import needs to be
withdrawn, use a normal revert/removal PR and restore the previous CI wiring.
Do not reset or force-push protected `main`. The installed snapshot can continue
running independently while a repository-level correction is reviewed.

The initial rehearsal used one full mailbox and preserved message text apart
from trailing blank lines. The production per-commit replay adds the provenance
trailers above; it must be revalidated after those additions. Historical commit
signatures remain verifiable in the original archive, not in the rewritten
copies. Use project-prefixed tags for future releases, for example
`bobowatch/v0.3.1`; do not move or reuse old release identities.

## CI design without changing the protection contract

Preserve the existing event policy exactly: PRs targeting `main` run on
`labeled`; pushes to `main` run automatically. Opening a PR or pushing to a
development branch must not quietly gain a new trigger. Preserve read-only
workflow permissions, no persisted checkout credentials, and current concurrency
behavior. Do not copy BoboWatch's rulesets or repository settings onto Boboji.

For the first migration, run the complete checks whenever CI is requested.
Two projects do not yet justify a changed-path dispatcher or a generic build
system. Keep the shared entry workflow under root `.github/workflows/`; nested
project `.github/workflows/` files are not active workflows. Remove the imported
project's obsolete `.github/` policy copy in the adaptation commit and update its
GitHub documentation to point at the root rules.

| Job | Scope | Runtime / commands |
| --- | --- | --- |
| Existing pytest matrix | BoboTrail | Retain Python 3.9 on Ubuntu 24.04 and Python 3.13 on the existing runner; root `python3 -m pytest -q` |
| BoboWatch Python matrix | BoboWatch | Python 3.11 and 3.14; install its dev requirements, run its Ruff lint/format checks and `python -Werror::ResourceWarning -m unittest discover -s tests -v` |
| BoboWatch plain JavaScript | BoboWatch | Explicit Node 24 setup; `node --test tests/test_*.cjs` |
| BoboWatch browser | BoboWatch | Python 3.14, Node 24, locked `npm ci`, Chromium and WebKit; existing fictional chart and full-dashboard harnesses |

Use `defaults.run.working-directory: projects/bobowatch` for BoboWatch jobs.
Action inputs remain repository-relative: update pip/npm cache dependency paths
explicitly to the project requirements and browser lockfile. Isolate caches by
project/runtime/lockfile and leave generated test output untracked.

Change root `pytest.ini` discovery from all of `projects/` to the explicit
`projects/bobotrail/tests` directory, keeping its current `pythonpath`.
The root pytest command will then continue to mean the location-history suite.
BoboWatch runs through its own native command; Python 3.9 must not accidentally
collect Python 3.11 syntax. Do not add every future project's source directory
to one global `PYTHONPATH`, which would create import and test-name collisions.
Document the per-project commands in the root index once there are two suites.

**A passing BoboWatch check must be part of the existing required gate.**
Leaving the old pytest job independent would allow a broken BoboWatch PR to
merge with green location-history tests. Retain the required status context
`pytest (Python 3.13)` and its GitHub Actions integration. Extend the existing
pytest matrix job to depend on the BoboWatch Python and browser jobs, use
`if: always()`, and explicitly fail if any dependency's result is not `success`
before running the location-history tests. Thus a failure, cancellation, or
unexpected skip becomes a failing required check instead of a green or skipped
gate. Python 3.9 also waits for those dependencies; that small extra wait avoids
a new aggregation framework. Include the plain Node tests in a dependency job.

Exercise this with an intentional failing BoboWatch check in the migration
branch before restoring it and requesting final CI. Verify the required check
fails, then label the final clean head and wait for all checks. Preserve the
existing main/development rulesets and repository settings byte-for-byte.

If CI cost later warrants routing, keep this stable required gate and filter
jobs inside the workflow. Do not path-filter the required workflow itself:
GitHub can leave a required check pending when the entire workflow is filtered
out. Routing must include shared CI/rules/config changes, removals, renames, and
the reverse dependency from BoboWatch adapter changes to future Flightrepo
packaging/integration checks. Treat unknown changes as a full run.

CI must use temporary fictional data. It must not deploy, mount production RAM
volumes, read production tokens/databases, register real producers, or start
login/boot services. Browser dependencies remain development-only.

## Installed BoboWatch deployment

Keep the existing private runtime at
`~/Library/Application Support/fyi.boboji.watch`, or the operator's existing
explicit runtime directory. Its `app/` snapshot, virtualenv, launchd job, logs,
configuration, tokens, registrations, and storage policy live outside the source
checkout. Launchd runs that installed snapshot, not the source tree. Changing the
Git checkout does not change the running service.

Most path handling is already project-relative: `deployment/deploy.py` and
`installation/install.py` use their parent directory; browser/test harnesses
locate the project from their own files. Preserve these relationships. Calling
`git rev-parse HEAD` from the nested project will correctly record Boboji's
commit, but augment the receipt with the source repository, project path, and
project tree ID so an operator can distinguish a BoboWatch build from unrelated
monorepo changes. Preserve the installed-file hashes and receipt verification.

One installer guard needs deliberate adaptation: `root.is_relative_to(repo)`
currently means outside the standalone source repo. After moving it, checking
only the project directory would permit a private installation elsewhere
inside Boboji. Resolve the containing Git worktree root and keep the installation
outside that whole worktree. Test nested paths and symlink resolution with
temporary fixtures. Do not expand this into an installer rewrite.

Update all source-checkout commands and canonical source links. After the
import has merged and its checks pass, the equivalent operator command is:

```sh
cd /Users/lichen/p/boboji/projects/bobowatch
./deployment/watch deploy
./deployment/watch check
./deployment/watch status
```

These are future cutover commands, not commands executed by this design task.
Use the same `--runtime-dir` or `BOBOWATCH_RUNTIME_DIR` selection as before.
Keep Python 3.11+, dependency pins, port, access policy, inventory identities,
wire protocol, schema migrations, RAM capacity, and lifecycle behavior unchanged
for this source-only move. Do not deploy from an unmerged/dirty checkout while
claiming a clean revision in the receipt.

Before the maintenance window, record the installed revision, runtime path,
schema, RAM ownership/epoch, oldest retained observation, quota and effective
configuration using private operator output. Verify a reinstallable previous
source revision and dependency availability. Do not export telemetry or secrets
into the PR or create durable RAM-history backups as an incidental migration
step: the installed history is deliberately RAM-only.

Then stop/install/start/check through the existing deploy command. Stop retains
the owned RAM volume. Do not release, reformat, resize, reboot, relocate the
runtime, or run a second instance. Producers can continue counting during the
short collector interruption; verify reporting resumes afterward. Confirm:

- The installation receipt identifies the intended Boboji project revision and
  its installed application/asset hashes validate.
- `/health`, `/ready`, authenticated storage checks, the local dashboard, and
  trusted-LAN access work. The current deploy command's storage check alone is
  not the complete acceptance checklist.
- RAM ownership and epoch are unchanged, retained history remains, and quota is
  applied. Do not require byte-for-byte database equality while live ingestion
  and normal retention continue.
- Existing inventory/replica IDs, credentials, access policy, endpoint, port, and
  producer counters remain consistent; no duplicate monitor is serving.
- The already installed Flightrepo sender resumes without an application
  redeployment; check Trip Dollar's sender as well if enabled. Do not restart
  consumer applications just because their monitor's source repository moved.

Keep an observed validation window covering multiple configured producer
intervals and a deliberate stop/start that retains the same epoch before
archiving. A source move is not a zero-downtime upgrade; RAM can still be lost
on reboot/power loss under the existing storage policy.

Rollback remains an explicit stop/reinstall/start/check from the recorded
previous BoboWatch source. Never release RAM as part of rollback. The installer
has no atomic release switch or automatic rollback; a failed install stays
stopped/incomplete until a successful reinstall. Keep this migration free of
schema changes so the old code remains compatible with surviving history. If
schema behavior changes anyway, reassess rollback before deployment rather than
assuming an old executable can read a newer database.

Do not add automatic production deployment on every monorepo merge. Releases
remain per project; unrelated location-history changes should restart nothing.
If deployment automation is introduced later, explicitly select the project,
revision, and private runtime, serialize by runtime, and validate the project
and its dependencies before invoking the existing deployment interface.

## Standalone consumers and adapter distribution

Both Flightrepo and Trip Dollar currently embed a selected standard-library
adapter into their application wheels from `vendor/bobowatch`. Trip Dollar uses
the WSGI adapter; Flightrepo uses ASGI. A source-only audit of Flightrepo would
miss an independently maintained consumer, so support for standalone projects
must be part of the migration rather than an assumed future monorepo import.

Preserve both current pins for historical builds. Current BoboWatch `main`
already retains Trip Dollar's pin. Flightrepo's otherwise unreferenced pin needs
the compatibility tag described above. Verify fresh legacy builds without local
Git object caches before archival. Neither consumer needs a production restart
for the collector's repository move.

For future updates to consumers that remain standalone, recommend a small
versioned **adapter wheel**, built from the canonical modules under
`projects/bobowatch/bobowatch/`. Keep its packaging script, module allowlist,
tests, and release instructions inside the BoboWatch project. Build in a
temporary staging directory; do not maintain a second source copy in Git.
The distribution should include both ASGI and WSGI plus their standard-library
dependencies, version/license metadata, and source provenance. It must not
include collector storage/dashboard code or require Waitress, a live monitor,
production registration, or frontend tools.

Publish the checked wheel as a project-prefixed, explicitly created Boboji
release asset. Consumers can pin its immutable URL/version and SHA-256 without
adding a registry or mirrored repository. Do not attach production publishing
to the existing test triggers. Record the source commit/project tree and check
the release artifact against the CI-tested build.

Migrate each standalone consumer through its own compatibility PR: replace the
submodule-based build input with the pinned adapter dependency, remove its
embedded adapter files and related Hatch/dev path settings, update installation
and CI commands, and verify its built application outside the checkout. Only one
distribution should own the `bobowatch` import namespace in a consumer virtualenv;
do not install the new wheel alongside an old app wheel that still embeds those
same files. Test monitoring enabled/disabled, both framework adapters, offline
registration, startup failure isolation, and clean install/upgrade behavior.
Keep server/adapters wire-compatible; upgrade the collector before any future
protocol increase.

The collector source move does not need to wait for both apps to deploy a new
dependency. Archival does need a documented choice for every maintained
standalone consumer: adopt the tested adapter artifact, join the monorepo, or
explicitly accept the supported frozen version. Keeping the old submodule pin
buildable must not be described as receiving future fixes. Do not archive with
an unacknowledged expectation of continued source updates in the old repo.

At audit time, BoboWatch had no complete adapter distribution configuration.
The implementation now builds it through `scripts/build_adapter.py` and verifies
it through `scripts/verify_adapter.py` in the shared required CI chain. The clean
virtualenv checks prove isolated imports, absence of collector dependencies and
import-time threads, and rebuildability from its standalone source archive.

## Flightrepo's later source and data migration

Flightrepo already packages a selected standard-library subset of
`vendor/bobowatch/bobowatch` into its wheel. Its installer runs `git submodule
update --init vendor/bobowatch`, its development import paths and Hatch
force-include entries refer to that directory, and its wheel probe verifies
adapter imports outside the checkout without loading Waitress or the monitor
database. Therefore changing only the submodule URL to Boboji would break the
expected directory layout.

For the collector's initial source move, leave Flightrepo's pin and installed
wheel alone. Before archival, publish a source tag such as
`compat/flightrepo-6979491` at the exact pinned commit, include it in the verified
backup, and prove a clean clone of Flightrepo can initialize the pin and
build/probe its wheel. Keep the old repository name and URL available.

When Flightrepo joins Boboji, remove its nested submodule and package the adapter
from the canonical sibling project as an explicit build input. Stage the needed
modules into a disposable build directory and include them in both relevant
distributions; do not maintain a second editable copy in Git. Update installer
submodule commands, Hatch/dev import settings, CI checkout options, dependency
provenance, and package verification together. Build and test the wheel outside
the source checkout, with monitoring both disabled and enabled and with its
expected protocol compatibility. A BoboWatch adapter change must trigger these
consumer checks. Moving projects into one repo does not remove this dependency.

If Flightrepo stays standalone or needs newer adapter fixes before its source
migration, use the adapter artifact and compatibility PR described above.

Flightrepo's data is a separate later cutover. The installed settings currently
record `/Users/lichen/p/flightrepo/var/hosted/flights.db` in **real** mode; this is
not a disposable demo database. Its installer requires the resolved database
to be under that project's resolved `var/`. Migrating its tracked source would
copy none of that ignored state and would change the new default data location.

Prefer a first code cutover that preserves the existing absolute data path:
create an ignored `projects/flightrepo/var` symlink to the existing `var`, validate
the resolved containment rule, and preserve the installed runtime settings.
This leaves the old directory as an explicit data dependency, so keep it until
a separate, verified storage relocation is complete. A durable long-term state
directory outside all checkouts is a reasonable later improvement, but requires
an intentional change to the current installer's containment policy.

Before either form of data cutover, inventory serving and ingestion databases,
WAL/SHM files, producer/publisher jobs, quotas, lock/authority identities, cache
paths, settings, and backup/restore procedures. Stop all affected writers for
the final consistent handoff, including independent ingestion/publish jobs;
stopping the web service alone is insufficient. Keep ingestion and serving
stores distinct, preserve real mode, validate schema/authority, counts and
actual route results, and check local and public serving after restart. Use
SQLite's backup API for a live snapshot; do not copy only a live `.db` file or
separate it from its journals. Test the restore and rollback on disposable
copies, retain the old data, and allow only the intended writer to resume.
Archiving a remote Git repository neither moves nor backs up local databases.

## Archival gates and sequencing

The implementation should start with one Boboji history/import PR. Follow it
with the adapter-distribution/consumer compatibility PRs needed for the selected
standalone projects and a controlled operator cutover. Add the source
compatibility tag and final deprecation README/description after selecting full
migration. Those are source metadata changes, not a new round of application
development there. Do not leave two active canonical repositories or set up
ongoing synchronization.

Archive `lichen-liu/bobowatch` only after all of the following are recorded:

- Full migration was selected; the replay/adaptation PR was rebase-merged and
  the expected 22 historical commits and provenance are present on `main`.
- The unchanged required check contract gates the project checks, all final
  checks pass on the current head, and branch protections remain intact.
- A fresh Boboji checkout runs BoboWatch without an old sibling checkout or
  submodule; the complete browser suite has passed as well as Python/Node.
- The installed service was cut over, verified over multiple producer
  intervals and a stop/start, and has a tested previous-revision rollback path.
- The Flightrepo compatibility tag exists, fresh legacy Flightrepo and Trip
  Dollar submodule builds succeed, and every maintained standalone consumer has
  a tested adapter artifact/update path or an explicit frozen-version decision.
- The full original Git backup, including the legacy pin and reviewed refs,
  was verified by restore and kept somewhere durable outside Git.
- Old README/description point to Boboji's project directory and explain the
  compatibility archive. Existing source URLs, issue/PR links, and retained
  commit/tag references remain available. Archival is not a repository redirect.
- Any new open work, settings, integrations, release assets, and notices have
  been accounted for; obsolete automation/integrations have been handled
  explicitly. Recheck these even though the initial API inventory was empty.

Then archive the original repository without deleting or renaming it. GitHub
archival makes code, branches, tags, PRs, issues, and other repository metadata
read-only; finish the tag and README changes first. Unarchive if recovery later
requires source metadata changes. Do not archive it for a submodule-only choice.

## Initial rehearsal before implementation

A disposable local checkout replayed the source on the audited Boboji base.
It did not alter either installed runtime, the source repository, remote refs,
CI settings, or database contents.

- All 22 imported commits were linear. Each imported historical project tree
  exactly matched its source tree, including file modes. Final source tree:
  `7db6bb518beca20c69cecd20757f9ce383f6c168`.
- Author names, emails, and dates survived the mailbox replay; messages matched
  after ignoring trailing blank lines. Original commit IDs necessarily changed.
- Existing Boboji tests: **1,063 passed**, from the repository root using its
  existing Python 3.14 environment and `python3 -m pytest -q`.
- Relocated BoboWatch tests: **102 Python tests passed** with ResourceWarnings
  treated as errors on Python 3.14; **34 plain Node tests passed** on Node 25.9.
  The two server tests required permission to bind disposable localhost ports.
- Playwright/browser tests were not run locally: the matching development
  library exists but the required browsers are not installed. Python 3.11,
  Node 24, and the proposed CI gating/installer adaptations remain to be checked
  by the implementation PR. No live RAM/launchd cutover was attempted.

Those initial results validated mechanical relocation. The subsequent
adaptation, CI, consumer, deployment, rollback, and archival gates are completed
and recorded above and in `migration.json`. Raw bundles, mailbox, commit maps,
and generated output remain outside Git under the private migration directory.

## References

- [BoboWatch audited source](https://github.com/lichen-liu/bobowatch/tree/d66c9d311e40be80bc8c431c186cf7edd944ff2c)
- [Flightrepo audited source](https://github.com/lichen-liu/flightrepo/tree/451d61918843466f612e5232139611ae8f0aaf19)
- [Trip Dollar audited source](https://github.com/lichen-liu/trip_dollar/tree/e5e14f81a219ae2d4c0606f2a5f8070a7f0cf190)
- [Git submodules](https://git-scm.com/docs/gitsubmodules),
  [patch export](https://git-scm.com/docs/git-format-patch),
  [patch application and path prefixing](https://git-scm.com/docs/git-am),
  [verified Git bundles](https://git-scm.com/docs/git-bundle)
- [GitHub workflow filters, dependencies, and job conditions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub PR merge methods](https://docs.github.com/en/pull-requests/reference/pull-request-merges)
- [GitHub repository archival](https://docs.github.com/en/repositories/archiving-a-github-repository/archiving-repositories)
- [SQLite online backup](https://www.sqlite.org/backup.html) and
  [unsafe file/journal handling](https://www.sqlite.org/howtocorrupt.html)
