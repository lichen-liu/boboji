# Boboji

A monorepo for independently runnable projects. Each project keeps its code,
tests, and documentation together under `projects/`.

| Project | Purpose |
| --- | --- |
| [BoboTrail](projects/bobotrail/README.md) | Convert Google Maps Timeline to Fog of World GPX, inspect country timelines, and preview/confirm GPX pruning. |

From the repository root:

```sh
python3 projects/bobotrail/timeline_to_fog.py var/location-history.json -o var/history.gpx
python3 projects/bobotrail/gpx_countries.py var/history.gpx --timeline
python3 projects/bobotrail/gpx_prune.py var/history.gpx --countries CA --dry-run
```

BoboTrail uses Python 3.9+ and the standard library. Their
[project README](projects/bobotrail/README.md) documents usage and
[denoising audit](projects/bobotrail/docs/denoising_audit.md).

Run all current tests from the repository root:

```sh
python3 -m pip install pytest
python3 -m pytest -q
```

The root `pytest.ini` discovers tests under `projects/` and lists the current
Python project roots so scripts can be tested without installing packages.
Project-specific instructions live with their project; shared repository rules
are in [AGENTS.md](AGENTS.md). Add new projects as sibling directories when
needed. Private exports, generated outputs, and caches belong in ignored `var/`
folders. Existing repository-root `var/` inputs remain usable.

The proposed first external-repository migration is documented in the
[BoboWatch migration design](projects/bobowatch/docs/monorepo-migration.md).
It covers history, project boundaries, CI, installed runtimes, downstream
consumers, rollback, and the conditions for archiving the original repository.
BoboWatch has not yet been imported into this checkout.

GitHub follows `trip_dollar`: PRs to `main`, up-to-date branches, required
`pytest (Python 3.13)`, squash/rebase merges only, no bypasses, and no force
pushes or deletion of `main`. Development branches require linear history.
Add any PR label after the final push to request CI; pushes to `main` test
automatically. CI tests Python 3.9 and 3.13. Matching settings live under
`.github/`.
