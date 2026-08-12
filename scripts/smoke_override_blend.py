"""
Smoke test for Override Blend (trigger.override_blend).

Exercises the plan-time scaling that makes a blended trigger's event finish
exactly at the next enabled trigger (or song end):

  1. Tail math      — sequential ramps accumulate (200 + 300 = 500ms).
  2. Stretch        — 5s gap over a 500ms event → ×10 (2000ms + 3000ms ramps).
  3. Compress       — 250ms gap → ×0.5 (100ms + 150ms ramps).
  4. Song-end       — no later trigger: gap runs to duration_ms.
  5. Default ramps  — ramp_ms=None materializes smooth_ramp_ms × factor;
                      set_color copies carry ramp_scale for card entries.
  6. Guards         — No Action event (tail 0), disabled next trigger skipped,
                      near-1 factors left alone, event_offset_ms unscaled.
  7. Beats          — beat-timed spacing unscaled, ramps still scale.

Run:  .venv/bin/python -m scripts.smoke_override_blend
Exit code 0 = all assertions passed.
"""
from __future__ import annotations

import sys

from config import settings
from models.music_event import (
    MorphStepAction, MorphTarget, MusicEvent, ParallelChild, ParallelGroupAction,
    SequenceChild, SequenceGroupAction, SetColorAction,
)
from models.song_profile import MusicTrigger, SongProfile
from services.trigger_engine import TriggerEngine

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failures
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _failures += 1


def _morph(ramp_ms) -> MorphStepAction:
    return MorphStepAction(
        ramp_ms=ramp_ms,
        targets=[MorphTarget(aspect="brightness")],
    )


def _two_ramp_event(offset_ms: int = 0) -> MusicEvent:
    """composite: seq_group[ morph(200ms) → morph(300ms) ] — natural tail 500ms."""
    return MusicEvent(
        id="ev-blend-test", name="Blend Test", event_type="composite",
        event_offset_ms=offset_ms,
        root=SequenceGroupAction(children=[
            SequenceChild(actions=[_morph(200)]),
            SequenceChild(actions=[_morph(300)]),
        ]),
    )


def _engine(triggers: list[MusicTrigger], duration_ms: int = 60000) -> TriggerEngine:
    eng = TriggerEngine()
    eng._profile = SongProfile(
        spotify_uri="spotify:track:smoke", title="Smoke", artist="Test",
        duration_ms=duration_ms, triggers=triggers,
    )
    return eng


