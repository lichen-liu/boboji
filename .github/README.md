# Shared CI and repository policy

Use `codex/` branches and PRs to `main`. Keep development history linear by
rebasing rather than merging `main` into a branch. Main requires an up-to-date
branch and the GitHub Actions check `pytest (Python 3.13)`; protections and
repository settings remain defined in this directory.

After the final push, add any PR label to request CI (`run-ci` by convention).
If the label already exists, remove and add it again. Opening a PR or pushing to
a development branch does not run CI. Rebase/push updates require another label.
Pushes to `main` run automatically. Do not add automatic production deployment.

The single entry workflow retains those trigger rules and runs:

- BoboTrail: the root pytest command on Python 3.9 and 3.13.
- BoboWatch: its native unittest, Ruff, JavaScript, and isolated adapter wheel
  and source-distribution checks on Python 3.11 and 3.14, using Node 24.
- BoboWatch browsers: fictional Chromium desktop and WebKit phone workflows.

The existing pytest matrix waits for the BoboWatch jobs and runs even if a
dependency fails. It explicitly fails unless both dependency jobs succeeded,
so BoboWatch failure, cancellation, or an unexpected skip cannot produce a
passing required check. Preserve this gate when adding projects.

All checks run when requested. Do not path-filter away a required workflow.
Any future job-level routing must include shared CI/config changes, removals,
renames, and consumer dependencies, and must retain a failing required gate
when an expected check does not pass. Keep test data synthetic and temporary.

Merge ordinary PRs with squash or rebase after all checks pass on the final,
up-to-date head. Do not force-push `main` or bypass protections in ordinary work.
The owner-requested chronological reconstruction is recorded with its one-time
publication procedure and commit map in [repository history](history/README.md).
GitHub rebase merges preserve author dates but replace committer dates, so they
must not be used to publish a reconstruction that promises both original dates.
