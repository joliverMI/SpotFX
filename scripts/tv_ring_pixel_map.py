"""The TV ring: a per-LED lookup for `tv-backlight` so every strip effect
turns round the screen like a sconce (the star improve plan, 2026-11-12 —
his "The TV currently has blobs all moving ... because of how it is
segmented. Make it work more radially, like the other round strips
(sconces)"; Q9 default: ring by angle about the TV's centre; Q6: a device
fix applied to every strip effect on the TV).

WHY A SCONCE LOOKS RADIAL AND THE TV DID NOT: `tv-mapper` is a copy-mapped
virtual — the strip effect renders once at 560 px and every segment gets
that frame resampled, so a 28-px sconce ring shows the whole pattern
wrapped once round and every blob is an arc; the TV got the same 560 px
one-to-one along its perimeter, where a blob is a stretch of one edge.

THE LOOKUP: physical LED i shows effect pixel round(theta_i / 2pi * 560),
theta_i the angle of LED i's real position about the screen centre
(config/tv_backlight_layout.json — HyperHDR's layout on the strip's own Pi,
aspect-corrected to 16:9 so angle is angle, not screen fraction). Equal
ANGLE per pixel, not equal length: a blob is the same arc on the long and
the short edges and turns about the centre at the effect's own pace. The
device's `center_offset` (90 today — a roll that only made sense for a
one-to-one loop) is SUPERSEDED by the angle table and set to 0 — a ring
pattern's start angle has no visible meaning, so there is nothing to fold
in; the old value is kept in the revert sidecar so undo restores it.
`fx/devices/__init__.py` applies `pixel_map` in assemble_frame for EVERY
effect the device shows; an empty map is today.

The map is a permutation of 0..559 (asserted), so no effect pixel is lost
and none is shown twice.

Operates on the fx config SPECTRA runs (`storage/spectra/fx-live/config.json`
by default) — raw JSON, two keys on one device entry (`pixel_map`,
`center_offset`), timestamped backup, --revert (empty map, center_offset
back to what was recorded in the map's own sidecar), dry run by default.
Applied at deploy by DJ (a `spectra` restart loads it; the restart hazard
in AGENTS.md applies).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config as spectra_config                # noqa: E402

DEVICE_ID = "tv-backlight"
LAYOUT = Path(__file__).resolve().parent.parent / "config" / "tv_backlight_layout.json"
ASPECT = 16.0 / 9.0


def load_layout(path: Path = LAYOUT) -> list[tuple[float, float]]:
    """Each LED's centre in screen fractions (x right, y down)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return [((l[0] + l[1]) / 2.0, (l[2] + l[3]) / 2.0) for l in d["leds"]]


def ring_map(centres: list[tuple[float, float]]) -> list[int]:
    """effect pixel index for each physical LED, by angle about the screen
    centre (0 at the top, clockwise seen from the front), aspect-corrected.
    Ties in angle are broken by LED order; the result is a permutation."""
    n = len(centres)
    ang = []
    for i, (u, v) in enumerate(centres):
        a = math.atan2((u - 0.5) * ASPECT, -(v - 0.5))     # 0 at the top, clockwise
        ang.append(((a % (2 * math.pi)), i))
    # rank the LEDs by angle; the k-th LED round the ring shows effect pixel k
    order = sorted(range(n), key=lambda i: ang[i])
    table = [0] * n
    for k, led in enumerate(order):
        table[led] = k
    assert sorted(table) == list(range(n)), "the ring map must be a permutation"
    return table


def _device(cfg: dict) -> dict:
    hits = [d for d in cfg.get("devices", []) if d.get("id") == DEVICE_ID]
    if len(hits) != 1:
        raise SystemExit(f"{DEVICE_ID}: {len(hits)} device entries in the config — refusing")
    return hits[0]


def run(config_file: Path, *, apply: bool, revert: bool) -> dict:
    if not config_file.exists():
        raise SystemExit(f"no {config_file}")
    cfg = json.loads(config_file.read_text(encoding="utf-8"))
    dev = _device(cfg)
    dcfg = dev.setdefault("config", {})
    n = int(dcfg.get("pixel_count", 0))
    centres = load_layout()
    if n != len(centres):
        raise SystemExit(f"{DEVICE_ID} has {n} pixels, the layout {len(centres)} — refusing")
    sidecar = config_file.parent / f"{DEVICE_ID}.pixel-map-prior.json"
    cur_map = dcfg.get("pixel_map") or []
    cur_off = int(dcfg.get("center_offset", 0) or 0)
    if revert:
        prior = json.loads(sidecar.read_text()) if sidecar.exists() else {"center_offset": 0}
        new_map, new_off = [], int(prior.get("center_offset", 0))
    else:
        new_map, new_off = ring_map(centres), 0
    change = {"device": DEVICE_ID, "pixel_map": (len(cur_map), len(new_map)),
              "center_offset": (cur_off, new_off)}
    print(f"— {DEVICE_ID}: pixel_map {len(cur_map)} -> {len(new_map)} entries, "
          f"center_offset {cur_off} -> {new_off}")
    if cur_map == new_map and cur_off == new_off:
        print("nothing to do")
        return change
    if not apply:
        print(f"\nDRY RUN — would write {config_file} (use --apply); only "
              f"{DEVICE_ID}'s pixel_map and center_offset change.")
        return change
    backup_dir = config_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    shutil.copy2(config_file, backup_dir / f"fx-config-tv-ring-{stamp}.json")
    if not revert and not sidecar.exists():
        sidecar.write_text(json.dumps({"center_offset": cur_off}))
    dcfg["pixel_map"] = new_map
    dcfg["center_offset"] = new_off
    fd, tmp = tempfile.mkstemp(dir=str(config_file.parent), prefix=".config-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, config_file)
    print(f"patched {config_file}")
    return change


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--config-file", type=Path,
                    default=Path(spectra_config.FX_LIVE_CONFIG_DIR) / "config.json")
    a = ap.parse_args()
    run(a.config_file, apply=a.apply, revert=a.revert)


if __name__ == "__main__":
    main()
