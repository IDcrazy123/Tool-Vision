# ToolVision repository instructions

This file is the automatic entry point for Codex and other agents that support
`AGENTS.md`. It applies to the whole repository. Do not replace it with an
unconfigured `.agent/` folder: Codex discovers this filename at repository
startup.

## Mission and maturity

ToolVision measures relative XYZ nozzle offsets on multi-tool Klipper printers
while asking the user for as little hardware-specific configuration as
possible. It inherits the Z measurement sign/workflow from Axiscope and the XY
centering/sign pattern from kTAMV.

The current release is a monitored, report-only pilot. Never claim broad
hardware support from the single observed pilot, and never add automatic
production-offset writes without an approved ADR, safety gates and HIL
evidence.

## Read before changing code

Always read these files before implementation:

1. `docs/README.md` — documentation map and source-of-truth rules.
2. `docs/ARCHITECTURE.md` — measurement signs, process boundaries and motion
   invariants.
3. `docs/RISK_REGISTER.md` — open risks and exit criteria.
4. `docs/PROJECT_PLAN.md` — workstream order and release gates.
5. `docs/CODE_CONVENTIONS.md` — code and comment contract.
6. `docs/DEVELOPMENT.md` and `docs/TESTING.md` — workflow and verification.

For install, update, state, deployment or printer work, also read
`docs/DATA_AND_STORAGE.md`, `docs/OPERATIONS.md`, `docs/BACKUP_RESTORE.md` and
`docs/RELEASE.md`. Read the newest relevant audit/ADR, but do not rewrite a
historical audit to describe newer behavior.

## Non-negotiable invariants

- Keep results report-only. Do not call `SAVE_CONFIG`, write tool offsets or
  mutate production calibration automatically.
- Preserve the documented signs:
  `XY = raw center(tool) - raw center(reference)` and
  `Z = raw trigger(tool) - raw trigger(reference)`.
- Klippy owns homing checks, motion, probing, tool changes and heater cleanup.
  The host service owns camera capture and computer vision; it must never move
  the printer.
- Do not add OpenCV/NumPy to the Klipper process or new blocking network work to
  its reactor. R-001 tracks the existing synchronous HTTP risk.
- Treat motion, heat, probe and tool-change failures as safety paths. Preflight
  every target that can be known, retract/recover when Klipper is ready, clear
  owned heater targets and retain both primary and cleanup failures.
- Current station teaching assumes the reference tool has configured XYZ
  offset zero. Do not hide this limitation; R-002 must be closed before
  claiming otherwise.
- Hardware thresholds and tolerances require a cited upstream rule or measured
  corpus/HIL evidence. Never infer a universal threshold from one printer or
  one image.
- User config/state/result are data. Preserve explicit paths, make schema/path
  changes migratable, back up before mutation and never commit credentials,
  private camera URLs, printer IPs or user calibration data.

## Required workflow

1. Inspect `git status`, current revision and applicable instructions. Preserve
   unrelated or user-owned worktree changes.
2. For a major or safety-relevant change, create one timestamped local backup
   directory under `.local-backups/` before mutation. Keep it ignored by Git;
   do not push backup branches/tags to GitHub. Git tags are reserved for
   semantic releases because Moonraker parses the nearest tag as the updater
   version (ADR-0004). Back up printer config/state/result before deploy or HIL.
   Use `docs/templates/CHANGE_PLAN.md`.
3. Map the request to an existing Risk ID, or create one before changing a
   safety/data/deployment contract.
4. Reproduce with a focused test or captured evidence. Make the smallest
   vertical slice; do not mix formatting modernization with behavior changes.
5. Verify after each slice. Start with focused tests, then run the complete gate
   required by `docs/TESTING.md`.
6. Update code, tests, comments, changelog and affected source-of-truth docs in
   the same commit. Create an ADR for an invariant or architectural decision.
7. Use the Moonraker canary/update path for printer deployment. Do not hand-edit
   installed runtime files and call that a release.

Use `apply_patch` for hand edits. Do not use destructive Git or filesystem
commands to discard unknown work. Keep backups outside active config and record
their exact local path in change evidence.

## Minimum verification

```bash
python -m unittest discover -s tests -v
python -m compileall -q scripts klippy server tests
bash -n install.sh
bash -n uninstall.sh
git diff --check
```

Run Ruff, dependency audit, coverage, API/component tests, failure injection,
simulator and HIL as required by `docs/TESTING.md`. A documentation-only change
still requires internal-link validation and `git diff --check`.

## Definition of done

Work is not done until behavior and failure behavior are tested at the required
level, documentation matches runtime reality, backup/rollback is recorded,
open risks are updated, version/path/service names agree, the intended remote
branch/tag is verified and the worktree contains no unexplained changes.

When facts are uncertain, label them `Observed`, `Planned` or `Unknown`. Do not
turn plans into claims of implemented or supported behavior.
