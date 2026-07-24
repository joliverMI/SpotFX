"""
Offline smoke test for per-param Reactivity sub-fields (Shape-style).

Covers:
  1. Legacy single-number distribution unchanged; distribute:false params
     (accel, edge_speed, impulse_decay, horizon_hold) stay out of the spread.
  2. Per-param absolute sets: raw-range values, clamping, integer coercion.
  3. Per-param entries win over the spread for the same param.
  4. Per-param nudges (mode=nudge) from the current cached value.
  5. Zero nudge_amount + per-param nudge → no distribution no-op writes.
  6. Toggle tri-state (keybeat2d half_beat) via reactivity_values.
  7. Params the current effect lacks are ignored.
  8. ValueBinding inside reactivity_values resolves (map + integer kinds).
  9. New blackhole registry entries present (accel / kill_radius /
     horizon_hold) with defaults.

No LedFX needed — pure compiler + resolver math.

USAGE
  .venv/bin/python scripts/smoke_reactivity_params.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from models.music_event import MorphStepAction, MorphTarget  # noqa: E402
from services import morph_aspects, signal_resolver           # noqa: E402
from services.morph_compiler import _patch_for_aspect         # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


BH_CFG = {
    "spawn_rate": 1.0, "beat_burst": 1, "base_speed": 1.0, "max_blobs": 50,
    "spawn_audio": 1.0, "speed_audio": 1.0, "horizon_audio": 0.3,
    "accel": 2.5, "edge_speed": 0.25, "impulse_decay": 0.06, "horizon_hold": 2.5,
}


def patch_for(target: MorphTarget, effect: str = "blackhole", cfg: dict | None = None,
              intensity=None) -> dict:
    return _patch_for_aspect(effect, target.aspect, target, cfg or dict(BH_CFG),
                             intensity, vid="v1", nudge_dir={})


print("1) legacy distribution excludes distribute:false params")
t = MorphTarget(aspect="reactivity", mode="absolute",
                absolute_value={"number": 1.0})
p = patch_for(t)
check("spawn_rate spread to top of range", p.get("spawn_rate") == 60.0, str(p))
check("beat_burst spread via aspect_scale 0.6", p.get("beat_burst") == round(0 + 12 * 0.6), str(p))
for excluded in ("accel", "edge_speed", "impulse_decay", "horizon_hold"):
    check(f"{excluded} NOT in spread", excluded not in p, str(p))

print("2) per-param absolute sets")
t = MorphTarget(aspect="reactivity", mode="absolute", absolute_value={
    "reactivity_values": {"accel": 3.5, "edge_speed": 0.1, "beat_burst": 20, "horizon_hold": 4.0},
})
p = patch_for(t)
check("accel set raw", p.get("accel") == 3.5, str(p))
check("edge_speed set raw", p.get("edge_speed") == 0.1, str(p))
check("beat_burst clamped to max int", p.get("beat_burst") == 12, str(p))
check("horizon_hold set raw", p.get("horizon_hold") == 4.0, str(p))
check("no spread params leaked", "spawn_rate" not in p, str(p))

print("3) per-param wins over the spread")
t = MorphTarget(aspect="reactivity", mode="absolute", absolute_value={
    "number": 1.0, "reactivity_values": {"spawn_rate": 5.0},
})
p = patch_for(t)
check("spawn_rate overridden to 5", p.get("spawn_rate") == 5.0, str(p))
check("base_speed still spread", p.get("base_speed") == round(0.05 + (2.0 - 0.05) * 0.8, 4), str(p))

print("4) per-param nudge from current value")
t = MorphTarget(aspect="reactivity", mode="nudge", nudge_amount=0.0, absolute_value={
    "reactivity_nudges": {"edge_speed": {"amount": 0.1, "scale": 0.0}},
})
p = patch_for(t)
expected = round(0.25 + 0.1 * (1.0 - 0.05), 4)
check("edge_speed nudged +10% of range", p.get("edge_speed") == expected, str(p))
print("5) …and zero nudge_amount emits no distribution no-ops")
check("only the nudged param present", set(p) == {"edge_speed"}, str(p))

print("6) toggle tri-state via reactivity_values")
t = MorphTarget(aspect="reactivity", mode="absolute", absolute_value={
    "reactivity_values": {"half_beat": "toggle"},
})
p = patch_for(t, effect="keybeat2d", cfg={"half_beat": False})
check("half_beat toggled on", p.get("half_beat") is True, str(p))

print("7) unsupported params ignored")
t = MorphTarget(aspect="reactivity", mode="absolute", absolute_value={
    "reactivity_values": {"accel": 3.0},
})
p = patch_for(t, effect="power", cfg={"bass_decay_rate": 0.5})
check("accel ignored on power", "accel" not in p, str(p))

print("8) bindings inside reactivity_values resolve")
action = MorphStepAction(targets=[MorphTarget(aspect="reactivity", mode="absolute", absolute_value={
    "reactivity_values": {
        "spawn_rate": {"bind": "signal", "signal": "section_energy",
                       "mode": "map", "in_min": 0, "in_max": 1,
                       "out_min": 0, "out_max": 30},
        "beat_burst": {"bind": "signal", "signal": "section_energy",
                       "mode": "map", "in_min": 0, "in_max": 1,
                       "out_min": 0, "out_max": 8},
    },
})])
check("has_bindings sees dict bindings", signal_resolver.has_bindings(action))
resolved = signal_resolver.resolve_action_bindings(action, lambda b: 0.5)
rv = resolved.targets[0].absolute_value.reactivity_values
check("spawn_rate mapped from signal", rv.get("spawn_rate") == 15.0, str(rv))
check("beat_burst mapped + int-coerced", rv.get("beat_burst") == 4, str(rv))
p = patch_for(resolved.targets[0])
check("resolved values compile", p.get("spawn_rate") == 15.0 and p.get("beat_burst") == 4, str(p))

print("9) registry: new blackhole params + defaults")
d = morph_aspects.effect_defaults("blackhole") or {}
check("defaults carry accel/kill_radius/horizon_hold",
      d.get("accel") == 2.5 and d.get("kill_radius") == 0.04 and d.get("horizon_hold") == 2.5, str(d))
react = morph_aspects.params_for_aspect("blackhole", "reactivity")
for pname in ("accel", "edge_speed", "impulse_decay", "horizon_hold"):
    check(f"{pname} tagged reactivity", pname in react, str(react))
meta = morph_aspects.aspect_param_meta()
check("catalog param_meta exposes ranges",
      meta.get("blackhole", {}).get("accel", {}).get("max") == 5.0
      and meta.get("blackhole", {}).get("accel", {}).get("distribute") is False, str(meta.get("blackhole", {}).get("accel")))

print()
if FAILURES:
    print(f"✗ {len(FAILURES)} failure(s): {FAILURES}")
    sys.exit(1)
print("✓ all reactivity per-param checks passed")
