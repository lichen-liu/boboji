# Location history project rules

- Keep tools as standalone snake_case Python 3.9+ scripts using the standard
  library. `gpx_prune.py` shares `gpx_countries.py` from this directory.
- Keep tests under `tests/`, offline, and based on synthetic location data.
  Run `python3 -m pytest -q` from the repository root or this project directory.
- Keep documentation here and detailed audits under `docs/`.
- Keep private exports, generated tracks, and downloaded boundaries in ignored
  `var/` storage. Preserve users' existing input files and cached boundaries.
- Test direct CLI execution and copied-alone behavior when changing imports or
  runtime paths. Denoising changes analysis only; pruning requires confirmation.
