"""
Offline smoke test: Intensity Chooser + intensity scaling + trigger
color-group override.

Covers:
  1. chooser lane selection: default lane (no intensity / below first dot),
     threshold lower bounds, tie-break to the later lane, empty group no-op;
  2. _execute_action fires exactly the selected lane's actions, honoring
     resolved_picks pinning;
  3. plan-time _resolve_random_picks records the chooser pick from energy;
  4. nested chooser depth-cap doesn't loop;
  5. _scaled_intensity: song value beats genre, genre beats 1.0, clamps 0-1,
     None passes through;
  6. _resolve_color_ref: override wins for the "__scene_group__" sentinel,
     unknown/non-group cards fall back to the designated group, no override =
     unchanged behavior.

No LedFX writes: ledfx_client.trigger_scene is stubbed to a recorder.

USAGE
  .venv/bin/python scripts/smoke_intensity_features.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.music_event import (                     # noqa: E402
    IntensityChooserAction, IntensityLane, LedFxSceneAction, MusicEvent,
    SCENE_GROUP_COLOR_REF,
)
import services.trigger_engine as te_mod             # noqa: E402
from services.trigger_engine import TriggerEngine    # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def scene(sid: str) -> LedFxSceneAction:
    return LedFxSceneAction(scene_id=sid)


def chooser(*thresholds: float) -> IntensityChooserAction:
    """Default lane fires 'lane0'; each threshold t adds a lane firing 'laneN'."""
    lanes = [IntensityLane(threshold=0.0, actions=[scene("lane0")])]
    for i, t in enumerate(thresholds, start=1):
        lanes.append(IntensityLane(threshold=t, actions=[scene(f"lane{i}")]))
    return IntensityChooserAction(lanes=lanes)


async def main() -> None:
    eng = TriggerEngine()
    fired: list[str] = []

    async def fake_trigger_scene(sid: str) -> None:
        fired.append(sid)

    te_mod.ledfx_client.trigger_scene = fake_trigger_scene  # type: ignore

    print("1. lane selection")
    act = chooser(0.3, 0.6, 0.6)
    pick = TriggerEngine._pick_intensity_lane
    check("no intensity → default", pick(act, None) is act.lanes[0])
    check("below first dot → default", pick(act, 0.29) is act.lanes[0])
    check("exact threshold → that lane", pick(act, 0.3) is act.lanes[1])
    check("tie → later lane", pick(act, 0.7) is act.lanes[3])
    check("empty group → None", pick(IntensityChooserAction(), 0.5) is None)
    check("zero dots → default",
          pick(IntensityChooserAction(lanes=[IntensityLane(actions=[])]), 0.9) is not None)

    print("2. execution fires the selected lane only")

    async def run(intensity, action, picks=None):
        fired.clear()
        te_mod._FIRE_INTENSITY.set(intensity)
        await eng._execute_action(action, [], resolved_picks=picks)
        return list(fired)

    check("intensity 0.5 → lane1", await run(0.5, act) == ["lane1"])
    check("intensity 0.9 → lane3 (tie)", await run(0.9, act) == ["lane3"])
    check("no intensity → lane0", await run(None, act) == ["lane0"])
    pinned = {act.id: act.lanes[2].id}
    check("resolved_picks pins the lane", await run(0.1, act, pinned) == ["lane2"])

    print("3. plan-time pick resolution")
    out = eng._resolve_random_picks(act, [], energy=0.65)
    check("chooser recorded in picks", out.get(act.id) == act.lanes[3].id,
          f"got {out}")
    out2 = eng._resolve_random_picks(act, [], energy=None)
    check("no energy → default recorded", out2.get(act.id) == act.lanes[0].id)

    print("4. nesting depth cap")
    deep = chooser(0.5)
    inner = deep
    for _ in range(8):
        nxt = chooser(0.5)
        inner.lanes[0].actions = [nxt]
        inner = nxt
    inner.lanes[0].actions = [scene("bottom")]
    got = await run(None, deep)  # default lane chain
    check("deep nest terminates (cap)", got == [] or got == ["bottom"])

    print("5. intensity scaling")

    class P:  # minimal stand-in for SongProfile
        spotify_uri = "spotify:track:smoke"
        artist_genre = ["testcore"]
        intensity_scale = None
        intensity_scale_source = None

    import services.audio_shape_service as ass
    orig_find = ass._find_profile_for_genres
    ass._find_profile_for_genres = lambda genres: {"default_intensity_scale": 0.5}
    try:
        eng._profile = P()
        eng._genre_scale_uri = None
        # genre slider 0.5 → song scale 0.6*0.5+0.1 = 0.4 → 0.8*0.4 = 0.32
        check("genre fallback (compressed)", abs(eng._scaled_intensity(0.8) - 0.32) < 1e-9)
        P.intensity_scale = 1.5
        check("song value beats genre", eng._scaled_intensity(0.8) == 1.0)  # 1.2 clamped
        check("clamps to 1.0", eng._scaled_intensity(0.9) == 1.0)
        P.intensity_scale = 0.0
        check("0% → 0.0", eng._scaled_intensity(0.9) == 0.0)
        check("None passes through", eng._scaled_intensity(None) is None)
        eng._profile = None
        check("no profile → unscaled", eng._scaled_intensity(0.7) == 0.7)
    finally:
        ass._find_profile_for_genres = orig_find

    print("6. color-group override")
    grp = MusicEvent(id="sg", name="G", event_type="scene_group",
                     scene_group_color_ref_id="designated-group")
    orig_get_event = te_mod.get_event
    te_mod.get_event = lambda gid: grp if gid == "sg" else None
    from services import color_set_store

    class Card:
        def __init__(self, kind): self.kind = kind

    cards = {"override-group": Card("group"), "not-a-group": Card("set")}
    orig_get_by_id = color_set_store.get_by_id
    color_set_store.get_by_id = lambda cid: cards.get(cid)
    try:
        eng._active_scene_group_id = "sg"
        te_mod._FIRE_COLOR_GROUP.set(None)
        check("no override → designated",
              eng._resolve_color_ref(SCENE_GROUP_COLOR_REF) == "designated-group")
        te_mod._FIRE_COLOR_GROUP.set("override-group")
        check("override wins",
              eng._resolve_color_ref(SCENE_GROUP_COLOR_REF) == "override-group")
        te_mod._FIRE_COLOR_GROUP.set("deleted-card")
        check("missing card → designated",
              eng._resolve_color_ref(SCENE_GROUP_COLOR_REF) == "designated-group")
        te_mod._FIRE_COLOR_GROUP.set("not-a-group")
        check("non-group card → designated",
              eng._resolve_color_ref(SCENE_GROUP_COLOR_REF) == "designated-group")
        te_mod._FIRE_COLOR_GROUP.set("override-group")
        check("real ref ids untouched by override",
              eng._resolve_color_ref("some-real-id") == "some-real-id")
    finally:
        te_mod.get_event = orig_get_event
        color_set_store.get_by_id = orig_get_by_id

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
