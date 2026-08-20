#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${TOOL_VISION_SOURCE_DIR:-${SCRIPT_DIR}}"
ARCHIVE_URL="${TOOL_VISION_ARCHIVE_URL:-https://github.com/IDcrazy123/Tool-Vision/archive/refs/heads/main.tar.gz}"
BOOTSTRAP_DIR=""
TEMP_UNIT=""

cleanup() {
    if [[ -n "${TEMP_UNIT}" && -f "${TEMP_UNIT}" ]]; then
        rm -f -- "${TEMP_UNIT}"
    fi
    if [[ -n "${BOOTSTRAP_DIR}" && -d "${BOOTSTRAP_DIR}" ]]; then
        case "$(basename -- "${BOOTSTRAP_DIR}")" in
            tool-vision-install.*) rm -rf -- "${BOOTSTRAP_DIR}" ;;
            *) echo "WARNING: Refusing to remove unexpected temporary path: ${BOOTSTRAP_DIR}" >&2 ;;
        esac
    fi
}
trap cleanup EXIT

source_is_complete() {
    [[ -f "$1/klippy/extras/tool_vision.py" ]] &&
        [[ -f "$1/server/requirements.txt" ]] &&
        [[ -f "$1/server/tool-vision.service.in" ]] &&
        [[ -f "$1/tool_vision.cfg" ]] &&
        [[ -f "$1/uninstall.sh" ]]
}

bootstrap_source_if_needed() {
    if source_is_complete "${SOURCE_DIR}"; then
        SOURCE_DIR="$(cd -- "${SOURCE_DIR}" && pwd)"
        return
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "ERROR: curl is required when install.sh is run without a local source bundle." >&2
        exit 1
    fi
    if ! command -v tar >/dev/null 2>&1; then
        echo "ERROR: tar is required when install.sh is run without a local source bundle." >&2
        exit 1
    fi

    BOOTSTRAP_DIR="$(mktemp -d -t tool-vision-install.XXXXXX)"
    mkdir -p -- "${BOOTSTRAP_DIR}/source"
    echo "Downloading a temporary Tool Vision source archive..."
    curl --fail --location --silent --show-error \
        "${ARCHIVE_URL}" -o "${BOOTSTRAP_DIR}/source.tar.gz"
    tar -xzf "${BOOTSTRAP_DIR}/source.tar.gz" \
        -C "${BOOTSTRAP_DIR}/source" --strip-components=1
    SOURCE_DIR="${BOOTSTRAP_DIR}/source"

    if ! source_is_complete "${SOURCE_DIR}"; then
        echo "ERROR: Downloaded archive does not contain a complete Tool Vision source bundle." >&2
        exit 1
    fi
}

require_file() {
    if [[ ! -f "$1" ]]; then
        echo "ERROR: Required file not found: $1" >&2
        exit 1
    fi
}

escape_sed() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

install_runtime_file() {
    local source_path="$1"
    local target_path="$2"
    local mode="${3:-0644}"

    if [[ -e "${target_path}" ]] &&
        [[ "$(readlink -f -- "${source_path}")" == "$(readlink -f -- "${target_path}")" ]]; then
        return
    fi
    sudo -u "${INSTALL_USER}" install -D -m "${mode}" \
        "${source_path}" "${target_path}"
}

bootstrap_source_if_needed

INSTALL_USER="${TOOL_VISION_USER:-${SUDO_USER:-$(id -un)}}"
INSTALL_GROUP="$(id -gn "${INSTALL_USER}")"
USER_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
KLIPPER_DIR="${KLIPPER_DIR:-${USER_HOME}/klipper}"
RUNTIME_DIR="${TOOL_VISION_RUNTIME_DIR:-${USER_HOME}/printer_data/tool-vision}"
CONFIG_DIR="${TOOL_VISION_CONFIG_DIR:-${USER_HOME}/printer_data/config}"
CONFIG_TARGET="${CONFIG_DIR}/Tool-Vision/tool_vision.cfg"
VENV_DIR="${TOOL_VISION_VENV:-${USER_HOME}/tool-vision-env}"
SERVICE_NAME="tool-vision.service"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}"
KLIPPER_TARGET="${KLIPPER_DIR}/klippy/extras/tool_vision.py"
LISTEN_HOST="${TOOL_VISION_HOST:-127.0.0.1}"
LISTEN_PORT="${TOOL_VISION_PORT:-8085}"
LOG_DIR="${TOOL_VISION_LOG_DIR:-${USER_HOME}/printer_data/logs/tool-vision}"

echo "Tool Vision 2 installer"
echo "  Source  : ${SOURCE_DIR}"
echo "  Runtime : ${RUNTIME_DIR}"
echo "  Config  : ${CONFIG_TARGET}"
echo "  User    : ${INSTALL_USER}"
echo "  Klipper : ${KLIPPER_DIR}"
echo "  Venv    : ${VENV_DIR}"

