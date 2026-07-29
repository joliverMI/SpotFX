"""
Offline smoke test: SetColorAction sentinel refs + Scene Group Color Group.

Covers _resolve_color_ref / _execute_set_color resolution:
  1. a real card id passes through untouched;
  2. "__scene_group__" → the active scene_group's scene_group_color_ref_id;
  3. active group with NO designated Color Group → falls back to the current
     (last-fired) group;
  4. no active scene group at all → current group;
  5. nothing resolvable → "" (executor no-ops);
  6. "__current__" → last_color_group_id ("" when none yet);
  7. firing a real Color Group via _execute_set_color records it as the
     current group (state.last_color_group_id).

No LedFX writes: the one _execute_set_color call bails on a missing member.

USAGE
  .venv/bin/python scripts/smoke_color_ref_resolution.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.music_event import (                      # noqa: E402
    MusicEvent, SetColorAction,
    SCENE_GROUP_COLOR_REF, CURRENT_COLOR_GROUP_REF,
)
from models.color_set import ColorSetCard, GroupMember  # noqa: E402
from models.state import state                        # noqa: E402
import services.trigger_engine as te_mod              # noqa: E402
from services import color_set_store                  # noqa: E402
from services.trigger_engine import TriggerEngine     # noqa: E402

GROUP_WITH_COLOR = MusicEvent(
    id="sg-colored", name="SG colored", event_type="scene_group",
    scene_group_color_ref_id="cg-designated",
)
GROUP_PLAIN = MusicEvent(id="sg-plain", name="SG plain", event_type="scene_group")
EVENTS = {e.id: e for e in (GROUP_WITH_COLOR, GROUP_PLAIN)}

CARDS = {
    "cg-live": ColorSetCard(
        id="cg-live", name="Live Group", kind="group",
        members=[GroupMember(color_set_id="missing-set")],
    ),
}


def fresh_engine(active_group: str | None = None, last_group: str = ""):
    te = object.__new__(TriggerEngine)
    te._active_scene_group_id = active_group
    te._color_cursor = {}
    te._color_cursor_dir = {}
    te._color_cursor_prev = {}
    te._palette_hue = None
    te._signal_now = lambda name: 0.0
    state.active_scene_group_id = active_group or ""
    state.last_color_group_id = last_group
    return te


PASS = 0


def check(label: str, got, want):
    global PASS
    ok = got == want
    print(f"  {'✓' if ok else '✗ FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        sys.exit(1)
    PASS += 1


def main():
    te_mod.get_event = lambda eid: EVENTS.get(eid)
    color_set_store.get_by_id = lambda cid: CARDS.get(cid)

    print("1. real id passes through")
    check("real id", fresh_engine()._resolve_color_ref("cg-live"), "cg-live")

    print("2. scene-group sentinel → designated group")
    te = fresh_engine(active_group="sg-colored")
    check("designated", te._resolve_color_ref(SCENE_GROUP_COLOR_REF), "cg-designated")

    print("3. active group designates nothing → current group fallback")
    te = fresh_engine(active_group="sg-plain", last_group="cg-last")
    check("fallback to current", te._resolve_color_ref(SCENE_GROUP_COLOR_REF), "cg-last")

    print("4. no active group → current group")
    te = fresh_engine(last_group="cg-last")
    check("no active group", te._resolve_color_ref(SCENE_GROUP_COLOR_REF), "cg-last")

    print("5. nothing resolvable → ''")
    check("empty", fresh_engine()._resolve_color_ref(SCENE_GROUP_COLOR_REF), "")

    print("6. current sentinel")
    check("current", fresh_engine(last_group="cg-last")._resolve_color_ref(CURRENT_COLOR_GROUP_REF), "cg-last")
    check("current empty", fresh_engine()._resolve_color_ref(CURRENT_COLOR_GROUP_REF), "")

    print("7. firing a group records it as current")
    te = fresh_engine()
    action = SetColorAction(ref_id="cg-live")
    asyncio.run(te._execute_set_color(action))  # bails on missing member set
    check("last_color_group_id", state.last_color_group_id, "cg-live")

    print(f"\nAll {PASS} checks passed.")


if __name__ == "__main__":
    main()
