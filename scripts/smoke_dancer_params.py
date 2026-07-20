"""
Offline smoke test for the Dancer/GIF-effect engine paths.

Asserts, with a stubbed ledfx_client (no LedFX writes):
  1. string params: Dance GIF + Beat Frames land in ONE instant PUT patch;
  2. fallback_s: routes to set_virtual_effect_fallback with the FULL merged
     config (current tint preserved) and does not touch the cache;
  3. tint: color param patches (instant at ramp 0; gradient-ramp when smooth);
  4. the seeded Dancer event parses and its lanes contain the expected shapes.

USAGE
  .venv/bin/python scripts/smoke_dancer_params.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from api import ledfx_client                                    # noqa: E402
from models.music_event import (                                # noqa: E402
    EffectParamChange,
    LedFxEffectParamAction,
)
from models.state import state                                  # noqa: E402
from services import trigger_engine as te                       # noqa: E402
from services.trigger_engine import TriggerEngine               # noqa: E402

VID = "crystal-mapper"

passed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        sys.exit(1)


def seed_cache() -> None:
    state.ledfx_virtual_cache[VID] = {
        "effect": {
            "type": "keybeat2d",
            "config": {
                "image_location": "spotfx/dancer/dancer_basic.gif",
                "beat_frames": "0 3 6 9 12 15 18 21",
                "tint": "#20c0ff",
                "force_fit": True,
            },
        },
        "config": {},
    }


calls: list[tuple] = []


async def rec_set_virtual_effect(vid, etype, config):
    calls.append(("put", vid, etype, dict(config)))


async def rec_set_virtual_effect_fallback(vid, etype, config, fallback_s):
    calls.append(("fallback", vid, etype, dict(config), fallback_s))


def rec_ramp_gradient_params(vid, etype, patch, ramp_ms, step_ms=25):
    calls.append(("gradient_ramp", vid, etype, dict(patch), ramp_ms))
    async def _noop():
        pass
    return _noop()


ledfx_client.set_virtual_effect = rec_set_virtual_effect
ledfx_client.set_virtual_effect_fallback = rec_set_virtual_effect_fallback
ledfx_client.ramp_gradient_params = rec_ramp_gradient_params


async def main() -> None:
    engine = TriggerEngine()

    # 1 — style swap: image_location + beat_frames in ONE instant patch
    seed_cache()
    calls.clear()
    action = LedFxEffectParamAction(
        virtual_id=VID,
        ramp_ms=0,
        params=[
            EffectParamChange(param_label="Dance GIF", string_value="spotfx/dancer/dancer_disco.gif"),
            EffectParamChange(param_label="Beat Frames", string_value="0 3 6 9 12 15 18 21"),
        ],
    )
    await engine._execute_action(action)
    puts = [c for c in calls if c[0] == "put"]
    check("style swap is exactly one PUT", len(puts) == 1, repr(calls))
    check(
        "image_location + beat_frames in the same patch",
        puts[0][3].get("image_location") == "spotfx/dancer/dancer_disco.gif"
        and "beat_frames" in puts[0][3],
        repr(puts),
    )

    # 2 — fallback burst: merged config via set_virtual_effect_fallback
    seed_cache()
    calls.clear()
    burst = LedFxEffectParamAction(
        virtual_id=VID,
        fallback_s=7.0,
        params=[
            EffectParamChange(param_label="Dance GIF", string_value="spotfx/dancer/dancer_basic_big.gif"),
            EffectParamChange(param_label="Beat Frames", string_value="0 4 8 12"),
        ],
    )
    await engine._execute_action(burst)
    fbs = [c for c in calls if c[0] == "fallback"]
    check("fallback_s routes to set_virtual_effect_fallback", len(fbs) == 1, repr(calls))
    _, _, etype, merged, fb_s = fbs[0]
    check("fallback merges full config (tint preserved)",
          merged.get("tint") == "#20c0ff" and merged.get("force_fit") is True, repr(merged))
    check("fallback carries the big-move gif + seconds",
          merged.get("image_location") == "spotfx/dancer/dancer_basic_big.gif" and fb_s == 7.0,
          repr(fbs))
    check("fallback leaves cache untouched",
          state.ledfx_virtual_cache[VID]["effect"]["config"]["image_location"]
          == "spotfx/dancer/dancer_basic.gif", "")

    # 3 — tint: instant at ramp 0; gradient-ramp when ramped
    seed_cache()
    calls.clear()
    await engine._execute_action(LedFxEffectParamAction(
        virtual_id=VID, ramp_ms=0,
        params=[EffectParamChange(param_label="Dancer Color", string_value="#ff2080")],
    ))
    check("tint instant patch at ramp 0",
          any(c[0] == "put" and c[3].get("tint") == "#ff2080" for c in calls), repr(calls))
    seed_cache()
    calls.clear()
    await engine._execute_action(LedFxEffectParamAction(
        virtual_id=VID, ramp_ms=400,
        params=[EffectParamChange(param_label="Dancer Color", string_value="#ffd020")],
    ))
    check("tint gradient-ramps when ramp_ms > 0",
          any(c[0] == "gradient_ramp" and c[3].get("tint") == "#ffd020" for c in calls),
          repr(calls))

    # 3b — blackhole params: numeric ramp, gradient ramp, toggle
    state.ledfx_virtual_cache[VID] = {
        "effect": {"type": "blackhole", "config": {"swirl": 1.2, "reverse": False}},
        "config": {},
    }
    calls.clear()
    rec_ramps: list[tuple] = []

    def rec_ramp_effect_params(vid, etype, patch, ramp_ms, step_ms=25):
        rec_ramps.append((vid, etype, dict(patch), ramp_ms))
        async def _noop():
            pass
        return _noop()

    ledfx_client.ramp_effect_params = rec_ramp_effect_params
    await engine._execute_action(LedFxEffectParamAction(
        virtual_id=VID, ramp_ms=500,
        params=[EffectParamChange(param_label="Swirl", target_value=-2.0)],
    ))
    check("blackhole Swirl ramps as numeric",
          any(p.get("swirl") == -2.0 for _, _, p, _ in rec_ramps), repr(rec_ramps))
    calls.clear()
    await engine._execute_action(LedFxEffectParamAction(
        virtual_id=VID, ramp_ms=400,
        params=[EffectParamChange(
            param_label="Gradient",
            string_value="linear-gradient(90deg, rgb(0,255,0) 0%, rgb(0,0,255) 100%)",
        )],
    ))
    check("blackhole Gradient routes to gradient ramp",
          any(c[0] == "gradient_ramp" and "gradient" in c[3] for c in calls), repr(calls))
    calls.clear()
    await engine._execute_action(LedFxEffectParamAction(
        virtual_id=VID,
        params=[EffectParamChange(param_label="Reverse Flow", toggle_action="toggle")],
    ))
    check("blackhole Reverse Flow toggles instantly",
          any(c[0] == "put" and c[3].get("reverse") is True for c in calls), repr(calls))

    # 3c — morph_step Shape aspect drives blackhole swirl/horizon/reverse
    from models.music_event import (
        AspectValue,
        MorphScope,
        MorphStepAction,
        MorphTarget,
    )
    state.ledfx_virtual_cache[VID] = {
        "effect": {
            "type": "blackhole",
            "config": {"swirl": 3.0, "reverse": True, "horizon_scale": 0.25},
        },
        "config": {},
    }
    calls.clear()
    rec_ramps.clear()
    await engine._execute_action(MorphStepAction(
        ramp_ms=300,
        targets=[MorphTarget(
            scope=MorphScope(virtual_ids=[VID]),
            aspect="shape",
            absolute_value=AspectValue(
                swirl=-4.0, horizon_scale=0.9, reverse="toggle"
            ),
        )],
    ))
    ramp_patches: dict = {}
    for _, _, p, _ in rec_ramps:
        ramp_patches.update(p)
    put_patches: dict = {}
    for c in calls:
        if c[0] == "put":
            put_patches.update(c[3])
    check("morph shape ramps blackhole swirl",
          ramp_patches.get("swirl") == -4.0, repr(rec_ramps))
    check("morph shape clamps horizon_scale to its 0.8 max",
          ramp_patches.get("horizon_scale") == 0.8, repr(rec_ramps))
    check("morph shape toggles reverse (True -> False)",
          put_patches.get("reverse") is False, repr(calls))

    # 4 — the seeded Dancer event parses with the expected lane shapes
    from services import profile_manager
    dancer = next((e for e in profile_manager.list_events() if e.name == "Dancer"), None)
    check("Dancer event exists", dancer is not None, "run scripts/seed_dancer_event.py")
    lanes = {lane.name: lane for lane in dancer.morph_lanes}
    check("Dancer has First/Rest/Shape/Color lanes",
          set(lanes) == {"First", "Rest", "Shape", "Color"}, repr(set(lanes)))
    shape_group = lanes["Shape"].alternatives[0]
    fallback_opts = [
        opt for opt in shape_group.options
        if any(getattr(a, "fallback_s", None) for a in opt.actions)
    ]
    check("every Shape-lane option is a fallback burst",
          len(fallback_opts) == len(shape_group.options), repr(shape_group.options))

    print(f"\nall {passed} checks passed")


if __name__ == "__main__":
    asyncio.run(main())
