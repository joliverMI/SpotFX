"""
Offline smoke test: the scene_morph action steps the ACTIVE Scene Group.

Covers:
  1. no active group → no-op (no lanes run);
  2. after a group fires, scene_morph +1 / -1 walks the group and fires the
     member with normal First/Rest;
  3. advance=0 re-fires the current member (its Rest lane);
  4. Force Scene holding a single scene → no-op;
  5. Force Scene holding a group → scene_morph steps the FORCED group;
  6. ordinal stepping is forced even on weighted-mode groups;
  7. every scene_morph fire bumps the scene-fire counter (updates waits).

USAGE
  .venv/bin/python scripts/smoke_scene_morph.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                            # noqa: E402
from models.music_event import MusicEvent, SceneMorphAction  # noqa: E402
import services.trigger_engine as te_mod               # noqa: E402
from services.trigger_engine import TriggerEngine      # noqa: E402

A = MusicEvent(id="scene-A", name="Scene A", event_type="scene_update")
B = MusicEvent(id="scene-B", name="Scene B", event_type="scene_update")
C = MusicEvent(id="scene-C", name="Scene C", event_type="scene_update")
G = MusicEvent(
    id="grp", name="Group", event_type="scene_group",
    scene_group_members=[{"event_id": m} for m in ("scene-A", "scene-B", "scene-C")],
)
GW = MusicEvent(
    id="grp-w", name="Weighted Group", event_type="scene_group",
    scene_group_mode="weighted",
    scene_group_members=[{"event_id": m} for m in ("scene-A", "scene-B", "scene-C")],
)
EVENTS = {e.id: e for e in (A, B, C, G, GW)}
lane_runs: list[tuple[str, int]] = []


def _set(key, val):
    object.__setattr__(settings, key, val)


def fresh_engine():
    te = object.__new__(TriggerEngine)
    te._last_scene_update_id = None
    te._scene_cursor = {}
    te._scene_cursor_dir = {}
    te._scene_cursor_prev = {}
    te._active_scene_group_id = None
    te._scene_fire_seq = 0
    te._scene_fire_event = asyncio.Event()

    async def _fake_run_one_lane(event, lane_index, labels, skip_event_ids=None,
                                 preselected=None, resolved_picks=None):
        lane_runs.append((event.id, lane_index))
        return object()
    te._run_one_lane = _fake_run_one_lane
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

    # ── 1. no active group → no-op ─────────────────────────────────────────
    te = fresh_engine()
    lane_runs.clear()
    await te._execute_scene_morph(SceneMorphAction(), [])
    check("no active group: no-op", lane_runs == [], repr(lane_runs))

    # ── 2. group fires, then ±1 stepping ───────────────────────────────────
    await te._execute_scene_event(G, [])          # → A (First), group active
    lane_runs.clear()
    await te._execute_scene_morph(SceneMorphAction(advance=1), [])
    check("morph +1 fires B First", lane_runs == [("scene-B", 0)], repr(lane_runs))
    lane_runs.clear()
    await te._execute_scene_morph(
        SceneMorphAction(advance=1, direction="backward"), [])
    check("morph -1 flips back to A (First — not last scene)",
          lane_runs == [("scene-A", 0)], repr(lane_runs))

    # ── 3. advance=0 re-fires the current member → Rest ────────────────────
    lane_runs.clear()
    await te._execute_scene_morph(SceneMorphAction(advance=0), [])
    check("advance 0 re-fires current member (Rest)",
          lane_runs == [("scene-A", 1)], repr(lane_runs))

    # ── 4. forced single scene → no-op ─────────────────────────────────────
    _set("force_scene_enabled", True)
    _set("force_scene_event_id", "scene-C")
    lane_runs.clear()
    await te._execute_scene_morph(SceneMorphAction(), [])
    check("forced single scene: no-op", lane_runs == [], repr(lane_runs))

    # ── 5. forced group → steps the forced group ───────────────────────────
    te = fresh_engine()
    _set("force_scene_event_id", "grp-w")
    lane_runs.clear()
    await te._execute_scene_morph(SceneMorphAction(), [])
    check("forced group is stepped even with no prior fire",
          lane_runs == [("scene-A", 0)], repr(lane_runs))
    check("forced group becomes active", te._active_scene_group_id == "grp-w")

    # ── 6. weighted group still steps ordinally under scene_morph ──────────
    picked = []
    for _ in range(4):
        lane_runs.clear()
        await te._execute_scene_morph(SceneMorphAction(), [])
        picked.append(lane_runs[0][0])
    check("weighted group walks in order under scene_morph",
          picked == ["scene-B", "scene-C", "scene-A", "scene-B"], repr(picked))

    # ── 7. counter bumps per morph fire ────────────────────────────────────
    before = te._scene_fire_seq
    await te._execute_scene_morph(SceneMorphAction(), [])
    check("scene_morph bumps the scene-fire counter",
          te._scene_fire_seq == before + 1,
          f"{before} → {te._scene_fire_seq}")

    _set("force_scene_enabled", False)
    _set("force_scene_event_id", "")
    print("OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
