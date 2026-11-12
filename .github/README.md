# Repository and CI guidelines

These conventions follow [Trip Dollar's CI guide](https://github.com/lichen-liu/trip_dollar/blob/e5e14f81a219ae2d4c0606f2a5f8070a7f0cf190/.github/README.md)
and its active main/development branch rulesets at that revision.

## Requesting PR tests

CI runs the complete offline pytest suite on Python 3.13 and checks an isolated
wheel installation. PR runs are requested manually by adding any label to a PR
targeting `main`; `run-ci` is the conventional label. If a label is already
present, remove it and add it again to request a fresh run.

Before merging:

1. Rebase your branch onto the latest `main` and push it. Development branches
   require linear history.
2. Add a label to the PR to request CI on that commit.
3. Wait for `pytest (Python 3.13)` to pass, then squash or rebase merge.

Opening/reopening a PR and pushing commits do not trigger PR CI. Request it again
after every new push and whenever the branch needs updating with `main`.
Required checks from older commits are insufficient. `workflow_dispatch` is
not used as a substitute for a required PR check.

Every push to `main` starts another run. Separate commits have distinct
concurrency groups and do not cancel one another. A failed post-merge test
reports a failure and does not roll back the merge.

## GitHub settings

The source-controlled desired settings are:

- [`repository-settings.json`](repository-settings.json): squash/rebase enabled,
  merge commits disabled, merged branches deleted, automatic merge disabled.
- [`rulesets/main.json`](rulesets/main.json): a PR, an up-to-date branch, and the
  GitHub Actions `pytest (Python 3.13)` check are required; no reviewer approvals
  or bypass actors; branch deletion and force pushes are blocked.
- [`rulesets/development.json`](rulesets/development.json): linear history for
  all branches except `main`.

JSON files describe settings; GitHub enforces them only after they are applied
to the repository. An empty repository must receive its initial `main` commit
before the required-check rule is activated. Subsequent work uses PRs.

An administrator can apply merge settings with:

```sh
gh api --method PATCH repos/lichen-liu/boboji --input .github/repository-settings.json
```

Create each missing ruleset with `POST /repos/lichen-liu/boboji/rulesets` and its
JSON file, or update an existing matching ruleset using `PUT` and its ID. Inspect
existing rulesets first so this does not create duplicates.
