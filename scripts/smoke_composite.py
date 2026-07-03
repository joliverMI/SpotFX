"""
Offline smoke test for the composite (node-tree) event executors.

No LedFX writes and NO real sleeping: ledfx_client calls are recorded, and
asyncio.sleep / time.monotonic run on a virtual clock, so ms-sequence spacing,
parallel offsets, beats timelines, pre-ramp shifts and the 100 ms safety pad
are asserted exactly and instantly. Safe to run while SpotFX is live.

USAGE
  .venv/bin/python scripts/smoke_composite.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from api import ledfx_client                                   # noqa: E402
from models.music_event import MusicEvent                      # noqa: E402
from services.trigger_engine import TriggerEngine              # noqa: E402


# ── virtual clock (discrete-event; correct for concurrent staggered sleeps) ──
from scripts._virtual_clock import VirtualClock  # noqa: E402

clock = VirtualClock()
_ = time  # time.monotonic patched by VirtualClock


def now() -> int:
    return clock.now_ms

# ── recorders ───────────────────────────────────────────────────────────────
fired: list[tuple] = []


async def rec_set_config(cfg: dict) -> None:
    fired.append(("brightness", cfg.get("global_brightness"), now()))


def rec_ramp_brightness(value, ramp_ms, step_ms=25):
    fired.append(("ramp", value, ramp_ms, now()))
    async def _noop():
        pass
    return _noop()


async def rec_set_virtual_config(vid, cfg):
    fired.append(("vconfig", vid, tuple(sorted(cfg)), now()))


ledfx_client.set_config = rec_set_config                    # type: ignore
ledfx_client.ramp_brightness = rec_ramp_brightness          # type: ignore
ledfx_client.set_virtual_config = rec_set_virtual_config    # type: ignore


def b(v: float, ramp: int = 0) -> dict:
    return {"type": "ledfx_global_brightness", "brightness": v, "ramp_ms": ramp}


def ev(root: dict | None, **kw) -> MusicEvent:
    return MusicEvent(
        name=kw.pop("name", "smoke"), event_type="composite", root=root,
        pre_brightness_enabled=False, pre_transition_enabled=False, **kw,
    )


def reset():
    fired.clear()
    clock.reset()


def fail(msg: str):
    print(f"✗ FAIL: {msg}\n  fired={fired}")
    sys.exit(1)


def ok(msg: str):
    print(f"✓ {msg}")


def brightness_times() -> list[tuple[float, int]]:
    return [(f[1], f[2]) for f in fired if f[0] == "brightness"]


async def main() -> None:
    engine = TriggerEngine()
    engine._local_beat_interval_ms = lambda at_ms: 200  # type: ignore
    engine._beats_cache = [0.0, 0.2, 0.4]  # have_beats=True

    # ── 1. ms sequence: order + spacing (incl. child-0 delay) ──────────────
    reset()
    seq = {"type": "sequence_group", "children": [
        {"delay_ms": 0, "actions": [b(0.1)]},
        {"delay_ms": 100, "actions": [b(0.2)]},
        {"delay_ms": 250, "actions": [b(0.3)]},
    ]}
    await clock.run(engine._execute_composite(ev(seq), []))
    if brightness_times() != [(0.1, 0), (0.2, 100), (0.3, 350)]:
        fail(f"ms sequence spacing wrong: {brightness_times()}")
    ok("ms sequence: order + cumulative delays exact (0/100/350)")

    # ── 2. parallel offsets: anchor = min(offset), rel sleeps ───────────────
    reset()
    par = {"type": "parallel_group", "children": [
        {"name": "early", "offset_ms": -500, "actions": [b(0.5)]},
        {"name": "late", "offset_ms": 0, "actions": [b(0.6)]},
    ]}
    await clock.run(engine._execute_composite(ev(par), []))
    got = sorted(brightness_times(), key=lambda x: x[1])
    if got != [(0.5, 0), (0.6, 500)]:
        fail(f"parallel offsets wrong: {got}")
    ok("parallel: anchor=min(offset), stagger 500ms exact")

    # ── 3. resolved_picks pin the random branch; fallback re-rolls ─────────
    reset()
    rg = {"type": "random_group", "id": "rg1", "options": [
        {"id": "oA", "actions": [b(0.11)]},
        {"id": "oB", "actions": [b(0.22)]},
    ]}
    e3 = ev(rg)
    for _ in range(20):
        await clock.run(engine._execute_composite(e3, [], resolved_picks={"rg1": "oB"}))
    vals = {f[1] for f in fired if f[0] == "brightness"}
    if vals != {0.22}:
        fail(f"resolved_picks not honored: {vals}")
    reset()
    for _ in range(50):
        await clock.run(engine._execute_composite(e3, []))  # fresh picks
    vals = {f[1] for f in fired if f[0] == "brightness"}
    if vals != {0.11, 0.22}:
        fail(f"fresh-pick fallback broken: {vals}")
    ok("random: resolved_picks pinned; fresh-pick fallback varies")

    # ── 4. beats timeline: pre_ramp shift + spacing ─────────────────────────
    reset()
    beats = {"type": "sequence_group", "timing": "beats", "children": [
        {"delay_beats": 0, "pre_ramp": True, "actions": [b(0.4, ramp=300)]},
        {"delay_beats": 0, "pre_ramp": False, "actions": [b(0.5)]},
        {"delay_beats": 1, "pre_ramp": False, "actions": [b(0.6)]},
    ]}
    await clock.run(engine._execute_composite(ev(beats), [], anchor_ms=1000))
    # nominal: 1000, 1200, 1600; c0 pre-ramps to 700 → origin. offsets 0/500/900.
    ramps = [(f[1], f[2], f[3]) for f in fired if f[0] == "ramp"]
    bts = brightness_times()
    if ramps != [(0.4, 300, 0)]:
        fail(f"beats c0 pre-ramp wrong: {ramps}")
    if bts != [(0.5, 500), (0.6, 900)]:
        fail(f"beats spacing wrong: {bts}")
    ok("beats: pre_ramp shift −300ms, spacing (1+delay_beats)·interval exact")

    # ── 5. safety pad + ramp compression ────────────────────────────────────
    reset()
    beats2 = {"type": "sequence_group", "timing": "beats", "children": [
        {"delay_beats": 0, "pre_ramp": True, "actions": [b(0.4, ramp=300)]},
        {"delay_beats": 0, "pre_ramp": True, "actions": [b(0.5, ramp=300)]},
    ]}
    await clock.run(engine._execute_composite(ev(beats2), [], anchor_ms=1000))
    # c1 nominal 1200, raw 900 < earliest (700+300+100=1100) → fire 1100, ramp 100
    ramps = [(f[1], f[2], f[3]) for f in fired if f[0] == "ramp"]
    if ramps != [(0.4, 300, 0), (0.5, 100, 400)]:
        fail(f"safety pad / compression wrong: {ramps}")
    ok("beats: 100ms safety pad clamps fire, ramp compressed 300→100")

    # ── 6. revert (ms): snapshot before body, restore after delay ───────────
    reset()
    ledfx_client._current_brightness = 0.77  # type: ignore
    seqr = {"type": "sequence_group", "children": [
        {"actions": [b(0.1)]},
    ], "revert": {"enabled": True, "delay_ms": 200, "transition_ms": 0}}
    await clock.run(engine._execute_composite(ev(seqr), []))
    bts = brightness_times()
    if bts != [(0.1, 0), (0.77, 200)]:
        fail(f"revert wrong: {bts}")
    ok("revert: pre-state 0.77 restored 200ms after body")

    # ── 7. depth cap: 7-deep nesting stops silently ─────────────────────────
    reset()
    deep: dict = {"type": "sequence_group", "children": [{"actions": [b(0.9)]}]}
    for _ in range(7):
        deep = {"type": "sequence_group", "children": [{"actions": [deep]}]}
    await clock.run(engine._execute_composite(ev(deep), []))
    if brightness_times():
        fail("depth cap failed — deep leaf fired")
    ok("depth cap (5) stops runaway nesting")

    # ── 8. beat_fallback=skip with no beat data ─────────────────────────────
    reset()
    engine._beats_cache = []
    skip_ev = ev({"type": "sequence_group", "timing": "beats",
                  "beat_fallback": "skip",
                  "children": [{"actions": [b(0.3)]}]})
    await clock.run(engine._execute_composite(skip_ev, []))
    if brightness_times():
        fail("beat_fallback=skip fired without beats")
    fb_ev = ev({"type": "sequence_group", "timing": "beats",
                "beat_fallback": "fallback",
                "children": [{"actions": [b(0.3)]}]})
    await clock.run(engine._execute_composite(fb_ev, []))
    if not brightness_times():
        fail("beat_fallback=fallback did not fire")
    engine._beats_cache = [0.0]
    ok("beats: fallback=skip gates, fallback=fallback fires")

    # ── 9. describe strings (resolved-aware) ────────────────────────────────
    seq_desc = engine._describe_action(ev(seq).root)
    if " > " not in seq_desc:
        fail(f"sequence describe: {seq_desc!r}")
    par_desc = engine._describe_action(ev(par).root)
    if "early" not in par_desc or "·" not in par_desc:
        fail(f"parallel describe: {par_desc!r}")
    rg_model = ev(rg).root
    unresolved = engine._describe_action(rg_model)
    resolved = engine._describe_action(rg_model, resolved={"rg1": "oB"})
    if unresolved != "🎲 1 of 2" or "22" not in resolved.replace("0.22", "22"):
        fail(f"random describe: {unresolved!r} / {resolved!r}")
    ok(f"describe: seq={seq_desc!r} par~ok random resolved={resolved!r}")

    # ── 10. scene-override eligibility matrix ───────────────────────────────
    morph = {"type": "morph_step", "targets": [
        {"scope": {"categories": ["Strips"]}, "aspect": "brightness",
         "absolute_value": {"number": 0.5}},
    ]}
    flat_par = ev({"type": "parallel_group", "children": [
        {"name": "L1", "offset_ms": 0, "actions": [morph]},
        {"name": "L2", "offset_ms": 0, "actions": [
            {"type": "random_group", "id": "rgX", "options": [
                {"id": "o1", "actions": [morph]},
                {"id": "o2", "actions": [morph]},
            ]},
        ]},
    ]}, scene_override=True)
    picks = engine._composite_scene_picks(flat_par, {"rgX": "o1"})
    assert picks is not None and len(picks) == 2, f"flatten failed: {picks}"
    assert engine._event_eligible_for_scene_override(flat_par, picks=picks)
    # unresolved random → None → ineligible
    assert engine._composite_scene_picks(flat_par, None) is None
    assert not engine._event_eligible_for_scene_override(flat_par, picks=None)
    # mixed offsets → ineligible
    mixed = ev({"type": "parallel_group", "children": [
        {"offset_ms": -500, "actions": [morph]},
        {"offset_ms": 0, "actions": [morph]},
    ]}, scene_override=True)
    mp = engine._composite_scene_picks(mixed, {})
    assert mp is not None and not engine._event_eligible_for_scene_override(mixed, picks=mp)
    # sequence root → not flattenable
    seq_ov = ev(seq, scene_override=True)
    assert engine._composite_scene_picks(seq_ov, {}) is None
    ok("scene-override: flat-parallel+resolved eligible; unresolved/mixed/sequence fall back")

    print("\nALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
