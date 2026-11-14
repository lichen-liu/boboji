# BoboWatch project rules

- See `docs/monorepo-migration.md` and `docs/migration.json` for source provenance
  and the rollout gates. The former standalone repository is a compatibility archive.
- Keep code, tests, examples, installation, deployment, and documentation
  here. Retain the `bobowatch` Python import name and Python 3.11+ requirement.
- Preserve the existing unittest, plain Node, and fictional Playwright checks.
  Keep project environments and dependencies separate from other projects.
- Installation and deployment remain explicit operator actions. Preserve the
  private runtime path, credentials, inventory, RAM volume ownership, history
  epoch, quota, and on-demand lifecycle during a source-repository migration.
- Use temporary fictional runtimes for tests. Do not run tests against installed
  runtimes or commit databases, credentials, logs, exports, or migration bundles.
- Shared GitHub policy belongs at the repository root. Do not activate a second
  copy of the old repository's settings or change branch protections or triggers
  as part of the migration.
- Build the standard-library adapter only from its canonical module allowlist
  through `scripts/build_adapter.py`; verify both the isolated wheel and sdist.
  Standalone consumers pin the versioned release artifact and SHA-256.
