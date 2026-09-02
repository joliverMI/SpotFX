#!/usr/bin/env python
"""EXECUTABLE SPEC — where the pose fingerprint's boundaries actually sit,
measured through the real machinery rather than asserted.

`tests/test_pose_fingerprint.py` proves each verdict once. This walks the
whole range either side of every boundary and PRINTS what the instrument
says at each step, because the property that matters is not "it can say
camera_moved" but "there is nowhere in the range where it says something
confident and wrong". A gate whose boundary nobody has swept is a number
somebody hoped for.

WHAT IT SWEEPS, all through `pose_fingerprint.measure` -> the map's own
`room_mapping._map_one` -> the real footprint arithmetic -> the real
centroid:

  1  A CAMERA MOVE of growing size. Small enough is `match`; past the
     tolerance it must be `camera_moved` and never anything else.
  2  A ROOM CHANGE of growing size (one fixture moves, the rest stay).
     Small enough is `match`; large enough is `room_changed`; the band
     between is `cannot_tell`, which is the honest answer and NOT a gap.
  3  PARALLAX — a camera slid sideways, so every fixture moves by a
     different amount. It must NEVER read as `room_changed`.
  4  REPEAT NOISE — the same room photographed twice. How far the centroids
     wander is what `CENTROID_TOLERANCE` has to clear, so it is measured
     here rather than believed.
  5  ANCHOR COUNT AND SPREAD — the two cases that can never discriminate,
     and which say so at establishment.

Read-only and offline: no camera, no room, no light, and no store is
written (the measurement runs against a throwaway room with no `save_room`,
exactly as production does).
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from spectra import config as scfg

# BELT AND BRACES: nothing on this path writes a store (every measurement
# runs against a throwaway room), but a check script that reaches real code
# repoints its stores anyway — the established per-script isolation pattern.
_TMP = tempfile.mkdtemp(prefix="check-pose-fingerprint-")
scfg.ROOM_MAPS_FILE = os.path.join(_TMP, "room_maps.json")
scfg.CALIBRATIONS_DIR = os.path.join(_TMP, "calibrations")

from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration, Point,  # noqa: E402
                                     RoomMap)
from spectra.services import mapping_refusals, room_mapping  # noqa: E402
from spectra.services import capture_settings as cs  # noqa: E402
from spectra.services import pose_fingerprint as pf  # noqa: E402

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
BLOB_SIGMA = 0.05
BLOB_PEAK = 200.0
CARRIERS = ["north", "east", "south", "west"]
ROOM = {"north": (0.25, 0.25), "east": (0.75, 0.30),
        "south": (0.70, 0.72), "west": (0.28, 0.70)}

_X, _Y = np.meshgrid((np.arange(GRID_W) + 0.5) / GRID_W,
                     (np.arange(GRID_H) + 0.5) / GRID_H)

failures: list[str] = []


def check(ok: bool, what: str) -> bool:
    print(f"  {'PASS: ' if ok else 'FAIL: '}{what}")
    if not ok:
        failures.append(what)
    return ok


def _frame(blobs: dict, lit: list[str], rng=None) -> np.ndarray:
    grid = np.zeros((GRID_H, GRID_W), dtype=np.float64)
    for vid in lit:
        if vid not in blobs:
            continue
        cx, cy = blobs[vid]
        grid += BLOB_PEAK * np.exp(-((_X - cx) ** 2 + (_Y - cy) ** 2)
                                   / (2 * BLOB_SIGMA ** 2))
    if rng is not None:
        grid = grid + rng.uniform(-2.0, 2.0, grid.shape)
    return np.clip(grid, 0.0, 255.0)


class Session(cs.SessionCameraDouble):
    pose_id = "pose-check"
    id = "sess-check"
    closed = False
    run_abort = None
    keep_full_frames = False
    lever_verdict = None

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"
        locked = True

        @staticmethod
        def as_dict():
            return {"exposure_locked": True, "white_balance_locked": True,
                    "exposure_time": None, "gain": None,
                    "exposure_time_range": [3.0, 2047.0],
                    "manual_refusals": []}

    def __init__(self, blobs, seed=None):
        self.blobs = dict(blobs)
        self.lit: list[str] = []
        self.rng = np.random.default_rng(seed) if seed is not None else None
        self.hello = {"client": "spectra-capture-client", "host": "check",
                      "camera": {"kind": "v4l2", "device": "/dev/video0"}}
        self.camera_lock = dict(self.lock.as_dict())

    def refusal(self):
        return None

    def _camera_clock(self):
        return 0.0

    def _camera_lock_view(self):
        return dict(self.camera_lock)

    async def gather(self, seconds, min_frames=1):
        n = max(min_frames, room_mapping.MIN_FRAMES)
        grids = [_frame(self.blobs, self.lit, self.rng) for _ in range(n)]
        return grids, [int(g.max()) for g in grids]


def _deps(session):
    async def get_virtuals():
        return {c: {"active": True, "pixel_count": 20,
                    "config": {"grouping": 1},
                    "segments": [[f"{c}-fixture", 0, 19, False]],
                    "effect": {"type": "singleColor", "config": {}}}
                for c in CARRIERS}

    async def chains():
        return {c: [{"id": f"{c}-fixture", "type": "wled"}] for c in CARRIERS}

    async def open_hold(program, intensity, *, step="dark", **kw):
        session.lit = list(program.lit_virtual_ids) if step == "lit" else []
        return {"held": True}

    async def close_hold():
        return None

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=close_hold, sleep=sleep,
        clock=lambda: 0.0, spectra_owns=lambda: True)


def measure(blobs, seed=None):
    sess = Session(blobs, seed=seed)
    room = RoomMap(name="Check", carrier_ids=list(CARRIERS), axis=AXIS)
    return asyncio.run(pf.measure(room, _deps(sess))).references


def main() -> int:
    tol = pf.CENTROID_TOLERANCE
    print("THE POSE FINGERPRINT — where the boundaries actually sit\n")
    print(f"  centroid tolerance   {tol:.3f} of frame width "
          f"({tol * GRID_W:.1f} grid cells)")
    print(f"  move separation      x{pf.MOVE_SEPARATION:g} "
          f"(= {tol * pf.MOVE_SEPARATION:.3f})")
    print(f"  min anchors          {pf.MIN_DISCRIMINATING}")
    print(f"  min anchor spread    {pf.MIN_ANCHOR_SPREAD:.3f}\n")

    base = measure(ROOM)
    print(f"§0  the room, measured: "
          + ", ".join(f"{r.emitter_id}({r.x:.3f},{r.y:.3f}) w={r.weight:.1f}"
                      for r in base) + "\n")

    # ── 1. a camera move, swept ────────────────────────────────────────────
    print("§1  A CAMERA MOVE, swept. Every fixture shifts by one vector.")
    for d in (0.005, 0.015, 0.025, 0.04, 0.08, 0.15, 0.25):
        moved = {v: (x + d, y) for v, (x, y) in ROOM.items()}
        j = pf.judge(base, measure(moved))
        print(f"    shift {d:.3f}  ->  {j.verdict:<13} "
              f"(common {j.common_shift:.4f}, residual {j.max_residual:.4f})")
        if d <= tol * 0.6:
            check(j.verdict == mapping_refusals.POSE_MATCH,
                  f"a {d:.3f} shift is inside the band and reads as a match")
        elif d >= tol * 1.5:
            check(j.verdict == mapping_refusals.POSE_CAMERA_MOVED,
                  f"a {d:.3f} shift is named as the camera")
        # The band between is allowed to be either — what is NOT allowed is
        # a camera move ever reading as the ROOM.
        check(j.verdict != mapping_refusals.POSE_ROOM_CHANGED,
              f"a {d:.3f} camera shift never reads as the room")
    print()

    # ── 2. a room change, swept ────────────────────────────────────────────
    print("§2  A ROOM CHANGE, swept. ONE fixture moves; the rest stay put.")
    for d in (0.005, 0.02, 0.05, 0.10, 0.20, 0.30):
        moved = dict(ROOM)
        x, y = moved["east"]
        moved["east"] = (x + d, y)
        j = pf.judge(base, measure(moved))
        print(f"    one fixture {d:.3f}  ->  {j.verdict:<13} "
              f"(moved {j.moved} of {j.checked})")
        if d <= tol * 0.6:
            check(j.verdict == mapping_refusals.POSE_MATCH,
                  f"one fixture moving {d:.3f} is inside the band")
        elif d >= tol * pf.MOVE_SEPARATION * 1.2:
            check(j.verdict == mapping_refusals.POSE_ROOM_CHANGED,
                  f"one fixture moving {d:.3f} is named as the room")
        check(j.verdict != mapping_refusals.POSE_CAMERA_MOVED,
              f"one fixture moving {d:.3f} never reads as the camera")
    print()

    # ── 3. parallax ────────────────────────────────────────────────────────
    print("§3  PARALLAX — a camera SLID sideways: every fixture moves, by a "
          "different amount.")
    for spread_factor in (1.5, 3.0, 6.0):
        slid = {}
        for i, (v, (x, y)) in enumerate(sorted(ROOM.items())):
            slid[v] = (x + 0.04 * (1 + i * (spread_factor - 1) / 3), y)
        j = pf.judge(base, measure(slid))
        print(f"    depth ratio {spread_factor:.1f}  ->  {j.verdict:<13} "
              f"(common {j.common_shift:.4f}, residual {j.max_residual:.4f})")
        check(j.verdict != mapping_refusals.POSE_ROOM_CHANGED,
              f"a camera slid sideways (ratio {spread_factor:.1f}) never "
              f"reads as the room")
    print()

    # ── 4. repeat noise ────────────────────────────────────────────────────
    print("§4  REPEAT NOISE — the same room, photographed twice.")
    worst = 0.0
    for seed in range(1, 6):
        a = {r.emitter_id: r for r in measure(ROOM, seed=seed)}
        b = measure(ROOM, seed=seed + 100)
        w = max(math.dist((a[r.emitter_id].x, a[r.emitter_id].y), (r.x, r.y))
                for r in b)
        worst = max(worst, w)
        j = pf.judge(list(a.values()), b)
        print(f"    seed {seed}: worst centroid wander {w:.5f}  ->  {j.verdict}")
        check(j.verdict == mapping_refusals.POSE_MATCH,
              f"a re-measure of an unchanged room (seed {seed}) is a match")
    print(f"    worst over 5 pairs: {worst:.5f}  "
          f"({worst / tol * 100:.1f}% of the tolerance)")
    check(worst < tol / 3.0,
          "the instrument's own repeat wander is under a third of the "
          "tolerance it has to clear")
    print()

    # ── 5. what can never discriminate, and says so ────────────────────────
    print("§5  THE TWO ANCHOR SETS THAT CAN NEVER DISCRIMINATE.")
    two = base[:2]
    ok, note = pf.discriminating(two)
    print(f"    {len(two)} anchors -> discriminating={ok}: {note[:90]}...")
    check(ok is False, "two anchors are declared non-discriminating at "
                       "establishment")
    shifted_two = [r.model_copy(update={"x": r.x + 0.2}) for r in two]
    check(pf.judge(two, shifted_two).verdict == mapping_refusals.POSE_CANNOT_TELL,
          "two anchors shifting together still says it cannot tell")
    check(pf.judge(two, two).verdict == mapping_refusals.POSE_MATCH,
          "a non-discriminating pose can still say nothing changed")

    clustered = [r.model_copy(update={"x": 0.5 + 0.01 * i, "y": 0.5})
                 for i, r in enumerate(base)]
    ok2, note2 = pf.discriminating(clustered)
    print(f"    clustered spread {pf.spread(clustered):.3f} -> "
          f"discriminating={ok2}")
    check(ok2 is False, "anchors lighting one part of the frame are declared "
                        "non-discriminating at establishment")
    moved_cluster = [r.model_copy(update={"x": r.x + 0.2}) for r in clustered]
    check(pf.judge(clustered, moved_cluster).verdict
          == mapping_refusals.POSE_CANNOT_TELL,
          "a clustered pose shifting wholesale still says it cannot tell")
    print()

    if failures:
        print(f"{len(failures)} CHECK(S) FAILED")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL POSE FINGERPRINT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
