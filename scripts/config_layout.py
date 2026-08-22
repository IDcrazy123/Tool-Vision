#!/usr/bin/env python3
"""Prepare ToolVision files without editing Klipper or Moonraker configs.

The installer owns the runtime and the editable ToolVision file only. Users add
the short Klipper include and optional Moonraker updater section themselves.
Before any file is copied, this helper creates a local, verified backup set.
"""

import argparse
import fnmatch
import hashlib
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile

KLIPPER_INCLUDE = "[include tool_vision.cfg]"

_TOOLVISION_CFG_INCLUDE_RE = re.compile(
    r"^[ \t]*\[include[ \t]+(?:(?:Tool-Vision|Printer-Setup)/)?"
    r"tool_vision\.cfg\][ \t]*(?:[#;].*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_TOOLVISION_UPDATER_RE = re.compile(
    r"^[ \t]*\[update_manager[ \t]+tool-vision\][ \t]*(?:[#;].*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_LEGACY_UPDATER_INCLUDE_RE = re.compile(
    r"^[ \t]*\[include[ \t]+Tool-Vision/"
    r"moonraker_update_manager\.conf\][ \t]*(?:[#;].*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_INCLUDE_VALUE_RE = re.compile(
    r"^[ \t]*\[include[ \t]+([^\]\r\n]+)\][ \t]*(?:[#;].*)?$",
    re.IGNORECASE | re.MULTILINE,
)


class LayoutError(RuntimeError):
    """A configuration migration cannot be completed without risking data."""


def _path(value):
    return pathlib.Path(value).expanduser().resolve()


def _validate_paths(config_dir, backup_dir):
    config_dir = _path(config_dir)
    backup_dir = _path(backup_dir)
    if backup_dir == config_dir or config_dir in backup_dir.parents:
        raise LayoutError(
            "backup directory must be outside the active config root: %s"
            % backup_dir
        )
    return config_dir, backup_dir


def _require_file(path, label):
    if not path.is_file():
        raise LayoutError("%s not found: %s" % (label, path))


def _read_text(path):
    try:
        with path.open("r", encoding="utf-8", newline=None) as handle:
            return handle.read()
    except (OSError, UnicodeError) as exc:
        raise LayoutError("cannot read %s: %s" % (path, exc))


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()


def _same_content(left, right):
    return (
        left.stat().st_size == right.stat().st_size
        and _sha256(left) == _sha256(right)
    )


