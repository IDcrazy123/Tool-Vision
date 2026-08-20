#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_USER="${TOOL_VISION_USER:-${SUDO_USER:-$(id -un)}}"
USER_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
KLIPPER_DIR="${KLIPPER_DIR:-${USER_HOME}/klipper}"
VENV_DIR="${TOOL_VISION_VENV:-${USER_HOME}/tool-vision-env}"
KLIPPER_TARGET="${KLIPPER_DIR}/klippy/extras/tool_vision.py"

sudo systemctl disable --now tool-vision.service 2>/dev/null || true
sudo rm -f -- /etc/systemd/system/tool-vision.service
sudo systemctl daemon-reload

if [[ -L "${KLIPPER_TARGET}" ]]; then
    rm -f -- "${KLIPPER_TARGET}"
fi

if [[ "${1:-}" == "--purge-venv" && -d "${VENV_DIR}" ]]; then
    case "${VENV_DIR}" in
        "${USER_HOME}"/*tool-vision*) rm -rf -- "${VENV_DIR}" ;;
        *) echo "Refusing to purge unexpected venv path: ${VENV_DIR}" >&2; exit 1 ;;
    esac
fi

echo "Tool Vision service and Klipper link removed."
echo "Remove the [tool_vision] include manually before restarting Klipper."
