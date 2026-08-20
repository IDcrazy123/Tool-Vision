# Tool Vision 2

Tool Vision measures relative **X, Y, and Z tool offsets** on Klipper
toolchanger printers by combining an upward-facing nozzle camera with a fixed
microswitch.

The project keeps the strongest ideas from kTAMV and Axiscope while removing
their hardware assumptions:

- kTAMV-style multi-strategy image processing, multi-frame stability checks,
  radial pixel-to-motion calibration, and iterative nozzle centering.
- Axiscope-style `PrinterProbeMultiAxis` switch probing, dynamic tool lists,
  reference-tool deltas, and configurable G-code workflow hooks.
- Native camera frames: no 640x480 constant and no forced resize.
- Resolution-relative target, ROI, and blob-area settings.
- Safe station travel: Z is lifted before every XY move to the camera or switch.
- Report-only output by default; production tool configs are never rewritten.

## Scope and safety

Tool Vision is a measurement system, not a first-layer compensation model.
A switch can produce repeatable mechanical deltas that still differ from the
best printing offsets because of switch force, nozzle temperature, bed
temperature, frame expansion, and measurement location. Validate every result
with a controlled first-layer print before applying it.

Tool Vision ships disabled by design. Do not enable it on a production printer
until the camera and switch station coordinates have been measured. If
`[axiscope]` or `[tools_calibrate]` is already active, disable it before enabling
`[tool_vision]`.

Never configure more than one of these sections at the same time:

```ini
[tool_vision]
[axiscope]
[tools_calibrate]
```

All three can allocate the same `probe_multi_axis` resource.

## Architecture

```text
Tool-Vision/
├── Axiscope/                      Pinned reference submodule; not installed
├── kTAMV/                         Pinned reference submodule; not installed
├── klippy/extras/tool_vision.py   Klipper motion and XYZ orchestration
├── server/
│   ├── app.py                     Versioned HTTP API and single-job worker
│   ├── camera.py                  HTTP/OpenCV native-frame acquisition
│   ├── detection.py               Multi-strategy stable nozzle detection
│   ├── transform.py               Affine/quadratic pixel-motion fit
│   ├── requirements.txt           Host-only Python dependencies
│   └── tool-vision.service.in     Installer-populated systemd template
├── tests/                         Host-side deterministic tests
├── tool_vision.cfg                Portable Klipper configuration example
├── install.sh                     No-clone bootstrap and runtime installer
└── uninstall.sh                   Service and symlink removal
```

OpenCV and NumPy run in an isolated host service. Klipper uses only Python's
standard library to exchange short JSON messages, so the Klipper environment
does not need computer-vision packages.

## Reference repositories

Axiscope and kTAMV are pinned Git submodules for design comparison and
provenance. They retain their own histories and licenses, and neither directory
is imported or installed by Tool Vision.

Clone the complete development tree with:

```bash
git clone --recurse-submodules https://github.com/IDcrazy123/Tool-Vision.git
cd Tool-Vision
```

For an existing clone, retrieve the reference trees with:

```bash
git submodule update --init --recursive
```

The submodules are development references kept on the PC. They are never
downloaded or copied into the printer runtime.

## Camera compatibility

`camera_source` supports:

- Crowsnest MJPEG stream or snapshot URLs.
- Other HTTP JPEG/MJPEG camera servers.
- RTSP streams through OpenCV.
- V4L2 paths such as `/dev/video0`.
- OpenCV numeric camera indexes such as `0`.

With `camera_mode: auto`, HTTP/HTTPS uses the HTTP JPEG reader and every other
source uses OpenCV. `camera_width`, `camera_height`, and `camera_fps` default to
`0`, which means the device/native default. They are optional requests for
direct OpenCV devices; they are not processing dimensions.

After optional rotation and flipping, the detector reads the actual
`frame.shape`. The model stores that frame size and forces recalibration if it
changes.

## Detection model

