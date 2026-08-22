# ToolVision 3 architecture

This document records the invariants behind the rewrite. It is intentionally
short and implementation-oriented so future changes do not accidentally alter
offset signs or bypass a safety check.

## Scope

ToolVision measures relative nozzle offsets on a Klipper multi-tool machine.
It does not silently write production offsets. The default output is a report
and a JSON result file which the operator reviews before applying.

Only two pieces of hardware configuration are fundamental:

- `pin` for a normally-open or normally-closed Z contact switch;
- a camera source, selected explicitly or discovered from Moonraker.

Fixture coordinates, image thresholds, regions of interest, focus thresholds,
pixel scale, camera rotation and tool count are not normal configuration. They
are either learned, read from Moonraker/toolchanger, or derived from the camera
frame.

## Source-derived measurement rules

### Z — Axiscope compatible

The operator puts the reference nozzle above the switch and runs one setup
command. ToolVision records the current raw X/Y and approach Z, verifies that
the switch can trigger, measures the reference trigger Z, and atomically saves
the station. Each tool is subsequently probed at that physical station.

For tool `n`:

```text
z_offset[n] = raw_trigger_z[n] - raw_trigger_z[reference]
```

This is the sign used by Axiscope. Five samples, median aggregation, 0.05 mm
sample tolerance and two retries are the source-backed defaults. They remain
overridable per command for unusual hardware, not required in `.cfg`.

Axiscope keeps heating in optional G-code templates; its documented example
preheats all tools to 150 C, offers an after-pickup scrub hook, and cools all
tools at the end. ToolVision uses the same 150 C reference automatically. It
sets all targets first, waits for the active extruder after each pickup, runs
`after_select_gcode`, and measures only then. `TEMP=` remains an advanced
override, including `TEMP=0` for an explicitly cold run. Heater targets are
cleared in a `finally` path so a normal calibration exception cannot leave tools
heating. An MCU/Klipper emergency shutdown remains outside G-code cleanup
guarantees.

### XY — kTAMV compatible

The operator puts the reference nozzle approximately at the image center and
runs one setup command. The host service learns a stable detector profile from
the native-resolution frame. Klipper then executes the ten kTAMV calibration
moves on a 0.5 mm radius, fits a robust pixel-to-machine transform and centers
the nozzle iteratively.

At least 8 of 10 useful calibration points are required. Transform schema 2
must also have full rank, sensible conditioning, pass both training and
leave-one-out residual validation, and prove that measured pixel noise maps to
no more than the centering tolerance. Nominal correction plus estimated
uncertainty must fit inside that tolerance before centering succeeds.

For a tool centered above the same camera target:

```text
xy_offset[n] = raw_center_position[n] - raw_center_position[reference]
```

This matches kTAMV and the current klipper-toolchanger camera-align example.

## Camera discovery

If `camera_source` is absent, the host asks Moonraker for enabled webcams:

1. use the only enabled camera;
2. otherwise use an exact `camera_name` match;
3. otherwise prefer a unique camera whose name/location contains a nozzle-tool
   alignment keyword;
4. otherwise stop and list candidates.

Ambiguous cameras are never selected by list order. Moonraker rotation and flip
metadata are applied automatically. The service uses the snapshot URL when
available and retains native resolution.

## Detection and focus

Setup evaluates several kTAMV-style preprocessing/polarity strategies, clusters
their detections over a frame burst and learns the stable candidate nearest the
camera center. Runtime detection uses the learned strategy and geometry rather
than user-entered OpenCV thresholds. A runtime frame with multiple spatially
distinct profile matches is rejected; it is never resolved merely by choosing
the closest candidate.

Focus is reported as a relative sharpness metric from the detected nozzle area.
There is deliberately no universal absolute focus cutoff: focus-operator
performance depends on noise, contrast, saturation and window size. A setup is
accepted only when the nozzle is detected consistently and the motion-to-pixel
transform validates; this is the practical "image is usable" test.