def main() -> int:
    settings.smooth_ramp_ms = 500

    t0 = MusicTrigger(id="t0", timestamp_ms=10000, event_id="ev-blend-test",
                      override_blend=True)
    t_next = MusicTrigger(id="t1", timestamp_ms=15000, event_id="whatever")

    print("1. Tail math")
    eng = _engine([t0, t_next])
    ev = _two_ramp_event()
    tail = eng._blend_event_tail_ms(ev, t0.timestamp_ms)
    check("sequential ramps accumulate", tail == 500.0, f"tail={tail}")
    par = MusicEvent(
        id="ev-par", name="Par", event_type="composite",
        root=ParallelGroupAction(children=[
            ParallelChild(offset_ms=0, actions=[_morph(200)]),
            ParallelChild(offset_ms=100, actions=[_morph(300)]),
        ]),
    )
    ptail = eng._blend_event_tail_ms(par, t0.timestamp_ms)
    check("parallel tail = max(offset+ramp)", ptail == 400.0, f"tail={ptail}")

    print("2. Stretch to the next trigger (5s gap, 500ms event → ×10)")
    factor = eng._blend_factor_for(t0, ev)
    check("factor = 10", factor == 10.0, f"factor={factor}")
    plan, _desc = eng._plan_timeline(ev, t0, [], time_scale=factor)
    eng._blend_scale_plan(plan, factor)
    root = plan[0].event.root
    r1 = root.children[0].actions[0].ramp_ms
    r2 = root.children[1].actions[0].ramp_ms
    check("ramps scale 200→2000, 300→3000", (r1, r2) == (2000, 3000), f"{r1}, {r2}")
    check("fire_at stays at the trigger", plan[0].fire_at_ms == 10000,
          f"fire_at={plan[0].fire_at_ms}")

    print("3. Compress (250ms gap → ×0.5)")
    eng2 = _engine([t0, MusicTrigger(id="t1", timestamp_ms=10250, event_id="x")])
    f2 = eng2._blend_factor_for(t0, ev)
    check("factor = 0.5", f2 == 0.5, f"factor={f2}")
    plan2, _ = eng2._plan_timeline(ev, t0, [], time_scale=f2)
    eng2._blend_scale_plan(plan2, f2)
    root2 = plan2[0].event.root
    check("ramps compress 200→100, 300→150",
          (root2.children[0].actions[0].ramp_ms,
           root2.children[1].actions[0].ramp_ms) == (100, 150))

    print("4. Song end fallback (no later trigger)")
    eng3 = _engine([t0], duration_ms=12500)
    f3 = eng3._blend_factor_for(t0, ev)
    check("gap runs to duration_ms (2500/500 = ×5)", f3 == 5.0, f"factor={f3}")

    print("5. Default ramps + set_color ramp_scale")
    ev_default = MusicEvent(
        id="ev-default", name="Default", event_type="composite",
        root=SequenceGroupAction(children=[
            SequenceChild(actions=[_morph(None)]),
            SequenceChild(actions=[SetColorAction(ref_id="card", ramp_ms=None)]),
        ]),
    )
    tail_d = eng._blend_event_tail_ms(ev_default, t0.timestamp_ms)
    check("None ramps fall back to smooth_ramp_ms", tail_d == 1000.0, f"tail={tail_d}")
    fd = eng._blend_factor_for(t0, ev_default)  # 5000 / 1000 = 5
    plan_d, _ = eng._plan_timeline(ev_default, t0, [], time_scale=fd)
    eng._blend_scale_plan(plan_d, fd)
    rd = plan_d[0].event.root
    check("morph None ramp materializes 500→2500",
          rd.children[0].actions[0].ramp_ms == 2500,
          f"ramp={rd.children[0].actions[0].ramp_ms}")
    sc = rd.children[1].actions[0]
    check("set_color carries ramp_scale ×5", sc.ramp_scale == 5.0 and sc.ramp_ms == 2500,
          f"ramp_scale={sc.ramp_scale}, ramp={sc.ramp_ms}")

    print("6. Guards")
    from services.profile_manager import get_event
    noop = get_event("fixed-no-action")
    check("No Action factor is None (tail 0)",
          eng._blend_factor_for(t0, noop) is None)
    eng4 = _engine([
        t0,
        MusicTrigger(id="dis", timestamp_ms=11000, event_id="x", enabled=False),
        MusicTrigger(id="t1", timestamp_ms=15000, event_id="x"),
    ])
    check("disabled trigger doesn't end the blend",
          eng4._blend_factor_for(t0, ev) == 10.0)
    eng5 = _engine([t0, MusicTrigger(id="t1", timestamp_ms=10501, event_id="x")])
    check("factor ≈1 skipped", eng5._blend_factor_for(t0, ev) is None)
    ev_off = _two_ramp_event(offset_ms=-150)
    plan_o, _ = eng._plan_timeline(ev_off, t0, [], time_scale=10.0)
    eng._blend_scale_plan(plan_o, 10.0)
    check("event_offset_ms stays unscaled (fires 150ms early, not 1500)",
          plan_o[0].fire_at_ms == 10000 - 150, f"fire_at={plan_o[0].fire_at_ms}")

    print("7. Beat-timed spacing stays musical")
    ev_beats = MusicEvent(
        id="ev-beats", name="Beats", event_type="composite",
        root=SequenceGroupAction(timing="beats", children=[
            SequenceChild(actions=[_morph(200)]),
            SequenceChild(delay_beats=1, actions=[_morph(300)]),
        ]),
    )
    # fallback interval = 500ms (no tempo cache): child1 at beat +2 → tail 1000
    btail = eng._blend_event_tail_ms(ev_beats, t0.timestamp_ms)
    check("beats tail uses beat interval (pre_ramp ends on beat)",
          btail == 1000.0, f"tail={btail}")
    plan_b, _ = eng._plan_timeline(ev_beats, t0, [], time_scale=5.0)
    eng._blend_scale_plan(plan_b, 5.0)
    rb = plan_b[0].event.root
    check("delay_beats unscaled, ramps scaled ×5",
          rb.children[1].delay_beats == 1
          and rb.children[0].actions[0].ramp_ms == 1000
          and rb.children[1].actions[0].ramp_ms == 1500)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("All Override Blend smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