Each frame is processed through dark/light adaptive and Otsu masks. Strict and
relaxed contour profiles filter candidates by:

- area as a ratio of the full native frame;
- circularity;
- convexity;
- inertia/aspect ratio;
- distance to the configured target.

The detector accepts a position only after `detection_stable_frames`
consecutive samples cluster within the configured tolerance. Results include
the native frame size, confidence, chosen strategy, diameter, and X/Y sample
standard deviation.

Important tuning groups in `tool_vision.cfg`:

| Goal | Parameters |
|---|---|
| Crop unrelated objects | `camera_roi_*` ratios |
| Move the optical target | `camera_target_*_ratio` |
| Detect dark or bright openings | `detector_polarity` |
| Globally relax/tighten | `detector_sensitivity` |
| Match nozzle apparent size | `detector_min/max_area_ratio` |
| Reject irregular blobs | circularity/convexity/inertia |
| Reject camera jitter | stable frames and stability tolerance |
| Compensate lighting | gamma, adaptive C, blur size |

Change one group at a time and use `TV_CAMERA_CHECK` plus
`/api/v1/frame` to evaluate the result.

## Camera calibration model

The reference tool moves through a configurable radial pattern. Each sample
contains a measured machine delta and observed pixel delta. The service fits:

```text
machine_delta = transform(pixel_delta)
```

`affine` is recommended. `quadratic` is available for visibly distorted optics
and requires at least eight useful points. Calibration is rejected when the
design matrix is rank-deficient, ill-conditioned, or exceeds
`camera_max_rms_error`.

Unlike the legacy implementation, there is no hard-coded damping constant in
the fitted matrix. Damping and maximum step size are explicit centering safety
parameters in the Klipper config.

## Installation without cloning on the printer

The printer does not need Git or a repository checkout. Download and run the
bootstrap script on the Klipper host:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/IDcrazy123/Tool-Vision/main/install.sh \
  -o /tmp/tool-vision-install.sh
