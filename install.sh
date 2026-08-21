#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${TOOL_VISION_SOURCE_DIR:-${SCRIPT_DIR}}"
GIT_ORIGIN_URL="${TOOL_VISION_GIT_ORIGIN:-https://github.com/IDcrazy123/Tool-Vision.git}"
GIT_BOOTSTRAP_BRANCH="${TOOL_VISION_GIT_BRANCH:-main}"
TEMP_UNIT=""
TEMP_UPDATE_CONFIG=""

cleanup() {
    if [[ -n "${TEMP_UNIT}" && -f "${TEMP_UNIT}" ]]; then
        rm -f -- "${TEMP_UNIT}"
    fi
    if [[ -n "${TEMP_UPDATE_CONFIG}" && -f "${TEMP_UPDATE_CONFIG}" ]]; then
        rm -f -- "${TEMP_UPDATE_CONFIG}"
    fi
}
trap cleanup EXIT

source_is_complete() {
    [[ -f "$1/klippy/extras/tool_vision.py" ]] &&
        [[ -f "$1/server/requirements.txt" ]] &&
        [[ -f "$1/server/tool-vision.service.in" ]] &&
        [[ -f "$1/moonraker_update_manager.conf.in" ]] &&
        [[ -f "$1/tool_vision.cfg" ]] &&
        [[ -f "$1/uninstall.sh" ]]
}

ensure_persistent_git_source() {
    local default_repo="${USER_HOME}/Tool-Vision"
    local git_root=""

    if command -v git >/dev/null 2>&1 &&
        git -C "${SOURCE_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git_root="$(git -C "${SOURCE_DIR}" rev-parse --show-toplevel)"
        if source_is_complete "${git_root}"; then
            SOURCE_DIR="$(cd -- "${git_root}" && pwd)"
            return
        fi
    fi
    if ! command -v git >/dev/null 2>&1; then
        echo "ERROR: git is required for Moonraker-managed ToolVision updates." >&2
        exit 1
    fi
    if [[ -e "${default_repo}" ]]; then
        if git -C "${default_repo}" rev-parse --is-inside-work-tree >/dev/null 2>&1 &&
            source_is_complete "${default_repo}"; then
            SOURCE_DIR="$(cd -- "${default_repo}" && pwd)"
            return
        fi
        echo "ERROR: ${default_repo} exists but is not a complete Git checkout." >&2
        echo "Move it aside or set TOOL_VISION_SOURCE_DIR to a clean checkout." >&2
        exit 1
    fi

    echo "Creating the persistent Git checkout required by Moonraker updates..."
    sudo -u "${INSTALL_USER}" git clone --branch "${GIT_BOOTSTRAP_BRANCH}" \
        --single-branch "${GIT_ORIGIN_URL}" "${default_repo}"
    SOURCE_DIR="$(cd -- "${default_repo}" && pwd)"
    if ! source_is_complete "${SOURCE_DIR}"; then
        echo "ERROR: Cloned repository does not contain a complete ToolVision release." >&2
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

INSTALL_USER="${TOOL_VISION_USER:-${SUDO_USER:-$(id -un)}}"
INSTALL_GROUP="$(id -gn "${INSTALL_USER}")"
USER_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"

# Validate privilege escalation before cloning or changing any user/system files.
# This prevents a non-interactive install from stopping halfway at systemd.
if ! sudo -v; then
    echo "ERROR: Administrator privileges are required to install ToolVision." >&2
    exit 1
fi

ensure_persistent_git_source
KLIPPER_DIR="${KLIPPER_DIR:-${USER_HOME}/klipper}"
RUNTIME_DIR="${SOURCE_DIR}"
CONFIG_DIR="${TOOL_VISION_CONFIG_DIR:-${USER_HOME}/printer_data/config}"
DATA_DIR="${TOOL_VISION_DATA_DIR:-$(dirname -- "${CONFIG_DIR}")}"
CONFIG_TARGET="${CONFIG_DIR}/Tool-Vision/tool_vision.cfg"
MOONRAKER_CONFIG="${MOONRAKER_CONFIG:-${CONFIG_DIR}/moonraker.conf}"
MOONRAKER_ALLOWED_SERVICES="${MOONRAKER_ALLOWED_SERVICES:-${DATA_DIR}/moonraker.asvc}"
MOONRAKER_UPDATE_CONFIG="${CONFIG_DIR}/Tool-Vision/moonraker_update_manager.conf"
MOONRAKER_INCLUDE="[include Tool-Vision/moonraker_update_manager.conf]"
MOONRAKER_SERVICE="${MOONRAKER_SERVICE:-moonraker}"
VENV_DIR="${TOOL_VISION_VENV:-${USER_HOME}/tool-vision-env}"
SERVICE_NAME="tool-vision.service"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}"
KLIPPER_EXTRAS="${KLIPPER_DIR}/klippy/extras"
LISTEN_HOST="${TOOL_VISION_HOST:-127.0.0.1}"
LISTEN_PORT="${TOOL_VISION_PORT:-8085}"
LOG_DIR="${TOOL_VISION_LOG_DIR:-${USER_HOME}/printer_data/logs/tool-vision}"
UPDATE_ORIGIN="$(git -C "${RUNTIME_DIR}" remote get-url origin)"
UPDATE_BRANCH="$(git -C "${RUNTIME_DIR}" symbolic-ref --quiet --short HEAD || true)"
REPO_CHANGES="$(git -C "${RUNTIME_DIR}" status --porcelain)"

