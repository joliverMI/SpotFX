"""One-time catch-up for the four device names the "always wins" fix
(fx/devices/wled.py async_initialize, fx/VENDOR.md #53) cannot itself
repair.

THE GAP THE CODE FIX LEAVES BEHIND. Before #53, a WLED device's
`self._config` dict IS the same object as `host.config["devices"][i]
["config"]` (`Devices.create_from_config` passes it by reference,
`Device.__init__` stores it unchanged) — so the old unconditional
`wled_config["name"] = wled_name` in `async_initialize()` corrupted
`host.config` in memory on every host start/re-activation, well before
any explicit save. SPECTRA then calls `save_config(host.config, ...)` on
essentially every ordinary scene/flare write during playback (`fx/
facade.py`'s `_effects_put`/`_effects_post`, the seam every `fx_seam.
apply_writes` write funnels through) — so the very next effect write
after any restart flushed the clobbered "WLED" name back to
`storage/spectra/fx-live/config.json`. The Admiral restarted SPECTRA
several times on 2026-10-06 while renaming `crystal`/`tv-backlight`/
`dining-table`/`porch-rail`, so their on-disk names are very likely
already stuck at the stale "WLED" by the time #53 ships. #53's new rule —
"an already-set name is left untouched" — has no way to tell that
corrupted "WLED" apart from a name he genuinely wants, so it will not
self-heal; this script is the one-time, data-side half of his ask.

THE PATH IS THE SAME ONE THE APP'S OWN RENAME USES: `device_console.
rename_device`/`update_device`'s STORED branch merges into
`raw["devices"][i]["config"]["name"]`, and the LIVE branch (`fx/
facade.py::_device_put`) ends up writing the identical
`host.config["devices"][i]["config"]["name"]` key once the save lands.
This script edits that same key, nothing else.

SCOPED AND SAFE: only the four named device ids are touched, and only
when their CURRENT stored name is exactly the stale "WLED" — a device he
has already renamed to something else, or one that genuinely still
carries no name at all, is left alone. Idempotent: re-running after a
successful --apply finds nothing left to do.

Dry-run by default; --apply writes (atomic tmp+replace) AFTER copying the
config to a timestamped backup, and ASSERTS the written file is
semantically identical to the original except for exactly the planned
`name` fields before declaring success.

Run from repo root:
    .venv/bin/python scripts/repair_stale_wled_device_names.py [--config PATH] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STALE_NAME = "WLED"

# device id -> the friendly name he set (and that keeps reverting).
FRIENDLY_NAMES = {
    "crystal": "Crystal",
    "tv-backlight": "TV Backlight",
    "dining-table": "Dining Table",
    "porch-rail": "Porch Rail",
}


def find_stale(devices: list[dict]) -> list[dict]:
    """Devices among FRIENDLY_NAMES whose stored config name is exactly the
    stale firmware default — the only ones this script ever touches."""
    stale: list[dict] = []
    for entry in devices:
        device_id = str(entry.get("id") or "")
        if device_id not in FRIENDLY_NAMES:
            continue
        current = (entry.get("config") or {}).get("name")
        if current != STALE_NAME:
            continue
        stale.append({"id": device_id, "current": current,
                      "target": FRIENDLY_NAMES[device_id]})
    return stale


def assert_only_planned_name_changes(before: dict, after: dict,
                                     planned: dict[str, str]) -> None:
    """The written diff must equal the planned diff: every device and every
    top-level key identical except that exactly the planned device ids'
    `config.name` moved from "WLED" to their target name."""
    b_devices = {str(d.get("id")): d for d in before.get("devices") or []}
    a_devices = {str(d.get("id")): d for d in after.get("devices") or []}
    if set(b_devices) != set(a_devices):
        raise AssertionError("the set of devices changed — refusing")
    b_top = {k: v for k, v in before.items() if k != "devices"}
    a_top = {k: v for k, v in after.items() if k != "devices"}
    if b_top != a_top:
        raise AssertionError("a top-level config key other than devices "
                             "changed — refusing")
    changed: set[str] = set()
    for device_id, bd in b_devices.items():
        ad = a_devices[device_id]
        if device_id in planned:
            b_cfg = dict(bd.get("config") or {})
            a_cfg = dict(ad.get("config") or {})
            if b_cfg.get("name") != STALE_NAME:
                raise AssertionError(
                    f"{device_id}: expected stale name before the write, "
                    f"found {b_cfg.get('name')!r} — refusing")
            if a_cfg.get("name") != planned[device_id]:
                raise AssertionError(
                    f"{device_id}: planned rename did not land (after="
                    f"{a_cfg.get('name')!r})")
            b_rest = {k: v for k, v in b_cfg.items() if k != "name"}
            a_rest = {k: v for k, v in a_cfg.items() if k != "name"}
            if b_rest != a_rest:
                raise AssertionError(f"{device_id}: a config key other "
                                     f"than `name` changed — refusing")
            b_outer = {k: v for k, v in bd.items() if k != "config"}
            a_outer = {k: v for k, v in ad.items() if k != "config"}
            if b_outer != a_outer:
                raise AssertionError(f"{device_id}: a device key other "
                                     f"than `config` changed — refusing")
            changed.add(device_id)
        else:
            if bd != ad:
                raise AssertionError(f"{device_id}: changed but was not "
                                     f"planned — refusing")
    if changed != set(planned):
        raise AssertionError(f"planned {sorted(planned)} but changed "
                             f"{sorted(changed)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None,
                        help="fx-live config.json path (default: "
                             "spectra.config.FX_LIVE_CONFIG_DIR/config.json)")
    parser.add_argument("--apply", action="store_true",
                        help="write the correction (default: dry-run report)")
    args = parser.parse_args()

    if args.config:
        path = Path(args.config)
    else:
        from spectra import config as scfg
        path = scfg.FX_LIVE_CONFIG_DIR / "config.json"

    if not path.exists():
        print(f"no fx config at {path} — pass --config PATH")
        return 2

    original = json.loads(path.read_text(encoding="utf-8"))
    devices = original.get("devices") or []
    print(f"config: {path}")
    print(f"  {len(devices)} devices")

    stale = find_stale(devices)
    if not stale:
        print("nothing to correct — none of crystal/tv-backlight/"
              "dining-table/porch-rail currently carries the stale "
              "\"WLED\" name")
        return 0

    print(f"\n  stale name(s) to fix ({len(stale)}):")
    for s in stale:
        print(f"    {s['id']:<14} {s['current']!r}  ->  {s['target']!r}")

    planned = {s["id"]: s["target"] for s in stale}

    if not args.apply:
        print(f"\ndry-run: would set {len(planned)} device name(s) in "
              f"{path} (pass --apply). Only each device's `config.name` "
              f"key changes; every other field keeps its value.")
        return 0

    patched = json.loads(json.dumps(original))
    for entry in patched.get("devices") or []:
        device_id = str(entry.get("id") or "")
        if device_id in planned:
            entry.setdefault("config", {})["name"] = planned[device_id]

    assert_only_planned_name_changes(original, patched, planned)

    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"{path.stem}-wled-names-{stamp}.json"
    shutil.copy2(path, backup_path)
    print(f"\nbacked up {path} -> {backup_path}")

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(patched, ensure_ascii=False, sort_keys=True,
                              indent=4), encoding="utf-8")
    os.replace(tmp, path)

    written = json.loads(path.read_text(encoding="utf-8"))
    if written != patched:
        raise SystemExit("FATAL: the written file does not match the "
                         "planned config — check the backup at "
                         + str(backup_path))
    assert_only_planned_name_changes(original, written, planned)

    print(f"wrote {path}: {len(planned)} device name(s) changed:")
    for device_id, target in sorted(planned.items()):
        print(f"    {device_id}: \"{STALE_NAME}\" -> {target!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
