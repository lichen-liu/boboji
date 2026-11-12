# Boboji guidelines

Follow the applicable Trip Dollar conventions documented in README.md and
.github/README.md. The reference revision is
e5e14f81a219ae2d4c0606f2a5f8070a7f0cf190.

- Use Python 3.11+ with `src/boboji/` and Hatchling packaging. Keep the conversion
  core independent of the command-line adapter and third-party runtime packages.
- Use snake_case Python filenames. `timeline_to_fog.py` is the directly runnable
  entry script; installed entry points must call the same implementation.
- Keep tests offline, use synthetic location fixtures, and run `python -m pytest
  -q` after behavioral changes. Verify an isolated wheel when packaging changes.
- Never commit personal Timeline exports, generated private tracks, credentials,
  environment directories, or runtime logs. Errors must not echo location data.
- Preserve source track boundaries and timestamps. Do not infer missing routes,
  substitute current dates, or silently discard invalid positional data.
- Keep user instructions, format support, examples, and architecture docs aligned
  with behavior. New formats need explicit adapters and regression coverage.
- After the initial empty-repository bootstrap, use `codex/` development branches
  and PRs to `main`. Keep development history linear, request CI by adding a PR
  label after the final push, and squash or rebase merge only after the latest
  required Python 3.13 check passes on an up-to-date branch.
- GitHub ruleset JSON is desired configuration, not proof of active protection;
  verify live settings when changing repository protection.