require_file "${SOURCE_DIR}/klippy/extras/tool_vision.py"
require_file "${SOURCE_DIR}/server/__init__.py"
require_file "${SOURCE_DIR}/server/app.py"
require_file "${SOURCE_DIR}/server/camera.py"
require_file "${SOURCE_DIR}/server/detection.py"
require_file "${SOURCE_DIR}/server/requirements.txt"
require_file "${SOURCE_DIR}/server/tool-vision.service.in"
require_file "${SOURCE_DIR}/server/transform.py"
require_file "${SOURCE_DIR}/tool_vision.cfg"
require_file "${SOURCE_DIR}/install.sh"
require_file "${SOURCE_DIR}/uninstall.sh"
if [[ ! -d "${KLIPPER_DIR}/klippy/extras" ]]; then
    echo "ERROR: Klipper extras directory not found under ${KLIPPER_DIR}" >&2
    echo "Set KLIPPER_DIR=/actual/path and run this installer again." >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required." >&2
    exit 1
fi

echo "[1/6] Persisting the minimal runtime on the printer..."
install_runtime_file "${SOURCE_DIR}/install.sh" "${RUNTIME_DIR}/install.sh" 0755
install_runtime_file "${SOURCE_DIR}/uninstall.sh" "${RUNTIME_DIR}/uninstall.sh" 0755
install_runtime_file "${SOURCE_DIR}/tool_vision.cfg" "${RUNTIME_DIR}/tool_vision.cfg"
install_runtime_file "${SOURCE_DIR}/klippy/extras/tool_vision.py" \
    "${RUNTIME_DIR}/klippy/extras/tool_vision.py"
for server_file in __init__.py app.py camera.py detection.py requirements.txt \
    tool-vision.service.in transform.py; do
    install_runtime_file "${SOURCE_DIR}/server/${server_file}" \
        "${RUNTIME_DIR}/server/${server_file}"
done

sudo -u "${INSTALL_USER}" mkdir -p -- "$(dirname -- "${CONFIG_TARGET}")"
if [[ ! -e "${CONFIG_TARGET}" ]]; then
    install_runtime_file "${RUNTIME_DIR}/tool_vision.cfg" "${CONFIG_TARGET}"
    echo "  Created the editable config at ${CONFIG_TARGET}"
else
    echo "  Preserved the existing editable config at ${CONFIG_TARGET}"
fi

echo "[2/6] Creating/updating the isolated host-service environment..."
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    sudo -u "${INSTALL_USER}" python3 -m venv "${VENV_DIR}"
fi
sudo -u "${INSTALL_USER}" "${VENV_DIR}/bin/python" -m pip install --upgrade pip
sudo -u "${INSTALL_USER}" "${VENV_DIR}/bin/python" -m pip install \
    -r "${RUNTIME_DIR}/server/requirements.txt"

echo "[3/6] Linking the persisted Klipper extension..."
if [[ -e "${KLIPPER_TARGET}" && ! -L "${KLIPPER_TARGET}" ]]; then
    BACKUP_TARGET="${KLIPPER_TARGET}.pre-tool-vision-$(date +%Y%m%d-%H%M%S)"
    sudo -u "${INSTALL_USER}" cp -a -- "${KLIPPER_TARGET}" "${BACKUP_TARGET}"
    echo "  Preserved existing regular file as ${BACKUP_TARGET}"
fi
sudo -u "${INSTALL_USER}" ln -sfn -- \
    "${RUNTIME_DIR}/klippy/extras/tool_vision.py" "${KLIPPER_TARGET}"

echo "[4/6] Installing a path-independent systemd unit..."
sudo -u "${INSTALL_USER}" mkdir -p -- "${LOG_DIR}"
TEMP_UNIT="$(mktemp)"
sed \
    -e "s|@USER@|$(escape_sed "${INSTALL_USER}")|g" \
    -e "s|@PROJECT_DIR@|$(escape_sed "${RUNTIME_DIR}")|g" \
    -e "s|@PYTHON@|$(escape_sed "${VENV_DIR}/bin/python")|g" \
    -e "s|@HOST@|$(escape_sed "${LISTEN_HOST}")|g" \
    -e "s|@PORT@|$(escape_sed "${LISTEN_PORT}")|g" \
    -e "s|@LOG_DIR@|$(escape_sed "${LOG_DIR}")|g" \
    "${RUNTIME_DIR}/server/tool-vision.service.in" > "${TEMP_UNIT}"
sudo install -m 0644 "${TEMP_UNIT}" "${SERVICE_TARGET}"

echo "[5/6] Removing the legacy underscore-named service if present..."
if systemctl list-unit-files tool_vision.service >/dev/null 2>&1; then
    sudo systemctl disable --now tool_vision.service || true
    sudo rm -f -- /etc/systemd/system/tool_vision.service
fi

echo "[6/6] Starting Tool Vision and restarting Klipper..."
sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl restart klipper

echo
echo "Installation complete. No Git repository was created on the printer."
echo "Runtime: ${RUNTIME_DIR}"
echo "Editable Mainsail config: ${CONFIG_TARGET}"
echo "Next steps:"
echo "  1. Set real camera_x/y/z_pos and camera_safe_z in tool_vision.cfg."
echo "  2. Disable [axiscope] and [tools_calibrate]."
echo "  3. Include Tool-Vision/tool_vision.cfg from printer.cfg."
echo "  4. FIRMWARE_RESTART, then run TV_STATUS and TV_CAMERA_CHECK."
echo "Service health: http://${LISTEN_HOST}:${LISTEN_PORT}/api/v1/health"
