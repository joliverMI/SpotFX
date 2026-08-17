"""Read-only fixture verification for Ambient's second colour
(spectra-dark-light-vs-ambient-ruling, SPECTRA_SPEC.md §63) — the room-proof
standing order requires ("verify at the bridges, not at our own status"),
reusing ambient.py's OWN light-resolution/matching code directly rather than
re-deriving which lights and which colour-match tolerance count, so this
proof is checked against the exact set and definition Ambient itself uses,
never a parallel guess.

HAZARD, same as scripts/verify_dark_light_fixtures.py: a disposable worktree
isolates the FILESYSTEM ONLY, not the NETWORK. This script has NO default
target — --config (the fx-live config.json carrying real bridge IPs and
credentials) is REQUIRED, so pointing this at his real bridges is something
you had to type, not something that happened by omission.

Makes ZERO writes: every call is a plain GET, via ambient._hue_get, never
ambient._hue_put. Trigger the actual display_mode/ambient_color_dark
change separately (PUT /api/room-controls) — run this before/after to see
the delta independently of whatever the PUT itself reported.

For each Hue bridge in the config, resolves the SAME light set
ambient._resolve_lights_named() would (the entertainment group's declared
members, not merely "every light on the bridge" — a bridge can carry many
unrelated lights), and reports each one's live on/xy against BOTH the
normal and dark target colours using ambient._color_matches's own
tolerance, so a human reading the output can tell at a glance which colour
(if either) each bulb currently carries.

Run from repo root:
    .venv/bin/python scripts/verify_ambient_dark_colour_fixtures.py \\
        --config /path/to/fx-live/config.json \\
        --normal-color '#f5da8c' --dark-color '#1a2a6c'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from spectra.services import ambient


def _hue_devices(config: dict) -> list[dict]:
    return [d for d in config.get("devices", []) if d.get("type") == "hue"]


async def _report_device(dev_id: str, cfg: dict, normal_xy, dark_xy) -> None:
    print(f"\n--- {dev_id} ({cfg.get('ip_address')}) ---")
    async with ambient._bridge_client(cfg) as client:
        try:
            lights = await ambient._resolve_lights_named(client, cfg)
        except Exception as exc:
            print(f"  ERROR resolving entertainment-group lights: {exc!r}")
            return
        print(f"  {len(lights)} light(s) in this device's entertainment group")
        for rid, name in lights:
            try:
                state = (await ambient._hue_get(
                    client, f"/clip/v2/resource/light/{rid}"))["data"][0]
            except Exception as exc:
                print(f"  light {rid} ({name}): ERROR reading state: {exc!r}")
                continue
            on = (state.get("on") or {}).get("on")
            xy = (state.get("color") or {}).get("xy") or {}
            x, y = xy.get("x"), xy.get("y")
            normal_match = ambient._color_matches(state, normal_xy) if normal_xy else False
            dark_match = ambient._color_matches(state, dark_xy) if dark_xy else False
            tag = ("NORMAL" if normal_match else "DARK" if dark_match else "neither") \
                if (normal_xy or dark_xy) else ""
            print(f"  light {rid} ({name}): on={on} xy=({x}, {y}) -> {tag}")


async def main_async(args) -> None:
    raw = json.loads(Path(args.config).read_text())
    devices = _hue_devices(raw)
    print(f"config: {args.config}")
    print(f"  {len(devices)} Hue device(s)")

    normal_xy = ambient._hex_to_xy(args.normal_color) if args.normal_color else None
    dark_xy = ambient._hex_to_xy(args.dark_color) if args.dark_color else None
    if args.normal_color:
        print(f"  normal colour {args.normal_color} -> xy {normal_xy}")
    if args.dark_color:
        print(f"  dark colour   {args.dark_color} -> xy {dark_xy}")

    for dev in devices:
        await _report_device(dev.get("id", dev.get("config", {}).get("name", "?")),
                             dev.get("config", {}), normal_xy, dark_xy)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True,
                        help="fx-live config.json path — required, no default (see module docstring)")
    parser.add_argument("--normal-color", default=None, help="hex, e.g. #f5da8c")
    parser.add_argument("--dark-color", default=None, help="hex, e.g. #1a2a6c")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
