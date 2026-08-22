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

At least 8 of 10 useful calibration points are required. A transform must also
have full rank, sensible conditioning and pass residual/outlier validation.

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
than user-entered OpenCV thresholds.

Focus is reported as a relative sharpness metric from the detected nozzle area.
There is deliberately no universal absolute focus cutoff: focus-operator
performance depends on noise, contrast, saturation and window size. A setup is
accepted only when the nozzle is detected consistently and the motion-to-pixel
transform validates; this is the practical "image is usable" test.

## Motion safety

- XYZ must be homed and the printer must not be printing.
- Setup requires the configured reference tool already mounted. It never
  performs a surprise tool change after the operator manually positions it.
- Version 3.2.1 assumes the reference tool's configured XYZ offset is zero when
  teaching and revisiting a station. This condition is not yet enforced in code;
  automatic all-tool station-envelope preflight is tracked as R-002 in the risk
  register.
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

## Moonraker-managed deployment

The Git checkout is the runtime. Klipper's four extension links and the
ToolVision systemd service therefore see a Moonraker `git_repo` update
immediately; copying files to a second non-Git runtime would make the UI claim
success while leaving old code active. The generated updater section also
declares the isolated virtualenv and requirements file, then asks Moonraker to
restart `tool-vision` and `klipper` after a successful update.

Moonraker permits an extension updater to restart a third-party systemd unit
only when the exact, case-sensitive service name is present in the data
directory's `moonraker.asvc`. The installer backs up that file and appends only
`tool-vision`; uninstall performs the inverse operation without altering the
other allowed services.

User-owned calibration config and learned/result JSON remain under
`printer_data/config/Tool-Vision`, outside the repository. This preserves
Moonraker's pristine-repository invariant without cluttering the config root.
The installer records the currently checked-out branch as `primary_branch` and
never guesses or switches the user's channel. Installer backups are kept under
`printer_data/config_backups/tool-vision`, not beside active configuration.
