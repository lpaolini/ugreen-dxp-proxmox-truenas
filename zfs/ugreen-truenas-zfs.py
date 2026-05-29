#!/usr/bin/env python3
# Poll ZFS status inside the TrueNAS VM and drive the UGREEN front-panel LEDs.
# Requires: qemu-guest-agent running inside TrueNAS and the ugreen LED driver
# exposing /sys/class/leds/disk[1-4]/color.
import argparse
import json
import os
import signal
import subprocess
import sys
import syslog
import threading
from dataclasses import dataclass

VMID = os.environ.get("VMID", "101")
LED_BASE = "/sys/class/leds"
TAG = "ugreen-truenas-zfs"
DEBUG = os.environ.get("DEBUG", "1") == "1"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "30"))
LEDS_OFF_ON_EXIT = os.environ.get("LEDS_OFF_ON_EXIT", "1") == "1"
# Bay N is wired to the path shown — UGREEN backplane constant.
# Verify with `ls -l /dev/disk/by-path/` inside the guest.
BAYS = {
    "1": "/dev/disk/by-path/pci-0000:00:10.0-ata-1",
    "2": "/dev/disk/by-path/pci-0000:00:10.0-ata-2",
    "3": "/dev/disk/by-path/pci-0000:00:10.0-ata-3",
    "4": "/dev/disk/by-path/pci-0000:00:10.0-ata-4",
}


@dataclass(frozen=True)
class LedState:
    color: str | None       # e.g. "0 40 0"; None = don't touch
    blink_type: str | None  # e.g. "blink 500 500", "none", or None = don't touch
    brightness: int | None  # 0..255; None = don't touch


# LED presentation for each state. ZFS leaf-vdev state strings (ONLINE, DEGRADED,
# FAULTED, UNAVAIL, REMOVED, OFFLINE) double as keys here so apply_disk_leds can
# use them directly. The four "bad" rows currently share one red-blink presentation
# but are kept as distinct entries so they can diverge later. The remaining keys
# (RESILVER, MISSING, OFF, CHECKING, ERROR) are script-internal.
STATES = {
    "OFF":          LedState("0 0 0",     "none",               1),
    "CHECKING":     LedState(None,        "blink 100 100",    None),
    "ONLINE":       LedState("0 40 0",    "none",             255),
    "ONLINE_ALERT": LedState("40 40 0",   "none",             255),
    "DEGRADED":     LedState("80 40 0",   "blink 500 500",    255),
    "FAULTED":      LedState("80 0 0",    "blink 500 500",    255),
    "UNAVAIL":      LedState("80 0 0",    "blink 500 500",    255),
    "REMOVED":      LedState("80 0 0",    "blink 500 500",    255),
    "OFFLINE":      LedState("80 0 0",    "blink 500 500",    255),
    "RESILVER":     LedState("80 80 80",  "blink 500 500",    255),
    "MISSING":      LedState("40 0 40",   "blink 500 500",    255),
    "ERROR":        LedState("80 0 0",    "none",             255),
}

# Severity ordering, so a partition-level FAULTED wins over a disk-level ONLINE.
# ONLINE_ALERT ranks just above ONLINE so a disk that is healthy-but-full on one
# pool beats a plain-ONLINE sibling, but still loses to anything actually broken.
STATE_RANK = {"ONLINE": 0, "ONLINE_ALERT": 1, "OFFLINE": 2, "DEGRADED": 3,
              "REMOVED": 4, "UNAVAIL": 5, "FAULTED": 6}
UNRANKED = len(STATE_RANK)  # rank for any unexpected state — sorts above all known ones

# Fill ratio at or above which an ONLINE leaf is upgraded to ONLINE_ALERT.
ALERT_THRESHOLD = 0.75

syslog.openlog(TAG)
STOP_REQUESTED = threading.Event()


def log(msg):
    syslog.syslog(msg)
    print(f"[{TAG}] {msg}", file=sys.stderr)


def dbg(msg):
    if DEBUG:
        print(f"[{TAG}][debug] {msg}", file=sys.stderr)


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value) + "\n")
    except OSError as e:
        log(f"sysfs write failed: {path}={value!r}: {e}")
        return False
    return True


