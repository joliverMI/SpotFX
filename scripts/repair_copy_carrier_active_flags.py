"""Repair the fx-live config residue that keeps the Living Room take from
bringing up its copy-mapped carrier (tv-mapper).

THE RESIDUE, and how it strands a take. A copy-mapped external carrier
virtual (his `tv-mapper`, `mapping: "copy"`) streams across several
fixtures — `tv-backlight` and both kitchen sconces. Each of those fixtures
also has its OWN device-virtual (`is_device: "<device>"`), and those are the
strips a capture run brings up briefly to light a fixture in parts. The
device layer enforces mutual exclusion — `fx/devices/__init__.py::
Device.add_segments_batch` deactivates every external virtual streaming to a
device whose own device-virtual activates — so a device-virtual and the
copy-carrier in front of it can never BOTH render.

A capture/commission run that was interrupted in its own crash window (a
process kill, a restart, a hard abort between `activate_for_capture` and
`deactivate_after_capture`) leaves those device-virtuals PERSISTED
`active: true`. On the next config load, tv-mapper is restored active, then
each device-virtual activates and evicts it — so tv-mapper holds its effect
with no render thread, the Living Room has zero active carriers, and the
take rolls back to `released`. The cold-load fix (fm/tvmapper-cold-load-fix)
respects the stored `active` flag, so it cannot override a residue that
stores the WRONG flag.

THE REPAIR, and why it is always safe. For every device-virtual that is
stored `active: true` while a copy-mapped external carrier that is itself
stored `active: true` streams to that same device, set the device-virtual
`active: false`. This makes the carrier deterministically win on load —
which is the only outcome the device layer would ever allow anyway, since
the two can never both render. Nothing else is touched: not the carrier,
not the device-virtual's stored effect, not any other key.

Deliberately NARROW: only a device-virtual behind an active COPY-mapped
carrier is flipped. A span virtual, a blender/mask/foreground/background
layer, a gap dummy — none are considered, because none is the copy-carrier
eviction this bug is about.

The recurrence itself is fixed in code (a capture run no longer PERSISTS a
transient `active: true` for a substitute — spectra/services/room_mapping.py
production_deps + fx/facade.py `_virtual_put_active`'s `persist` flag,
fx/VENDOR.md #37). This script is the one-time catch-up for a config that
already carries the residue, the same relationship
scripts/check_spectra_expected_active.py has to live_host's own runtime
intersection.

Dry-run by default; --apply writes (atomic tmp+replace) AFTER copying the
config to a timestamped backup, and ASSERTS the written file differs from
the original in EXACTLY the planned `active` flips and nothing else before
declaring success. Idempotent: a config with no residue reports nothing to
do and writes nothing.

Run from repo root:
    .venv/bin/python scripts/repair_copy_carrier_active_flags.py [--config PATH] [--apply]
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

COPY_MAPPING = "copy"


def _mapping(virtual: dict) -> str:
    return str((virtual.get("config") or {}).get("mapping") or "")


def _segment_devices(virtual: dict) -> set[str]:
    """Device ids a virtual's segments reference (segment[0])."""
    out: set[str] = set()
    for seg in virtual.get("segments") or []:
        if seg:
            out.add(str(seg[0]))
    return out


def carrier_owned_devices(virtuals: list[dict]) -> dict[str, list[str]]:
    """device id -> the active copy-mapped external carriers streaming to it.

    An EXTERNAL virtual has a falsy `is_device`; a copy-mapped one has
    `config.mapping == "copy"`; only carriers that are themselves stored
    `active: true` count — an inactive carrier is not "the one that should
    win", so a device-virtual sharing its device is left alone."""
    owned: dict[str, list[str]] = {}
    for v in virtuals:
        if v.get("is_device"):
            continue                                  # a device-virtual
        if not v.get("active"):
            continue                                  # inactive carrier
        if _mapping(v) != COPY_MAPPING:
            continue                                  # span/blender/etc.
        for device_id in _segment_devices(v):
            owned.setdefault(device_id, []).append(str(v.get("id")))
    return owned


def find_residue(virtuals: list[dict]) -> list[dict]:
    """The device-virtuals to flip, each with the carrier(s) that own its
    device. A device-virtual is `is_device: "<device>"` (truthy) and its
    device is carrier-owned and it is stored `active: true`."""
    owned = carrier_owned_devices(virtuals)
    residue: list[dict] = []
    for v in virtuals:
        device_id = v.get("is_device")
        if not device_id:
            continue                                  # not a device-virtual
        if str(device_id) not in owned:
            continue                                  # no copy-carrier on it
        if not v.get("active"):
            continue                                  # already correct
        residue.append({"id": str(v.get("id")),
                        "device": str(device_id),
                        "carriers": owned[str(device_id)]})
    return residue


