"""
Offline smoke test for the Orbits effect registration + shared shape params.

Covers:
  1. Registry: orbits in morph.supported_effects + Matrix category, defaults
     present, no accent param (trails reuse each particle's own color).
  2. Shape aspect on orbits: x/y_offset scale conversion, horizon_scale
     (tether radius) clamp, reverse tri-state; the `edges` sub-field lands on
     `particle_count` ("Edge / Particle Count") with clamping; `blob_size` is
     a shape sub-field; radial-only sub-fields (star/twist/swirl) are
     silently skipped.
  3. Shape aspect on blackhole now carries x/y_offset too.
  4. Reactivity distribution on orbits drives ONLY reactivity_scale — every
     balance param (speed_jump/speed_jog/brightness_audio/size_audio/…) is
     distribute:false so the single number stays a master scale.
  5. Per-param reactivity: color_shift nudge +1 (the A,B,C -> C,A,B color
     jump), jiggle set; particle_count is NOT a reactivity param anymore
     (moved to Shape) so legacy reactivity entries are ignored.

No LedFX needed — pure compiler + registry math.

USAGE
  .venv/bin/python scripts/smoke_orbits_params.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from models.music_event import MorphTarget                 # noqa: E402
from services import morph_aspects                         # noqa: E402
from services.morph_compiler import _patch_for_aspect      # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


ORBITS_CFG = {
    "particle_count": 6, "x_offset": 0.5, "y_offset": 0.5,
    "horizon_scale": 0.4, "orbit_radius": 0.25, "blob_size": 1.5,
    "spin": 0.15, "base_speed": 0.5, "reverse": False, "jiggle": 0.2,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 0,
}


def patch_for(target: MorphTarget, effect: str = "orbits", cfg: dict | None = None,
              intensity=None) -> dict:
    return _patch_for_aspect(effect, target.aspect, target, cfg or dict(ORBITS_CFG),
                             intensity, vid="v1", nudge_dir={})


print("1) registry")
check("orbits morph-supported", "orbits" in morph_aspects.supported_effects())
d = morph_aspects.effect_defaults("orbits") or {}
check("defaults present (tuned)", d.get("particle_count") == 6 and d.get("horizon_scale") == 0.19
      and d.get("orbit_radius") == 0.53 and d.get("radius_scale") == 1.8
      and d.get("tether_scatter") == 0.0, str(d))
check("no accent param (trails reuse particle colors)", morph_aspects.accent_param_for("orbits") is None)
shape = morph_aspects.params_for_aspect("orbits", "shape")
for pname in ("x_offset", "y_offset", "horizon_scale", "orbit_radius", "blob_size",
              "radius_scale", "trail_decay", "gradient_spin", "reverse"):
    check(f"{pname} tagged shape", pname in shape, str(shape))

print("2) shape aspect on orbits")
t = MorphTarget(aspect="shape", mode="absolute", absolute_value={
    "x_offset": -1.0, "y_offset": 0.5, "horizon_scale": 2.0, "reverse": "toggle",
    "radius_scale": 3.0,
    "star": 0.5, "edges": 4, "twist": 1.0, "swirl": 3.0,
})
p = patch_for(t)
check("x_offset -1 → LedFX 0.0", p.get("x_offset") == 0.0, str(p))
check("y_offset 0.5 → LedFX 0.75", p.get("y_offset") == 0.75, str(p))
check("horizon_scale clamped to 0.8", p.get("horizon_scale") == 0.8, str(p))
check("radius_scale clamped to 2.0", p.get("radius_scale") == 2.0, str(p))
check("reverse toggled on", p.get("reverse") is True, str(p))
check("edges lands on particle_count", p.get("particle_count") == 4, str(p))
for skipped in ("star", "edges", "twist", "swirl", "polygon"):
    check(f"{skipped} skipped on orbits", skipped not in p, str(p))

t = MorphTarget(aspect="shape", mode="absolute", absolute_value={
    "edges": 40, "blob_size": 9.0,
})
p = patch_for(t)
check("edges→particle_count clamped to 16", p.get("particle_count") == 16, str(p))
check("blob_size clamped to 6", p.get("blob_size") == 6.0, str(p))
t = MorphTarget(aspect="shape", mode="nudge", absolute_value={
    "edges_nudge": {"amount": 1, "scale": 0.0},
    "blob_size_nudge": {"amount": 0.1, "scale": 0.0},
})
p = patch_for(t)
check("edge/particle nudge 6→7", p.get("particle_count") == 7, str(p))
check("blob_size nudge 1.5→2.05 (0.1 of 0.5..6)", p.get("blob_size") == 2.05, str(p))

print("3) shape aspect x/y_offset now applies to blackhole")
t = MorphTarget(aspect="shape", mode="absolute", absolute_value={
    "x_offset": 0.0, "y_offset": -0.5, "swirl": -2.0,
})
p = patch_for(t, effect="blackhole", cfg={"x_offset": 0.5, "y_offset": 0.5, "swirl": 3.0})
check("x_offset 0 → LedFX 0.5", p.get("x_offset") == 0.5, str(p))
check("y_offset -0.5 → LedFX 0.25", p.get("y_offset") == 0.25, str(p))
check("swirl still works on blackhole", p.get("swirl") == -2.0, str(p))

print("4) reactivity distribution = master scale only")
t = MorphTarget(aspect="reactivity", mode="absolute", absolute_value={"number": 1.0})
p = patch_for(t)
check("reactivity_scale spread to top of range", p.get("reactivity_scale") == 2.0, str(p))
for excluded in ("spin", "base_speed", "speed_jump", "speed_jog", "brightness_audio",
                 "size_audio", "jiggle", "tether_scatter", "particle_count",
                 "color_shift", "impulse_decay"):
    check(f"{excluded} NOT in spread", excluded not in p, str(p))

print("5) per-param reactivity")
t = MorphTarget(aspect="reactivity", mode="nudge", nudge_amount=0.0, absolute_value={
    "reactivity_nudges": {"color_shift": {"amount": 1, "scale": 0.0}},
})
p = patch_for(t)
check("color_shift nudged 0 → 1 (color jump)", p.get("color_shift") == 1, str(p))
check("only the nudged param present", set(p) == {"color_shift"}, str(p))
t = MorphTarget(aspect="reactivity", mode="absolute", absolute_value={
    "reactivity_values": {"particle_count": 40, "jiggle": 0.75, "speed_jog": 2.0},
})
p = patch_for(t)
check("legacy reactivity particle_count ignored (moved to Shape)",
      "particle_count" not in p, str(p))
check("jiggle set raw", p.get("jiggle") == 0.75, str(p))
check("speed_jog set raw", p.get("speed_jog") == 2.0, str(p))

print("6) seeded 'Orbits' scene lanes compile against the tuned config")
import json as _json

_events = _json.load(open(Path(__file__).resolve().parent.parent / "storage" / "events.json"))
_evs = _events.get("events", _events)
if isinstance(_evs, dict):
    _evs = list(_evs.values())
_scene = next((e for e in _evs if e.get("name") == "Orbits"
               and e.get("event_type") == "scene_update"), None)
_setter = next((e for e in _evs if e.get("name") == "Orbits Scene Setter"), None)
check("scene + setter seeded", bool(_scene) and bool(_setter))
if _scene and _setter:
    from models.music_event import MusicEvent
    scene = MusicEvent(**_scene)
    lanes = {ln.name: ln for ln in scene.morph_lanes}
    check("lanes present", set(lanes) == {"First", "Rest", "Shape", "Color"}, str(set(lanes)))
    first_alt = lanes["First"].alternatives[0]
    check("First → Setter ref", getattr(first_alt, "event_id", None) == _setter["id"])

    tuned = dict(ORBITS_CFG)

    def steps_of(action):
        """Yield every MorphStepAction nested under an action node."""
        out = []
        t = getattr(action, "type", None)
        if t == "morph_step":
            out.append(action)
        for child in (getattr(action, "children", None) or []):
            for a in (getattr(child, "actions", None) or []):
                out.extend(steps_of(a))
        for opt in (getattr(action, "options", None) or []):
            for a in (getattr(opt, "actions", None) or []):
                out.extend(steps_of(a))
        for a in (getattr(action, "actions", None) or []):
            out.extend(steps_of(a))
        return out

    rest_steps = steps_of(lanes["Rest"].alternatives[0])
    check("Rest carries a reverse toggle", any(
        t.aspect == "shape" and t.absolute_value.reverse == "toggle"
        for s in rest_steps for t in s.targets))
    rest_colors = [a for c in (lanes["Rest"].alternatives[0].children or [])
                   for a in (c.actions or []) if getattr(a, "type", "") == "set_color"]
    check("Rest cycles the group by 3", any(a.advance == 3 for a in rest_colors), str(rest_colors))

    # walk every morph_step under a lane regardless of how Javi has nested
    # parallel/random groups since seeding
    def lane_steps(lane):
        out = []
        for alt in lane.alternatives:
            out.extend(steps_of(alt))
        return out

    def set_colors_of(action):
        out = []
        if getattr(action, "type", None) == "set_color":
            out.append(action)
        for child in (getattr(action, "children", None) or []):
            for a in (getattr(child, "actions", None) or []):
                out.extend(set_colors_of(a))
        for opt in (getattr(action, "options", None) or []):
            for a in (getattr(opt, "actions", None) or []):
                out.extend(set_colors_of(a))
        return out

    shape_steps = lane_steps(lanes["Shape"])
    patches = [
        _patch_for_aspect("orbits", t.aspect, t, dict(tuned),
                          None, vid="crystal-mapper", nudge_dir={})
        for s in shape_steps for t in s.targets
    ]
    check("Shape lane: reverse toggles", any(p.get("reverse") is True for p in patches), str(patches))
    check("Shape lane: add particle 6→7", any(p.get("particle_count") == 7 for p in patches), str(patches))
    check("Shape lane: remove particle 6→5", any(p.get("particle_count") == 5 for p in patches), str(patches))
    hi_cfg = dict(tuned, particle_count=10)
    hi_patches = [
        _patch_for_aspect("orbits", t.aspect, t, dict(hi_cfg), None, vid="v", nudge_dir={})
        for s in shape_steps for t in s.targets if t.mode == "nudge"
    ]
    check("add clamps at hi bound 10", all(p.get("particle_count", 0) <= 10 for p in hi_patches), str(hi_patches))

    color_steps = lane_steps(lanes["Color"])
    jump = [
        _patch_for_aspect("orbits", t.aspect, t, dict(tuned), None, vid="v", nudge_dir={})
        for s in color_steps for t in s.targets
    ]
    check("Color lane: color_shift 0→1 jump", any(p.get("color_shift") == 1 for p in jump), str(jump))
    cycles = [a for alt in lanes["Color"].alternatives for a in set_colors_of(alt)]
    check("Color lane: cycle group advance 1", any(a.advance == 1 for a in cycles))

print()
if FAILURES:
    print(f"✗ {len(FAILURES)} failure(s): {FAILURES}")
    sys.exit(1)
print("✓ all orbits param checks passed")