def _copy_atomic(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".tool-vision-", dir=str(target.parent)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(str(temporary), stat.S_IMODE(source.stat().st_mode))
        os.replace(str(temporary), str(target))
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _backup_file(source, backup_dir, relative_path):
    target = backup_dir / relative_path
    if target.exists():
        raise LayoutError("refusing to overwrite backup: %s" % target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    if not _same_content(source, target):
        raise LayoutError("backup verification failed: %s" % target)
    return target


def _safe_config_value(value, label):
    value = str(value)
    if not value or "\n" in value or "\r" in value:
        raise LayoutError("invalid %s for Moonraker updater" % label)
    return value


def render_updater_block(repo_dir, origin, primary_branch, virtualenv):
    """Return the optional Moonraker block shown to the user for copy/paste."""
    values = {
        "repo_dir": _safe_config_value(repo_dir, "repository path"),
        "origin": _safe_config_value(origin, "origin"),
        "primary_branch": _safe_config_value(primary_branch, "primary branch"),
        "virtualenv": _safe_config_value(virtualenv, "virtualenv"),
    }
    return "\n".join(
        (
            "[update_manager tool-vision]",
            "type: git_repo",
            "channel: dev",
            "path: %(repo_dir)s" % values,
            "origin: %(origin)s" % values,
            "primary_branch: %(primary_branch)s" % values,
            "virtualenv: %(virtualenv)s" % values,
            "requirements: server/requirements.txt",
            "managed_services: tool-vision klipper",
            "info_tags:",
            "  desc=ToolVision automatic XYZ tool-offset calibration",
        )
    )


def _has_explicit_option(config_path, option):
    content = _read_text(config_path)
    pattern = re.compile(
        r"^[ \t]*%s[ \t]*[:=]" % re.escape(option), re.MULTILINE
    )
    return bool(pattern.search(content))


def _printer_loads_toolvision(content):
    """Recognize the documented include and wildcards that load the same file."""
    if _TOOLVISION_CFG_INCLUDE_RE.search(content):
        return True
    targets = (
        "tool_vision.cfg",
        "Printer-Setup/tool_vision.cfg",
        "Tool-Vision/tool_vision.cfg",
    )
    for match in _INCLUDE_VALUE_RE.finditer(content):
        pattern = match.group(1).strip().replace("\\", "/")
        if any(
            fnmatch.fnmatchcase(target.lower(), pattern.lower())
            for target in targets
        ):
            return True
    return False


def _prepare_install_layout(
    config_dir, config_source, printer_config, moonraker_config, backup_dir
):
    config_dir, backup_dir = _validate_paths(config_dir, backup_dir)
    config_source = _path(config_source)
    printer_config = _path(printer_config)
    moonraker_config = _path(moonraker_config)
    _require_file(config_source, "ToolVision config template")
    _require_file(printer_config, "Klipper printer config")
    _require_file(moonraker_config, "Moonraker config")
    _read_text(printer_config)
    _read_text(moonraker_config)

    # Follow the actual main Klipper config instead of assuming a particular
    # Moonraker data layout. This also keeps the documented relative include
    # valid when PRINTER_CONFIG points at a custom location.
    target_dir = printer_config.parent
    config_target = target_dir / "tool_vision.cfg"
    if config_target.exists() and not config_target.is_file():
        raise LayoutError("editable config target is not a file: %s" % config_target)
    for filename in ("tool_vision_state.json", "tool_vision_results.json"):
        generated_target = target_dir / filename
        if generated_target.exists() and not generated_target.is_file():
            raise LayoutError(
                "generated data target is not a file: %s" % generated_target
            )
    return {
        "config_dir": config_dir,
        "backup_dir": backup_dir,
        "config_source": config_source,
        "printer_config": printer_config,
        "moonraker_config": moonraker_config,
        "target_dir": target_dir,
        "config_target": config_target,
    }


def preflight_install_layout(
    config_dir, config_source, printer_config, moonraker_config, backup_dir
):
    """Validate every layout input that can be checked without writing."""
    return _prepare_install_layout(
        config_dir, config_source, printer_config, moonraker_config, backup_dir
    )["backup_dir"]


def _backup_layout(prepared):
    """Back up every user file in scope before migration copies start."""
    config_dir = prepared["config_dir"]
    backup_dir = prepared["backup_dir"]
    target_dir = prepared["target_dir"]
    printer_setup_dir = config_dir / "Printer-Setup"
    legacy_dir = config_dir / "Tool-Vision"
    candidates = [
        (prepared["printer_config"], pathlib.Path("machine-config/printer.cfg")),
        (
            prepared["moonraker_config"],
            pathlib.Path("machine-config/moonraker.conf"),
        ),
        (
            target_dir / "tool_vision.cfg",
            pathlib.Path("current/tool_vision.cfg"),
        ),
        (
            target_dir / "tool_vision_state.json",
            pathlib.Path("current/tool_vision_state.json"),
        ),
        (
            target_dir / "tool_vision_results.json",
            pathlib.Path("current/tool_vision_results.json"),
        ),
        (
            printer_setup_dir / "tool_vision.cfg",
            pathlib.Path("legacy/Printer-Setup/tool_vision.cfg"),
        ),
        (
            printer_setup_dir / "tool_vision_state.json",
            pathlib.Path("legacy/Printer-Setup/tool_vision_state.json"),
        ),
        (
            printer_setup_dir / "tool_vision_results.json",
            pathlib.Path("legacy/Printer-Setup/tool_vision_results.json"),
        ),
        (
            legacy_dir / "tool_vision.cfg",
            pathlib.Path("legacy/Tool-Vision/tool_vision.cfg"),
        ),
        (
            legacy_dir / "tool_vision_state.json",
            pathlib.Path("legacy/Tool-Vision/tool_vision_state.json"),
        ),
        (
            legacy_dir / "tool_vision_results.json",
            pathlib.Path("legacy/Tool-Vision/tool_vision_results.json"),
        ),
        (
            legacy_dir / "moonraker_update_manager.conf",
            pathlib.Path("legacy/Tool-Vision/moonraker_update_manager.conf"),
        ),
    ]
    if target_dir != config_dir:
        for filename in (
            "tool_vision.cfg",
            "tool_vision_state.json",
            "tool_vision_results.json",
        ):
            candidates.append(
                (
                    config_dir / filename,
                    pathlib.Path("legacy/config-root") / filename,
                )
            )
    for source, relative in candidates:
        if source.is_file():
            _backup_file(source, backup_dir, relative)


def _copy_legacy_if_absent(source, target):
    if not source.is_file():
        return False
    if not target.exists():
        _copy_atomic(source, target)
        if not _same_content(source, target):
            raise LayoutError("migration verification failed: %s" % target)
        return True
    if not target.is_file():
        raise LayoutError("migration target is not a file: %s" % target)
    if not _same_content(source, target):
        print(
            "WARNING: preserving conflicting legacy file for manual comparison: %s"
            % source,
            file=sys.stderr,
        )
    return False


def install_layout(
    config_dir, config_source, printer_config, moonraker_config, backup_dir
):
    """Back up and prepare editable files without editing machine configs."""
    prepared = _prepare_install_layout(
        config_dir, config_source, printer_config, moonraker_config, backup_dir
    )
    _backup_layout(prepared)

    config_dir = prepared["config_dir"]
    target_dir = prepared["target_dir"]
    config_target = prepared["config_target"]
    legacy_dirs = [
        config_dir / "Printer-Setup",
        config_dir / "Tool-Vision",
    ]
    if target_dir != config_dir:
        legacy_dirs.append(config_dir)
    for legacy_dir in legacy_dirs:
        _copy_legacy_if_absent(legacy_dir / "tool_vision.cfg", config_target)
    if not config_target.exists():
        _copy_atomic(prepared["config_source"], config_target)
    if not config_target.is_file():
        raise LayoutError("editable config was not created: %s" % config_target)

    generated = (
        ("state_file", "tool_vision_state.json"),
        ("result_file", "tool_vision_results.json"),
    )
    for option, filename in generated:
        if _has_explicit_option(config_target, option):
            continue
        target = target_dir / filename
        for legacy_dir in legacy_dirs:
            _copy_legacy_if_absent(legacy_dir / filename, target)

    # Legacy files remain because printer.cfg/moonraker.conf are user-managed.
    # The README explains when they may be removed after manual include changes.
    return prepared["backup_dir"]


def prepare_uninstall(config_dir, printer_config, moonraker_config, backup_dir):
    """Back up configs and require the user to remove manual integrations."""
    config_dir, backup_dir = _validate_paths(config_dir, backup_dir)
    printer_config = _path(printer_config)
    moonraker_config = _path(moonraker_config)
    _require_file(printer_config, "Klipper printer config")
    _require_file(moonraker_config, "Moonraker config")
    printer_content = _read_text(printer_config)
    moonraker_content = _read_text(moonraker_config)

    _backup_file(
        printer_config, backup_dir, pathlib.Path("machine-config/printer.cfg")
    )
    _backup_file(
        moonraker_config, backup_dir, pathlib.Path("machine-config/moonraker.conf")
    )
    target_dir = printer_config.parent
    for filename in (
        "tool_vision.cfg",
        "tool_vision_state.json",
        "tool_vision_results.json",
    ):
        source = target_dir / filename
        if source.is_file():
            _backup_file(
                source, backup_dir, pathlib.Path("current") / filename
            )

    remaining = []
    if _printer_loads_toolvision(printer_content):
        remaining.append("ToolVision [include ...tool_vision.cfg] in printer.cfg")
    if _TOOLVISION_UPDATER_RE.search(moonraker_content):
        remaining.append("[update_manager tool-vision] in moonraker.conf")
    if _LEGACY_UPDATER_INCLUDE_RE.search(moonraker_content):
        remaining.append("legacy ToolVision updater include in moonraker.conf")
    if remaining:
        raise LayoutError(
            "manual cleanup required before uninstall; remove: %s; backups: %s"
            % (", ".join(remaining), backup_dir)
        )
    return backup_dir


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", required=True)
    common.add_argument("--printer-config", required=True)
    common.add_argument("--moonraker-config", required=True)
    common.add_argument("--backup-dir", required=True)

    install = subparsers.add_parser("install", parents=[common])
    install.add_argument("--config-source", required=True)
    install.add_argument("--check-only", action="store_true")
    subparsers.add_parser("uninstall", parents=[common])
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            operation = (
                preflight_install_layout if args.check_only else install_layout
            )
            operation(
                config_dir=args.config_dir,
                config_source=args.config_source,
                printer_config=args.printer_config,
                moonraker_config=args.moonraker_config,
                backup_dir=args.backup_dir,
            )
        else:
            prepare_uninstall(
                config_dir=args.config_dir,
                printer_config=args.printer_config,
                moonraker_config=args.moonraker_config,
                backup_dir=args.backup_dir,
            )
    except (LayoutError, OSError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
