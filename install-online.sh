#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${MEDUSAHC_CONTROL_REPOSITORY:-Irbis3D/MedusaHC-Control}"
ACCESS_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

log() { printf '[MedusaHC Control] %s\n' "$*"; }
die() { printf '[MedusaHC Control] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || die "Run with: curl -fsSL INSTALL_SCRIPT_URL | sudo bash"
command -v curl >/dev/null 2>&1 || die "curl is required."
command -v tar >/dev/null 2>&1 || die "tar is required."
[[ -r /dev/tty ]] || die "An interactive SSH terminal is required."

if [[ "$#" -eq 0 ]]; then
    installer_arguments=(install)
else
    installer_arguments=("$@")
fi

case "${installer_arguments[0]}" in
    install|update|uninstall|status) ;;
    *) die "Unsupported action: ${installer_arguments[0]}" ;;
esac

REPOSITORY_REF="${MEDUSAHC_CONTROL_REF:-}"
if [[ -z "${REPOSITORY_REF}" && "${installer_arguments[0]}" != "install" ]]; then
    manifest="/var/lib/medusahc-control/install-state.env"
    if [[ -f "${manifest}" ]]; then
        REPOSITORY_REF="$(sed -nE 's/^PANEL_BRANCH=([^[:space:]]+)$/\1/p' "${manifest}" | head -1)"
    fi
fi
if [[ -z "${REPOSITORY_REF}" ]]; then
    cat >/dev/tty <<'EOF'
Which MedusaHC version is installed on this printer?
  1) Macro version
  2) Python-script version
Select 1 or 2 [1]:
EOF
    read -r controller_reply </dev/tty
    case "${controller_reply:-1}" in
        1) REPOSITORY_REF="main" ;;
        2) REPOSITORY_REF="python-controller" ;;
        *) die "Please select 1 or 2." ;;
    esac
fi

PACKAGE_URL="${MEDUSAHC_CONTROL_PACKAGE_URL:-https://api.github.com/repos/${REPOSITORY}/tarball/${REPOSITORY_REF}}"

temporary_directory="$(mktemp -d /tmp/medusahc-control-install.XXXXXX)"
trap 'rm -rf -- "${temporary_directory}"' EXIT

package_file="${temporary_directory}/medusahc-control.tar.gz"
source_directory="${temporary_directory}/source"
mkdir -p "${source_directory}"

log "Downloading panel branch: ${REPOSITORY_REF}"
curl_options=(
    -fL
    --retry 3
    --connect-timeout 15
    -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28"
)
if [[ -n "${ACCESS_TOKEN}" ]]; then
    curl_options+=(-H "Authorization: Bearer ${ACCESS_TOKEN}")
fi
curl "${curl_options[@]}" "${PACKAGE_URL}" -o "${package_file}"
tar -xzf "${package_file}" -C "${source_directory}"

installer="$(find "${source_directory}" -maxdepth 3 -type f -name install.sh -print -quit)"
[[ -n "${installer}" ]] || die "install.sh was not found in the downloaded package."

log "Starting the installer..."
MEDUSAHC_CONTROL_REF="${REPOSITORY_REF}" \
    bash "${installer}" "${installer_arguments[@]}" </dev/tty >/dev/tty
