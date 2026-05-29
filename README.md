# ugreen-dxp-proxmox-truenas

Systemd services and Python helpers for driving UGREEN DXP fan PWM and
front-panel disk LEDs from a TrueNAS VM running under Proxmox.

This project is targeted at UGREEN DXP 4800 PRO users who run TrueNAS Scale as
a VM on a Proxmox host. It has only been tested on the DXP 4800 PRO. Other
UGREEN DXP models may work with minimal changes, but you should expect to
verify the fan PWM sysfs paths, LED sysfs paths, VM ID, and bay-to-disk mapping
before relying on it.

## How it works

The helpers run on the Proxmox host, not inside TrueNAS. They use the Proxmox
`qm guest exec` command to query a TrueNAS Scale VM through the QEMU guest agent,
then apply the result to the UGREEN hardware exposed on the Proxmox host.

There are two services:

- `ugreen-truenas-fan.service` polls disk temperatures from `sensors -j` inside
  the TrueNAS VM, reads the host CPU temperature from sysfs, chooses the higher
  PWM value from the configured disk and CPU fan curves, and writes that value to
  the UGREEN fan PWM sysfs path on the Proxmox host. If temperature collection
  fails, it uses the configured failsafe PWM.
- `ugreen-truenas-zfs.service` polls `lsblk` and `zpool status -pj main` inside
  the TrueNAS VM, maps the VM's disks back to the four physical UGREEN bays, and
  drives `/sys/class/leds/disk1` through `/sys/class/leds/disk4` to show ZFS
  health, missing disks, and resilvering.

Both services poll every 30 seconds. Static configuration lives in two systemd
environment files:

- `/etc/ugreen-truenas-fan.conf`
- `/etc/ugreen-truenas-zfs.conf`

The `VMID` setting is intentionally commented out with `100` as the example VM
ID. Uncomment it and set it to the Proxmox VM ID of your TrueNAS Scale VM before
starting the services. If `VMID` is not configured, the services exit instead of
guessing.

Edit those files when your hwmon paths, LED paths, fan curves, ZFS bay mapping,
or polling interval differ from the tested DXP 4800 PRO layout. The most
commonly adjusted settings are `VMID`, `POLL_INTERVAL`, `FAN_PWM_PATH`,
`FAN_PWM_ENABLE_PATH`, `FAN_INPUT_PATH`, `CPU_TEMP_PATH`, `HDD_FAN_CURVE`,
`CPU_FAN_CURVE`, `TEMP_CHIP_REGEX`, `LED_BASE`, `ALERT_THRESHOLD`, and the
`BAY_1_PATH` through `BAY_4_PATH` values.

## Requirements

- Proxmox running directly on the UGREEN DXP host.
- TrueNAS Scale running as a Proxmox VM.
- QEMU guest agent installed and running inside the TrueNAS VM.
- `sensors -j` available inside the TrueNAS VM for disk temperature polling.
- `jq`, `lsblk`, and `zpool` available inside the TrueNAS VM for LED state
  polling.
- UGREEN fan and LED sysfs devices exposed on the Proxmox host.

## Install from GitHub Pages

After GitHub Pages is enabled from GitHub Actions, publish a release tag such as
`v0.1.0`. The workflow will build the Debian package, sign the apt repository,
and publish it at:

```text
https://lpaolini.github.io/ugreen-dxp-proxmox-truenas/
```

If GitHub rejects a tag deployment with an environment protection error, open
`Settings -> Environments -> github-pages` and allow deployments from tags that
match `v*`. Alternatively, run the workflow manually from the default branch and
set the `version` input to the release version, for example `0.1.0`.

On the Proxmox host, install the repository signing key, add the signed apt
repository, and install the package:

```bash
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://lpaolini.github.io/ugreen-dxp-proxmox-truenas/ugreen-dxp-proxmox-truenas.asc | gpg --dearmor | sudo tee /etc/apt/keyrings/ugreen-dxp-proxmox-truenas.gpg >/dev/null
echo "deb [signed-by=/etc/apt/keyrings/ugreen-dxp-proxmox-truenas.gpg] https://lpaolini.github.io/ugreen-dxp-proxmox-truenas stable main" | sudo tee /etc/apt/sources.list.d/ugreen-dxp-proxmox-truenas.list
sudo apt update
sudo apt install ugreen-dxp-proxmox-truenas
```

For a fork or renamed repository, replace the GitHub Pages URL with:

```text
https://<github-user-or-org>.github.io/<repository-name>/
```

The package installs the helpers to `/usr/bin`, installs the systemd units to
`/lib/systemd/system`, reloads systemd, and enables the fan and ZFS services.
The services will not run successfully until `VMID` is configured.

After installing, edit both config files and uncomment/set `VMID` to the Proxmox
VM ID of your TrueNAS Scale VM:

```bash
sudo nano /etc/ugreen-truenas-fan.conf
sudo nano /etc/ugreen-truenas-zfs.conf
```

For example:

```text
VMID=100
```

Then restart the services so systemd starts them with the updated configuration:

```bash
sudo systemctl restart ugreen-truenas-fan.service
sudo systemctl restart ugreen-truenas-zfs.service
```

## Repository signing

The GitHub Actions workflow signs the apt repository metadata before publishing
to GitHub Pages. It expects an ASCII-armored private GPG key in the repository
secret `APT_SIGNING_KEY`. If the key has a passphrase, also set
`APT_SIGNING_PASSPHRASE`.

Create a signing key locally:

```bash
gpg --quick-generate-key "ugreen-dxp-proxmox-truenas apt <lpaolini@users.noreply.github.com>" ed25519 sign 2y
gpg --list-secret-keys --keyid-format=long
gpg --armor --export-secret-keys <fingerprint>
```

Paste the exported private key into `APT_SIGNING_KEY`. The workflow derives and
publishes the public key as `ugreen-dxp-proxmox-truenas.asc`; client machines use
that public key through the `signed-by=` apt source option.

## Build locally

```bash
./packaging/build-deb.sh 0.1.0 dist
```

The resulting package will be written to:

```text
dist/ugreen-dxp-proxmox-truenas_0.1.0_all.deb
```