def set_led(n, state_key):
    s = STATES[state_key]
    d = f"{LED_BASE}/disk{n}"
    dbg(f"LED {n} -> {state_key}")
    if not os.path.isdir(d):
        log(f"LED sysfs missing: {d}")
        return False

    ok = True
    if s.color is not None:
        ok = _write(f"{d}/color", s.color) and ok
    if s.blink_type is not None:
        ok = _write(f"{d}/blink_type", s.blink_type) and ok
    if s.brightness is not None:
        ok = _write(f"{d}/brightness", s.brightness) and ok
    return ok


def set_all_leds(state_key):
    ok = True
    for n in BAYS:
        ok = set_led(n, state_key) and ok
    return ok


def build_guest_cmd(bays):
    """Shell command the guest agent runs: ship lsblk, zpool status, and each bay's
    current disk name back as one JSON object {lsblk, zpool, bays}."""
    lines = [
        "jq -n",
        "--argjson lsblk \"$(lsblk -Jlo NAME,PARTUUID,TYPE,PKNAME 2>/dev/null || echo '{}')\"",
        "--argjson zpool \"$(zpool status -pj main 2>/dev/null || echo '{}')\"",
    ]
    for bay, path in bays.items():
        lines.append(
            f"--arg bay{bay} \"$(readlink -e {path} 2>/dev/null | sed 's|.*/||')\""
        )
    bays_obj = ",".join(f'"{bay}":$bay{bay}' for bay in bays)
    lines.append("'{lsblk:$lsblk, zpool:$zpool, bays:{" + bays_obj + "}}'")
    return " ".join(lines)


def flash_checking_pattern():
    """Flash all front-panel LEDs while the guest is queried."""
    set_all_leds("CHECKING")


