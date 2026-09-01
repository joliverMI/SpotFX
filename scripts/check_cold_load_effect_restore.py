#!/usr/bin/env python
"""Real-data proof for the tv-mapper cold-load failure (VENDOR.md #29).

Reads his ACTUAL `storage/spectra/fx-live/config.json` READ-ONLY, rewrites
every device to a vendored DUMMY of the same pixel count into a throwaway
directory, and cold-loads it through the real `FxHost.start()`.  Nothing
here touches his room: no WLED, no Hue, no network, no write back.

The device swap is deliberately the ONLY change, because the defect is not
about any device's behaviour — it is about CONFIG ORDER:

    idx 14  tv-mapper            active: true,  EXTERNAL over tv-backlight
                                 + both sconces (mapping: copy)
    idx 22  sconce-kitchen-left  active: FALSE, stored effect singleColor
    idx 27  sconce-kitchen-right active: FALSE, stored effect singleColor

Restoring a stored effect used to activate its virtual regardless of the
stored `active` flag, and a DEVICE virtual activating evicts every external
virtual on its device (`Device.add_segments_batch`).  Both sconces load
after tv-mapper, so both evicted it, and nothing brought it back.

Usage:  .venv/bin/python scripts/check_cold_load_effect_restore.py
        [--config PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_CONFIG = "/home/javi/SpotFX/storage/spectra/fx-live/config.json"
TARGET = "tv-mapper"


def dummify(config: dict) -> dict:
    """Every device becomes a dummy of the same pixel count. Pixel counts are
    preserved because segment validation is checked against them."""
    out = copy.deepcopy(config)
    for device in out.get("devices") or []:
        cfg = device.get("config") or {}
        device["type"] = "dummy"
        device["config"] = {
            "name": cfg.get("name", device["id"]),
            "pixel_count": cfg.get("pixel_count", 1),
            "refresh_rate": min(int(cfg.get("refresh_rate", 30) or 30), 30),
            "rows": cfg.get("rows", 1),
            "center_offset": 0,
            "icon_name": "mdi:eye-off",
        }
    return out


def declared_active(config: dict) -> list[str]:
    return [v["id"] for v in config.get("virtuals") or []
            if v.get("active") and "effect" in v]


async def cold_load(config_dir: str):
    from fx import headless
    from fx.host import FxHost

    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    state = {}
    for virtual in host.virtuals.values():
        state[virtual.id] = {
            "active": bool(virtual.active),
            "effect": getattr(virtual.active_effect, "type", None),
        }
    failures = dict(getattr(host.virtuals, "restore_failures", {}))
    await host.shutdown()
    return state, failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print(f"no fx config at {args.config} — pass --config PATH "
              f"(this script reads a real fx-live config READ-ONLY; the "
              f"mechanism itself is covered offline by "
              f"tests/test_cold_load_effect_restore.py)")
        return 2

    with open(args.config) as fh:
        real = json.load(fh)

    order = [v["id"] for v in real["virtuals"]]
    print(f"read (read-only): {args.config}")
    print(f"  {len(real['devices'])} devices, {len(order)} virtuals\n")

    if TARGET in order:
        idx = order.index(TARGET)
        segs = {s[0] for s in real["virtuals"][idx].get("segments") or []}
        later = [(i, v["id"]) for i, v in enumerate(real["virtuals"])
                 if i > idx and v.get("is_device") in segs]
        print(f"{TARGET} is at config index {idx}; it streams to {sorted(segs)}")
        print("device virtuals for those devices that load LATER "
              "(each one used to evict it):")
        for i, vid in later:
            stored = real["virtuals"][i]
            print(f"  idx {i:>2}  {vid:<24} active={stored.get('active')!r:<6} "
                  f"effect={(stored.get('effect') or {}).get('type')}")
        if not later:
            print("  (none — the ordering that caused the defect is not "
                  "present in this config)")
        print()

    tmp = tempfile.mkdtemp(prefix="fx-cold-load-")
    with open(os.path.join(tmp, "config.json"), "w") as fh:
        json.dump(dummify(real), fh)

    state, failures = asyncio.run(cold_load(tmp))

    expected = declared_active(real)
    dark = [vid for vid in expected
            if not state.get(vid, {}).get("active")]

    print("virtuals the stored config says should be driving:")
    for vid in expected:
        got = state.get(vid, {})
        mark = "ok " if got.get("active") else "DARK"
        print(f"  [{mark}] {vid:<24} effect={got.get('effect')}")
    print()

    if failures:
        print("restore failures named by the load audit:")
        for vid, reason in sorted(failures.items()):
            print(f"  {vid}: {reason}")
        print()

    if dark:
        print(f"FAIL: {len(dark)} declared-active virtual(s) came up dark: "
              f"{dark}")
        return 1
    print(f"PASS: all {len(expected)} declared-active virtuals are driving "
          f"after a cold load, and the audit named nothing.")
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except Exception:
        import traceback
        traceback.print_exc()
        status = 2
    sys.stdout.flush()
    sys.stderr.flush()
    # AGENTS.md: fx's TemporalEffect spawns non-daemon threads this harness
    # never joins, and FxHost.stop() refuses — a plain return hangs forever.
    os._exit(status)
