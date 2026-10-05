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


def cpu_seconds(pid: int) -> float:
    """utime+stime of a process (all threads), in seconds, from /proc."""
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")
