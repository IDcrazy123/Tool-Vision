#!/usr/bin/env python3
"""Validate Git metadata against Moonraker's git_repo version contract."""

import argparse
import pathlib
import re
import subprocess
import sys

_GIT_DESCRIPTION_RE = re.compile(
    r"^(?P<tag>v[0-9]+(?:\.[0-9]+)+"
    r"(?:[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview)[-_.]?[0-9]*)?)"
    r"(?:-(?P<count>[0-9]+)(?:-g(?P<sha>[a-fA-F0-9]+))?)?"
    r"(?P<dirty>-dirty)?(?P<inferred>-(?:inferred|shallow))?$",
    re.IGNORECASE,
)


class ReleaseMetadataError(RuntimeError):
    """Git metadata would be reported as an unknown Moonraker version."""


def validate_git_description(description, expected_version):
    """Return the release tag or raise when Moonraker cannot report it safely."""
    description = str(description).strip()
    match = _GIT_DESCRIPTION_RE.match(description)
    if match is None:
        raise ReleaseMetadataError(
            "git describe does not start from a Moonraker-compatible semantic "
            "release tag: %s" % description
        )
    if match.group("dirty"):
        raise ReleaseMetadataError("release worktree is dirty: %s" % description)
    expected_tag = "v%s" % str(expected_version).strip()
    detected_tag = match.group("tag")
    if detected_tag != expected_tag:
        raise ReleaseMetadataError(
            "Git tag %s does not match runtime version %s"
            % (detected_tag, expected_version)
        )
    return detected_tag


def _git_description(repo):
    try:
        return subprocess.check_output(
            (
                "git", "-C", str(repo), "describe", "--always", "--tags",
                "--long", "--dirty", "--abbrev=8",
            ),
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        output = getattr(exc, "output", "")
        raise ReleaseMetadataError("cannot run git describe: %s" % (output or exc))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True, help="runtime version without v")
    parser.add_argument(
        "--repo",
        default=str(pathlib.Path(__file__).resolve().parents[1]),
        help="ToolVision Git checkout",
    )
    args = parser.parse_args(argv)
    try:
        description = _git_description(pathlib.Path(args.repo).resolve())
        tag = validate_git_description(description, args.expected)
    except ReleaseMetadataError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    print("Moonraker version metadata OK: %s (%s)" % (tag, description))
    return 0


if __name__ == "__main__":
    sys.exit(main())
