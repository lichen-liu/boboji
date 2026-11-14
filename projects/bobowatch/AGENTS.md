# BoboWatch project rules

- This directory currently contains a proposed migration design, not an imported
  application. See `docs/monorepo-migration.md` for the evidence and rollout gates.
- Keep eventual code, tests, examples, installation, deployment, and documentation
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
