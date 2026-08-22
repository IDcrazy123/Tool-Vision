# Change plan — detector/transform hardening

- Owner: Codex + repository owner
- Date: 2026-08-22 (Asia/Saigon)
- Baseline commit/version: `ed8ac8e` / runtime `v3.2.2`
- Risk IDs: R-005, R-006, R-010, R-013, R-016, R-017
- Issue/PR: pending
- Backup Git tag: `backup/pre-detection-hardening-20260822`
- Printer backup path/checksum: not applicable until an authorized HIL/canary run

## Problem và evidence

Audit baseline identified four measurement-validity gaps that require direct
source review and regression evidence before implementation:

- runtime detection may accept a weak best candidate without an ambiguity gate;
- repeated identical frames can look stable even when the camera is frozen;
- transform validation does not yet prove physically useful motion-to-pixel
  sensitivity or an independent return/holdout observation;
- decoded frame size and OpenCV capture duration are not fully bounded, and
  configuration can race a running job.
- the memory-only host is not rehydrated before XY calibration after a service
  restart, and missing correction fields fail open as zero movement.

These are hypotheses from R-005/R-010/R-013 until reproduced against current
code. R-006 remains open because synthetic tests cannot establish broad
hardware accuracy.

## Desired behavior

- Reject ambiguous, stale/frozen or internally inconsistent observations with
  actionable errors instead of returning a plausible center.
- Reject transforms that are numerically fit but unsupported by adequate image
  displacement/validation evidence.
- Bound camera inputs and configuration mutation without adding user tuning
  parameters.
- Preserve valid kTAMV-compatible ten-point behavior and current user workflow.
- Do not claim universal thresholds or close multi-hardware risk without real
  corpus/HIL evidence.

## Invariants

- Motion/limits: no Klipper motion sequence or limit behavior changes in this
  workstream.
- Heater/toolchange: unchanged.
- Offset signs: XY remains `raw center(tool) - raw center(reference)`; Z is
  unchanged.
- State/schema/API: detector profile/result/top-level state remain compatible.
  Transform schema 2 is deliberately incompatible because schema 1 cannot
  contain newly measured stability/uncertainty evidence; migration is backup +
  fail-fast + rerun `TV_SETUP_CAMERA`, not fabricated numeric fields.
- User workflow: still jog reference nozzle and run one setup command; no new
  required `.cfg` tuning.

## Design/options

The implementation will use only gates justified by pinned upstream behavior,
official OpenCV semantics or data derived from the setup samples themselves.
It will not invent a fixed focus/contrast/pixel-scale threshold for every
camera. Each proposed gate must first have a failing regression test and a
documented failure state.

## File/task breakdown

1. Read current detector/camera/transform/API and all related tests.
2. Trace pinned Axiscope `9a1a9ef`/kTAMV `72421f2` implementations and official
   primary sources.
3. Add focused regression tests for confirmed faults.
4. Implement the smallest detector/transform/camera/concurrency slices.
5. Update architecture, risk register, testing and changelog.

## Verification

- Unit: detection ambiguity/freshness, transform degeneracy/sensitivity and
  camera bounds.
- Integration: Flask configure/job serialization and failure responses.
- Corpus replay: synthetic/adversarial regression fixtures in-repo; real corpus
  remains required before R-006 can close.
- HIL: required before release/deploy because detector/transform behavior
  changes; not performed without printer backup and operator authorization.
- Failure injection: stale camera, distractor, malformed/oversized frame and
  concurrent configure/start.

## Rollback

Revert the detector-hardening commit/branch to
`backup/pre-detection-hardening-20260822`. Before any canary setup, copy the
schema-1 `tool_vision_state.json`; a rollback must restore that matching file
before restarting the older host/Klippy, because `v3.2.2` cannot consume
transform schema 2. If canary behavior rejects formerly valid hardware, restore
the previous Git revision and matching state, verify host health, then run only
the prior release smoke procedure. No printer state has been changed by this
development run.

## Completion evidence

- Backup: annotated remote tag
  `backup/pre-detection-hardening-20260822` dereferences to baseline
  `ed8ac8e0a9a60223c3a79ba4856ff1138d90b8ba`.
- Sources: pinned Axiscope `9a1a9ef`, kTAMV `72421f2`, official OpenCV/NumPy
  references and accepted/rejected inheritance are recorded in
  [`../DETECTION_DESIGN.md`](../DETECTION_DESIGN.md).
- Test-first reproduction: ambiguity, malformed profile/frame, tiny pixel
  sensitivity, unbounded samples/pixels, configure race and frozen-frame tests
  failed on the baseline behavior before implementation.
- Final local suite: `python -m unittest discover -s tests -v` — 70/70 pass.
- Compile/fatal lint: `compileall` pass; Ruff `E9,F63,F7,F82` pass.
- Coverage: branch coverage 73% total; core Klippy 40%, app 75%, camera 71%,
  detector 83%, transform 75%.
- Dependency: `pip-audit -r server/requirements.txt` — no known vulnerability.
- Deployment contract: `install.sh` and `uninstall.sh` parse with Debian pilot
  `bash -n` over stdin; scripts were not executed.
- Repository: `git diff --check` pass; pinned submodules unchanged.
- Known quality debt: unconfigured whole-tree Ruff run still reports 109
  style/broad-catch findings. They are classified under the existing lint/CI
  workstream; this RC does not claim a clean full Ruff gate.
- Not run: real-image corpus replay, Klipper simulator and HIL. No printer
  motion, heat, state write or deployment occurred. Therefore R-005, R-006,
  R-010 and R-017 remain open/mitigating and no stable release tag is allowed.
- Implementation commit: `b94876d` (`feat: harden camera detection and
  transform safety`). Documentation/evidence is committed separately in the
  same branch; remote branch push follows its final diff check.
