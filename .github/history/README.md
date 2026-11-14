# Repository history

On 2026-11-14, the owner requested a chronological, linear history with no
merge commits, accepting changed commit IDs. This replaces the initial
BoboWatch import, which had appended October work after November GPX work.

## Recorded reconstruction

The [commit map](2026-11-14.json) records 48 source commits and aliases from the
previously published import. BoboWatch's 22 public main commits run from
October 18–29, followed by Boboji's 22 original GPX commits from November 11–13,
then the rename, integration, migration record, and license-removal commits.
The record added by this reconstruction has its actual new timestamp.

Both original `author` and `committer` headers are preserved byte for byte,
including identity, epoch, and timezone. The resulting committer dates are
nondecreasing. Each commit has at most one parent. Source order is preserved;
parents joining the projects are reconstructed and do not describe original
cross-project ancestry. Directory relocation and new parents change commit IDs
and invalidate original signatures. Original signed objects remain in archives.
Source repository/commit trailers identify the original objects; BoboWatch PR
references are qualified with the original repository name.

Every historical BoboWatch subtree matches its original tree, including blob
IDs and file modes. Original GPX snapshots retain their files while carrying
the already existing BoboWatch subtree. Later integration snapshots retain
their full original trees. Before this audit record, the final tree is exactly
the previous main tree, `9bf1038e73d240506239ccd8990e48d180f0be04`.
The audit changes documentation and maps only. The MIT removal and project
versions remain in effect.

## Preserved references and production

`archive/boboji-main-before-chronology-2026-11-14` retains previous main
`386955abb98e8267a292a3c53ddcc29c44d87d2f` and its ancestors. The existing
`bobowatch-adapter/v0.3.0` and `bobowatch-adapter/v0.3.1` tags, release assets,
hashes, and embedded source revisions stay unchanged. Their original commit
IDs remain valid even though they are outside the reconstructed main line.
Consumers and installed receipts using those revisions remain resolvable.

The archived [BoboWatch repository](https://github.com/lichen-liu/bobowatch)
retains its original public objects and `compat/flightrepo-6979491`. Private
restore-verified bundles retain local-only history without publishing it.
The previous Boboji history bundle and operations record are in ignored
`var/history-rewrite/2026-11-14/`; keep an independent copy outside this checkout
before deleting it. A Git bundle does not back up ignored databases or exports.

This Git operation does not reinstall services or move state. BoboWatch's
installed runtime, producer endpoints, credentials, RAM history, and both
consumer applications continue using their existing configuration. Flightrepo's
real database remains in its original location. Release provenance continues
to identify the actual revision used to build each installed artifact.

## Validation and publication

Normal work follows the [shared CI policy](../README.md). This owner-requested
rewrite requires a one-time non-fast-forward update of `main`; a PR rebase would
replace the preserved committer dates, and a merge would violate the chosen
history shape. No routine force-push exception is introduced.

Publish the linear candidate under `codex/` first. Because its root differs
from old main, validate it through a separate PR based on old main, pinning
every checkout step to the exact candidate SHA. Request CI with a label after
the final push, using the existing workflow events and complete test matrix.
Close that validation PR without merging it. Temporary checkout overrides must
never enter main. Independently verify source metadata, historical trees,
chronological order, zero merges, final application files, and `git fsck`.

Only after those checks pass, retain the archive tag, recheck the expected old
main SHA, and use an explicit `--force-with-lease=refs/heads/main:<old-sha>`.
Any temporary administrator bypass must be restricted to this operation and
removed immediately in a `finally` cleanup. Compare both live rulesets and
repository merge settings with their pre-operation snapshots. Keep workflow
triggers and required status-check names unchanged. Verify automatic push CI
on the new main as well.

## Updating another checkout

First inspect `git status` and commit or stash work you want to retain. Back up
ignored personal files separately. Then, from a clean checkout on main:

```sh
git branch backup/main-before-chronology main
git fetch origin --tags
git switch main
git reset --hard origin/main
git log --reverse --format='%h %aI %cI %s' main
git rev-list --count --merges main
```

The final command must print `0`. Do not merge or pull the old main into the new
line. For unfinished branches, create a fresh `codex/` branch from new main and
cherry-pick only unpublished work, using the map to avoid duplicating imported
changes. Retain old backup branches until recovery is no longer needed. Reset
does not migrate ignored data, and there is no reason to run `git clean`.

## Later repository migrations

Keep each incoming project under `projects/<name>/` with its own commands and
deployments. Inventory public main history, outstanding work, immutable pins,
releases, integrations, and private state before importing. Back up and restore
the original refs, including dependency pins outside main. Keep private or
abandoned branches out of the public line unless separately reviewed.

Older incoming commits require another coordinated reconstruction to maintain
global chronology. Batch planned imports when practical to avoid repeatedly
changing consumers' commit references. Preserve source order and both timestamps;
if a source clock goes backward or a merge requires flattening, document and
resolve that case before publication. Do not silently invent dates or claim
that reconstructed parents are original ancestry.

Overlay each project's historical snapshot at its own path. Keep historical
submodule pins and compatibility archives buildable; mapping a pin to a newer
BoboWatch tree changes its meaning. A pin outside imported main, such as
Flightrepo's older pin, needs its own retained original object. At the actual
integration date, adapt maintained consumers to the canonical sibling project
or the versioned adapter artifact, and test installed packages outside the
checkout. Include dependent consumer checks when BoboWatch changes.

Database and service cutovers remain separate operations. For Flightrepo,
inventory the existing `var` paths and every writer, verify consistent backups
and restores, preserve real mode and the configured database path for the first
code cutover, then validate serving and ingestion before removing any old data
directory. Archiving a Git repository does not migrate its database.
