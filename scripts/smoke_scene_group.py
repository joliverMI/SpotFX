"""
Offline smoke test: Scene Group events (event_type "scene_group").

Covers:
  1. cycle wrap order A→B→C→A, backward walks the other way;
  2. bounce reverses at the ends instead of wrapping;
  3. weighted mode excludes the current member when configured;
  4. empty group / deleted member handling (no-op / skip);
  5. firing a group sets _last_scene_update_id to the MEMBER (First on a
     newly rotated-to member, Rest on a repeat via advance=0);
  6. a direct scene_update fire clears the active group;
  7. Force Scene holding a group rotates one member per redirected pick,
     and stale plan-time picks are dropped;
  8. _pick_scene_lanes returns [] for groups (fire-time advance only).

No LedFX writes: _run_one_lane / _pick_lane_action are stubbed to recorders.

USAGE
  .venv/bin/python scripts/smoke_scene_group.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                          # noqa: E402
from models.music_event import MusicEvent            # noqa: E402
import services.trigger_engine as te_mod             # noqa: E402
from services.trigger_engine import TriggerEngine    # noqa: E402

A = MusicEvent(id="scene-A", name="Scene A", event_type="scene_update")
B = MusicEvent(id="scene-B", name="Scene B", event_type="scene_update")
C = MusicEvent(id="scene-C", name="Scene C", event_type="scene_update")

def group(gid="grp", members=("scene-A", "scene-B", "scene-C"), mode="cycle",
          behavior="wrap", exclude=True):
    return MusicEvent(
        id=gid, name=f"Group {gid}", event_type="scene_group",
        scene_group_members=[{"event_id": m} for m in members],
        scene_group_mode=mode, scene_group_cycle_behavior=behavior,
        scene_group_exclude_current=exclude,
    )

EVENTS = {e.id: e for e in (A, B, C)}
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
    te._scene_fire_cond = asyncio.Condition()

    async def _fake_run_one_lane(event, lane_index, labels, skip_event_ids=None,
                                 preselected=None, resolved_picks=None):
        lane_runs.append((event.id, lane_index))
        return preselected or object()
    te._run_one_lane = _fake_run_one_lane
    te._pick_lane_action = lambda event, lane_index, labels: (event.id, lane_index)
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

    # ── 1. cycle wrap forward + backward ───────────────────────────────────
    te = fresh_engine()
    g = group()
    picked = [te._select_scene_group_member(g).id for _ in range(4)]
    check("wrap forward A→B→C→A",
          picked == ["scene-A", "scene-B", "scene-C", "scene-A"], repr(picked))
    back = te._select_scene_group_member(g, direction="backward").id
    check("wrap backward steps back", back == "scene-C", back)

    # ── 2. bounce reverses at the ends ──────────────────────────────────────
    te = fresh_engine()
    g = group(gid="grp-b", behavior="bounce")
    picked = [te._select_scene_group_member(g).id for _ in range(5)]
    check("bounce A→B→C→B→A",
          picked == ["scene-A", "scene-B", "scene-C", "scene-B", "scene-A"],
          repr(picked))

    # ── 3. weighted excludes current ────────────────────────────────────────
    te = fresh_engine()
    g = group(gid="grp-w", mode="weighted", exclude=True)
    last = te._select_scene_group_member(g).id
    repeats = [te._select_scene_group_member(g).id for _ in range(20)]
    no_repeat = all(a != b for a, b in zip([last] + repeats, repeats))
    check("weighted never repeats the current member", no_repeat, repr(repeats[:6]))

    # ── 4. empty group / dead member ────────────────────────────────────────
    te = fresh_engine()
    check("empty group returns None",
          te._select_scene_group_member(group(gid="grp-e", members=())) is None)
    g = group(gid="grp-d", members=("scene-A", "gone", "scene-C"))
    picked = [te._select_scene_group_member(g).id for _ in range(3)]
    check("deleted member is skipped", "gone" not in picked
          and picked[:2] == ["scene-A", "scene-C"], repr(picked))
    tag = await te._execute_scene_group(group(gid="grp-e2", members=()), [])
    check("firing an empty group is a tagged no-op", tag == "(empty scene group)", tag)

    # ── 5. group fire → member is the last scene, First then Rest ──────────
    te = fresh_engine()
    g = group(gid="grp-f", members=("scene-A", "scene-B"))
    EVENTS[g.id] = g
    lane_runs.clear()
    tag = await te._execute_scene_event(g, [])
    check("group fire runs member First lane", lane_runs == [("scene-A", 0)],
          repr(lane_runs))
    check("member becomes last scene", te._last_scene_update_id == "scene-A")
    check("group becomes active", te._active_scene_group_id == "grp-f")
    check("tag names group and member", "Group grp-f" in tag and "Scene A" in tag, tag)
    lane_runs.clear()
    await te._execute_scene_event(g, [])
    check("next group fire rotates to B (First)", lane_runs == [("scene-B", 0)],
          repr(lane_runs))

    # ── 6. direct scene_update clears the active group ─────────────────────
    lane_runs.clear()
    await te._execute_scene_event(C, [])
    check("direct scene pick clears active group",
          te._active_scene_group_id is None and te._last_scene_update_id == "scene-C")

    # ── 7. Force Scene holds a group: every pick rotates it ────────────────
    te = fresh_engine()
    g = group(gid="grp-fs", members=("scene-A", "scene-B"))
    EVENTS[g.id] = g
    _set("force_scene_enabled", True)
    _set("force_scene_event_id", "grp-fs")
    lane_runs.clear()
    await te._execute_scene_event(C, [])   # any scene pick → group advance
    await te._execute_scene_event(C, [])
    await te._execute_scene_event(C, [])   # wraps back to A → Rest? no: A repeat=False? cursor A,B,A
    check("forced group rotates per pick",
          [r[0] for r in lane_runs] == ["scene-A", "scene-B", "scene-A"],
          repr(lane_runs))
    check("rotated-to member runs First each time (not the last scene)",
          [r[1] for r in lane_runs] == [0, 0, 0], repr(lane_runs))
    check("forced group is the active group", te._active_scene_group_id == "grp-fs")
    # stale plan picks (rolled against a scene_update) never reach the lanes
    lane_runs.clear()
    await te._execute_scene_event(C, [], preselected={0: ("stale", 0)},
                                  picks_event_id="scene-C")
    check("stale picks dropped on forced-group redirect",
          lane_runs and lane_runs[0][0] == "scene-B", repr(lane_runs))

    # ── 8b. Rest-lane scene_morph must not clobber the last scene ──────────
    # Poison state seen live: cursor points at B while last-scene says A, so
    # every group fire selects A as a "repeat" → Rest → morph fires B First —
    # and stamping last AFTER the lane would reset it to A, locking the loop
    # (B's setter fires on every pick, A's never; room pinned to one member).
    from types import SimpleNamespace
    te = fresh_engine()
    g = group(gid="grp-p", members=("scene-A", "scene-B"))
    EVENTS[g.id] = g
    te._active_scene_group_id = "grp-p"
    te._scene_cursor["grp-p"] = 1          # cursor on B...
    te._last_scene_update_id = "scene-A"   # ...but engine thinks A is live

    real_runner = te._run_one_lane

    async def morphing_runner(event, lane_index, labels, skip_event_ids=None,
                              preselected=None, resolved_picks=None):
        lane_runs.append((event.id, lane_index))
        if lane_index == 1:  # Rest lane holds a scene_morph (advance 1)
            await te._execute_scene_morph(
                SimpleNamespace(advance=1, direction="forward"),
                labels, skip_event_ids)
        return object()
    te._run_one_lane = morphing_runner

    lane_runs.clear()
    await te._execute_scene_event(g, [])
    check("poisoned pick runs A Rest then morphs to B First",
          lane_runs == [("scene-A", 1), ("scene-B", 0)], repr(lane_runs))
    check("morphed-to member stays the last scene (no clobber)",
          te._last_scene_update_id == "scene-B", te._last_scene_update_id)
    lane_runs.clear()
    await te._execute_scene_event(g, [])
    check("next pick escapes the loop (A First, not Rest again)",
          lane_runs == [("scene-A", 0)], repr(lane_runs))
    te._run_one_lane = real_runner

    # ── 8. plan preview: groups resolve at fire time ────────────────────────
    check("plan preview returns [] when a group is forced",
          te._pick_scene_lanes(C, []) == [])
    _set("force_scene_enabled", False)
    _set("force_scene_event_id", "")
    check("plan preview returns [] for a direct group fire",
          te._pick_scene_lanes(g, []) == [])

    print("OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
