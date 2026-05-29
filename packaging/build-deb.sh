#!/usr/bin/env bash
set -euo pipefail

PACKAGE="ugreen-dxp-proxmox-truenas"
VERSION="${1:-}"
OUT_DIR="${2:-dist}"

if [[ -z "${VERSION}" ]]; then
  VERSION="$(git describe --tags --always --dirty 2>/dev/null || echo "0.0.0")"
fi

# Debian versions cannot include the common Git tag prefix.
VERSION="${VERSION#v}"

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "${BUILD_DIR}"' EXIT

PKG_DIR="${BUILD_DIR}/${PACKAGE}_${VERSION}_all"

install -d -m 0755 \
  "${PKG_DIR}/DEBIAN" \
  "${PKG_DIR}/usr/bin" \
  "${PKG_DIR}/lib/systemd/system" \
  "${OUT_DIR}"

install -m 0755 fan/ugreen-truenas-fan.py "${PKG_DIR}/usr/bin/ugreen-truenas-fan.py"
install -m 0755 zfs/ugreen-truenas-zfs.py "${PKG_DIR}/usr/bin/ugreen-truenas-zfs.py"

for unit in \
  fan/ugreen-truenas-fan.service \
  zfs/ugreen-truenas-zfs.service
do
  sed 's#/usr/local/bin/#/usr/bin/#g' "${unit}" > "${PKG_DIR}/lib/systemd/system/$(basename "${unit}")"
  chmod 0644 "${PKG_DIR}/lib/systemd/system/$(basename "${unit}")"
done

cat > "${PKG_DIR}/DEBIAN/control" <<CONTROL
Package: ${PACKAGE}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: lpaolini <lpaolini@users.noreply.github.com>
Depends: python3, systemd, qemu-server
Description: UGREEN DXP Proxmox/TrueNAS fan and ZFS LED helpers
 Systemd units and Python helpers for driving UGREEN fan PWM and front-panel
 disk LEDs from a TrueNAS VM running under Proxmox.
CONTROL

cat > "${PKG_DIR}/DEBIAN/postinst" <<'POSTINST'
#!/usr/bin/env bash
set -e

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  systemctl disable --now ugreen-truenas-zfs.timer || true
  systemctl enable --now ugreen-truenas-zfs.service || true
  systemctl disable --now ugreen-truenas-fan.timer || true
  systemctl enable --now ugreen-truenas-fan.service || true
fi
POSTINST

cat > "${PKG_DIR}/DEBIAN/prerm" <<'PRERM'
#!/usr/bin/env bash
set -e

if [[ "${1:-}" = "remove" || "${1:-}" = "deconfigure" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now ugreen-truenas-zfs.timer || true
    systemctl disable --now ugreen-truenas-zfs.service || true
    systemctl disable --now ugreen-truenas-fan.timer || true
    systemctl disable --now ugreen-truenas-fan.service || true
  fi
  /usr/bin/ugreen-truenas-zfs.py --stop || true
  /usr/bin/ugreen-truenas-fan.py --stop || true
fi
PRERM

cat > "${PKG_DIR}/DEBIAN/postrm" <<'POSTRM'
#!/usr/bin/env bash
set -e

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
fi
POSTRM

chmod 0755 \
  "${PKG_DIR}/DEBIAN/postinst" \
  "${PKG_DIR}/DEBIAN/prerm" \
  "${PKG_DIR}/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "${PKG_DIR}" "${OUT_DIR}/${PACKAGE}_${VERSION}_all.deb"
