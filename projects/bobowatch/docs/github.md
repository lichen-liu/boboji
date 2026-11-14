# GitHub development

BoboWatch's canonical source is
[Boboji / BoboWatch](https://github.com/lichen-liu/boboji/tree/main/projects/bobowatch).
Code, tests, installation, deployment, and documentation stay in this project.

Follow the shared [CI and branch policy](../../../.github/README.md): `codex/`
branches, linear history, PRs to `main`, and a label after the final push to
request checks. The existing required `pytest (Python 3.13)` job gates the
project's Python, JavaScript, packaging, and browser checks. Do not apply the
former standalone repository's settings/rulesets to Boboji.

Ordinary changes may squash or rebase. The initial migration uses rebase merge
to retain the 22 source-main commits. Original commit IDs and PR discussions
stay in [the original repository](https://github.com/lichen-liu/bobowatch);
replayed commits have source provenance trailers. See the
[migration record](migration.json) and [design](monorepo-migration.md).

Application installation is independent of CI. Use the
[operator guide](runtime.md) for an explicit project deployment and the
[adapter release guide](adapter-release.md) for maintained standalone consumers.
