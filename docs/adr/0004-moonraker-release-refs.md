# ADR-0004 — Separate Moonraker release tags from local backups

- Status: Accepted
- Date: 2026-08-22
- Risk IDs: R-007, R-016

## Context

Production reported a valid, pristine `tool-vision` updater at commit `5e79f633`
whose `version` and `remote_version` were both `?`. The observed Git description
was `backup/pre-detection-hardening-20260822-3-g5e79f63`.

Moonraker's official `git_repo` implementation runs
`git describe --always --tags --long --dirty` and parses the nearest tag as a
semantic/PEP-440-style Git version. A non-semantic annotated backup tag can be
nearer than the last `vX.Y.Z` tag, so the repository remains updateable but its
reported version becomes unknown.

Sources checked against the pilot's pinned Moonraker
`d5ee17128bb88434aacdab90c2e9e990e2b64e4a`:

- [`git_deploy.py` version discovery](https://github.com/Arksine/moonraker/blob/d5ee17128bb88434aacdab90c2e9e990e2b64e4a/moonraker/components/update_manager/git_deploy.py#L367-L371);
- [`GitVersion` semantic parser](https://github.com/Arksine/moonraker/blob/d5ee17128bb88434aacdab90c2e9e990e2b64e4a/moonraker/utils/versions.py#L327-L373);
- [official Git Repo Configuration](https://moonraker.readthedocs.io/en/latest/configuration/#git-repo-configuration).

## Decision

- Published code receives an immutable semantic release tag matching the
  runtime version, including supported prerelease forms such as
  `v3.3.0-rc2`.
- New work backups use timestamped directories under `.local-backups/`, which
  is ignored by Git. Backup branches/tags are not pushed to GitHub.
- Existing backup tags are retained unchanged. We do not delete tags, move
  tags or rewrite history to repair UI metadata.
- The already-published `3.3.0-rc1` code at `5e79f633` receives the matching
  annotated tag `v3.3.0-rc1`. The `v3.3.0-rc2` tag is created only on the
  eventual `main` release/merge commit, never on an unmerged feature branch.
- Release verification runs `scripts/release_metadata.py --expected X.Y.Z...`
  after commit/tag creation and before rollout.

## Consequences

- `git describe --tags` remains based on a semantic release tag, so Moonraker
  can populate `version` and `remote_version`.
- Local backup directories do not affect version discovery or use GitHub as a
  backup store. Important printer data still needs an off-device copy under the
  separate retention policy.
- The matching RC1 release tag resolves the observed production commit without
  destroying recovery points. Historical backup tags may still produce `?` on
  other commits between semantic releases; the next semantic release tag
  resolves those descendants after merge.

## Verification

- Unit tests reject the observed `backup/...` description and accept
  `v3.3.0-rc2-N-g<sha>`.
- Release evidence records the semantic tag, dereferenced commit, local
  `git describe`, and Moonraker updater status after refresh.
