# Flyji / Flightrepo project rules

- Keep application code, ingestion tools, tests, fixtures, docs, installation,
  and deployment in this project. Keep the existing Python 3.11+ runtime and
  `flight-routes-engine` distribution and CLI names.
- Shared GitHub policy and CI live at the monorepo root. Run the native pytest,
  Ruff, Node, package, and fictional Chromium/WebKit suites from this directory.
- Production state belongs in ignored root `var/flightrepo/`; this project's
  ignored `var` symlink points there. Never commit databases, sidecars, provider
  caches, logs, credentials, or private settings. Tests use disposable fixtures.
- Serving and ingestion are separate databases with persistent identities and
  publication authority. Preserve real mode, identities, generations, quotas,
  locks, and monitoring configuration. Relocation must include the stored
  authoritative serving path and all affected writers; see `docs/migration.md`.
- Deployments remain explicit operator actions. Use the existing private
  installed runtime and Cloudflare tunnel. Never start another production
  instance, seed a real database, or redeploy other projects for this migration.
- Consume the hash-pinned BoboWatch adapter as its own distribution. Do not
  embed another copy. Integration tests use the canonical sibling collector;
  shared CI runs them whenever BoboWatch changes.