if [[ -z "${UPDATE_BRANCH}" ]]; then
    echo "ERROR: ToolVision must be checked out on a branch, not detached HEAD." >&2
    exit 1
fi
if [[ -n "${REPO_CHANGES}" ]]; then
    echo "ERROR: Moonraker updates require a clean ToolVision Git checkout." >&2
    git -C "${RUNTIME_DIR}" status --short >&2
    echo "Commit, stash, or discard these changes before installing." >&2
    exit 1
fi
if [[ "$(readlink -f -- "${RUNTIME_DIR}")" == "$(readlink -f -- "${CONFIG_DIR}")"/* ]]; then
    echo "ERROR: ToolVision Git checkout cannot live inside ${CONFIG_DIR}." >&2
    exit 1
fi

echo "ToolVision 3 installer"
echo "  Source  : ${SOURCE_DIR}"
echo "  Runtime : ${RUNTIME_DIR}"
echo "  Config  : ${CONFIG_TARGET}"
echo "  User    : ${INSTALL_USER}"
echo "  Klipper : ${KLIPPER_DIR}"
echo "  Venv    : ${VENV_DIR}"
echo "  Updates : ${UPDATE_BRANCH} from ${UPDATE_ORIGIN}"

require_file "${SOURCE_DIR}/klippy/extras/tool_vision.py"
require_file "${SOURCE_DIR}/klippy/extras/tool_vision_client.py"
require_file "${SOURCE_DIR}/klippy/extras/tool_vision_state.py"
require_file "${SOURCE_DIR}/klippy/extras/tool_vision_toolchanger.py"
require_file "${SOURCE_DIR}/server/__init__.py"
require_file "${SOURCE_DIR}/server/app.py"
require_file "${SOURCE_DIR}/server/camera.py"
require_file "${SOURCE_DIR}/server/detection.py"
require_file "${SOURCE_DIR}/server/requirements.txt"
require_file "${SOURCE_DIR}/server/tool-vision.service.in"
require_file "${SOURCE_DIR}/moonraker_update_manager.conf.in"
require_file "${SOURCE_DIR}/server/transform.py"
require_file "${SOURCE_DIR}/tool_vision.cfg"
require_file "${SOURCE_DIR}/install.sh"
require_file "${SOURCE_DIR}/uninstall.sh"
if [[ ! -d "${KLIPPER_EXTRAS}" ]]; then
    echo "ERROR: Klipper extras directory not found under ${KLIPPER_DIR}" >&2
    echo "Set KLIPPER_DIR=/actual/path and run this installer again." >&2
    exit 1
fi
if [[ ! -f "${KLIPPER_EXTRAS}/tools_calibrate.py" ]]; then
    echo "ERROR: tools_calibrate.py from klipper-toolchanger is required." >&2
    echo "Install/update https://github.com/viesturz/klipper-toolchanger first." >&2
    echo "The [tools_calibrate] cfg section itself must remain disabled." >&2
    exit 1
fi
if [[ ! -f "${MOONRAKER_CONFIG}" ]]; then
    echo "ERROR: Moonraker config not found at ${MOONRAKER_CONFIG}." >&2
    echo "Set MOONRAKER_CONFIG=/actual/path and run this installer again." >&2
    exit 1
fi
if [[ ! -f "${MOONRAKER_ALLOWED_SERVICES}" ]]; then
    echo "ERROR: Moonraker allowed-services file not found at ${MOONRAKER_ALLOWED_SERVICES}." >&2
    echo "Start Moonraker once, or set TOOL_VISION_DATA_DIR to its actual data directory." >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required." >&2
    exit 1
fi

echo "[1/7] Using the persistent Git runtime on the printer..."
install_runtime_file "${SOURCE_DIR}/install.sh" "${RUNTIME_DIR}/install.sh" 0755
install_runtime_file "${SOURCE_DIR}/uninstall.sh" "${RUNTIME_DIR}/uninstall.sh" 0755
install_runtime_file "${SOURCE_DIR}/tool_vision.cfg" "${RUNTIME_DIR}/tool_vision.cfg"
for klipper_file in tool_vision.py tool_vision_client.py tool_vision_state.py \
    tool_vision_toolchanger.py; do
    install_runtime_file "${SOURCE_DIR}/klippy/extras/${klipper_file}" \
        "${RUNTIME_DIR}/klippy/extras/${klipper_file}"
done
for server_file in __init__.py app.py camera.py detection.py requirements.txt \
    tool-vision.service.in transform.py; do
    install_runtime_file "${SOURCE_DIR}/server/${server_file}" \
        "${RUNTIME_DIR}/server/${server_file}"
done

sudo -u "${INSTALL_USER}" mkdir -p -- "$(dirname -- "${CONFIG_TARGET}")"
if [[ ! -e "${CONFIG_TARGET}" ]]; then
    install_runtime_file "${RUNTIME_DIR}/tool_vision.cfg" "${CONFIG_TARGET}"
    echo "  Created the editable config at ${CONFIG_TARGET}"
elif grep -Eq '^# Tool( )?Vision 2' "${CONFIG_TARGET}"; then
    CONFIG_BACKUP="${CONFIG_TARGET}.pre-v3-$(date +%Y%m%d-%H%M%S)"
    sudo -u "${INSTALL_USER}" cp -a -- "${CONFIG_TARGET}" "${CONFIG_BACKUP}"
    sudo -u "${INSTALL_USER}" install -m 0644 \
        "${RUNTIME_DIR}/tool_vision.cfg" "${CONFIG_TARGET}"
    echo "  Migrated generated v2 config; backup: ${CONFIG_BACKUP}"
else
    echo "  Preserved the existing editable config at ${CONFIG_TARGET}"
fi

echo "[2/7] Creating/updating the isolated host-service environment..."
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    sudo -u "${INSTALL_USER}" python3 -m venv "${VENV_DIR}"
fi
sudo -u "${INSTALL_USER}" "${VENV_DIR}/bin/python" -m pip install --upgrade pip
sudo -u "${INSTALL_USER}" "${VENV_DIR}/bin/python" -m pip install \
    -r "${RUNTIME_DIR}/server/requirements.txt"

echo "[3/7] Linking the persisted Klipper extension modules..."
for klipper_file in tool_vision.py tool_vision_client.py tool_vision_state.py \
    tool_vision_toolchanger.py; do
    KLIPPER_TARGET="${KLIPPER_EXTRAS}/${klipper_file}"
    if [[ -e "${KLIPPER_TARGET}" && ! -L "${KLIPPER_TARGET}" ]]; then
        BACKUP_TARGET="${KLIPPER_TARGET}.pre-tool-vision-$(date +%Y%m%d-%H%M%S)"
        sudo -u "${INSTALL_USER}" cp -a -- "${KLIPPER_TARGET}" "${BACKUP_TARGET}"
        echo "  Preserved existing regular file as ${BACKUP_TARGET}"
    fi
    sudo -u "${INSTALL_USER}" ln -sfn -- \
        "${RUNTIME_DIR}/klippy/extras/${klipper_file}" "${KLIPPER_TARGET}"
done

echo "[4/7] Installing a path-independent systemd unit..."
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

echo "[5/7] Registering ToolVision with Moonraker Update Manager..."
TEMP_UPDATE_CONFIG="$(mktemp)"
sed \
    -e "s|@REPO_DIR@|$(escape_sed "${RUNTIME_DIR}")|g" \
    -e "s|@ORIGIN@|$(escape_sed "${UPDATE_ORIGIN}")|g" \
    -e "s|@PRIMARY_BRANCH@|$(escape_sed "${UPDATE_BRANCH}")|g" \
    -e "s|@VIRTUALENV@|$(escape_sed "${VENV_DIR}")|g" \
    "${RUNTIME_DIR}/moonraker_update_manager.conf.in" > "${TEMP_UPDATE_CONFIG}"
sudo -u "${INSTALL_USER}" install -D -m 0644 \
    "${TEMP_UPDATE_CONFIG}" "${MOONRAKER_UPDATE_CONFIG}"

# Moonraker supports Klipper-style includes. Keep the generated updater section
# separate from moonraker.conf so reinstalling never rewrites user-owned options.
if ! grep -Eq \
    '^[[:space:]]*\[include[[:space:]]+Tool-Vision/(moonraker_update_manager\.conf|\*\.conf)\][[:space:]]*(#.*)?$' \
    "${MOONRAKER_CONFIG}"; then
    MOONRAKER_BACKUP="${MOONRAKER_CONFIG}.pre-tool-vision-$(date +%Y%m%d-%H%M%S)"
    sudo -u "${INSTALL_USER}" cp -a -- "${MOONRAKER_CONFIG}" "${MOONRAKER_BACKUP}"
    printf '\n# ToolVision updater (managed by ToolVision install.sh)\n%s\n' \
        "${MOONRAKER_INCLUDE}" | \
        sudo -u "${INSTALL_USER}" tee -a "${MOONRAKER_CONFIG}" >/dev/null
    echo "  Added ${MOONRAKER_INCLUDE}; backup: ${MOONRAKER_BACKUP}"
else
    echo "  Moonraker include already present"
fi

# Current Moonraker releases require third-party services to be explicitly
# authorized before Update Manager may restart them. Preserve the generated
# default list and append only ToolVision's exact, case-sensitive unit name.
if ! grep -Fxq 'tool-vision' "${MOONRAKER_ALLOWED_SERVICES}"; then
    ALLOWED_SERVICES_BACKUP="${MOONRAKER_ALLOWED_SERVICES}.pre-tool-vision-$(date +%Y%m%d-%H%M%S)"
    sudo -u "${INSTALL_USER}" cp -a -- \
        "${MOONRAKER_ALLOWED_SERVICES}" "${ALLOWED_SERVICES_BACKUP}"
    # Start with a newline because third-party installers may have written the
    # existing final entry without a trailing line ending.
    printf '\ntool-vision\n' | \
        sudo -u "${INSTALL_USER}" tee -a "${MOONRAKER_ALLOWED_SERVICES}" >/dev/null
    echo "  Authorized tool-vision service; backup: ${ALLOWED_SERVICES_BACKUP}"
else
    echo "  tool-vision service already authorized"
fi

echo "[6/7] Removing the legacy underscore-named service if present..."
if systemctl list-unit-files tool_vision.service >/dev/null 2>&1; then
    sudo systemctl disable --now tool_vision.service || true
    sudo rm -f -- /etc/systemd/system/tool_vision.service
fi

echo "[7/7] Starting ToolVision and reloading Moonraker/Klipper..."
sudo systemctl daemon-reload
# `enable --now` starts a stopped service but does not reload an already-running
# service. Always restart so an upgrade cannot leave the old API process alive.
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl restart klipper
sudo systemctl restart "${MOONRAKER_SERVICE}"

echo
echo "Installation complete. Moonraker now manages this Git checkout."
echo "Git runtime: ${RUNTIME_DIR}"
echo "Editable Mainsail config: ${CONFIG_TARGET}"
echo "Moonraker updater config: ${MOONRAKER_UPDATE_CONFIG}"
echo "Next steps:"
echo "  1. Set only the optional Z-switch pin in tool_vision.cfg."
echo "  2. Disable [axiscope] and [tools_calibrate]."
echo "  3. Include Tool-Vision/tool_vision.cfg from printer.cfg."
echo "  4. Restart, home, jog T0 over the camera, and run TV_SETUP_CAMERA."
echo "  5. Jog T0 above the switch and run TV_SETUP_SWITCH (when pin is set)."
echo "  6. Run TV_CALIBRATE MODE=Z. Heating to 150 C and cooldown are automatic."
echo "     Results are report-only by default."
echo "Service health: http://${LISTEN_HOST}:${LISTEN_PORT}/api/v2/health"
