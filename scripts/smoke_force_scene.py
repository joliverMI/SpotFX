"""
Offline smoke test: Force Scene redirects every Scene Update fire.

With settings.force_scene_enabled + force_scene_event_id set to scene F:
  1. firing any other scene_update reasserts F instead: First lane (lane 0)
     when F isn't active yet, then F's Rest lane (lane 1) on repeats — the
     same First/Rest logic as a natural fire of F;
  2. plan-time picks rolled for a different event are dropped at fire time
     (picks_event_id guard), while picks rolled for F pass through;
  3. _pick_scene_lanes (plan preview) redirects the same way, so the Now
     Playing board previews the forced scene;
  4. flares still run against the forced scene once it is active;
  5. with the flag off (or a bogus event id) behavior is unchanged
     (First then Rest on the fired event itself).

No LedFX writes: _run_one_lane / _pick_lane_action are stubbed to recorders.

USAGE
  .venv/bin/python scripts/smoke_force_scene.py
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

F = MusicEvent(id="scene-F", name="Forced Scene", event_type="scene_update")
B = MusicEvent(id="scene-B", name="Other Scene", event_type="scene_update")
FLARE = MusicEvent(id="flare-C", name="Color Flare", event_type="color_flare")
EVENTS = {e.id: e for e in (F, B, FLARE)}

lane_runs: list[tuple[str, int, object]] = []  # (event_id, lane_index, preselected)


def _set(key, val):
    object.__setattr__(settings, key, val)


async def main() -> int:
    te_mod.get_event = lambda eid: EVENTS.get(eid)

    te = object.__new__(TriggerEngine)
    te._last_scene_update_id = None
    # Scene Group / updates-wait state the scene dispatch now touches.
    te._scene_cursor = {}
    te._scene_cursor_dir = {}
    te._scene_cursor_prev = {}
    te._active_scene_group_id = None
    te._scene_fire_seq = 0
    te._scene_fire_cond = asyncio.Condition()

    async def _fake_run_one_lane(event, lane_index, labels, skip_event_ids=None,
                                 preselected=None, resolved_picks=None):
        lane_runs.append((event.id, lane_index, preselected))
        return preselected or object()
    te._run_one_lane = _fake_run_one_lane
    te._pick_lane_action = lambda event, lane_index, labels: (event.id, lane_index)
    te._describe_action = lambda a: "x"

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
        ok = ok and cond

    # ── Flag off: normal First → Rest on the fired event ──────────────────
    _set("force_scene_enabled", False)
    _set("force_scene_event_id", "")
    await te._execute_scene_event(B, [])
    await te._execute_scene_event(B, [])
    check("off: First then Rest on fired event",
          lane_runs[:2] == [("scene-B", 0, None), ("scene-B", 1, None)],
          repr(lane_runs[:2]))

    # ── Flag on: reassert F — First once, then Rest ───────────────────────
    _set("force_scene_enabled", True)
    _set("force_scene_event_id", "scene-F")
    lane_runs.clear()
    tag1 = await te._execute_scene_event(B, [])
    tag2 = await te._execute_scene_event(B, [])
    tag3 = await te._execute_scene_event(F, [])
    check("on: every scene_update reasserts F (First then Rest)",
          [r[:2] for r in lane_runs] == [("scene-F", 0), ("scene-F", 1), ("scene-F", 1)],
          repr(lane_runs))
    check("on: F becomes the active scene", te._last_scene_update_id == "scene-F")
    check("on: tags are First then Rest", tag1.startswith("First")
          and tag2.startswith("Rest") and tag3.startswith("Rest"),
          f"{tag1!r} {tag2!r} {tag3!r}")

    # ── Pick provenance: stale picks dropped, F's picks kept ──────────────
    lane_runs.clear()
    sentinel = ("preselected", "action")
    await te._execute_scene_event(B, [], preselected={1: sentinel},
                                  picks_event_id="scene-B")
    await te._execute_scene_event(B, [], preselected={1: sentinel},
                                  picks_event_id="scene-F")
    check("picks for the replaced event are dropped", lane_runs[0][2] is None,
          repr(lane_runs[0]))
    check("picks rolled for F pass through", lane_runs[1][2] is sentinel,
          repr(lane_runs[1]))

    # ── Plan preview redirects the same way ───────────────────────────────
    picks = te._pick_scene_lanes(B, [])
    check("plan preview picks F's Rest lane (F active)",
          picks == [(1, ("scene-F", 1))], repr(picks))

    # ── Flares run against the forced scene ───────────────────────────────
    lane_runs.clear()
    await te._execute_scene_event(FLARE, [])
    check("flare runs on F's Color lane", lane_runs == [("scene-F", 3, None)],
          repr(lane_runs))

    # ── Bogus forced id falls back to normal behavior ─────────────────────
    _set("force_scene_event_id", "does-not-exist")
    lane_runs.clear()
    await te._execute_scene_event(B, [])
    check("bogus forced id: normal fire", lane_runs == [("scene-B", 0, None)],
          repr(lane_runs))

    _set("force_scene_enabled", False)
    _set("force_scene_event_id", "")
    print("OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
