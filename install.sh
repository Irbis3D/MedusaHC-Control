#!/usr/bin/env bash
set -euo pipefail

APP_NAME="medusahc-control"
APP_DIR="/opt/${APP_NAME}"
STATE_DIR="/var/lib/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
CONFIG_FILE="${STATE_DIR}/config.json"
MANIFEST_FILE="${STATE_DIR}/install-state.env"
MANAGED_BEGIN="# >>> MEDUSAHC CONTROL >>>"
MANAGED_END="# <<< MEDUSAHC CONTROL <<<"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

action="install"
assume_yes=0
dry_run=0
purge=0
manual_config=0

usage() {
  cat <<'EOF'
MedusaHC Control installer

Usage:
  sudo ./install.sh [install|update] [--yes] [--dry-run] [--manual-config]
  sudo ./install.sh uninstall [--yes] [--purge]
  ./install.sh status
  ./install.sh self-test

The installer auto-detects the printer user, Klipper and printer_data paths.
Override unusual layouts with MEDUSAHC_USER, MEDUSAHC_CONFIG_DIR,
MEDUSAHC_KLIPPER_DIR or MEDUSAHC_PORT.
EOF
}

for argument in "$@"; do
  case "${argument}" in
    install|update|uninstall|status|self-test) action="${argument}" ;;
    --yes|-y) assume_yes=1 ;;
    --dry-run) dry_run=1 ;;
    --purge) purge=1 ;;
    --manual-config) manual_config=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: ${argument}" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '[MedusaHC Control] %s\n' "$*"; }
die() { printf '[MedusaHC Control] ERROR: %s\n' "$*" >&2; exit 1; }

