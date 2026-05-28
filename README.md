# ugreen-dxp-proxmox-truenas

Systemd timers and Python helpers for driving UGREEN DXP fan PWM and
front-panel disk LEDs from a TrueNAS VM running under Proxmox.

## Install from GitHub Pages

After this repository is renamed to `ugreen-dxp-proxmox-truenas` and GitHub
Pages is enabled from GitHub Actions, publish a release tag such as `v0.1.0`.
The workflow will build the Debian package and publish an apt repository at:

```text
https://<github-user-or-org>.github.io/ugreen-dxp-proxmox-truenas/
```

On the Proxmox host, add that apt repository and install the package:

```bash
echo "deb [trusted=yes] https://<github-user-or-org>.github.io/ugreen-dxp-proxmox-truenas stable main" | sudo tee /etc/apt/sources.list.d/ugreen-dxp-proxmox-truenas.list
sudo apt update
sudo apt install ugreen-dxp-proxmox-truenas
```

The package installs the helpers to `/usr/bin`, installs the systemd units to
`/lib/systemd/system`, reloads systemd, and enables the fan and ZFS timers.

## Build locally

```bash
./packaging/build-deb.sh 0.1.0 dist
```

The resulting package will be written to:

```text
dist/ugreen-dxp-proxmox-truenas_0.1.0_all.deb
```
