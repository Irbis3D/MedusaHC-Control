#!/usr/bin/env bash
set -euo pipefail

APP_NAME="medusahc-control"
APP_DIR=""
LEGACY_APP_DIR="/opt/${APP_NAME}"
STATE_DIR="/var/lib/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
REPOSITORY_URL="https://github.com/Irbis3D/MedusaHC-Control.git"
PRIMARY_BRANCH="main"
CONFIG_FILE="${STATE_DIR}/config.json"
MANIFEST_FILE="${STATE_DIR}/install-state.env"
MANAGED_BEGIN="# >>> MEDUSAHC CONTROL >>>"
MANAGED_END="# <<< MEDUSAHC CONTROL <<<"
MOONRAKER_MANAGED_BEGIN="# >>> MEDUSAHC CONTROL UPDATE MANAGER >>>"
MOONRAKER_MANAGED_END="# <<< MEDUSAHC CONTROL UPDATE MANAGER <<<"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

action="install"
assume_yes=0
dry_run=0
purge=0
manual_config=0
manual_moonraker=0

usage() {
  cat <<'EOF'
MedusaHC Control installer

Usage:
  sudo ./install.sh [install|update] [--yes] [--dry-run] [--manual-config] [--manual-moonraker]
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
    --manual-moonraker) manual_moonraker=1 ;;
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
  APP_DIR="${MEDUSAHC_APP_DIR:-${install_home}/${APP_NAME}}"

  config_dir="${MEDUSAHC_CONFIG_DIR:-${install_home}/printer_data/config}"
  printer_data_dir="$(dirname -- "${config_dir}")"
  printer_cfg="${config_dir}/printer.cfg"
  variables_cfg="${config_dir}/MHC_variables.cfg"
  managed_cfg="${config_dir}/medusahc_control.cfg"
  moonraker_cfg="${config_dir}/moonraker.conf"
  moonraker_update_cfg="${config_dir}/medusahc-control-update.cfg"
  moonraker_asvc="${printer_data_dir}/moonraker.asvc"
  [[ -f "${printer_cfg}" ]] || die "printer.cfg was not found at ${printer_cfg}."
  [[ -f "${moonraker_cfg}" ]] || die "moonraker.conf was not found at ${moonraker_cfg}."

  klipper_dir="${MEDUSAHC_KLIPPER_DIR:-${install_home}/klipper}"
  klipper_extras="${klipper_dir}/klippy/extras"
  [[ -d "${klipper_extras}" ]] || die "Klipper extras were not found at ${klipper_extras}. Set MEDUSAHC_KLIPPER_DIR."
  adapter_target="${klipper_extras}/mhc_dashboard.py"
}

read_configured_port() {
  [[ -f "${CONFIG_FILE}" ]] || return 0
  python3 - "${CONFIG_FILE}" <<'PY' 2>/dev/null || true
import json
import sys

try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get("port", "")
    if isinstance(value, int):
        print(value)
except (OSError, ValueError, TypeError):
    pass
PY
}