def fetch_guest_report():
    """Run the guest command via qm; return the parsed guest JSON report.
    On any failure, drive LEDs to an error state and return None."""
    dbg(f"Querying guest for report...")
    try:
        proc = subprocess.run(
            ["qm", "guest", "exec", VMID, "--timeout", "20",
             "--", "/bin/sh", "-c", build_guest_cmd(BAYS)],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(proc.stdout or "{}")
    except subprocess.CalledProcessError as e:
        log(f"qm guest exec failed (rc={e.returncode}): {(e.stderr or '').strip()}")
        set_all_leds("ERROR")
        return None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        log(f"qm guest exec failed: {e}")
        set_all_leds("ERROR")
        return None

    rc = payload.get("exitcode", 1)
    out = payload.get("out-data", "") or ""
    dbg(f"Queried guest for report status code={rc}, length={len(out)}")
    if rc != 0 or not out:
        log(f"guest command failed (rc={rc})")
        set_all_leds("ERROR")
        return None

    try:
        # return json.loads(out)
        report = json.loads(out)
        bays = report.get("bays", {})
        lsblk = report.get("lsblk", {})
        zpool = report.get("zpool", {})
        return bays, lsblk, zpool
    except json.JSONDecodeError as e:
        log(f"guest JSON parse failed: {e}; raw={out[:200]!r}")
        set_all_leds("ERROR")
        return None


def build_device_to_partuuids(lsblk_obj):
    """{disk_name: [partuuid, ...]} — for every disk in lsblk, the partuuids of its partitions.
    Disk name (e.g. "sdb") is what /dev/disk/by-path/ symlinks resolve to; partuuid is what
    ZFS uses as the vdev name."""
    devs = lsblk_obj.get("blockdevices", [])
    disks = {d["name"] for d in devs if d.get("type") == "disk"}
    result = {n: [] for n in disks}
    for d in devs:
        if d.get("type") != "part":
            continue
        parent, partuuid = d.get("pkname"), d.get("partuuid")
        if parent in result and partuuid:
            result[parent].append(partuuid)
    return result


def _iter_leaf_disk_vdevs(vdev, ancestor_fill=None):
    """Yield (leaf, fill_ratio) for each leaf-disk descendant. fill_ratio is
    alloc_space/total_space of the nearest ancestor vdev (or self) that exposes
    both fields, or None if none does. Requires `zpool status -p` for numeric
    values; human-readable values like '7.44T' are silently ignored."""
    fill = ancestor_fill
    alloc, total = vdev.get("alloc_space"), vdev.get("total_space")
    if alloc is not None and total is not None:
        try:
            t = float(total)
            if t > 0:
                fill = float(alloc) / t
        except (TypeError, ValueError):
            pass  # keep inherited fill
    if vdev.get("vdev_type") == "disk":
        yield vdev, fill
    for child in (vdev.get("vdevs") or {}).values():
        yield from _iter_leaf_disk_vdevs(child, fill)


def build_vdev_state(zpool_obj):
    """{partuuid: state} for every leaf disk in the main pool.
    ONLINE leaves whose nearest enclosing vdev is ≥ ALERT_THRESHOLD full are
    promoted to ONLINE_ALERT."""
    vdev_state = {}
    for pool in (zpool_obj.get("pools") or {}).values():
        for vdev in (pool.get("vdevs") or {}).values():
            for leaf, fill in _iter_leaf_disk_vdevs(vdev):
                name, state = leaf.get("name"), leaf.get("state")
                if not (name and state):
                    continue
                if state == "ONLINE" and fill is not None and fill >= ALERT_THRESHOLD:
                    state = "ONLINE_ALERT"
                prev = vdev_state.get(name)
                if prev is None or STATE_RANK.get(state, UNRANKED) > STATE_RANK.get(prev, 0):
                    vdev_state[name] = state
    return vdev_state


def is_resilvering(zpool_obj):
    """True if any pool has an active RESILVER scan."""
    for pool in (zpool_obj.get("pools") or {}).values():
        scan = pool.get("scan_stats") or {}
        if scan.get("function") == "RESILVER" and scan.get("state") not in ("NONE", "FINISHED", None):
            return True
    return False


def update_leds(bays, device_to_partuuids, vdev_state, resilvering):
    """Paint each populated bay for its disk's ZFS state.
    Returns (empty_bays, present_partuuids)."""
    present_partuuids = set()
    empty_bays = []
    for bay in BAYS:
        device = bays.get(bay)
        if not device:
            empty_bays.append(bay)
            continue

        partuuids = device_to_partuuids.get(device, [])
        present_partuuids.update(partuuids)
        states = [vdev_state[p] for p in partuuids if p in vdev_state]
        zpool_state = max(states, key=lambda s: STATE_RANK.get(s, UNRANKED)) if states else None

        dbg(f"Bay {bay}: device={device} partuuids={partuuids} state={zpool_state}")
        key = zpool_state if zpool_state in STATES else "OFF"
        if key in ("ONLINE", "ONLINE_ALERT") and resilvering:
            key = "RESILVER"
        set_led(bay, key)

    populated = sum(1 for b in BAYS if bays.get(b))

    """Paint empty bays, one per vdev that ZFS expects but no bay holds.
    Remaining empty bays go OFF; logs a warning if missing > empty."""
    missing_count = sum(1 for v in vdev_state if v not in present_partuuids)

    dbg(
        f"Result: populated bays={populated}/{len(BAYS)}, vdev leaves={len(vdev_state)}, "
        f"empty bays={empty_bays}, missing vdevs={missing_count}, resilvering={int(resilvering)}"
    )

    if missing_count > len(empty_bays):
        log(f"missing vdevs ({missing_count}) exceed empty bays ({len(empty_bays)}); "
            f"some pulls won't be indicated")
    for i, bay in enumerate(empty_bays):
        set_led(bay, "MISSING" if i < missing_count else "OFF")


def control_once():
    dbg(f"Starting: VMID={VMID}")
    flash_checking_pattern()

    report = fetch_guest_report()
    if report is None:
        return False

    bays, lsblk, zpool = report
    device_to_partuuids = build_device_to_partuuids(lsblk)
    vdev_state = build_vdev_state(zpool)
    resilvering = is_resilvering(zpool)

    update_leds(bays, device_to_partuuids, vdev_state, resilvering)
    return True


def leds_off():
    log("turning front-panel LEDs off")
    return set_all_leds("OFF")


def request_stop(signum, _frame):
    dbg(f"Received signal {signum}, stopping")
    STOP_REQUESTED.set()


def run_loop():
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    log(f"starting ZFS LED control loop, interval={POLL_INTERVAL:g}s")
    try:
        while not STOP_REQUESTED.is_set():
            control_once()
            STOP_REQUESTED.wait(POLL_INTERVAL)
    finally:
        if LEDS_OFF_ON_EXIT:
            leds_off()


def main():
    parser = argparse.ArgumentParser(description="Drive UGREEN front-panel LEDs from TrueNAS ZFS status")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--start", action="store_true", help="run continuously instead of polling once")
    mode.add_argument("--stop", action="store_true", help="turn front-panel LEDs off and exit")
    args = parser.parse_args()

    if args.stop:
        sys.exit(0 if leds_off() else 1)

    if args.start:
        run_loop()
        return

    sys.exit(0 if control_once() else 1)


if __name__ == "__main__":
    main()