def diff_active(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """Every (virtual_id, before_active, after_active) that differs — used
    both to REPORT the plan and to VERIFY the written file changed in
    exactly the planned way and nothing else."""
    b = {v.get("id"): v for v in before.get("virtuals") or []}
    a = {v.get("id"): v for v in after.get("virtuals") or []}
    changes: list[tuple[str, object, object]] = []
    for vid in sorted(set(b) | set(a)):
        bv, av = b.get(vid), a.get(vid)
        if bv is None or av is None:
            changes.append((vid, "MISSING" if bv is None else bv,
                            "MISSING" if av is None else av))
            continue
        if bv.get("active") != av.get("active"):
            changes.append((vid, bv.get("active"), av.get("active")))
    return changes


def assert_only_planned_active_flips(before: dict, after: dict,
                                     planned_ids: set[str]) -> None:
    """The 'written diff equals the planned diff' guarantee. The whole config
    must be byte-identical to the original EXCEPT that exactly the planned
    device-virtuals flip `active` True -> False; every other key of every
    virtual, and every top-level key, is untouched."""
    b_virtuals = {v.get("id"): v for v in before.get("virtuals") or []}
    a_virtuals = {v.get("id"): v for v in after.get("virtuals") or []}
    if set(b_virtuals) != set(a_virtuals):
        raise AssertionError("the set of virtuals changed — refusing")
    # every non-virtuals top-level key identical
    b_top = {k: v for k, v in before.items() if k != "virtuals"}
    a_top = {k: v for k, v in after.items() if k != "virtuals"}
    if b_top != a_top:
        raise AssertionError("a top-level config key other than virtuals "
                             "changed — refusing")
    flipped: set[str] = set()
    for vid, bv in b_virtuals.items():
        av = a_virtuals[vid]
        if vid in planned_ids:
            if not (bv.get("active") is True and av.get("active") is False):
                raise AssertionError(
                    f"{vid}: planned flip did not land (before="
                    f"{bv.get('active')!r}, after={av.get('active')!r})")
            # everything except `active` byte-identical
            b_rest = {k: val for k, val in bv.items() if k != "active"}
            a_rest = {k: val for k, val in av.items() if k != "active"}
            if b_rest != a_rest:
                raise AssertionError(f"{vid}: a key other than `active` "
                                     f"changed — refusing")
            flipped.add(vid)
        else:
            if bv != av:
                raise AssertionError(f"{vid}: changed but was not planned — "
                                     f"refusing")
    if flipped != planned_ids:
        raise AssertionError(f"planned {sorted(planned_ids)} but flipped "
                             f"{sorted(flipped)}")


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
    virtuals = original.get("virtuals") or []
    print(f"config: {path}")
    print(f"  {len(original.get('devices') or [])} devices, "
          f"{len(virtuals)} virtuals")

    owned = carrier_owned_devices(virtuals)
    if owned:
        print("  devices owned by an active copy-mapped carrier:")
        for device_id, carriers in sorted(owned.items()):
            print(f"    {device_id} <- {', '.join(carriers)}")
    else:
        print("  no active copy-mapped carrier in this config")

    residue = find_residue(virtuals)
    if not residue:
        print("nothing to correct — no device-virtual behind an active "
              "copy-mapped carrier is stored active:true")
        return 0

    print(f"\n  residue: {len(residue)} device-virtual(s) stored active:true "
          f"while a copy-carrier owns their device (they evict it on load):")
    for r in residue:
        print(f"    {r['id']:<24} (device {r['device']}, behind "
              f"{', '.join(r['carriers'])})  ->  active:false")

    planned_ids = {r["id"] for r in residue}

    if not args.apply:
        print(f"\ndry-run: would set {len(planned_ids)} device-virtual(s) "
              f"active:false in {path} (pass --apply). Only the `active` key "
              f"changes; every other field on disk is left identical.")
        return 0

    # Build the patched config on a fresh copy of the raw dict.
    patched = json.loads(json.dumps(original))
    for v in patched.get("virtuals") or []:
        if str(v.get("id")) in planned_ids:
            v["active"] = False

    # Verify the plan BEFORE writing anything.
    assert_only_planned_active_flips(original, patched, planned_ids)

    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"{path.stem}-carrier-active-{stamp}.json"
    shutil.copy2(path, backup_path)
    print(f"\nbacked up {path} -> {backup_path}")

    # Match save_config's own on-disk serialization so the only real change
    # is the flipped flags and the app's next save does not churn the file.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(patched, ensure_ascii=False, sort_keys=True,
                              indent=4), encoding="utf-8")
    os.replace(tmp, path)

    # Re-read what actually landed and prove the diff is exactly the plan.
    written = json.loads(path.read_text(encoding="utf-8"))
    if written != patched:
        raise SystemExit("FATAL: the written file does not match the planned "
                         "config — check the backup at " + str(backup_path))
    assert_only_planned_active_flips(original, written, planned_ids)

    changes = diff_active(original, written)
    print(f"wrote {path}: {len(changes)} `active` flag(s) changed, and the "
          f"written diff equals the planned diff:")
    for vid, was, now in changes:
        print(f"    {vid}: active {was!r} -> {now!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
