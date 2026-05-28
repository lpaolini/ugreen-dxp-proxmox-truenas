#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="/usr/local/bin"
SYSTEMD_DIR="/etc/systemd/system"

PYTHON_SCRIPTS=(
  "zfs/ugreen-truenas-zfs.py"
  "fan/ugreen-truenas-fan.py"
)

SYSTEMD_UNITS=(
  "zfs/ugreen-truenas-zfs.service"
  "zfs/ugreen-truenas-zfs.timer"
  "fan/ugreen-truenas-fan.service"
  "fan/ugreen-truenas-fan.timer"
)

TIMERS=(
  "ugreen-truenas-zfs.timer"
  "ugreen-truenas-fan.timer"
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run this installer as root." >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required but was not found." >&2
  exit 1
fi

for file in "${PYTHON_SCRIPTS[@]}" "${SYSTEMD_UNITS[@]}"; do
  if [[ ! -f "${SCRIPT_DIR}/${file}" ]]; then
    echo "Missing required file: ${SCRIPT_DIR}/${file}" >&2
    exit 1
  fi
done

install -d -m 0755 "${BIN_DIR}" "${SYSTEMD_DIR}"

for file in "${PYTHON_SCRIPTS[@]}"; do
  install -m 0755 "${SCRIPT_DIR}/${file}" "${BIN_DIR}/$(basename "${file}")"
  echo "Installed ${BIN_DIR}/$(basename "${file}")"
done

for file in "${SYSTEMD_UNITS[@]}"; do
  install -m 0644 "${SCRIPT_DIR}/${file}" "${SYSTEMD_DIR}/$(basename "${file}")"
  echo "Installed ${SYSTEMD_DIR}/$(basename "${file}")"
done

systemctl daemon-reload

for timer in "${TIMERS[@]}"; do
  systemctl enable --now "${timer}"
  echo "Enabled and started ${timer}"
done

echo "Installation complete."
