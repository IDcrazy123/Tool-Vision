#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_USER="${TOOL_VISION_USER:-${SUDO_USER:-$(id -un)}}"
INSTALL_GROUP="$(id -gn "${INSTALL_USER}")"
USER_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
KLIPPER_DIR="${KLIPPER_DIR:-${USER_HOME}/klipper}"
VENV_DIR="${TOOL_VISION_VENV:-${USER_HOME}/tool-vision-env}"
KLIPPER_EXTRAS="${KLIPPER_DIR}/klippy/extras"
CONFIG_DIR="${TOOL_VISION_CONFIG_DIR:-${USER_HOME}/printer_data/config}"
DATA_DIR="${TOOL_VISION_DATA_DIR:-$(dirname -- "${CONFIG_DIR}")}"
MOONRAKER_CONFIG="${MOONRAKER_CONFIG:-${CONFIG_DIR}/moonraker.conf}"
MOONRAKER_ALLOWED_SERVICES="${MOONRAKER_ALLOWED_SERVICES:-${DATA_DIR}/moonraker.asvc}"
MOONRAKER_UPDATE_CONFIG="${CONFIG_DIR}/Tool-Vision/moonraker_update_manager.conf"
MOONRAKER_INCLUDE_RE='^[[:space:]]*\[include[[:space:]]+Tool-Vision/moonraker_update_manager\.conf\][[:space:]]*(#.*)?$'
MOONRAKER_SERVICE="${MOONRAKER_SERVICE:-moonraker}"

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

if [[ -f "${MOONRAKER_CONFIG}" ]] &&
    grep -Eq "${MOONRAKER_INCLUDE_RE}" "${MOONRAKER_CONFIG}"; then
    MOONRAKER_BACKUP="${MOONRAKER_CONFIG}.pre-tool-vision-uninstall-$(date +%Y%m%d-%H%M%S)"
    TEMP_MOONRAKER="$(mktemp)"
    sudo -u "${INSTALL_USER}" cp -a -- "${MOONRAKER_CONFIG}" "${MOONRAKER_BACKUP}"
    grep -Ev "${MOONRAKER_INCLUDE_RE}" "${MOONRAKER_CONFIG}" > "${TEMP_MOONRAKER}" || true
    sudo install -o "${INSTALL_USER}" -g "${INSTALL_GROUP}" -m 0644 \
        "${TEMP_MOONRAKER}" "${MOONRAKER_CONFIG}"
    rm -f -- "${TEMP_MOONRAKER}"
    echo "Removed Moonraker include; backup: ${MOONRAKER_BACKUP}"
fi
if [[ -f "${MOONRAKER_UPDATE_CONFIG}" ]]; then
    rm -f -- "${MOONRAKER_UPDATE_CONFIG}"
fi

if [[ -f "${MOONRAKER_ALLOWED_SERVICES}" ]] &&
    grep -Fxq 'tool-vision' "${MOONRAKER_ALLOWED_SERVICES}"; then
    ALLOWED_SERVICES_BACKUP="${MOONRAKER_ALLOWED_SERVICES}.pre-tool-vision-uninstall-$(date +%Y%m%d-%H%M%S)"
    TEMP_ALLOWED_SERVICES="$(mktemp)"
    sudo -u "${INSTALL_USER}" cp -a -- \
        "${MOONRAKER_ALLOWED_SERVICES}" "${ALLOWED_SERVICES_BACKUP}"
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

sudo systemctl restart "${MOONRAKER_SERVICE}"

echo "Tool Vision service and Klipper link removed."
echo "The Tool-Vision Git checkout, learned state, results and editable config were kept."
echo "Remove the [tool_vision] include manually before restarting Klipper."
