"""Shared pieces of the preview perf rig: his real favourite shapes, on DUMMY
devices only. Nothing here can reach a real fixture."""
from __future__ import annotations

import json
import os

# (virtual id, pixel_count, rows) -- his live favourites, read 2026-10-05 from
# GET /spectra/api/device-preview/favorites and fx-live/config.json.
SHAPES = [
    ("crystal-mapper", 2664, 37),
    ("tv-mapper", 736, 1),
    ("hues", 17, 1),
    ("single-color-effect", 2, 1),
]
LATENCY_ID = "hues"          # flashed black<->white for input-to-photon
MOTION_ID = "crystal-mapper"  # carries the motion / jitter measurement
# singleColor redraws on its OWN loop, every 100 ms at speed 1 — so a flash
# waited 0 to 100 ms inside the effect before any preview code saw it, on
# both systems, and eight flashes could not average that out. At speed 10
# the loop is 10 ms and the number measures the preview.
LATENCY_SPEED = 10.0

RAINBOW = ("linear-gradient(90deg, rgb(255,0,0) 0%, rgb(255,200,0) 14%, rgb(0,255,0) 28%, "
           "rgb(0,255,255) 42%, rgb(0,0,255) 56%, rgb(255,0,255) 70%, rgb(0,0,0) 85%, rgb(255,0,0) 100%)")


def effect_for(vid: str) -> dict:
    if vid == LATENCY_ID:
        return {"type": "singleColor",
                "config": {"color": "#000000", "speed": LATENCY_SPEED}}
    return {"type": "gradient",
            "config": {"gradient": RAINBOW, "gradient_roll": 6, "speed": 5.0}}


def build_config(version: str, extra: dict | None = None) -> dict:
    devices, virtuals = [], []
    for vid, n, rows in SHAPES:
        devices.append({"id": vid, "type": "dummy",
                        "config": {"name": vid, "pixel_count": n}})
        virtuals.append({
            "id": vid, "is_device": vid, "auto_generated": False, "active": True,
            "config": {"name": vid, "mapping": "span", "rows": rows,
                       "transition_time": 0.0},
            "segments": [[vid, 0, n - 1, False]],
            "effect": effect_for(vid),
        })
    cfg = {"configuration_version": version, "devices": devices, "virtuals": virtuals}
    cfg.update(extra or {})
    return cfg


def write_config(config_dir: str, version: str, extra: dict | None = None) -> None:
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(build_config(version, extra), f)


# ── his room's real topology, on dummies (the Live view rows) ───────────────
# Segment lists read 2026-10-05 from fx-live/config.json. FxHost sees only
# dummy devices; PRETEND_TYPES is what the rig tells the layout endpoint they
# are, so the Live view draws his fixtures' real kinds (a frame, bulbs, ...).
PRETEND_TYPES = {
    "crystal": "wled", "tv-backlight": "wled", "sconce-kitchen-left": "wled",
    "sconce-kitchen-right": "wled", "hue-lights": "hue", "dining-hues": "hue",
    "porch-rail": "wled", "dining-table": "wled",
}
ROOM_NAMES = {
    "crystal": "Crystal", "tv-backlight": "TV Backlight",
    "sconce-kitchen-left": "Sconce, Kitchen, Left",
    "sconce-kitchen-right": "Sconce, Kitchen, Right", "hue-lights": "Hue Lights",
    "dining-hues": "Dining Hues", "porch-rail": "Porch Rail", "dining-table": "Dining Table",
}


def _crystal_segments(repo: str) -> list:
    with open(os.path.join(repo, "storage", "device_profiles", "crystal-mapper.json")) as f:
        runs = json.load(f)["mask_rle"]
    segments, pixel, device_pixel, real = [], 0, 0, False
    for run in runs:
        for _ in range(run):
            if real:
                segments.append(["crystal", device_pixel, device_pixel, False, 0])
                device_pixel += 1
            else:
                segments.append(["gap-crystal-mapper", pixel, pixel, False, 0])
            pixel += 1
        real = not real
    return segments


