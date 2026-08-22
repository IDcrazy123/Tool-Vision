#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="${TOOL_VISION_USER:-${SUDO_USER:-$(id -un)}}"
INSTALL_GROUP="$(id -gn "${INSTALL_USER}")"
USER_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
KLIPPER_DIR="${KLIPPER_DIR:-${USER_HOME}/klipper}"
VENV_DIR="${TOOL_VISION_VENV:-${USER_HOME}/tool-vision-env}"
KLIPPER_EXTRAS="${KLIPPER_DIR}/klippy/extras"
CONFIG_DIR="${TOOL_VISION_CONFIG_DIR:-${USER_HOME}/printer_data/config}"
DATA_DIR="${TOOL_VISION_DATA_DIR:-$(dirname -- "${CONFIG_DIR}")}"
PRINTER_CONFIG="${PRINTER_CONFIG:-${CONFIG_DIR}/printer.cfg}"
MOONRAKER_CONFIG="${MOONRAKER_CONFIG:-${CONFIG_DIR}/moonraker.conf}"
MOONRAKER_ALLOWED_SERVICES="${MOONRAKER_ALLOWED_SERVICES:-${DATA_DIR}/moonraker.asvc}"
MOONRAKER_SERVICE="${MOONRAKER_SERVICE:-moonraker}"
KLIPPER_SERVICE="${KLIPPER_SERVICE:-klipper}"
BACKUP_ROOT="${TOOL_VISION_BACKUP_DIR:-${DATA_DIR}/config_backups/tool-vision}"
BACKUP_DIR="${BACKUP_ROOT}/uninstall-$(date +%Y%m%d-%H%M%S)-$$"
CONFIG_HELPER="${SCRIPT_DIR}/scripts/config_layout.py"

backup_user_file() {
    local source_path="$1"
    local relative_path="$2"
    local backup_path="${BACKUP_DIR}/${relative_path}"

    if [[ -e "${backup_path}" ]]; then
        echo "ERROR: refusing to overwrite backup: ${backup_path}" >&2
        exit 1
    fi
    sudo -u "${INSTALL_USER}" mkdir -p -- "$(dirname -- "${backup_path}")"
    sudo -u "${INSTALL_USER}" cp -a -- "${source_path}" "${backup_path}"
    if ! cmp -s -- "${source_path}" "${backup_path}"; then
        echo "ERROR: backup verification failed: ${backup_path}" >&2
        exit 1
    fi
}

if ! sudo -v; then
    echo "ERROR: Administrator privileges are required to uninstall ToolVision." >&2
    exit 1
fi
if [[ ! -f "${CONFIG_HELPER}" ]]; then
    echo "ERROR: configuration helper not found: ${CONFIG_HELPER}" >&2
    exit 1
fi

# Machine configuration is deliberately manual. Back it up first, then stop
# before system changes if the ToolVision include/updater block still exists.
echo "Checking manual configuration before uninstall..."
echo "Remove the ToolVision include from printer.cfg and the optional"
echo "[update_manager tool-vision] section from moonraker.conf, then rerun."
sudo -u "${INSTALL_USER}" python3 "${CONFIG_HELPER}" uninstall \
    --config-dir "${CONFIG_DIR}" \
    --printer-config "${PRINTER_CONFIG}" \
    --moonraker-config "${MOONRAKER_CONFIG}" \
    --backup-dir "${BACKUP_DIR}"

sudo systemctl disable --now tool-vision.service 2>/dev/null || true
sudo rm -f -- /etc/systemd/system/tool-vision.service
sudo systemctl daemon-reload

for klipper_file in tool_vision.py tool_vision_client.py tool_vision_state.py \
    tool_vision_toolchanger.py; do
    KLIPPER_TARGET="${KLIPPER_EXTRAS}/${klipper_file}"
    if [[ -L "${KLIPPER_TARGET}" ]]; then
        rm -f -- "${KLIPPER_TARGET}"
    fi
done

if [[ -f "${MOONRAKER_ALLOWED_SERVICES}" ]] &&
    grep -Fxq 'tool-vision' "${MOONRAKER_ALLOWED_SERVICES}"; then
    ALLOWED_SERVICES_BACKUP="${BACKUP_DIR}/moonraker.asvc"
    TEMP_ALLOWED_SERVICES="$(mktemp)"
    backup_user_file "${MOONRAKER_ALLOWED_SERVICES}" "moonraker.asvc"
    grep -Fvx 'tool-vision' "${MOONRAKER_ALLOWED_SERVICES}" > \
        "${TEMP_ALLOWED_SERVICES}" || true
    sudo install -o "${INSTALL_USER}" -g "${INSTALL_GROUP}" -m 0644 \
        "${TEMP_ALLOWED_SERVICES}" "${MOONRAKER_ALLOWED_SERVICES}"
    rm -f -- "${TEMP_ALLOWED_SERVICES}"
    echo "Removed tool-vision service authorization; backup: ${ALLOWED_SERVICES_BACKUP}"
fi

if [[ "${1:-}" == "--purge-venv" && -d "${VENV_DIR}" ]]; then
    case "${VENV_DIR}" in
        "${USER_HOME}"/*tool-vision*) rm -rf -- "${VENV_DIR}" ;;
        *) echo "Refusing to purge unexpected venv path: ${VENV_DIR}" >&2; exit 1 ;;
    esac
fi

sudo systemctl restart "${KLIPPER_SERVICE}"
sudo systemctl restart "${MOONRAKER_SERVICE}"

echo "Tool Vision service and Klipper link removed."
echo "The Tool-Vision Git checkout, learned state, results and editable config were kept."
echo "Local pre-uninstall backup: ${BACKUP_DIR}"
