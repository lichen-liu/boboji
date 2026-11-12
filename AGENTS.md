# Repository rules

- Keep tools as standalone snake_case Python scripts; use the standard library.
- Keep tests offline and use synthetic location data. Run `python3 -m pytest -q`.
- Keep personal exports, generated tracks, and credentials out of Git.
- Follow Trip Dollar's GitHub preferences, not its application structure:
  use `codex/` branches, linear history, and PRs to `main`; add a PR label after
  the final push for CI, then squash/rebase merge after the required check passes.
- Preserve the existing GitHub branch protections and CI trigger rules.