def build_room_config(version: str, repo: str) -> dict:
    sizes = {"crystal": 976, "gap-crystal-mapper": 4096, "tv-backlight": 560,
             "sconce-kitchen-left": 88, "sconce-kitchen-right": 88, "hue-lights": 10,
             "dining-hues": 7, "porch-rail": 1, "dining-table": 1}
    devices = [{"id": d, "type": "dummy",
                "config": {"name": ROOM_NAMES.get(d, d), "pixel_count": n}}
               for d, n in sizes.items()]
    shapes = {
        "crystal-mapper": ("span", 37, _crystal_segments(repo)),
        "tv-mapper": ("copy", 1, [["tv-backlight", 0, 559, False, 0],
                                  ["sconce-kitchen-right", 0, 27, False, 0],
                                  ["sconce-kitchen-right", 28, 87, False, 0],
                                  ["sconce-kitchen-left", 0, 27, False, -2],
                                  ["sconce-kitchen-left", 28, 87, False, -4]]),
        "hues": ("copy", 1, [["hue-lights", i, i, False, 0] for i in range(10)]
                 + [["dining-hues", i, i, False, 0] for i in range(7)]),
        "single-color-effect": ("copy", 1, [["porch-rail", 0, 0, False, 0],
                                            ["dining-table", 0, 0, False, 0]]),
    }
    virtuals = [{
        "id": vid, "is_device": False, "auto_generated": False, "active": True,
        "config": {"name": vid, "mapping": mapping, "rows": rows, "transition_time": 0.0},
        "segments": segments, "effect": effect_for(vid),
    } for vid, (mapping, rows, segments) in shapes.items()]
    # The strips' own device virtuals, asleep as in his config: a camera
    # measures a copy-mapped carrier through these (room_maps.json names
    # their pixel ranges), so the Room map needs them to exist.
    virtuals += [{
        "id": dev, "is_device": dev, "auto_generated": False, "active": False,
        "config": {"name": dev, "mapping": "span", "rows": 1, "transition_time": 0.0},
        "segments": [[dev, 0, sizes[dev] - 1, False, 0]],
    } for dev in ("tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right")]
    return {"configuration_version": version, "devices": devices, "virtuals": virtuals}


# ── a camera pose for that room (the Live view's Room map rows) ─────────────
# Synthetic footprints, 64x36 like the real store's: a soft blob per measured
# emitter with a wide faint spill, so the glow is as costly to add up as a
# real one. DENSER than his room is today (every block of the TV strip and
# both sconces seen, 74 emitters against his 12), so the gate measures the
# view with the whole room mapped.
MAP_POSE = "rigpose1"


def _blob(cx: float, cy: float, spread: float, peak: float) -> list[float]:
    import math
    out = []
    for row in range(36):
        for col in range(64):
            d2 = ((col + 0.5) / 64 - cx) ** 2 + (((row + 0.5) / 36 - cy) * 9 / 16) ** 2
            out.append(round(peak * (math.exp(-d2 / (2 * spread ** 2))
                                     + 0.08 * math.exp(-d2 / (2 * (spread * 6) ** 2))), 5))
    return out


def build_room_maps() -> dict:
    import math

    def footprint(emitter_id, carrier, grid, ranges=()):
        return {
            "emitter_id": emitter_id, "label": emitter_id, "carrier_id": carrier,
            "virtual_ids": sorted({r[0] for r in ranges}) or [carrier],
            "ranges": [{"virtual_id": v, "start": a, "end": b} for v, a, b in ranges],
            "grid": grid, "weight": round(sum(grid), 4),
            "capture": {"pose_id": MAP_POSE, "exposure_locked": True,
                        "white_balance_locked": True, "frame_width": 320, "frame_height": 180},
        }

    living = [footprint("unseen-sconce-tail", "tv-mapper", [],
                        [("sconce-kitchen-left", 80, 87)])]
    living[0].update({"unseen": True, "weight": 0.2, "note": "not seen from this pose"})
    for block in range(56):                      # the TV strip, round a screen
        turn = block / 56 * 2 * math.pi
        living.append(footprint(
            f"tv-backlight:blk{block}", "tv-mapper",
            _blob(0.36 + 0.13 * math.cos(turn), 0.6 + 0.18 * math.sin(turn), 0.02, 0.05),
            [("tv-backlight", block * 10, block * 10 + 9)]))
    for side, x in (("left", 0.62), ("right", 0.78)):
        for block in range(8):
            living.append(footprint(
                f"sconce-kitchen-{side}:blk{block}", "tv-mapper",
                _blob(x, 0.72 - block * 0.05, 0.016, 0.2),
                [(f"sconce-kitchen-{side}", block * 10, block * 10 + 9)]))
    rooms = [
        {"id": "rigliving", "name": "Living Room", "carrier_ids": ["tv-mapper"],
         "footprints": living},
        {"id": "rigcrystal", "name": "Crystal", "carrier_ids": ["crystal-mapper"],
         "footprints": [footprint("crystal-mapper", "crystal-mapper", _blob(0.52, 0.3, 0.035, 0.03))]},
        {"id": "rigdining", "name": "Dining Table + Porch", "carrier_ids": ["single-color-effect"],
         "footprints": [footprint("single-color-effect", "single-color-effect",
                                  _blob(0.86, 0.3, 0.03, 0.02))]},
    ]
    return {"rooms": rooms}


def cpu_seconds(pid: int) -> float:
    """utime+stime of a process (all threads), in seconds, from /proc."""
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")
