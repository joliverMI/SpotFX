"""
Offline smoke test for value bindings (signal-driven parameters).

Part 1 — pure resolver math with fabricated beats/sections (no engine).
Part 2 — engine seams (added in the P2 phase; see plan).

USAGE
  .venv/bin/python scripts/smoke_bindings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.value_binding import ValueBinding
from services.signal_resolver import (
    apply_binding, has_bindings, resolve_action_bindings, resolve_signal,
    static_ramp_ms,
)


def fail(msg: str):
    print(f"✗ FAIL: {msg}")
    sys.exit(1)


def ok(msg: str):
    print(f"✓ {msg}")


# ── fixtures: 20 beats @ 500ms, rms_total ramping 0.0 → 0.95 ────────────────
BEATS = [
    {"ms": i * 500, "rms_total": round(i * 0.05, 3), "rms_bass": 0.4, "onset_score": 0.2}
    for i in range(20)
]
SECTIONS = [
    {"start_ms": 0, "end_ms": 3000, "label": "intro", "energy_rms": 0.2},
    {"start_ms": 3000, "end_ms": 7000, "label": "build", "energy_rms": 0.6},
    {"start_ms": 7000, "end_ms": 10000, "label": "drop", "energy_rms": 0.95},
]


def vb(**kw) -> ValueBinding:
    return ValueBinding(**kw)


def main() -> None:
    # ── 1. nearest beat (window 0) ──────────────────────────────────────────
    b = vb(signal="rms_total")
    assert resolve_signal(b, BEATS, None, 5000) == 0.5, "nearest beat @5000ms"
    assert resolve_signal(b, BEATS, None, 5240) == 0.5, "rounds to nearer beat"
    assert resolve_signal(b, BEATS, None, 5260) == 0.55, "rounds up past midpoint"
    assert resolve_signal(b, BEATS, None, -500) == 0.0, "clamps before song"
    assert resolve_signal(b, BEATS, None, 99999) == 0.95, "clamps after song"
    ok("nearest-beat lookup incl. edges")

    # ── 2. rolling windows past / future / centered ─────────────────────────
    past = vb(signal="rms_total", window_beats=4, window_dir="past")
    # beats 7,8,9,10 → mean(.35,.4,.45,.5) = .425
    assert abs(resolve_signal(past, BEATS, None, 5000) - 0.425) < 1e-9, "past window"
    fut = vb(signal="rms_total", window_beats=4, window_dir="future")
    # beats 10..13 → mean(.5,.55,.6,.65) = .575
    assert abs(resolve_signal(fut, BEATS, None, 5000) - 0.575) < 1e-9, "future window"
    cen = vb(signal="rms_total", window_beats=4, window_dir="centered")
    # start=8 → beats 8..11 → mean(.4,.45,.5,.55) = .475
    assert abs(resolve_signal(cen, BEATS, None, 5000) - 0.475) < 1e-9, "centered window"
    # song-start clamping: past window at beat 1 shrinks to beats 0..1
    assert abs(resolve_signal(past, BEATS, None, 500) - 0.025) < 1e-9, "past clamps at start"
    # song-end clamping: future window at last beat shrinks to beat 19
    assert abs(resolve_signal(fut, BEATS, None, 9500) - 0.95) < 1e-9, "future clamps at end"
    ok("rolling windows: past/future/centered + edge clamping")

    # ── 3. section energy ───────────────────────────────────────────────────
    s = vb(signal="section_energy")
    assert resolve_signal(s, None, SECTIONS, 4000) == 0.6, "section containing now"
    assert resolve_signal(s, None, SECTIONS, 0) == 0.2, "first section inclusive start"
    assert resolve_signal(s, None, SECTIONS, 12000) == 0.95, "after last → nearest"
    assert resolve_signal(s, None, SECTIONS, -100) == 0.2, "before first → nearest"
    assert resolve_signal(s, None, None, 4000) is None, "no sections → None"
    ok("section_energy lookup incl. bounds")

    # ── 4. map mode: custom + inverted ranges, int rounding ─────────────────
    m = vb(mode="map", in_min=0.2, in_max=0.8, out_min=100, out_max=700)
    assert apply_binding(m, 0.5, "int0") == 400, "map midpoint"
    assert apply_binding(m, 0.0, "int0") == 100, "map clamps below in_min"
    assert apply_binding(m, 1.0, "int0") == 700, "map clamps above in_max"
    inv = vb(mode="map", out_min=1200, out_max=150)   # slow ramp at low energy
    assert apply_binding(inv, 0.0, "int0") == 1200, "inverted map low"
    assert apply_binding(inv, 1.0, "int0") == 150, "inverted map high"
    assert apply_binding(vb(mode="map", out_min=0, out_max=10), 0.34, "int1") == 3, "int round"
    assert apply_binding(vb(mode="map", out_min=0, out_max=0.5), 0.04, "int1") == 1, "int1 floor"
    assert apply_binding(vb(mode="map", out_min=-3, out_max=-3), 0.9, "int0") == 0, "int0 floor"
    assert apply_binding(vb(mode="map", out_min=0, out_max=2), 1.0, "float01") == 1.0, "float01 clamp"
    assert apply_binding(vb(mode="map", out_min=-2, out_max=2), 0.0, "float_pm1") == -1.0, "pm1 clamp"
    ok("map: custom/inverted ranges, int + range coercion")

    # ── 5. steps mode: tiers, toggles, fallbacks ────────────────────────────
    tiers = vb(mode="steps", steps=[
        {"threshold": 0.0, "value": 1},
        {"threshold": 0.4, "value": 2},
        {"threshold": 0.75, "value": 4},
    ])
    assert apply_binding(tiers, 0.1, "int1") == 1
    assert apply_binding(tiers, 0.5, "int1") == 2
    assert apply_binding(tiers, 0.9, "int1") == 4
    below = vb(mode="steps", steps=[{"threshold": 0.5, "value": 3}], fallback=7)
    assert apply_binding(below, 0.2, "int1") == 7, "below first step → fallback"
    noop = vb(mode="steps", steps=[{"threshold": 0.5, "value": 3}])
    assert apply_binding(noop, 0.2, "int1") is None, "below first, no fallback → no-op"
    tog = vb(mode="steps", steps=[{"threshold": 0.6, "value": True}], fallback=False)
    assert apply_binding(tog, 0.7, "tri_bool") is True
    assert apply_binding(tog, 0.3, "tri_bool") is False
    ts = vb(mode="steps", steps=[{"threshold": 0.3, "value": "off"}, {"threshold": 0.7, "value": "on"}])
    assert apply_binding(ts, 0.8, "toggle_str") == "on"
    assert apply_binding(ts, 0.5, "toggle_str") == "off"
    assert apply_binding(ts, 0.1, "toggle_str") is None, "toggle below first → no-op"
    ok("steps: tiers, tri-bool, toggle strings, fallback/no-op")

    # ── 6. signal-unavailable behavior ──────────────────────────────────────
    assert apply_binding(vb(mode="map", out_min=0, out_max=100, fallback=42), None, "int0") == 42
    assert apply_binding(vb(mode="map", out_min=0, out_max=100), None, "int0") == 50, "neutral 0.5"
    assert apply_binding(vb(mode="steps", steps=[{"threshold": 0, "value": 2}]), None, "int1") is None
    ok("no-signal: fallback, map neutral-0.5, steps no-op")

    # ── 7. map on toggle field guard ────────────────────────────────────────
    assert apply_binding(vb(mode="map", fallback=True), 0.9, "tri_bool") is True, "map-on-bool → fallback"
    ok("map mode on toggle fields falls back (guarded)")

    # ── 8. steps-sorting validator ──────────────────────────────────────────
    unsorted = vb(mode="steps", steps=[{"threshold": 0.7, "value": 4}, {"threshold": 0.0, "value": 1}])
    assert [st.threshold for st in unsorted.steps] == [0.0, 0.7]
    ok("steps auto-sorted ascending")

    # ── 9. resolve_action_bindings: hot path, substitution, memoization ─────
    from models.music_event import MorphColorAction, MorphStepAction, LedFxEffectParamAction

    plain = MorphColorAction(ref_id="x", advance=2)
    assert not has_bindings(plain)
    assert resolve_action_bindings(plain, lambda b: 0.9) is plain, "no-binding hot path returns same object"

    bound = MorphColorAction(ref_id="x", advance={
        "bind": "signal", "mode": "steps",
        "steps": [{"threshold": 0.0, "value": 1}, {"threshold": 0.75, "value": 4}],
    }, ramp_ms={"bind": "signal", "mode": "map", "out_min": 1200, "out_max": 150})
    calls = []
    def sigfn(b):
        calls.append(b.signal)
        return 0.9
    out = resolve_action_bindings(bound, sigfn)
    assert out is not bound and isinstance(bound.advance, ValueBinding), "original untouched"
    assert out.advance == 4 and out.ramp_ms == 255, f"resolved {out.advance}/{out.ramp_ms}"
    assert len(calls) == 1, "same (signal,window,dir) memoized"

    ms = MorphStepAction(targets=[{
        "aspect": "shape",
        "absolute_value": {
            "edges": {"bind": "signal", "mode": "map", "out_min": 3, "out_max": 8},
            "polygon": {"bind": "signal", "mode": "steps", "steps": [{"threshold": 0.6, "value": "toggle"}]},
        },
    }])
    out2 = resolve_action_bindings(ms, lambda b: 0.8)
    assert out2.targets[0].absolute_value.edges == 7, "edges mapped+rounded"
    assert out2.targets[0].absolute_value.polygon == "toggle", "tri-bool 'toggle' value"

    ep = LedFxEffectParamAction(params=[
        {"param_label": "Reactivity", "target_value": {"bind": "signal", "mode": "map", "out_min": 0.1, "out_max": 0.9}},
        {"param_label": "Flip", "toggle_action": {"bind": "signal", "mode": "steps", "steps": [{"threshold": 0.9, "value": "on"}]},
         "target_value": {"bind": "signal", "mode": "steps", "steps": [{"threshold": 0.99, "value": 1.0}]}},
    ])
    out3 = resolve_action_bindings(ep, lambda b: 0.5)
    assert len(out3.params) == 1, "no-op target_value drops its param change"
    assert out3.params[0].target_value == 0.5, "target_value mapped"
    ok("resolve_action_bindings: hot path, morph/color/effect substitution, drops")

    # ── 10. static_ramp_ms for plan-time arithmetic ─────────────────────────
    assert static_ramp_ms(300, lambda b: 0.9) == 300
    assert static_ramp_ms(None, lambda b: 0.9) is None
    assert static_ramp_ms(vb(mode="map", out_min=0, out_max=1000), lambda b: 0.25) == 250
    ok("static_ramp_ms resolves bindings for timeline max()")

    print("\nALL PASS (part 1 — pure resolver)")


if __name__ == "__main__":
    main()
