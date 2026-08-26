#!/usr/bin/env bash
set -euo pipefail

SOURCE_URL="https://github.com/Irbis3D/MedusaHC-Control/archive/refs/heads/python-controller.tar.gz"
temporary="$(mktemp -d)"
cleanup() { rm -rf -- "${temporary}"; }
trap cleanup EXIT

command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "tar is required" >&2; exit 1; }
curl -fsSL "${SOURCE_URL}" | tar -xz -C "${temporary}" --strip-components=1

# The documented curl | bash form consumes standard input. Reconnect the
# interactive manager to the user's terminal before it asks any questions.
if [[ -r /dev/tty ]]; then
  exec </dev/tty
fi

if [[ "${EUID}" -eq 0 ]]; then
  PYTHONDONTWRITEBYTECODE=1 bash "${temporary}/manager.sh" "$@"
else
  sudo env PYTHONDONTWRITEBYTECODE=1 bash "${temporary}/manager.sh" "$@"
fi