After Klippy commands a centering move, the next stable observation must also
show image displacement above the run's stability/quantization floor while the
nozzle remains outside tolerance. This catches repeated cached/frozen frames;
it does not replace the real-image corpus and HIL gate. The full source review
and remaining limitations are recorded in
[`DETECTION_DESIGN.md`](DETECTION_DESIGN.md).

Camera capture has two resource boundaries: compressed HTTP bytes and decoded
pixels. Network sources supported by OpenCV's FFmpeg/GStreamer timeout
properties receive open/read deadlines at `VideoCapture.open`. Because those
properties are backend-specific, local device hang/reconnect behavior remains
an open validation item rather than a universal guarantee.

## Motion safety

- XYZ must be homed and the printer must not be printing.
- Setup requires the configured reference tool already mounted. It never
  performs a surprise tool change after the operator manually positions it.
- The current implementation, including `v3.3.0-rc2`, assumes the reference
  tool's configured XYZ offset is zero when teaching and revisiting a station.
  This condition is not yet enforced in code; automatic all-tool
  station-envelope preflight is tracked as R-002 in the risk register.
- All targets are checked against kinematic limits before motion.
- The switch must be open before probing.
- Calibration owns the tool-heater targets: it defaults to the source-backed
  150 C reference and clears every target on success and recoverable errors.
- Station travel raises Z first, then moves XY, then approaches the fixture.
- A taught safe Z defaults to 5 mm above the setup position, clamped to the
  machine limit. `SAFE_Z=` on the setup command is the explicit override for a
  machine whose fixture needs more clearance.
- No software can infer arbitrary clamps or fixtures from a single upward
  camera. The operator remains responsible for a collision-free vertical path.

## Modules and ownership

```text
Klipper process                         Host service
-------------------------------         -------------------------------
tool_vision.py                          app.py       HTTP/job boundary
  command orchestration                 camera.py    discovery/capture
  guarded motion                        detection.py learned detector
  switch probing                        transform.py robust 2D model

tool_vision_toolchanger.py
  old/current API compatibility

tool_vision_state.py
  schema validation + atomic JSON
```

The host service never commands printer motion. The Klipper extension never
imports OpenCV or NumPy. This boundary keeps camera latency and image processing
away from Klipper's motion/MCU scheduling path.

The host service is memory-only. Before every XY calibration, Klippy
reconfigures it from the learned profile/transform stored in Klipper-owned
state. Reconfiguration is a gated state transition: jobs and transform calls
cannot start during candidate camera capture; a failed candidate leaves the
previous runtime intact. This is necessary because Moonraker may restart the
host and Klipper services independently during an update.

## Moonraker-managed deployment

The Git checkout is the runtime. Klipper's four extension links and the
ToolVision systemd service therefore see a Moonraker `git_repo` update
immediately; copying files to a second non-Git runtime would make the UI claim
success while leaving old code active. The installer prints a copy/paste
`[update_manager tool-vision]` section containing the actual checkout,
virtualenv, origin and current branch, but deliberately does not edit
`moonraker.conf`. This keeps ownership visible and avoids a general-purpose
config parser mutating a machine-specific include tree.

Moonraker permits an extension updater to restart a third-party systemd unit
only when the exact, case-sensitive service name is present in the data
directory's `moonraker.asvc`. The installer backs up that file and appends only
`tool-vision`; uninstall performs the inverse operation without altering the
other allowed services. Uninstall stops before system changes while a manual
Klipper include or ToolVision updater section is still present.

User-owned calibration config and learned/result JSON remain under
`printer_data/config/Printer-Setup`, outside the repository. This preserves
Moonraker's pristine-repository invariant and follows the machine's shared
configuration layout.
The installer records the currently checked-out branch as `primary_branch` and
never guesses or switches the user's channel; the printed block lets the user
review it before saving. Installer backups are kept under
`printer_data/config_backups/tool-vision`, not beside active configuration.

Moonraker derives a `git_repo` version from `git describe --tags`. Therefore
release tags use semantic names such as `v3.3.0-rc2`; backup snapshots created
after this decision stay in local backup folders excluded from Git. Historical
backup tags remain unchanged and are superseded by the nearest semantic release
tag rather than deleted or rewritten. See ADR-0004.
