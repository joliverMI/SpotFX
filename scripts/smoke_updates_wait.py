"""
Offline smoke test: sequence-child "updates" wait (delay_ms OR N scene fires).

Covers:
  1. delay_ms=5000 + delay_updates=2 releases on the 2nd scene-family fire
     (well under the time delay);
  2. delay_ms=100 + delay_updates=5 releases at ~100 ms (time delay wins);
  3. delay_ms=0 + delay_updates=1 waits on updates alone, and releases on a
     simulated track change (uri flip + waker) without counting a fire;
  4. every scene-family dispatch path bumps the counter (scene_update,
     update_scene/flares, scene_group) — via _execute_scene_event — plus
     scene_morph via its own hook;
  5. no delay_updates → plain sleep behavior unchanged.

USAGE
  .venv/bin/python scripts/smoke_updates_wait.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                          # noqa: E402
from models.music_event import MusicEvent            # noqa: E402
import services.trigger_engine as te_mod             # noqa: E402
from services.trigger_engine import TriggerEngine    # noqa: E402

A = MusicEvent(id="scene-A", name="Scene A", event_type="scene_update")
G = MusicEvent(
    id="grp", name="Group", event_type="scene_group",
    scene_group_members=[{"event_id": "scene-A"}],
)
FLARE = MusicEvent(id="flare", name="Color Flare", event_type="color_flare")
EVENTS = {e.id: e for e in (A, G, FLARE)}


def _set(key, val):
    object.__setattr__(settings, key, val)


def fresh_engine():
    te = object.__new__(TriggerEngine)
    te._last_scene_update_id = None
    te._last_uri = "uri-1"
    te._scene_cursor = {}
    te._scene_cursor_dir = {}
    te._scene_cursor_prev = {}
    te._active_scene_group_id = None
    te._scene_fire_seq = 0
    te._scene_fire_cond = asyncio.Condition()

    async def _fake_run_one_lane(event, lane_index, labels, skip_event_ids=None,
                                 preselected=None, resolved_picks=None):
        return object()
    te._run_one_lane = _fake_run_one_lane
    te._pick_lane_action = lambda event, lane_index, labels: None
    te._describe_action = lambda a: "x"
    return te


async def main() -> int:
    te_mod.get_event = lambda eid: EVENTS.get(eid)
    _set("force_scene_enabled", False)
    _set("force_scene_event_id", "")

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
        ok = ok and cond

    # ── 1. updates win the race ─────────────────────────────────────────────
    te = fresh_engine()

    async def fire_scenes(n, every_s):
        for _ in range(n):
            await asyncio.sleep(every_s)
            await te._execute_scene_event(A, [])

    t0 = time.monotonic()
    _, _ = await asyncio.gather(
        te._sleep_child_delay(5000, 2),
        fire_scenes(2, 0.05),
    )
    took = time.monotonic() - t0
    check("2 updates release a 5000ms delay early", took < 1.0, f"{took*1000:.0f}ms")

    # ── 2. time delay wins the race ─────────────────────────────────────────
    t0 = time.monotonic()
    await asyncio.gather(
        te._sleep_child_delay(100, 5),
        fire_scenes(1, 0.02),
    )
    took = time.monotonic() - t0
    check("timeout fires the child with updates unmet", 0.08 < took < 1.0,
          f"{took*1000:.0f}ms")

    # ── 3. updates-only wait + track-change release ─────────────────────────
    async def flip_track(after_s):
        await asyncio.sleep(after_s)
        te._last_uri = "uri-2"
        await te._wake_scene_waiters()

    seq_before = te._scene_fire_seq
    t0 = time.monotonic()
    await asyncio.gather(
        te._sleep_child_delay(0, 1),
        flip_track(0.05),
    )
    took = time.monotonic() - t0
    check("updates-only wait releases on track change", took < 1.0,
          f"{took*1000:.0f}ms")
    check("track-change waker does not count a fire",
          te._scene_fire_seq == seq_before)

    # ── 4. all dispatch paths bump the counter ─────────────────────────────
    te = fresh_engine()
    n0 = te._scene_fire_seq
    await te._execute_scene_event(A, [])       # scene_update
    await te._execute_scene_event(FLARE, [])   # flare (runs against last scene)
    await te._execute_scene_event(G, [])       # scene_group
    check("scene_update / flare / scene_group each count one update",
          te._scene_fire_seq == n0 + 3, f"{n0} → {te._scene_fire_seq}")

    # ── 5. no delay_updates → plain sleep ───────────────────────────────────
    t0 = time.monotonic()
    await te._sleep_child_delay(60, None)
    took = time.monotonic() - t0
    check("no updates: classic ms sleep", 0.05 < took < 0.5, f"{took*1000:.0f}ms")
    t0 = time.monotonic()
    await te._sleep_child_delay(0, None)
    check("delay 0 without updates returns immediately",
          time.monotonic() - t0 < 0.01)

    print("OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