run() {
  if [[ "${dry_run}" -eq 1 ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Run this command with sudo."
}

detect_user() {
  if [[ -n "${MEDUSAHC_USER:-}" ]]; then
    printf '%s\n' "${MEDUSAHC_USER}"
    return
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    printf '%s\n' "${SUDO_USER}"
    return
  fi
  local candidate=""
  local cfg
  for cfg in /home/*/printer_data/config/printer.cfg; do
    [[ -f "${cfg}" ]] || continue
    [[ -z "${candidate}" ]] || die "Multiple printer users found. Set MEDUSAHC_USER."
    candidate="$(stat -c '%U' "${cfg}")"
  done
  [[ -n "${candidate}" ]] || die "Cannot detect the printer user. Set MEDUSAHC_USER."
  printf '%s\n' "${candidate}"
}

detect_paths() {
  install_user="$(detect_user)"
  id "${install_user}" >/dev/null 2>&1 || die "User ${install_user} does not exist."
  install_group="$(id -gn "${install_user}")"
  install_home="$(getent passwd "${install_user}" | cut -d: -f6)"
  [[ -n "${install_home}" && -d "${install_home}" ]] || die "Cannot find the home directory for ${install_user}."

  config_dir="${MEDUSAHC_CONFIG_DIR:-${install_home}/printer_data/config}"
  printer_cfg="${config_dir}/printer.cfg"
  variables_cfg="${config_dir}/MHC_variables.cfg"
  managed_cfg="${config_dir}/medusahc_control.cfg"
  [[ -f "${printer_cfg}" ]] || die "printer.cfg was not found at ${printer_cfg}."

  klipper_dir="${MEDUSAHC_KLIPPER_DIR:-${install_home}/klipper}"
  klipper_extras="${klipper_dir}/klippy/extras"
  [[ -d "${klipper_extras}" ]] || die "Klipper extras were not found at ${klipper_extras}. Set MEDUSAHC_KLIPPER_DIR."
  adapter_target="${klipper_extras}/mhc_dashboard.py"
  port="${MEDUSAHC_PORT:-8090}"
}

confirm_change() {
  local prompt="$1"
  [[ "${assume_yes}" -eq 1 || "${dry_run}" -eq 1 ]] && return
  [[ -t 0 ]] || die "Interactive confirmation is unavailable. Re-run with --yes."
  printf '%s [y/N] ' "${prompt}"
  local reply
  read -r reply
  [[ "${reply}" =~ ^[Yy]$ ]] || { log "Cancelled."; exit 0; }
}

choose_config_mode() {
  if grep -Eq '^[[:space:]]*\[mhc_dashboard\][[:space:]]*$' "${printer_cfg}"; then
    config_mode="existing"
    return
  fi
  if grep -Fq "${MANAGED_BEGIN}" "${printer_cfg}"; then
    config_mode="managed"
    return
  fi
  if [[ "${manual_config}" -eq 1 ]]; then
    config_mode="manual"
    return
  fi
  if [[ "${assume_yes}" -eq 1 || "${dry_run}" -eq 1 ]]; then
    config_mode="managed"
    return
  fi
  [[ -t 0 ]] || die "Cannot ask permission to edit printer.cfg. Re-run with --yes or --manual-config."
  printf 'Add a marked [include medusahc_control.cfg] block to printer.cfg automatically? [Y/n] '
  local reply
  read -r reply
  if [[ -z "${reply}" || "${reply}" =~ ^[Yy]$ ]]; then
    config_mode="managed"
  elif [[ "${reply}" =~ ^[Nn]$ ]]; then
    config_mode="manual"
  else
    die "Please answer y or n."
  fi
}

check_sources() {
  [[ -d "${SCRIPT_DIR}/medusahc_control" ]] || die "medusahc_control package is missing next to install.sh."
  [[ -f "${SCRIPT_DIR}/printer/mhc_dashboard.py" ]] || die "printer/mhc_dashboard.py is missing."
  python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9 or newer is required"'
}

check_print_idle() {
  local state
  state="$(python3 - <<'PY' 2>/dev/null || true
import json
import urllib.request
try:
    with urllib.request.urlopen(
        "http://127.0.0.1:7125/printer/objects/query?print_stats", timeout=2
    ) as response:
        result = json.load(response)
    print(result.get("result", {}).get("status", {}).get("print_stats", {}).get("state", "unknown"))
except Exception:
    print("unknown")
PY
)"
  [[ "${state}" != "printing" && "${state}" != "paused" ]] || die "A print is ${state}. Installation is blocked until it finishes."
}

write_managed_include() {
  python3 - "${printer_cfg}" "${MANAGED_BEGIN}" "${MANAGED_END}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin, end = sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
block = f"{begin}\n[include medusahc_control.cfg]\n{end}\n"
if begin in text:
    raise SystemExit(0)
marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
if marker in text:
    text = text.replace(marker, block + marker, 1)
else:
    text = text.rstrip() + "\n\n" + block
path.write_text(text, encoding="utf-8")
PY
}

remove_managed_include() {
  python3 - "${printer_cfg}" "${MANAGED_BEGIN}" "${MANAGED_END}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin, end = sys.argv[2:4]
text = path.read_text(encoding="utf-8")
block = f"{begin}\n[include medusahc_control.cfg]\n{end}\n"
text = text.replace(block, "", 1)
path.write_text(text, encoding="utf-8")
PY
}

write_dashboard_cfg() {
  cat > "${managed_cfg}" <<'EOF'
# Managed by MedusaHC Control. Remove through: sudo ./install.sh uninstall
[mhc_dashboard]
pin_watch: pin_watch io
EOF
  chown "${install_user}:${install_group}" "${managed_cfg}"
  chmod 0644 "${managed_cfg}"
}

install_application() {
  run install -d -m 0755 "${APP_DIR}"
  if [[ "${dry_run}" -eq 0 ]]; then
    cp -a "${SCRIPT_DIR}/medusahc_control" "${APP_DIR}/"
    cp -a "${SCRIPT_DIR}/printer" "${APP_DIR}/"
    install -m 0644 "${SCRIPT_DIR}/pyproject.toml" "${APP_DIR}/pyproject.toml"
    install -m 0644 "${SCRIPT_DIR}/README.md" "${APP_DIR}/README.md"
    install -m 0644 "${SCRIPT_DIR}/INSTALLER.md" "${APP_DIR}/INSTALLER.md"
    install -m 0755 "${SCRIPT_DIR}/install.sh" "${APP_DIR}/install.sh"
    chown -R root:root "${APP_DIR}"
  fi

  run install -d -m 0750 -o "${install_user}" -g "${install_group}" "${STATE_DIR}"
}

install_adapter() {
  adapter_mode="existing"
  if [[ ! -e "${adapter_target}" && ! -L "${adapter_target}" ]]; then
    adapter_mode="managed"
    run ln -s "${APP_DIR}/printer/mhc_dashboard.py" "${adapter_target}"
  elif [[ -L "${adapter_target}" && "$(readlink -f "${adapter_target}")" == "${APP_DIR}/printer/mhc_dashboard.py" ]]; then
    adapter_mode="managed"
  fi

  if [[ "${config_mode}" != "existing" ]]; then
    if [[ "${dry_run}" -eq 1 ]]; then
      log "Would create ${managed_cfg}."
      if [[ "${config_mode}" == "managed" ]]; then
        log "Would add one marked include block to printer.cfg before SAVE_CONFIG."
      else
        log "Manual mode selected: printer.cfg would not be changed."
      fi
    else
      write_dashboard_cfg
      if [[ "${config_mode}" == "managed" ]]; then
        write_managed_include
      fi
    fi
  fi
}

write_runtime_config() {
  local legacy_config="/etc/medusahc-control.json"
  [[ -f "${CONFIG_FILE}" ]] && return
  if [[ "${dry_run}" -eq 1 ]]; then
    log "Would create ${CONFIG_FILE}."
    return
  fi
  python3 - "${CONFIG_FILE}" "${legacy_config}" "${port}" "${STATE_DIR}" "${printer_cfg}" "${variables_cfg}" <<'PY'
from pathlib import Path
import json
import sys

target, legacy = Path(sys.argv[1]), Path(sys.argv[2])
if legacy.is_file():
    data = json.loads(legacy.read_text(encoding="utf-8"))
else:
    data = {
        "bind": "0.0.0.0",
        "port": int(sys.argv[3]),
        "moonraker_url": "http://127.0.0.1:7125",
        "moonraker_api_key": "",
        "simulate": False,
        "poll_interval": 0.75,
        "control_token": "",
        "max_temperature": 290,
        "allow_commands": True,
    }
data.update({
    "database_path": str(Path(sys.argv[4]) / "medusahc-control.db"),
    "printer_config_path": sys.argv[5],
    "medusahc_variables_path": sys.argv[6] if Path(sys.argv[6]).is_file() else "",
    "simulate": False,
})
target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
  chown root:"${install_group}" "${CONFIG_FILE}"
  chmod 0640 "${CONFIG_FILE}"
}

write_service() {
  local temporary
  temporary="$(mktemp)"
  cat > "${temporary}" <<EOF
[Unit]
Description=MedusaHC Control dashboard
After=network-online.target moonraker.service
Wants=network-online.target

[Service]
Type=simple
User=${install_user}
Group=${install_group}
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/python3 -m medusahc_control --config ${CONFIG_FILE}
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${STATE_DIR} ${config_dir}

[Install]
WantedBy=multi-user.target
EOF
  if [[ "${dry_run}" -eq 1 ]]; then
    log "Would install ${SERVICE_FILE}."
  else
    install -m 0644 "${temporary}" "${SERVICE_FILE}"
  fi
  rm -f "${temporary}"
}

write_manifest() {
  [[ "${dry_run}" -eq 1 ]] && return
  {
    printf 'INSTALL_USER=%q\n' "${install_user}"
    printf 'INSTALL_GROUP=%q\n' "${install_group}"
    printf 'CONFIG_DIR=%q\n' "${config_dir}"
    printf 'PRINTER_CFG=%q\n' "${printer_cfg}"
    printf 'MANAGED_CFG=%q\n' "${managed_cfg}"
    printf 'ADAPTER_TARGET=%q\n' "${adapter_target}"
    printf 'ADAPTER_MODE=%q\n' "${adapter_mode}"
    printf 'CONFIG_MODE=%q\n' "${config_mode}"
  } > "${MANIFEST_FILE}"
  chown root:root "${MANIFEST_FILE}"
  chmod 0600 "${MANIFEST_FILE}"
}

backup_integration() {
  backup_dir="${STATE_DIR}/backups/install-$(date +%Y%m%d-%H%M%S)"
  run install -d -m 0700 "${backup_dir}"
  if [[ "${dry_run}" -eq 0 ]]; then
    cp -a "${printer_cfg}" "${backup_dir}/printer.cfg"
    [[ -f "${managed_cfg}" ]] && cp -a "${managed_cfg}" "${backup_dir}/medusahc_control.cfg" || true
    [[ -e "${adapter_target}" ]] && cp -aL "${adapter_target}" "${backup_dir}/mhc_dashboard.py" || true
  fi
}

install_or_update() {
  require_root
  detect_paths
  check_sources
  check_print_idle
  choose_config_mode

  log "Printer user: ${install_user}"
  log "Klipper: ${klipper_dir}"
  log "Config: ${config_dir}"
  install_application
  backup_integration
  install_adapter
  write_runtime_config
  write_service
  write_manifest

  if [[ "${dry_run}" -eq 0 ]]; then
    systemctl daemon-reload
    systemctl enable "${APP_NAME}.service" >/dev/null
    if [[ "${config_mode}" != "manual" ]]; then
      systemctl restart klipper.service
    fi
    systemctl restart "${APP_NAME}.service"
    systemctl is-active --quiet "${APP_NAME}.service" || die "The dashboard service did not start. Check journalctl -u ${APP_NAME}."
  fi

  local tool_count="unknown"
  tool_count="$(sed -nE 's/^[[:space:]]*variable_max_tool[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' "${variables_cfg}" 2>/dev/null | head -1 || true)"
  [[ -n "${tool_count}" ]] || tool_count="auto-detected at runtime"
  if [[ "${dry_run}" -eq 1 ]]; then
    log "Dry run complete. Detected tools: ${tool_count}. No files or services were changed."
  else
    log "Installed. Tools: ${tool_count}. Open http://PRINTER_IP:${port}"
    if [[ "${config_mode}" == "manual" ]]; then
      log "printer.cfg was not changed. Before the SAVE_CONFIG block, add:"
      printf '\n[include medusahc_control.cfg]\n\n'
      log "Then restart Klipper with: sudo systemctl restart klipper"
    fi
  fi
}

load_manifest() {
  [[ -f "${MANIFEST_FILE}" ]] || die "Installation manifest is missing at ${MANIFEST_FILE}."
  # The manifest is root-owned and only contains shell-escaped installer paths.
  source "${MANIFEST_FILE}"
  install_user="${INSTALL_USER}"
  install_group="${INSTALL_GROUP}"
  config_dir="${CONFIG_DIR}"
  printer_cfg="${PRINTER_CFG}"
  managed_cfg="${MANAGED_CFG}"
  adapter_target="${ADAPTER_TARGET}"
  adapter_mode="${ADAPTER_MODE}"
  config_mode="${CONFIG_MODE}"
}

uninstall_application() {
  require_root
  load_manifest
  check_print_idle
  if [[ "${config_mode}" == "manual" ]] && grep -Eq '^[[:space:]]*\[include[[:space:]]+medusahc_control\.cfg\][[:space:]]*$' "${printer_cfg}"; then
    die "Manual config mode is active. Remove [include medusahc_control.cfg] from printer.cfg, restart Klipper, then run uninstall again."
  fi
  confirm_change "Remove MedusaHC Control and restart Klipper once?"

  if [[ "${dry_run}" -eq 0 ]]; then
    systemctl disable --now "${APP_NAME}.service" >/dev/null 2>&1 || true
    if [[ "${config_mode}" == "managed" && -f "${printer_cfg}" ]]; then
      remove_managed_include
      rm -f "${managed_cfg}"
    elif [[ "${config_mode}" == "manual" ]]; then
      rm -f "${managed_cfg}"
    fi
    if [[ "${adapter_mode}" == "managed" && -L "${adapter_target}" ]]; then
      rm -f "${adapter_target}"
    fi
    rm -f "${SERVICE_FILE}"
    rm -rf "${APP_DIR}"
    systemctl daemon-reload
    systemctl restart klipper.service
    if [[ "${purge}" -eq 1 ]]; then
      rm -rf "${STATE_DIR}"
    fi
  else
    log "Would remove the managed include, adapter symlink, service and application directory."
  fi
  if [[ "${purge}" -eq 1 ]]; then
    log "Removed. Persistent data was purged."
  else
    log "Removed. Statistics, configuration and backups were kept in ${STATE_DIR}."
  fi
}

show_status() {
  printf 'Application: '
  [[ -d "${APP_DIR}" ]] && echo "installed at ${APP_DIR}" || echo "not installed"
  printf 'Service: '
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "${APP_NAME}.service"; then
    echo "active"
  else
    echo "inactive"
  fi
  printf 'Configuration: '
  [[ -f "${CONFIG_FILE}" ]] && echo "${CONFIG_FILE}" || echo "not found"
  printf 'Manifest: '
  [[ -f "${MANIFEST_FILE}" ]] && echo "present" || echo "not found"
}

self_test() {
  local test_dir original
  test_dir="$(mktemp -d)"
  printer_cfg="${test_dir}/printer.cfg"
  original="${test_dir}/printer.original.cfg"
  printf '[include MHC_variables.cfg]\n\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# test = 1\n' > "${printer_cfg}"
  cp "${printer_cfg}" "${original}"
  manual_config=1
  assume_yes=0
  choose_config_mode
  [[ "${config_mode}" == "manual" ]] || die "Manual printer.cfg mode was not selected."
  manual_config=0
  assume_yes=1
  choose_config_mode
  [[ "${config_mode}" == "managed" ]] || die "Confirmed automatic printer.cfg mode was not selected."
  write_managed_include
  [[ "$(grep -Fc "${MANAGED_BEGIN}" "${printer_cfg}")" -eq 1 ]] || die "Managed include was not inserted exactly once."
  write_managed_include
  [[ "$(grep -Fc "${MANAGED_BEGIN}" "${printer_cfg}")" -eq 1 ]] || die "Managed include is not idempotent."
  python3 - "${printer_cfg}" "${MANAGED_BEGIN}" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
assert text.index(sys.argv[2]) < text.index("#*# <---------------------- SAVE_CONFIG ---------------------->")
PY
  remove_managed_include
  cmp -s "${printer_cfg}" "${original}" || die "Managed include removal did not restore printer.cfg."
  rm -rf "${test_dir}"
  python3 -m compileall -q "${SCRIPT_DIR}/medusahc_control"
  log "Self-test passed. No printer files or services were changed."
}

case "${action}" in
  install|update) install_or_update ;;
  uninstall) uninstall_application ;;
  status) show_status ;;
  self-test) self_test ;;
esac
