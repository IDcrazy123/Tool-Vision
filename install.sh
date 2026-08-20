#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="${TOOL_VISION_USER:-${SUDO_USER:-$(id -un)}}"
INSTALL_GROUP="$(id -gn "${INSTALL_USER}")"
USER_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
KLIPPER_DIR="${KLIPPER_DIR:-${USER_HOME}/klipper}"
VENV_DIR="${TOOL_VISION_VENV:-${USER_HOME}/tool-vision-env}"
SERVICE_NAME="tool-vision.service"
SERVICE_TEMPLATE="${PROJECT_DIR}/server/tool-vision.service.in"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}"
KLIPPER_TARGET="${KLIPPER_DIR}/klippy/extras/tool_vision.py"
LISTEN_HOST="${TOOL_VISION_HOST:-127.0.0.1}"
LISTEN_PORT="${TOOL_VISION_PORT:-8085}"
LOG_DIR="${TOOL_VISION_LOG_DIR:-${USER_HOME}/printer_data/logs/tool-vision}"
TEMP_UNIT=""

cleanup() {
    if [[ -n "${TEMP_UNIT}" && -f "${TEMP_UNIT}" ]]; then
        rm -f -- "${TEMP_UNIT}"
    fi
}
trap cleanup EXIT

require_file() {
    if [[ ! -f "$1" ]]; then
        echo "ERROR: Required file not found: $1" >&2
        exit 1
    fi
}

escape_sed() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

echo "Tool Vision 2 installer"
echo "  Project : ${PROJECT_DIR}"
echo "  User    : ${INSTALL_USER}"
echo "  Klipper : ${KLIPPER_DIR}"
echo "  Venv    : ${VENV_DIR}"

require_file "${PROJECT_DIR}/klippy/extras/tool_vision.py"
require_file "${PROJECT_DIR}/server/requirements.txt"
require_file "${SERVICE_TEMPLATE}"
if [[ ! -d "${KLIPPER_DIR}/klippy/extras" ]]; then
    echo "ERROR: Klipper extras directory not found under ${KLIPPER_DIR}" >&2
    echo "Set KLIPPER_DIR=/actual/path and run this installer again." >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required." >&2
    exit 1
fi

echo "[1/5] Creating/updating the isolated host-service environment..."
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    sudo -u "${INSTALL_USER}" python3 -m venv "${VENV_DIR}"
fi
sudo -u "${INSTALL_USER}" "${VENV_DIR}/bin/python" -m pip install --upgrade pip
sudo -u "${INSTALL_USER}" "${VENV_DIR}/bin/python" -m pip install \
    -r "${PROJECT_DIR}/server/requirements.txt"

echo "[2/5] Linking the Klipper extension..."
if [[ -e "${KLIPPER_TARGET}" && ! -L "${KLIPPER_TARGET}" ]]; then
    BACKUP_TARGET="${KLIPPER_TARGET}.pre-tool-vision-$(date +%Y%m%d-%H%M%S)"
    cp -a -- "${KLIPPER_TARGET}" "${BACKUP_TARGET}"
    echo "  Preserved existing regular file as ${BACKUP_TARGET}"
fi
ln -sfn -- "${PROJECT_DIR}/klippy/extras/tool_vision.py" "${KLIPPER_TARGET}"

echo "[3/5] Installing a path-independent systemd unit..."
mkdir -p -- "${LOG_DIR}"
chown "${INSTALL_USER}:${INSTALL_GROUP}" "${LOG_DIR}"
TEMP_UNIT="$(mktemp)"
sed \
    -e "s|@USER@|$(escape_sed "${INSTALL_USER}")|g" \
    -e "s|@PROJECT_DIR@|$(escape_sed "${PROJECT_DIR}")|g" \
    -e "s|@PYTHON@|$(escape_sed "${VENV_DIR}/bin/python")|g" \
    -e "s|@HOST@|$(escape_sed "${LISTEN_HOST}")|g" \
    -e "s|@PORT@|$(escape_sed "${LISTEN_PORT}")|g" \
    -e "s|@LOG_DIR@|$(escape_sed "${LOG_DIR}")|g" \
    "${SERVICE_TEMPLATE}" > "${TEMP_UNIT}"
sudo install -m 0644 "${TEMP_UNIT}" "${SERVICE_TARGET}"

echo "[4/5] Removing the legacy underscore-named service if present..."
if systemctl list-unit-files tool_vision.service >/dev/null 2>&1; then
    sudo systemctl disable --now tool_vision.service || true
    sudo rm -f -- /etc/systemd/system/tool_vision.service
fi

echo "[5/5] Starting Tool Vision and restarting Klipper..."
sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl restart klipper

echo
echo "Installation complete. The production config was not edited."
echo "Next steps:"
echo "  1. Set real camera_x/y/z_pos and camera_safe_z in tool_vision.cfg."
echo "  2. Disable [axiscope] and [tools_calibrate]."
echo "  3. Include tool_vision.cfg from printer.cfg."
echo "  4. FIRMWARE_RESTART, then run TV_STATUS and TV_CAMERA_CHECK."
echo "Service health: http://${LISTEN_HOST}:${LISTEN_PORT}/api/v1/health"
