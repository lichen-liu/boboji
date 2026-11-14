# Boboji

A monorepo for Boboji projects. Each project owns its code, tests, dependencies,
documentation, and deployment under `projects/` and runs independently.

| Project | Purpose | Runtime |
| --- | --- | --- |
| [BoboTrail](projects/bobotrail/README.md) | Convert Google Maps Timeline to Fog of World GPX, inspect country timelines, and preview/confirm GPX pruning. | Python 3.9+, standard library |
| [BoboWatch](projects/bobowatch/README.md) | Local monitoring, application adapters, and a trusted-LAN dashboard. | Python 3.11+, pinned Waitress |
| [Flyji / Flightrepo](projects/flightrepo/README.md) | Flight ingestion, explicit publication, route exploration, and local/public serving. | Python 3.11+, FastAPI, SQLite |

Run BoboTrail from the repository root:

```sh
python3 projects/bobotrail/timeline_to_fog.py var/location-history.json -o var/history.gpx
python3 projects/bobotrail/gpx_countries.py var/history.gpx --timeline
python3 projects/bobotrail/gpx_prune.py var/history.gpx --countries CA --dry-run
```

Start a fictional BoboWatch demo from its project directory:

```sh
cd projects/bobowatch
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-core.txt
.venv/bin/python -m bobowatch demo
```

Production installation and deployment remain explicit operator actions. See
[BoboWatch operations](projects/bobowatch/docs/runtime.md) and
[standalone adapter releases](projects/bobowatch/docs/adapter-release.md).
Changing one project does not deploy or restart another project.

Run BoboTrail tests from the repository root:

```sh
python3 -m pip install pytest
python3 -m pytest -q
```

The root `pytest.ini` explicitly discovers BoboTrail tests; it does not collect
newer Python syntax from other projects. Run BoboWatch's native checks from its
project directory:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -Werror::ResourceWarning -m unittest discover -s tests -v
node --test tests/test_*.cjs
.venv/bin/python scripts/build_adapter.py --output var/adapter
.venv/bin/python scripts/verify_adapter.py var/adapter/*.whl --sdist var/adapter/*.tar.gz
```

Its [browser suite](projects/bobowatch/tests/browser/README.md) uses isolated
fictional data. Keep separate project environments and dependency pins.

Shared rules live in [AGENTS.md](AGENTS.md) and the
[CI policy](.github/README.md). GitHub uses `codex/` branches, linear history,
PRs to `main`, up-to-date branches, and squash/rebase merges. Add any PR label
after the final push to request CI; pushes to `main` run automatically.
The required `pytest (Python 3.13)` check gates BoboTrail plus BoboWatch's
Python, JavaScript, adapter packaging, and browser checks, plus Flyji’s Python,
package, JavaScript, and browser checks. Existing protections
and trigger rules are preserved.

Project-specific instructions live beside their code. Private exports, generated
outputs, credentials, caches, migration backups, and databases stay outside Git
or in ignored `var/` storage. Existing root `var/` inputs remain usable, and
BoboTrail's existing private data link survives the product rename.

The [BoboWatch migration design](projects/bobowatch/docs/monorepo-migration.md)
and [provenance manifest](projects/bobowatch/docs/migration.json) record the source
history, compatibility dependencies, rollout, and archival gates. Flightrepo’s [migration record](projects/flightrepo/docs/migration.md) documents
its chronological import, production storage relocation, and recovery commands.

The [history record and commit map](.github/history/README.md) describe the
chronological reconstruction, retained release references, and commands for
updating older clones. Main has a single parent chain with no merge commits.
