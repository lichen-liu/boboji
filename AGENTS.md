# Repository rules

- Keep each project self-contained under `projects/<project_name>/`, with its
  code, tests, documentation, and project-specific `AGENTS.md` together.
- Keep the repository root for the project index and shared repository/CI rules.
- Prefer each project's existing runtime and simple commands; add shared tooling
  only when multiple projects actually need it.
- Run current tests from the repository root with `python3 -m pytest -q`.
- Keep personal exports, generated tracks, caches, and credentials out of Git.
- Follow Trip Dollar's GitHub preferences, not its application structure:
  use `codex/` branches, linear history, and PRs to `main`; add a PR label after
  the final push for CI, then squash/rebase merge after the required check passes.
- Preserve the existing GitHub branch protections and CI trigger rules.