bash /tmp/tool-vision-install.sh
```

The script downloads a temporary source archive, copies only the required
runtime files into `~/printer_data/tool-vision`, and removes the temporary
archive when it exits. Tests, documentation, Axiscope, kTAMV, and Git metadata
are not installed on the printer. Only the editable
`~/printer_data/config/Tool-Vision/tool_vision.cfg` is exposed in Mainsail.

An extracted local source bundle can also be transferred to the Pi and run
offline with `./install.sh`; the persisted runtime is the same and the source
bundle can be removed afterward.

The installer discovers the actual login user, home directory, Klipper path,
and virtual-environment path. Override when needed:

```bash
KLIPPER_DIR=/opt/klipper \
TOOL_VISION_RUNTIME_DIR=/opt/tool-vision \
TOOL_VISION_CONFIG_DIR=/opt/printer_data/config \
TOOL_VISION_VENV=/opt/tool-vision-env \
TOOL_VISION_HOST=127.0.0.1 \
TOOL_VISION_PORT=8085 \
./install.sh
```

It installs an isolated venv, links the Klipper extension to the persisted
runtime, generates a systemd unit from the real paths, replaces the legacy
`tool_vision.service`, and restarts Klipper. Existing `tool_vision.cfg` values
are preserved and `printer.cfg` is never edited automatically.

## Required hardware configuration

1. Mount and configure an upward-facing nozzle camera.
2. With T0 active, manually place the nozzle at the intended optical focus.
3. Record `camera_x_pos`, `camera_y_pos`, and `camera_z_pos`.
4. Choose `camera_safe_z` high enough to clear all stationary hardware before
   XY station travel.
5. Measure the Z-switch X/Y/contact Z and choose `zswitch_safe_z`.
6. Verify switch pin polarity with a read-only endstop query before probing.
7. Set all motion speeds conservatively for the target machine.

Camera station values are intentionally commented in the example config. Tool
Vision refuses movement until all four values exist.

## Enable on Klipper

First disable any active `[axiscope]` section and keep `[tools_calibrate]`
disabled. Then include the configured file from a location deployed on the
printer:

```ini
[include path/to/tool_vision.cfg]
```

Run `FIRMWARE_RESTART` and verify:

```gcode
TV_STATUS
TV_SERVER_CONFIGURE
TV_CAMERA_CHECK
```

The processed frame is available locally at:

```text
http://127.0.0.1:8085/api/v1/frame
```

Bind the service to `0.0.0.0` only when LAN access is required and protected by
the local network/firewall.

## Progressive commissioning

Do not begin with a full five-tool run. Commission in this order:

1. `TV_CAMERA_CHECK` while the clean T0 nozzle is manually visible.
2. `TV_MOVE_TO_CAMERA` at low speeds; confirm safe-Z-before-XY motion.
3. `TV_CALIBRATE_CAMERA TOOL=0`; inspect RMS and condition values.
4. `TV_MEASURE_XY TOOL=0 REFERENCE=1` twice; confirm repeatability.
5. `TV_MOVE_TO_ZSWITCH`; confirm approach height without probing.
6. `TV_MEASURE_Z TOOL=0 REFERENCE=1`; repeat and compare trigger Z.
7. Measure one non-reference tool.
8. Only then run `TV_CALIBRATE_ALL MODE=XYZ`.

## G-code commands

| Command | Purpose |
|---|---|
| `TV_STATUS` | Klipper/server status and last error |
| `TV_SERVER_CONFIGURE` | Send current `.cfg` camera/detector values |
| `TV_CAMERA_CHECK` | Detect at the current position without motion |
| `TV_MOVE_TO_CAMERA` | Safe move to the camera station |
| `TV_MOVE_TO_ZSWITCH` | Safe move to the switch approach point |
| `TV_CALIBRATE_CAMERA [TOOL=0]` | Fit pixel-to-machine movement |
| `TV_MEASURE_XY TOOL=n [REFERENCE=1]` | Center and measure XY |
| `TV_MEASURE_Z TOOL=n [REFERENCE=1]` | Probe and measure Z |
| `TV_CALIBRATE_ALL MODE=XYZ` | Measure all configured tools |
| `TV_REPORT` | Reprint the current report |

`MODE` may be `XYZ`, `XY`, or `Z`. Tool discovery uses
`printer.toolchanger.tool_numbers` unless `tool_numbers` is explicitly set.

## Results and applying offsets

Results are written atomically to `result_file`, separate from all Klipper
configuration files. The console prints measured values and suggested
`SET_TOOL_PARAMETER` commands. Tool Vision never executes those commands and
never calls `SAVE_TOOL_PARAMETER` or `SAVE_CONFIG`.

Before applying anything:

- repeat the measurement at least three times;
- compare spread and confidence;
- keep the production offset backup;
- validate XY with a multi-tool alignment print;
- validate Z with a controlled first-layer test at real print temperatures.

## Service diagnostics

```bash
systemctl status tool-vision.service
journalctl -u tool-vision.service -n 100 --no-pager
curl http://127.0.0.1:8085/api/v1/health
```

The JSON health response reports whether the server is configured, whether a
job is active, the last native frame size, and transform quality.

## Uninstall

```bash
./uninstall.sh
```

This removes the service and Klipper symlink. It preserves the project, venv,
measurement results, and any installer-created backup. Use
`./uninstall.sh --purge-venv` only when the isolated environment should also be
removed.

## Credits

- [kTAMV](https://github.com/TypQxQ/kTAMV) by TypQxQ for the original camera
  calibration, multi-strategy detection, stability, and centering concepts.
- [Axiscope](https://github.com/nic335/Axiscope) / N3MI-DG for the original
  camera alignment workflow and multi-axis Z-switch integration.

Tool Vision 2 is a new implementation adapted for configurable hardware,
native camera resolutions, explicit quality metrics, and safer Klipper motion.
