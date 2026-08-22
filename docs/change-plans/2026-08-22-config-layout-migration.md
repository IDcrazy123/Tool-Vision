# Change plan — place ToolVision beside printer.cfg

- Owner: ToolVision maintainers / Codex
- Date: 2026-08-22
- Baseline commit/version: `5e79f633ab5b33998d8e1afa64a638386f1bc59b` / `v3.3.0-rc1`
- Risk IDs: R-007, R-009
- Issue/PR: branch `codex/config-layout-migration`
- Local backup directories:
  `.local-backups/20260822-1930-manual-config-workflow/` and
  `.local-backups/20260822-2030-universal-config-root/` (verified Git bundle
  plus 14 source/document files). The earlier remote tag
  `backup/pre-config-layout-migration-20260822-184537` is historical and will
  not be repeated.
- Printer backup path/checksum: not applicable during repository-only work; the
  installer must create timestamped copies below
  `${DATA_DIR}/config_backups/tool-vision` before changing printer files.

## Problem và evidence

The installer currently creates
`${CONFIG_DIR}/Tool-Vision/tool_vision.cfg` and a generated
`moonraker_update_manager.conf`, then includes that file from `moonraker.conf`.
This duplicates the machine's `Printer-Setup` layout and older versions also
placed learned state/results in the legacy directory. Reinstall and uninstall
cover only the generated include, not a direct updater section or the Klipper
include migration.

## Desired behavior

- Fresh install creates/preserves
  `tool_vision.cfg` in the directory containing the actual `PRINTER_CONFIG`,
  creates a verified local backup
  directory, and prints the exact Klipper include for manual copy/paste.
- The optional `[update_manager tool-vision]` block is printed for manual review
  and addition to `moonraker.conf`; installer does not edit either machine
  config and does not generate a separate updater file.
- Upgrade backs up user files, preserves an existing destination config, copies
  missing legacy defaults safely, and retains every legacy source until the
  user has changed includes and verified the new layout.
- Re-running the installer does not change machine configs or overwrite user
  data; every run creates its own local printer backup directory.
- Uninstall backs up first and refuses system mutations until the user removes
  the manual Klipper include/updater block; Git runtime, editable config,
  learned state and results remain.

## Invariants

- Motion/limits: no change.
- Heater/toolchange: no change.
- Offset signs: no change.
- State/schema/API: schema unchanged; default state/result paths move with the
  default config layout, while explicit user paths remain untouched.
- User workflow: Mainsail updates continue to operate on the persistent Git
  runtime after the user adds the displayed updater block; normal config is
  beside `printer.cfg` and machine config ownership remains explicit.

## Design/options

Do not parse/rewrite `printer.cfg` or `moonraker.conf`. Back them up with every
ToolVision config/state/result file in scope, verify copies by checksum, then
atomically copy legacy config/state/result only when the destination is absent.
If both copies exist, preserve both and warn. Print reviewed snippets for the
user; never remove legacy sources automatically because an old manual include
may still reference them.

## File/task breakdown

1. Test tái hiện: add deployment integration fixtures for fresh install,
   legacy upgrade, repeated install and uninstall.
2. Implementation: make installer/uninstaller backup-first while leaving
   Klipper/Moonraker edits manual and visible.
3. Migration/compatibility: copy missing config/default JSON with timestamped
   backups, document manual legacy include replacement and retain explicit path
   overrides.
4. Docs: update README, operations, architecture, storage, backup and testing
   contracts.
5. Deployment: run static/unit/integration gates, commit and push the branch;
   actual printer restore drill remains a pre-merge/release gate.

## Verification

- Unit: existing Python suite plus path/contract regression tests.
- Integration/simulator: isolated filesystem shell fixtures for fresh,
  upgrade, repeat and uninstall paths.
- Corpus replay: not applicable; detector behavior is unchanged.
- HIL: not required for motion behavior, but an idle-printer deployment and
  Moonraker refresh remain required before stable release.
- Failure injection: verify backups precede config mutation and conflicts keep
  a recoverable copy; full step-by-step installer rollback remains open under
  R-007.

## Rollback

Revert the migration commit or restore the local repository bundle/files. Restore
`printer.cfg`, `moonraker.conf`, editable config and JSON data from the newest
timestamped directory below `${DATA_DIR}/config_backups/tool-vision`, validate
Moonraker/Klipper configuration, then restart services. The Git runtime is never
deleted by install/uninstall and therefore remains independently recoverable.

## Completion evidence

- Local backup before the manual-workflow redesign:
  `.local-backups/20260822-1930-manual-config-workflow/` (29 files, Git ignored).
- Local backup before replacing the machine-specific `Printer-Setup` default:
  `.local-backups/20260822-2030-universal-config-root/` (verified complete Git
  bundle plus 14 relevant files, Git ignored).
- Windows local: 85/85 `unittest` pass; branch coverage 75% overall and 80% for
  `scripts/config_layout.py`; focused Ruff `E/F/I`, `compileall` and
  `git diff --check` pass; `pip-audit` reports no known requirement
  vulnerabilities.
- Debian 12 aarch64 pilot, isolated `/tmp`: 14/14 layout/release-metadata tests
  pass; `bash -n install.sh` and `bash -n uninstall.sh` pass. The temporary test
  directory was verified by `realpath` and removed after the run.
- No production config/service/runtime was changed by these tests. Full
  systemd/pip image install, printer restore drill and post-Moonraker-refresh
  check remain pre-release gates; R-007/R-009 stay open.
- Implementation commits: `4385b06` (`feat: prepare manual ToolVision config
  migration`) and `d6357c4` (`fix: place config beside printer config`). Remote
  branch/hash and semantic release-tag verification are recorded in the task
  handoff after push.