choose_port() {
  configured_port="$(read_configured_port)"
  if [[ "${action}" == "update" ]]; then
    port="${MEDUSAHC_PORT:-${configured_port:-8090}}"
    return
  fi

  local default_port="${MEDUSAHC_PORT:-8090}"
  if [[ "${assume_yes}" -eq 1 || "${dry_run}" -eq 1 || -n "${MEDUSAHC_PORT:-}" ]]; then
    port="${default_port}"
    return
  fi

  [[ -t 0 ]] || die "Cannot ask for the web interface port. Re-run with --yes or set MEDUSAHC_PORT."
  printf 'Web interface port [%s]: ' "${default_port}"
  local reply
  read -r reply
  port="${reply:-${default_port}}"
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

choose_moonraker_mode() {
  if grep -Fq "${MOONRAKER_MANAGED_BEGIN}" "${moonraker_cfg}"; then
    moonraker_mode="managed"
    return
  fi
  if ! grep -Fq "${MOONRAKER_MANAGED_BEGIN}" "${moonraker_cfg}" \
      && grep -Eq '^[[:space:]]*\[update_manager[[:space:]]+medusahc-control\][[:space:]]*$' "${moonraker_cfg}"; then
    moonraker_mode="existing"
    return
  fi
  if [[ "${manual_moonraker}" -eq 1 ]]; then
    moonraker_mode="manual"
    return
  fi
  if [[ "${assume_yes}" -eq 1 || "${dry_run}" -eq 1 ]]; then
    moonraker_mode="managed"
    return
  fi
  [[ -t 0 ]] || die "Cannot ask permission to edit moonraker.conf. Re-run with --yes or --manual-moonraker."
  printf 'Register MedusaHC Control in moonraker.conf for updates through Mainsail? [Y/n] '
  local reply
  read -r reply
  if [[ -z "${reply}" || "${reply}" =~ ^[Yy]$ ]]; then
    moonraker_mode="managed"
  elif [[ "${reply}" =~ ^[Nn]$ ]]; then
    moonraker_mode="manual"
  else
    die "Please answer y or n."
  fi
}

check_sources() {
  [[ -d "${SCRIPT_DIR}/medusahc_control" ]] || die "medusahc_control package is missing next to install.sh."
  [[ -f "${SCRIPT_DIR}/printer/mhc_dashboard.py" ]] || die "printer/mhc_dashboard.py is missing."
  [[ -f "${SCRIPT_DIR}/VERSION" ]] || die "VERSION is missing next to install.sh."
  command -v git >/dev/null 2>&1 || die "git is required."
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
saved_tail = text[text.index(marker):] if marker in text else None
if marker in text:
    text = text.replace(marker, block + marker, 1)
else:
    text = text.rstrip() + "\n\n" + block
if saved_tail is not None:
    new_tail = text[text.index(marker):]
    if new_tail != saved_tail:
        raise SystemExit("Refusing to write printer.cfg: SAVE_CONFIG data changed")
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
marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
saved_tail = text[text.index(marker):] if marker in text else None
updated = text.replace(block, "", 1)
if saved_tail is not None:
    new_tail = updated[updated.index(marker):]
    if new_tail != saved_tail:
        raise SystemExit("Refusing to write printer.cfg: SAVE_CONFIG data changed")
path.write_text(updated, encoding="utf-8")
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

write_moonraker_include() {
  python3 - "${moonraker_cfg}" "${MOONRAKER_MANAGED_BEGIN}" "${MOONRAKER_MANAGED_END}" "${APP_NAME}" "${APP_DIR}" "${REPOSITORY_URL}" "${PRIMARY_BRANCH}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin, end = sys.argv[2:4]
name, app_path, origin, branch = sys.argv[4:8]
text = path.read_text(encoding="utf-8")
block = f"""
{begin}
[update_manager {name}]
type: git_repo
channel: dev
path: {app_path}
origin: {origin}
primary_branch: {branch}
managed_services: {name} klipper
info_tags:
    desc=Experimental MedusaHC control dashboard
{end}
"""
if begin in text:
    start = text.index(begin)
    if start > 0 and text[start - 1] == "\n":
        start -= 1
    finish = text.index(end, start) + len(end)
    if finish < len(text) and text[finish] == "\n":
        finish += 1
    text = text[:start] + block + text[finish:]
else:
    text += block
path.write_text(text, encoding="utf-8")
PY
}

remove_moonraker_include() {
  python3 - "${moonraker_cfg}" "${MOONRAKER_MANAGED_BEGIN}" "${MOONRAKER_MANAGED_END}" "${APP_NAME}" "${APP_DIR}" "${REPOSITORY_URL}" "${PRIMARY_BRANCH}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin, end = sys.argv[2:4]
name, app_path, origin, branch = sys.argv[4:8]
text = path.read_text(encoding="utf-8")
if begin in text:
    start = text.index(begin)
    if start > 0 and text[start - 1] == "\n":
        start -= 1
    finish = text.index(end, start) + len(end)
    if finish < len(text) and text[finish] == "\n":
        finish += 1
    text = text[:start] + text[finish:]
else:
    # Compatibility with a v0.2.3 installation manually converted from the
    # legacy include to the exact inline updater block.
    exact_block = f"""[update_manager {name}]
type: git_repo
channel: dev
path: {app_path}
origin: {origin}
primary_branch: {branch}
managed_services: {name} klipper
info_tags:
    desc=Experimental MedusaHC control dashboard
"""
    text = text.replace(exact_block, "", 1)
path.write_text(text, encoding="utf-8")
PY
}

install_moonraker_update_manager() {
  if [[ "${moonraker_mode}" != "managed" ]]; then
    log "Moonraker Update Manager registration was not changed."
    return
  fi
  if ! grep -Fq "${MOONRAKER_MANAGED_BEGIN}" "${moonraker_cfg}" \
      && grep -Eq '^[[:space:]]*\[update_manager[[:space:]]+medusahc-control\][[:space:]]*$' "${moonraker_cfg}"; then
    die "moonraker.conf already contains an unmanaged medusahc-control updater section."
  fi

  if [[ "${dry_run}" -eq 1 ]]; then
    log "Would add one marked Update Manager block directly to ${moonraker_cfg}."
    log "Would authorize ${APP_NAME} in ${moonraker_asvc}."
    return
  fi

  write_moonraker_include
  rm -f -- "${moonraker_update_cfg}"

  touch "${moonraker_asvc}"
  if ! grep -Fxq "${APP_NAME}" "${moonraker_asvc}"; then
    printf '\n%s\n' "${APP_NAME}" >> "${moonraker_asvc}"
  fi
  chown "${install_user}:${install_group}" "${moonraker_asvc}"
  chmod 0644 "${moonraker_asvc}"
}

remove_moonraker_update_manager() {
  [[ "${moonraker_mode:-managed}" == "managed" ]] || return
  if [[ -f "${moonraker_cfg}" ]]; then
    remove_moonraker_include
  fi
  rm -f -- "${moonraker_update_cfg}"
  if [[ -f "${moonraker_asvc}" ]]; then
    python3 - "${moonraker_asvc}" "${APP_NAME}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
service = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
path.write_text("\n".join(line for line in lines if line.strip() != service) + "\n", encoding="utf-8")
PY
  fi
}

install_application() {
  local replacement_dir="${APP_DIR}.replacement.$$"
  if [[ "${dry_run}" -eq 1 ]]; then
    if [[ -d "${APP_DIR}/.git" ]]; then
      log "Would update the Git repository at ${APP_DIR}."
    else
      log "Would clone ${REPOSITORY_URL} to ${APP_DIR}."
    fi
  elif [[ -d "${APP_DIR}/.git" ]]; then
    local current_origin
    current_origin="$(runuser -u "${install_user}" -- git -C "${APP_DIR}" remote get-url origin)"
    [[ "${current_origin}" == "${REPOSITORY_URL}" ]] || die "Unexpected application Git origin: ${current_origin}"
    if [[ -n "$(runuser -u "${install_user}" -- git -C "${APP_DIR}" status --porcelain)" ]]; then
      die "The application repository contains local changes. Commit or remove them before updating."
    fi
    runuser -u "${install_user}" -- git -C "${APP_DIR}" fetch origin "${PRIMARY_BRANCH}"
    runuser -u "${install_user}" -- git -C "${APP_DIR}" checkout "${PRIMARY_BRANCH}"
    runuser -u "${install_user}" -- git -C "${APP_DIR}" merge --ff-only "origin/${PRIMARY_BRANCH}"
  else
    rm -rf -- "${replacement_dir}"
    git clone --branch "${PRIMARY_BRANCH}" --single-branch "${REPOSITORY_URL}" "${replacement_dir}"
    chown -R "${install_user}:${install_group}" "${replacement_dir}"
    if [[ -e "${APP_DIR}" ]]; then
      rm -rf -- "${APP_DIR}"
    fi
    mv "${replacement_dir}" "${APP_DIR}"
  fi

  if [[ "${dry_run}" -eq 0 ]]; then
    chown -R "${install_user}:${install_group}" "${APP_DIR}"
    if [[ "${LEGACY_APP_DIR}" != "${APP_DIR}" && -d "${LEGACY_APP_DIR}" ]]; then
      rm -rf -- "${LEGACY_APP_DIR}"
    fi
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
  elif [[ -L "${adapter_target}" && "$(readlink "${adapter_target}")" == "${LEGACY_APP_DIR}/printer/mhc_dashboard.py" ]]; then
    adapter_mode="managed"
    run rm -f -- "${adapter_target}"
    run ln -s "${APP_DIR}/printer/mhc_dashboard.py" "${adapter_target}"
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
  if [[ "${dry_run}" -eq 1 ]]; then
    log "Would write ${CONFIG_FILE} with web interface port ${port}."
    return
  fi
  python3 - "${CONFIG_FILE}" "${legacy_config}" "${port}" "${STATE_DIR}" "${printer_cfg}" "${variables_cfg}" <<'PY'
from pathlib import Path
import json
import sys

target, legacy = Path(sys.argv[1]), Path(sys.argv[2])
if target.is_file():
    data = json.loads(target.read_text(encoding="utf-8"))
elif legacy.is_file():
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
    "port": int(sys.argv[3]),
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
    printf 'APP_DIR=%q\n' "${APP_DIR}"
    printf 'CONFIG_DIR=%q\n' "${config_dir}"
    printf 'MOONRAKER_CFG=%q\n' "${moonraker_cfg}"
    printf 'MOONRAKER_UPDATE_CFG=%q\n' "${moonraker_update_cfg}"
    printf 'MOONRAKER_ASVC=%q\n' "${moonraker_asvc}"
    printf 'PRINTER_CFG=%q\n' "${printer_cfg}"
    printf 'MANAGED_CFG=%q\n' "${managed_cfg}"
    printf 'ADAPTER_TARGET=%q\n' "${adapter_target}"
    printf 'ADAPTER_MODE=%q\n' "${adapter_mode}"
    printf 'CONFIG_MODE=%q\n' "${config_mode}"
    printf 'MOONRAKER_MODE=%q\n' "${moonraker_mode}"
    printf 'PORT=%q\n' "${port}"
    printf 'INSTALLED_VERSION=%q\n' "$(tr -d '\r\n' < "${SCRIPT_DIR}/VERSION")"
  } > "${MANIFEST_FILE}"
  chown root:root "${MANIFEST_FILE}"
  chmod 0600 "${MANIFEST_FILE}"
}

backup_integration() {
  backup_dir="${STATE_DIR}/backups/install-$(date +%Y%m%d-%H%M%S)"
  run install -d -m 0700 "${backup_dir}"
  if [[ "${dry_run}" -eq 0 ]]; then
    cp -a "${printer_cfg}" "${backup_dir}/printer.cfg"
    if [[ "${moonraker_mode}" == "managed" ]]; then
      cp -a "${moonraker_cfg}" "${backup_dir}/moonraker.conf"
      [[ -f "${moonraker_asvc}" ]] && cp -a "${moonraker_asvc}" "${backup_dir}/moonraker.asvc" || true
    fi
    [[ -f "${managed_cfg}" ]] && cp -a "${managed_cfg}" "${backup_dir}/medusahc_control.cfg" || true
    [[ -f "${moonraker_update_cfg}" ]] && cp -a "${moonraker_update_cfg}" "${backup_dir}/medusahc-control-update.cfg" || true
    [[ -e "${adapter_target}" ]] && cp -aL "${adapter_target}" "${backup_dir}/mhc_dashboard.py" || true
  fi
}

install_or_update() {
  require_root
  detect_paths
  check_sources
  check_print_idle
  choose_port
  choose_config_mode
  choose_moonraker_mode

  log "Printer user: ${install_user}"
  log "Klipper: ${klipper_dir}"
  log "Config: ${config_dir}"
  log "Web interface port: ${port}"
  if [[ "${dry_run}" -eq 0 ]]; then
    systemctl stop "${APP_NAME}.service" >/dev/null 2>&1 || true
  fi
  install_application
  backup_integration
  install_adapter
  install_moonraker_update_manager
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
    if [[ "${moonraker_mode}" == "managed" ]]; then
      systemctl restart moonraker.service
      systemctl is-active --quiet moonraker.service || die "Moonraker did not restart after Update Manager integration."
    fi
  fi

  local max_tool="" tool_count="auto-detected at runtime"
  max_tool="$(sed -nE 's/^[[:space:]]*variable_max_tool[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' "${variables_cfg}" 2>/dev/null | head -1 || true)"
  if [[ "${max_tool}" =~ ^[0-9]+$ ]]; then
    tool_count="${max_tool}"
  fi
  if [[ "${dry_run}" -eq 1 ]]; then
    log "Dry run complete. Detected tools: ${tool_count}. No files or services were changed."
  else
    installed_version="$(tr -d '\r\n' < "${SCRIPT_DIR}/VERSION")"
    log "${action^} complete. Version: ${installed_version}. Tools: ${tool_count}. Open http://PRINTER_IP:${port}"
    if [[ "${config_mode}" == "manual" ]]; then
      log "printer.cfg was not changed. Before the SAVE_CONFIG block, add:"
      printf '\n[include medusahc_control.cfg]\n\n'
      log "Then restart Klipper with: sudo systemctl restart klipper"
    fi
    if [[ "${moonraker_mode}" == "manual" ]]; then
      log "moonraker.conf was not changed. To enable Mainsail updates manually, add:"
      cat <<EOF

[update_manager ${APP_NAME}]
type: git_repo
channel: dev
path: ${APP_DIR}
origin: ${REPOSITORY_URL}
primary_branch: ${PRIMARY_BRANCH}
managed_services: ${APP_NAME} klipper

EOF
      log "Also add '${APP_NAME}' as its own line in ${moonraker_asvc}, then restart Moonraker."
    fi
  fi
}

load_manifest() {
  [[ -f "${MANIFEST_FILE}" ]] || die "Installation manifest is missing at ${MANIFEST_FILE}."
  # The manifest is root-owned and only contains shell-escaped installer paths.
  source "${MANIFEST_FILE}"
  install_user="${INSTALL_USER}"
  install_group="${INSTALL_GROUP}"
  APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
  config_dir="${CONFIG_DIR}"
  moonraker_cfg="${MOONRAKER_CFG:-${config_dir}/moonraker.conf}"
  moonraker_update_cfg="${MOONRAKER_UPDATE_CFG:-${config_dir}/medusahc-control-update.cfg}"
  moonraker_asvc="${MOONRAKER_ASVC:-$(dirname -- "${config_dir}")/moonraker.asvc}"
  printer_cfg="${PRINTER_CFG}"
  managed_cfg="${MANAGED_CFG}"
  adapter_target="${ADAPTER_TARGET}"
  adapter_mode="${ADAPTER_MODE}"
  config_mode="${CONFIG_MODE}"
  moonraker_mode="${MOONRAKER_MODE:-managed}"
}

uninstall_application() {
  require_root
  load_manifest
  check_print_idle
  if [[ "${config_mode}" == "manual" ]] && grep -Eq '^[[:space:]]*\[include[[:space:]]+medusahc_control\.cfg\][[:space:]]*$' "${printer_cfg}"; then
    die "Manual config mode is active. Remove [include medusahc_control.cfg] from printer.cfg, restart Klipper, then run uninstall again."
  fi
  confirm_change "Remove MedusaHC Control and restart Klipper and Moonraker?"

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
    remove_moonraker_update_manager
    rm -f -- "${SERVICE_FILE}"
    rm -rf -- "${APP_DIR}"
    systemctl daemon-reload
    systemctl restart klipper.service
    if [[ "${moonraker_mode}" == "managed" ]]; then
      systemctl restart moonraker.service
    fi
    if [[ "${purge}" -eq 1 ]]; then
      rm -rf -- "${STATE_DIR}"
    fi
  else
    log "Would remove the Klipper and Moonraker integration, adapter symlink, service and application directory."
  fi
  if [[ "${purge}" -eq 1 ]]; then
    log "Removed. Persistent data was purged."
  else
    log "Removed. Statistics, configuration and backups were kept in ${STATE_DIR}."
  fi
}

show_status() {
  detect_paths
  printf 'Application: '
  [[ -d "${APP_DIR}" ]] && echo "installed at ${APP_DIR}" || echo "not installed"
  printf 'Service: '
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "${APP_NAME}.service"; then
    echo "active"
  else
    echo "inactive"
  fi
  printf 'Version: '
  if [[ -f "${APP_DIR}/VERSION" ]]; then
    tr -d '\r\n' < "${APP_DIR}/VERSION"
    printf '\n'
  else
    echo "not found"
  fi
  printf 'Configuration: '
  [[ -f "${CONFIG_FILE}" ]] && echo "${CONFIG_FILE}" || echo "not found"
  printf 'Web interface: '
  local configured_status_port
  configured_status_port="$(read_configured_port)"
  if [[ -n "${configured_status_port}" ]]; then
    echo "http://PRINTER_IP:${configured_status_port}"
  else
    echo "not configured"
  fi
  printf 'Manifest: '
  [[ -f "${MANIFEST_FILE}" ]] && echo "present" || echo "not found"
}

self_test() {
  local test_dir original moonraker_original
  test_dir="$(mktemp -d)"
  printer_cfg="${test_dir}/printer.cfg"
  original="${test_dir}/printer.original.cfg"
  moonraker_cfg="${test_dir}/moonraker.conf"
  moonraker_original="${test_dir}/moonraker.original.conf"
  printf '[include MHC_variables.cfg]\n\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# test = 1\n' > "${printer_cfg}"
  printf '[server]\nhost: 0.0.0.0\n' > "${moonraker_cfg}"
  cp "${printer_cfg}" "${original}"
  manual_config=1
  assume_yes=0
  choose_config_mode
  [[ "${config_mode}" == "manual" ]] || die "Manual printer.cfg mode was not selected."
  manual_config=0
  assume_yes=1
  choose_config_mode
  [[ "${config_mode}" == "managed" ]] || die "Confirmed automatic printer.cfg mode was not selected."
  manual_moonraker=1
  assume_yes=0
  choose_moonraker_mode
  [[ "${moonraker_mode}" == "manual" ]] || die "Manual moonraker.conf mode was not selected."
  manual_moonraker=0
  assume_yes=1
  choose_moonraker_mode
  [[ "${moonraker_mode}" == "managed" ]] || die "Confirmed automatic moonraker.conf mode was not selected."
  write_managed_include
  [[ "$(grep -Fc "${MANAGED_BEGIN}" "${printer_cfg}")" -eq 1 ]] || die "Managed include was not inserted exactly once."
  write_managed_include
  [[ "$(grep -Fc "${MANAGED_BEGIN}" "${printer_cfg}")" -eq 1 ]] || die "Managed include is not idempotent."
  python3 - "${printer_cfg}" "${original}" "${MANAGED_BEGIN}" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
original = Path(sys.argv[2]).read_text(encoding="utf-8")
begin = sys.argv[3]
marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
assert text.index(begin) < text.index(marker)
assert text[text.index(marker):] == original[original.index(marker):]
PY
  remove_managed_include
  cmp -s "${printer_cfg}" "${original}" || die "Managed include removal did not restore printer.cfg."
  cp "${moonraker_cfg}" "${moonraker_original}"
  write_moonraker_include
  write_moonraker_include
  [[ "$(grep -Fc "${MOONRAKER_MANAGED_BEGIN}" "${moonraker_cfg}")" -eq 1 ]] || die "Moonraker updater block is not idempotent."
  grep -Fq "[update_manager ${APP_NAME}]" "${moonraker_cfg}" || die "Moonraker updater section was not written inline."
  remove_moonraker_include
  cmp -s "${moonraker_cfg}" "${moonraker_original}" || die "Moonraker include removal did not restore moonraker.conf."
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
