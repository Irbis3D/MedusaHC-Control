#!/usr/bin/env bash
set -euo pipefail

SOURCE_URL="https://github.com/Irbis3D/MedusaHC-Control.git"
temporary="$(mktemp -d)"
cleanup() { rm -rf -- "${temporary}"; }
trap cleanup EXIT

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
git clone --quiet --depth 1 --branch main "${SOURCE_URL}" "${temporary}/source"

if [[ "${EUID}" -eq 0 ]]; then
  PYTHONDONTWRITEBYTECODE=1 bash "${temporary}/source/manager.sh" "$@"
else
  sudo env PYTHONDONTWRITEBYTECODE=1 bash "${temporary}/source/manager.sh" "$@"
fi
