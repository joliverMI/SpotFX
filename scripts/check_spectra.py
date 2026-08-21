"""Executable spec for the SPECTRA model + engine: value bindings in scene
params, dice-correlated randomness, intensity-conditional EFFECT SELECTION
(effect_steps: fire-time variant pick, load-unchanged guarantee, preview
parity, the engine interplay, the STAR strips migration), the four-class
responses block (legacy flare_bands shim), drift declarations, the colour-journey OVERRIDE
semantics (into/out-of custody transfer), binding resolution + dry-run
compile through the shared device model, store/API round-trips, the
sequencer engine on SPECTRA stores, the Mid Group seeder, and the S2
evolution engine: the response engine (NAMED FLARE KINDS — the item-8
model: drift-jump / momentary / permanent semantics, band select + scale,
the legacy load-unchanged-as-auto-named-kinds guarantee, name-broadcast
targeting, gain envelopes, dice re-rolls, the flare colour jump with the
intensity-scaled ramp-in, keep-current rung and the journey resuming from
the new point), the
read-only bridge (event classification, feeds, deferral split, RAW section
energy), and the seven Mid Group scenes' rebuild-table behaviors.

The drift conductor has its own spec: scripts/check_drift.py.

Run from repo root: .venv/bin/python scripts/check_spectra.py
Isolated: temp files for every store; no LedFX I/O, no audio, no network.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from random import Random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


td = Path(tempfile.mkdtemp(prefix="spectra-spec-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({
    "c1": {"id": "c1", "name": "Matrix", "parent_id": None,
           "virtuals": ["v-m1", "v-m2"], "effects": ["radial"], "role": None},
    "c2": {"id": "c2", "name": "MatrixChild", "parent_id": "c1",
           "virtuals": ["v-m3"], "effects": ["orbits"], "role": None},
    "c3": {"id": "c3", "name": "Strips", "parent_id": None,
           "virtuals": ["v-s1"], "effects": ["power"], "role": "wash"},
    "c4": {"id": "c4", "name": "Singles", "parent_id": None,
           "virtuals": ["v-single1"], "effects": ["power"], "role": None},
}))

from fx import light_ownership
light_ownership.OWNERSHIP_FILE = td / "ownership.json"

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.GRADIENT2D_FILE = scfg.SPECTRA_STORAGE / "gradients2d.json"
scfg.FIRE_HISTORY_FILE = scfg.SPECTRA_STORAGE / "fire_history.json"
scfg.SHOW_LOG_FILE = scfg.SPECTRA_STORAGE / "show_log.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"
scfg.AUDIO_SHAPES_DIR = td / "audio_shapes"
scfg.TRAINING_PROFILES_FILE = td / "training_profiles.json"

from spectra.models.binding import ValueBinding
from spectra.models.scene import (ColorJourneySpec, DriftRef, DriftSpec,
                                  FlareBand, ResponseSpec, SceneColorJourney,
                                  SceneDeviceConfig, SceneV2)
from spectra.services import (binding_resolver, color_journey, scene_compiler,
                              scene_store)
from spectra.services.binding_resolver import FireContext


def absolute_params(kind) -> dict:
    """A FlareKind's params as plain floats — every kind these checks build
    or migrate is absolute-mode-only (ParamTarget's legacy-compatible
    default), so this is exactly the pre-ParamTarget float dict these
    assertions compare against."""
    return {name: t.value for name, t in kind.params.items()
            if t.mode == "absolute"}

# ── bindings live inside scene params; scalars stay scalars ──────────────────
spin_map = {"bind": "signal", "signal": "trigger_intensity", "mode": "map",
            "out_min": 0.1, "out_max": 1.0, "fallback": 0.55}
scene = SceneV2(name="Spec", devices=[SceneDeviceConfig(
    target_kind="category", target="Matrix", effect_type="radial",
    params={
        "spin": spin_map,
        "star": {"bind": "signal", "signal": "random", "mode": "steps", "dice": "a",
                 "steps": [{"threshold": 0.0, "value": 0.3},
                           {"threshold": 0.4, "value": -0.3},
                           {"threshold": 0.8, "value": 0.0}], "fallback": 0.3},
        "edges": {"bind": "signal", "signal": "random", "mode": "steps", "dice": "a",
                  "steps": [{"threshold": 0.0, "value": 6},
                            {"threshold": 0.4, "value": 3},
                            {"threshold": 0.8, "value": 5}], "fallback": 6},
        "twist": 0.25,
    },
    brightness={"bind": "signal", "signal": "trigger_intensity", "mode": "map",
                "out_min": 0.3, "out_max": 1.0, "fallback": 0.8})])
check(isinstance(scene.devices[0].params["spin"], ValueBinding)
      and scene.devices[0].params["twist"] == 0.25,
      "params hold bindings and scalars side by side")
rt = SceneV2(**json.loads(scene.model_dump_json()))
check(isinstance(rt.devices[0].params["spin"], ValueBinding)
      and rt.devices[0].params["twist"] == 0.25
      and isinstance(rt.devices[0].brightness, ValueBinding),
      "round-trip keeps bindings (params + brightness) and scalars")
check(scene.dice_letters() == ["a"], "dice_letters() reports the scene's letters")

# ── resolution: ⚡ map, fallback, dice correlation, coercion ──────────────────
ctx = FireContext(1.0, rng=Random(7))
resolved = scene_compiler.resolve_scene(scene, ctx)
p = resolved.devices[0].params
check(p["spin"] == 1.0 and resolved.devices[0].brightness == 1.0,
      "⚡ map at intensity 1.0 → out_max")
ctx = FireContext(None, rng=Random(7))
p = scene_compiler.resolve_scene(scene, ctx).devices[0].params
check(p["spin"] == 0.55, "no signal → fallback (the migrated static)")
pairs = {(0.3, 6), (-0.3, 3), (0.0, 5)}
seen_pairs = set()
for seed in range(300):
    p = scene_compiler.resolve_scene(scene, FireContext(0.5, rng=Random(seed))).devices[0].params
    seen_pairs.add((p["star"], p["edges"]))
check(seen_pairs == pairs,
      "dice correlation: 300 fires land ONLY authored pairs, all three seen")
counts = {pair: 0 for pair in pairs}
rng = Random(123)
for _ in range(6000):
    p = scene_compiler.resolve_scene(scene, FireContext(0.5, rng=rng)).devices[0].params
    counts[(p["star"], p["edges"])] += 1
check(abs(counts[(0.3, 6)] / 6000 - 0.4) < 0.03
      and abs(counts[(-0.3, 3)] / 6000 - 0.4) < 0.03
      and abs(counts[(0.0, 5)] / 6000 - 0.2) < 0.03,
      f"dice thresholds 0.4/0.8 reproduce 2:2:1 weights ({counts})")
uncorr = SceneV2(name="u", devices=[SceneDeviceConfig(
    target="Matrix", effect_type="radial",
    params={"star": {"bind": "signal", "signal": "random", "mode": "steps",
                     "steps": [{"threshold": 0.0, "value": 0.0},
                               {"threshold": 0.5, "value": 1.0}]},
            "twist": {"bind": "signal", "signal": "random", "mode": "steps",
                      "steps": [{"threshold": 0.0, "value": 0.0},
                                {"threshold": 0.5, "value": 1.0}]}})])
differ = 0
for seed in range(200):
    p = scene_compiler.resolve_scene(uncorr, FireContext(0.5, rng=Random(seed))).devices[0].params
    differ += p["star"] != p["twist"]
check(differ > 30, f"dice=None stays independent per field ({differ}/200 differ)")
enum_steps = ValueBinding(signal="trigger_intensity", mode="steps",
                          steps=[{"threshold": 0.0, "value": "ballet"},
                                 {"threshold": 0.7, "value": "kpop"}])
check(binding_resolver.apply_binding(enum_steps, FireContext(0.9),
                                     binding_resolver.KIND_STRING) == "kpop"
      and binding_resolver.apply_binding(enum_steps, FireContext(0.2),
                                         binding_resolver.KIND_STRING) == "ballet",
      "string steps pick enum options by intensity (dance style)")
check(binding_resolver.apply_binding(
    ValueBinding(signal="rms_total", mode="map", out_min=0, out_max=1, fallback=0.42),
    FireContext(0.9), binding_resolver.KIND_NUMERIC) == 0.42,
    "beat-window signals resolve to fallback until the S2 bridge")
clamped = ValueBinding(signal="trigger_intensity", mode="map",
                       out_min=0, out_max=99, fallback=None)
check(binding_resolver.apply_binding(clamped, FireContext(1.0),
                                     binding_resolver.KIND_INTEGER, 1, 8) == 8,
      "registry min/max clamp the resolved value; integer coercion rounds")

# ── responses block: shim, four classes, per-class band validation ───────────
legacy = {"name": "Legacy", "devices": [],
          "flare_bands": [{"intensity_min": 0.0, "intensity_max": 0.5},
                          {"intensity_min": 0.5, "intensity_max": 1.0,
                           "param_patch": {"flames": 1.0}}]}
ls = SceneV2(**legacy)
ls_kinds = {k.name: k for k in ls.flare_kinds}
check(list(ls.responses) == ["flare"] and len(ls.responses["flare"].bands) == 2
      and absolute_params(ls_kinds["Flare patch 0.5–1"]) == {"flames": 1.0}
      and ls.responses["flare"].bands[1].kinds["Flare patch 0.5–1"] == 1.0,
      "legacy flare_bands loads unchanged as the flare class "
      "(patch → auto-named PERMANENT kind on its band)")
check("flare_bands" not in ls.model_dump(),
      "canonical serialized form carries responses only")
four = SceneV2(name="four", responses={
    "flare": ResponseSpec(bands=[FlareBand(intensity_min=0, intensity_max=1)],
                          color_set_jump=True),
    "charge": ResponseSpec(bands=[FlareBand(intensity_min=0.5, intensity_max=1)]),
    "lull": ResponseSpec(reroll_dice=False),
    "drop": ResponseSpec()})
check(set(four.responses) == {"flare", "charge", "lull", "drop"},
      "all four response classes carried")
try:
    ResponseSpec(bands=[FlareBand(intensity_min=0.0, intensity_max=0.6),
                        FlareBand(intensity_min=0.5, intensity_max=1.0)])
    raise SystemExit("FAIL: overlapping response bands accepted")
except ValidationError:
    print("ok: overlapping bands rejected per response class")

# ── NAMED FLARE KINDS (item 8): the shape, load-unchanged, validation ────────
from spectra.models.scene import FlareKind

# The LOAD-UNCHANGED GUARANTEE, spec-asserted on the live library's exact
# authored shape (Black Hole V2's three flare bands): every legacy field —
# per-band param_patch, gain (pulse = momentary, linear = permanent),
# per-class reroll_dice (legacy default True) and flare color_set_jump —
# becomes an auto-named kind attached to its band at scale ×1, legacy
# execution fields neutralize (ONE execution surface), and the round-trip
# is stable.
lib_shape = {"name": "BH", "devices": [], "responses": {"flare": {"bands": [
    {"intensity_min": 0.0, "intensity_max": 0.35, "curve": "linear",
     "gain": 0.7, "param_patch": {"spawn_rate": 0.7, "beat_burst": 1.0}},
    {"intensity_min": 0.35, "intensity_max": 0.7, "curve": "linear",
     "gain": 1.0, "param_patch": {"spawn_rate": 1.25, "beat_burst": 3.0}},
    {"intensity_min": 0.7, "intensity_max": 1.0, "curve": "pulse",
     "gain": 1.4, "param_patch": {"spawn_rate": 2.0, "beat_burst": 6.0}},
], "reroll_dice": True, "color_set_jump": True}}}
bh = SceneV2(**lib_shape)
bh_kinds = {k.name: k for k in bh.flare_kinds}
check(bh_kinds["Dice Re-roll"].type == "drift_jump"
      and bh_kinds["Dice Re-roll"].jump == "dice"
      and bh_kinds["Colour Jump"].jump == "color_set",
      "auto-named kinds: reroll_dice → Dice Re-roll, color_set_jump → "
      "Colour Jump (drift-jump type)")
check(bh_kinds["Flare patch 0.7–1"].type == "permanent"
      and absolute_params(bh_kinds["Flare patch 0.7–1"])
      == {"spawn_rate": 2.0, "beat_burst": 6.0},
      "auto-named kinds: a band's param_patch → PERMANENT kind, values kept")
check(bh_kinds["Flare gain 0.7–1"].type == "momentary"
      and bh_kinds["Flare gain 0.7–1"].gain == 1.4
      and bh_kinds["Flare gain 0–0.35"].type == "permanent"
      and bh_kinds["Flare gain 0–0.35"].gain == 0.7,
      "auto-named kinds: pulse gain → MOMENTARY, linear gain → PERMANENT")
top = bh.responses["flare"].bands[2]
check(set(top.kinds) == {"Flare patch 0.7–1", "Flare gain 0.7–1",
                         "Dice Re-roll", "Colour Jump"}
      and all(s == 1.0 for s in top.kinds.values()),
      "each band attaches exactly its authored kinds at scale ×1")
mid = bh.responses["flare"].bands[1]
check(set(mid.kinds) == {"Flare patch 0.35–0.7", "Dice Re-roll",
                         "Colour Jump"},
      "a neutral gain (1.0) names no kind — nothing invented")
check(all(b.gain == 1.0 and b.param_patch == {}
          for b in bh.responses["flare"].bands)
      and bh.responses["flare"].reroll_dice is False
      and bh.responses["flare"].color_set_jump is False,
      "legacy execution fields neutralize after migration — one surface")
bh_rt = json.loads(bh.model_dump_json())
check(bh_rt == json.loads(SceneV2(**bh_rt).model_dump_json()),
      "migration is idempotent — the canonical form round-trips verbatim")
check(SceneV2(**lib_shape).model_dump(exclude={"id"})
      == bh.model_dump(exclude={"id"}),
      "migration is deterministic — same input, same kinds")
csj_drop = SceneV2(name="d", responses={"drop": {
    "bands": [{"intensity_min": 0.0, "intensity_max": 1.0}],
    "reroll_dice": False, "color_set_jump": True}})
check("Colour Jump" not in {k.name for k in csj_drop.flare_kinds},
      "color_set_jump on a non-flare class was a legacy no-op — no kind")

try:
    FlareKind(name="bad", type="drift_jump")
    raise SystemExit("FAIL: drift-jump kind without a jump accepted")
except ValidationError:
    print("ok: a drift-jump kind must say which drift it jumps")
try:
    FlareKind(name="idle", type="momentary")
    raise SystemExit("FAIL: kind that moves nothing accepted")
except ValidationError:
    print("ok: a momentary/permanent kind must declare params and/or gain")
try:
    SceneV2(name="bad", flare_kinds=[
        FlareKind(name="Slam", type="momentary", gain=1.4)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(kinds={"Ghost": 1.0})])})
    raise SystemExit("FAIL: band referencing an undeclared kind accepted")
except ValidationError:
    print("ok: band kind references must resolve to declared kinds")
try:
    SceneV2(name="bad", flare_kinds=[
        FlareKind(name="Slam", type="momentary", gain=1.4),
        FlareKind(name="Slam", type="permanent", gain=0.5)])
    raise SystemExit("FAIL: duplicate kind names accepted")
except ValidationError:
    print("ok: duplicate flare kind names rejected")

# ── drift declarations: named profile / inline, validation ───────────────────
drifting = SceneV2(name="drift", devices=[SceneDeviceConfig(
    target="Matrix", effect_type="radial", params={"spin": 0.5},
    drift={"spin": DriftRef(inline=DriftSpec(kind="creep", rate_per_min=0.05,
                                             lo=0.1, hi=0.9)),
           "brightness": DriftRef(profile="slow-wander")},
    brightness=0.8)])
check(drifting.devices[0].drift["spin"].inline.motion == "bounce",
      "inline creep declaration carried with bounce default")
try:
    SceneDeviceConfig(target="Matrix", effect_type="radial",
                      drift={"ghost": DriftRef(profile="p")})
    raise SystemExit("FAIL: drift on an unset param accepted")
except ValidationError:
    print("ok: drift declaration on an unset param rejected")
try:
    DriftRef()
    raise SystemExit("FAIL: empty DriftRef accepted")
except ValidationError:
    print("ok: DriftRef needs exactly one of profile/inline")

# ── colour journey: room default, first-class override, custody semantics ────
room = color_journey.RoomColorState(wheel_position_deg=200.0)
inherit_scene = SceneV2(name="inh")
check(color_journey.active_journey(room, inherit_scene).custody == "room"
      and color_journey.active_journey(room, inherit_scene).degrees_per_min
      == 30.0,
      "inherit scene rides the room journey (the owner's live 30°/min "
      "reference pace as default)")
slow = SceneV2(name="slow", color_journey=SceneColorJourney(
    mode="inherit", pace_factor=0.0))
check(color_journey.active_journey(room, slow).degrees_per_min == 0.0,
      "pace_factor 0 holds the room walk while the scene shows")
override_scene = SceneV2(name="ovr", color_journey=SceneColorJourney(
    mode="override", journey=ColorJourneySpec(degrees_per_min=-30.0)))
try:
    SceneColorJourney(mode="override")
    raise SystemExit("FAIL: override without a journey spec accepted")
except ValidationError:
    print("ok: override requires a journey spec (first-class field)")

# INTO: custody transfers, the position does not move.
entered = color_journey.on_scene_enter(room, override_scene)
check(entered.custody == "scene" and entered.degrees_per_min == 30.0,
      "INTO override: the scene steers, at its own reference pace "
      "(direction now comes from the destination, so the sign folds away)")
# Destination model: pace is fixed at selection from distance.
check(color_journey.destination_pace(30.0, 90.0) == 30.0
      and color_journey.destination_pace(30.0, 30.0) == 15.0
      and abs(color_journey.destination_pace(30.0, 179.0)
              - 30.0 * (179.0 / 90.0)) < 1e-9
      and color_journey.destination_pace(30.0, 300.0) == 60.0,
      "the destination fixes its own pace: reference at 90°, ×0.5 floor "
      "near, ×2 ceiling far")
pos = room.wheel_position_deg
pos2, arrived = color_journey.step_toward(pos, 140.0, 30.0, dt_s=60.0)
check(pos2 == (200.0 - 30.0) % 360.0 and not arrived,
      "travel walks FROM the room's current position toward the "
      "destination along the shortest arc — no snap in")
pos3, arrived = color_journey.step_toward(pos2, 140.0, 30.0, dt_s=60.0)
check(pos3 == 140.0 and arrived,
      "arrival lands EXACTLY on the destination position")
# OUT: the room adopts the override's final position and resumes its pace.
room2 = color_journey.on_scene_exit(room, pos2)
check(room2.wheel_position_deg == pos2 and room2.destination is None,
      "OUT of override: room resumes from where the override left the "
      "wheel, with a fresh bearing to pick")
resumed = color_journey.active_journey(room2, inherit_scene)
check(resumed.custody == "room" and resumed.degrees_per_min == 30.0,
      "OUT of override: the room's own reference pace steers again")
check(color_journey.step_toward(room2.wheel_position_deg, 140.0, 30.0, 60.0,
                                palette_rainbow=True)
      == (room2.wheel_position_deg, False),
      "rainbow palette pauses the walk (binding exemption)")
check(color_journey.step_toward(None, 140.0, 30.0, 60.0) == (None, False),
      "no chromatic position yet → walk holds")

# ── compiler: subtree expansion, override layering, binding-free contract ────
res = scene_compiler.resolve_scene(scene, FireContext(1.0, rng=Random(1)))
writes = {w["virtual_id"]: w for w in scene_compiler.compile_scene(res)}
check(set(writes) == {"v-m1", "v-m2", "v-m3"},
      "category subtree expansion through fx/device_model")
check(writes["v-m1"]["config"]["spin"] == 1.0
      and writes["v-m1"]["config"]["brightness"] == 1.0,
      "resolved scalars land in the compiled config")
try:
    scene_compiler.compile_scene(scene)
    raise SystemExit("FAIL: compile accepted unresolved bindings")
except ValueError:
    print("ok: compile_scene refuses unresolved bindings (resolve first)")
fire = asyncio.run(scene_compiler.fire_scene(scene, intensity=0.5,
                                             rng=Random(5)))
check(fire["dry_run"] is True and len(fire["writes"]) == 3
      and any(r["param"] == "spin" for r in fire["resolved_bindings"])
      and "a" in fire["dice_rolls"],
      "dry-run fire: writes + resolution report + dice rolls, no I/O")

# ── intensity-conditional EFFECT SELECTION (decision: star-fold-entry-growth) ─
fold = SceneV2(name="Fold", devices=[SceneDeviceConfig(
    target_kind="category", target="Strips", effect_type="melt",
    params={},
    effect_steps=[{"threshold": 0.7, "effect_type": "power",
                   "params": {"bass_decay_rate": 0.6}}])])
rt_fold = SceneV2(**json.loads(fold.model_dump_json()))
check(rt_fold.devices[0].effect_steps[0].effect_type == "power"
      and rt_fold.devices[0].effect_steps[0].threshold == 0.7,
      "effect steps round-trip (threshold + per-effect params)")
check(SceneV2(name="plain", devices=[SceneDeviceConfig(
    target="Strips", effect_type="melt")]).devices[0].effect_steps == [],
      "single-effect form stays the plain default (empty steps)")

# LOAD-UNCHANGED GUARANTEE: a pre-growth file (no effect_steps key anywhere)
# loads to exactly the scene the canonical form holds — same serialization,
# no selection rows, same compiled effect at every intensity.
legacy_form = json.loads(scene.model_dump_json())
for d in legacy_form["devices"]:
    d.pop("effect_steps")
legacy_loaded = SceneV2(**legacy_form)
check(json.loads(legacy_loaded.model_dump_json())
      == json.loads(scene.model_dump_json()),
      "load-unchanged: a pre-growth scene file loads identical to canonical")
for inten in (0.0, 0.5, 1.0):
    lctx = FireContext(inten, rng=Random(9))
    lw = scene_compiler.compile_scene(
        scene_compiler.resolve_scene(legacy_loaded, lctx))
    check({w["effect_type"] for w in lw} == {"radial"}
          and not any(r["param"] == "effect" for r in lctx.resolved),
          f"load-unchanged: single-effect entry keeps its effect at ⚡ {inten}")


def fold_write(intensity):
    fctx = FireContext(intensity, rng=Random(1))
    res = scene_compiler.resolve_scene(fold, fctx)
    return scene_compiler.compile_scene(res)[0], fctx


w, fctx = fold_write(0.3)
check(w["effect_type"] == "melt" and "bass_decay_rate" not in w["config"],
      "below the boundary the entry resolves to the base effect (melt)")
w, fctx = fold_write(0.7)
check(w["effect_type"] == "power" and w["config"]["bass_decay_rate"] == 0.6,
      "at the boundary the step wins: a DIFFERENT effect, its own params")
check(any(r["param"] == "effect" and r["value"] == "power"
          for r in fctx.resolved),
      "the selection lands in the resolution report — the test-fire panel "
      "states the effect the intensity picked")
check(fold_write(0.69)[0]["effect_type"] == "melt"
      and fold_write(1.0)[0]["effect_type"] == "power",
      "threshold semantics mirror the steps binding (last step <= intensity)")
check(fold_write(None)[0]["effect_type"] == "melt",
      "no intensity axis → the base form (the base IS the fallback)")
try:
    scene_compiler.compile_scene(fold)
    raise SystemExit("FAIL: compile accepted unresolved effect steps")
except ValueError:
    print("ok: compile_scene refuses unresolved effect steps (resolve first)")
for bad_steps, why in (
        ([{"threshold": 0.5, "effect_type": "power"},
          {"threshold": 0.5, "effect_type": "orbits1d"}],
         "duplicate thresholds"),
        ([{"threshold": 0.0, "effect_type": "power"}],
         "threshold 0 would shadow the base form"),
        ([{"threshold": 0.5, "effect_type": ""}], "empty step effect"),
        ([{"threshold": 0.5, "effect_type": "melt"}],
         "same effect as the base (that's a ⚡ steps binding's job)"),
):
    try:
        SceneDeviceConfig(target="Strips", effect_type="melt",
                          effect_steps=bad_steps)
        raise SystemExit(f"FAIL: effect steps accepted ({why})")
    except ValidationError:
        print(f"ok: effect steps rejected — {why}")
dicey = SceneV2(name="dl", devices=[SceneDeviceConfig(
    target="Strips", effect_type="melt",
    effect_steps=[{"threshold": 0.6, "effect_type": "power",
                   "params": {"blur": {"bind": "signal", "signal": "random",
                              "mode": "steps", "dice": "z",
                              "steps": [{"threshold": 0.0, "value": 0.0},
                                        {"threshold": 0.5, "value": 2.0}]}}}])])
check(dicey.dice_letters() == ["z"],
      "dice_letters sees step-variant params")
SceneDeviceConfig(target="Strips", effect_type="melt",
                  effect_steps=[{"threshold": 0.6, "effect_type": "power",
                                 "params": {"blur": 1.0}}],
                  drift={"blur": DriftRef(inline=DriftSpec(
                      kind="creep", rate_per_min=0.1, lo=0.0, hi=2.0))})
print("ok: drift may target a param only a step variant sets")

# ── store + API round-trip ───────────────────────────────────────────────────
from fastapi.testclient import TestClient
from spectra.app import create_app
client = TestClient(create_app())

scene_store.save(scene)
check(scene_store.get_by_id(scene.id).name == "Spec", "store round-trip")
listed = client.get("/api/scenes").json()
check(len(listed) == 1 and listed[0]["name"] == "Spec",
      "GET /api/scenes lists the stored scene")
api_fire = client.post(f"/api/scenes/{scene.id}/fire",
                       json={"dry_run": True, "intensity": 0.9}).json()
check(api_fire["dry_run"] is True and api_fire["intensity"] == 0.9
      and api_fire["writes"], "API test-fire at a chosen intensity")
bad = dict(json.loads(scene.model_dump_json()))
bad["devices"][0]["drift"] = {"spin": {"profile": "nope", "inline": None}}
check(client.post("/api/scenes", json=bad).status_code == 422,
      "dangling named drift profile → 422")
r = client.put("/api/drift-profiles", json={
    "slow": {"id": "slow", "name": "Slow Wander",
             "spec": {"kind": "creep", "rate_per_min": 0.02, "lo": 0.2, "hi": 0.8}}})
check(r.status_code == 200, "drift profile library saves")
bad["devices"][0]["drift"] = {"spin": {"profile": "slow", "inline": None}}
check(client.post("/api/scenes", json=bad).status_code == 200,
      "scene referencing a real named profile saves")
check(client.put("/api/drift-profiles", json={}).status_code == 422,
      "deleting a profile still referenced by a scene → 422")
rj = client.get("/api/room-journey").json()
check(rj["journey"]["degrees_per_min"] == 30.0,
      "room journey served (30°/min effective default)")
client.put("/api/room-journey", json={
    "journey": {"degrees_per_min": 5.0}, "wheel_position_deg": 123.0,
    "destination": {"set_id": "x", "position_deg": 1.0,
                    "pace_deg_per_min": 9.0, "from_deg": 0.0}})
rj = client.get("/api/room-journey").json()
check(rj["journey"]["degrees_per_min"] == 5.0
      and rj["wheel_position_deg"] != 123.0
      and rj["destination"] is None,
      "journey PUT updates the declaration, never teleports the wheel or "
      "hand-steers the bearing")

# ── stepped-effect test-fire through the API: the preview IS the honest
#    window into the selection ────────────────────────────────────────────────
scene_store.save(fold)
api_lo = client.post(f"/api/scenes/{fold.id}/fire",
                     json={"dry_run": True, "intensity": 0.3}).json()
api_hi = client.post(f"/api/scenes/{fold.id}/fire",
                     json={"dry_run": True, "intensity": 0.9}).json()
check(api_lo["writes"][0]["effect_type"] == "melt"
      and api_hi["writes"][0]["effect_type"] == "power"
      and api_hi["writes"][0]["config"]["bass_decay_rate"] == 0.6
      and any(r["param"] == "effect" and r["value"] == "power"
              for r in api_hi["resolved_bindings"]),
      "API test-fire at a chosen intensity shows the effect that intensity "
      "selects (writes + the effect row) — preview parity")
scene_store.delete(fold.id)

# ── the manual apply-this-set surface + fires wear the room's set ────────────
GRAD_BLUE = "linear-gradient(90deg, #0000ff 0%, #4000ff 100%)"
scfg.COLOR_SETS_FILE.write_text(json.dumps({
    "set-blue": {"id": "set-blue", "name": "Blues", "kind": "set",
                 "entries": [{"scope": {"categories": ["Matrix"]},
                              "color_kind": "gradient",
                              "color_value": GRAD_BLUE}]},
}))
r = client.post("/api/room-color/apply", json={"set_id": "missing"})
check(r.status_code == 404, "apply-this-set refuses an unknown set")
r = client.post("/api/room-color/apply", json={"set_id": "set-blue"})
check(r.status_code == 200 and r.json()["applied"] == "set-blue"
      and color_journey.load_room().active_set_id == "set-blue",
      "apply-this-set (agent/fleet surface): the room's active set moves "
      "on the owner's word")
fired = asyncio.run(scene_compiler.fire_scene(scene, intensity=0.5))
set_writes = [w for w in fired["writes"]
              if w["config"].get("gradient") == GRAD_BLUE]
check(len(set_writes) > 0,
      "a fire with no explicit set WEARS THE ROOM'S ACTIVE SET — the "
      "owner's colours, never effect defaults")
scfg.COLOR_SETS_FILE.unlink()

# ── sequencer engine on SPECTRA stores: fire carries intensity; wheel is
#    shared room state ────────────────────────────────────────────────────────
from spectra.models.sequencer import (CurvePoint, CurveProfile, SelectorEntry,
                                      SequencerConfig)
from spectra.services import sequencer_store
from spectra.services.scene_sequencer import SceneSequencer

s_a = SceneV2(name="A")
s_b = SceneV2(name="B")
for s in (s_a, s_b):
    scene_store.save(s)
sequencer_store.save_curves({"flat": CurveProfile(id="flat", name="Flat",
                                                  points=[CurvePoint(x=0, y=1)])})
sequencer_store.save_config(SequencerConfig(enabled=True, entries={
    s_a.id: SelectorEntry(curve_ref="flat"),
    s_b.id: SelectorEntry(curve_ref="flat")}))
fired: list[tuple] = []
wheel_box: list = [None]

async def fake_fire(sid, cset, inten):
    fired.append((sid, cset, inten))

seq = SceneSequencer(
    rng=Random(9),
    fire=fake_fire,
    intensity=lambda: 0.7,
    render_intensity=lambda x: x,  # isolates selection-intensity from the
                                    # genre+bass render scale (own coverage
                                    # in check_triggers.py / intensity_scale)
    wheel_get=lambda: wheel_box[0],
    wheel_set=lambda d: wheel_box.__setitem__(0, d),
    list_scene_ids=lambda: {s_a.id, s_b.id},
    eligible_sets=lambda sid: {},
)

async def run_moments():
    await seq.on_track_state("uri:1")   # arms only
    await seq.on_track_state("uri:2")   # first real moment
    await seq.on_track_state("uri:3")

asyncio.run(run_moments())
check(len(fired) >= 1 and fired[0][2] == 0.7,
      "sequencer fire carries the moment's intensity to the compiler")
check(seq.status()["color"]["wheel_position_deg"] is None
      and seq.status()["enabled"] is True,
      "engine status reads the shared room wheel state")

# ── the seeder's S1 half on a fixture of the live scenes ─────────────────────
fixture = td / "live"
fixture.mkdir()
live_src = Path(__file__).parent.parent / "storage" / "scenes_v2.json"
if not live_src.exists():
    # Spec fixture: a minimal two-scene file shaped like the live one.
    (fixture / "scenes_v2.json").write_text(json.dumps({
        "id-mid": {"id": "id-mid", "name": "Mid Star V2", "labels": [],
                   "devices": [{"id": "d1", "target_kind": "category",
                                "target": "Matrix", "effect_type": "radial",
                                "params": {"polygon": True, "star": 0.3,
                                           "edges": 6, "spin": 0.55},
                                "color": {"mode": "set"}}],
                   "flare_bands": [{"intensity_min": 0.0, "intensity_max": 1.0}],
                   "choreography": {"enabled": False}},
        "id-plain": {"id": "id-plain", "name": "Unmapped", "labels": [],
                     "devices": [], "flare_bands": []},
    }))
else:
    (fixture / "scenes_v2.json").write_text(live_src.read_text())

import importlib
seed_mod = importlib.import_module("scripts.seed_spectra_from_v2")
raw = json.loads((fixture / "scenes_v2.json").read_text())
mid_raw = next(v for v in raw.values() if v["name"] == "Mid Star V2")
migrated, log = seed_mod.migrate_scene(mid_raw)
ms = SceneV2(**migrated)
star = ms.devices[0].params["star"]
check(isinstance(star, ValueBinding) and star.dice == "a"
      and star.fallback == mid_raw["devices"][0]["params"]["star"],
      "seeder: Mid Star star → 🎲 dice binding, static value as fallback")
check(any(k.name == "Colour Jump" and k.jump == "color_set"
          for k in ms.flare_kinds)
      and all("Colour Jump" in b.kinds
              for b in ms.responses["flare"].bands),
      "seeder: flare class seeds the Colour Jump kind on every band "
      "(the legacy Color lane)")
migrated2, _ = seed_mod.migrate_scene(mid_raw)
check(migrated == migrated2, "seeder migration is deterministic (idempotent)")
spin = ms.devices[0].params["spin"]
check(isinstance(spin, ValueBinding) and spin.fallback == 0.55
      and spin.out_min == 0.1 and spin.out_max == 1.0,
      "seeder: Mid Star spin → ⚡ 0.1→1.0, static 0.55 as fallback")
res = scene_compiler.resolve_scene(ms, FireContext(None, rng=Random(2)))
check(res.devices[0].params["spin"] == 0.55,
      "migrated scene with no signal resolves to its old static look")

# ═══ S2 — the evolution engine ═══════════════════════════════════════════════

from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import JUMP_MS, RecordingExecutor
from spectra.services.scene_response import (DICE_REROLL_GLIDE_MS,
                                              ResponseEngine, select_band)
from spectra.services import color_journey as cj

# ── band selection: [min, max), top band inclusive at exactly 1.0 ────────────
b_lo = FlareBand(intensity_min=0.0, intensity_max=0.5)
b_hi = FlareBand(intensity_min=0.5, intensity_max=1.0)
check(select_band([b_lo, b_hi], 0.0) is b_lo
      and select_band([b_lo, b_hi], 0.5) is b_hi
      and select_band([b_lo, b_hi], 1.0) is b_hi,
      "band selection: [min, max) with the top band inclusive at 1.0")
check(select_band([b_hi], 0.3) is None,
      "no band containing the intensity → the class stays silent")

# ── response-engine harness (fakes; the conductor spec is check_drift.py) ────
room_box: list = [cj.RoomColorState(wheel_position_deg=220.0,
                                    active_set_id="set-blue")]
from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
set_cards = {
    "set-red": ColorSetCard(id="set-red", name="Reds", entries=[
        ColorSetEntry(scope=SetScope(categories=["Matrix"]),
                      color_kind="solid", color_value="#ff0000",
                      brightness=0.9)]),
}
seq_cfg_box = [SequencerConfig(color_set_entries={
    "set-red": SelectorEntry()})]
eligible_box: list = [{"set-red": 10.0}]
surge_broadcasts: list[dict] = []


async def surge_capture(payload):
    surge_broadcasts.append(payload)

exec2 = RecordingExecutor()
conductor2 = DriftConductor(
    executor=exec2,
    intensity=lambda: 0.5,
    room_load=lambda: room_box[0],
    room_save=lambda st: room_box.__setitem__(0, st),
    set_position=lambda sid: {"set-blue": 220.0, "set-red": 10.0}.get(sid),
    drift_profiles=lambda: {},
    curve_profiles=lambda: {},
)
responder = ResponseEngine(
    conductor=conductor2, executor=exec2, rng=Random(11),
    broadcast=surge_capture,
    sequencer_config=lambda: seq_cfg_box[0],
    curve_profiles=lambda: {},
    eligible_sets=lambda sc: eligible_box[0],
    set_card=lambda sid: set_cards.get(sid),
    room_load=lambda: room_box[0],
    room_save=lambda st: room_box.__setitem__(0, st),
)

# LEGACY-AUTHORED responses (the pre-kinds shapes, historical defaults —
# flare/drop reroll on): the engine below must reproduce the legacy
# behaviors EXACTLY through their auto-named kinds — the executable half
# of the load-unchanged guarantee.
resp_base = json.loads(scene.model_dump_json())
resp_base.pop("flare_kinds", None)   # legacy input has no kinds key
resp_base["responses"] = {
    "flare": {"bands": [
        {"intensity_min": 0.0, "intensity_max": 0.5, "curve": "pulse",
         "gain": 1.6, "param_patch": {"twist": 0.9}},
        {"intensity_min": 0.5, "intensity_max": 1.0, "curve": "pulse",
         "gain": 2.0}], "reroll_dice": True, "color_set_jump": True},
    "charge": {"bands": [
        {"intensity_min": 0.5, "intensity_max": 1.0, "curve": "ease_in",
         "gain": 1.3}], "reroll_dice": False},
    "lull": {"bands": [
        {"intensity_min": 0.0, "intensity_max": 1.0, "curve": "linear",
         "gain": 0.5}], "reroll_dice": False},
    "drop": {"bands": [
        {"intensity_min": 0.7, "intensity_max": 1.0,
         "param_patch": {"spin": 1.0, "ghost_param": 5.0}}],
        "reroll_dice": True},
}
resp_scene = SceneV2(**resp_base)


def kind_recs(record, key):
    """The executed-kind records carrying a given detail key."""
    return [k for k in record.get("kinds", []) if key in k]

resolved_fire = scene_compiler.resolve_scene(resp_scene,
                                             FireContext(0.5, rng=Random(3)))
fire_writes = scene_compiler.compile_scene(resolved_fire)
conductor2.on_scene_fire(resp_scene, fire_writes, "set-blue")
base_brightness = conductor2.virtuals["v-m1"].brightness_baseline
check(abs(base_brightness - 0.65) < 1e-6,
      "baseline brightness = the fire's resolved binding (⚡ 0.65 at 0.5)")

# ── flare: re-roll (authored pairs), patch broadcast, pulse, colour jump ─────
record = asyncio.run(responder.on_event("flare", 0.3))
check(record["result"] == "applied"
      and record["band"] == {"intensity_min": 0.0, "intensity_max": 0.5}
      and {k["name"] for k in record["kinds"]}
      == {"Dice Re-roll", "Flare patch 0–0.5", "Flare gain 0–0.5",
          "Colour Jump"},
      "flare at 0.3 lands in its band and executes its auto-named kinds")
pairs = {(0.3, 6), (-0.3, 3), (0.0, 5)}
jumps = [w for w in exec2.writes if w["kind"] == "jump"]
glides0 = [w for w in exec2.writes if w["kind"] == "glide"]
reroll_jump = next(w for w in jumps if "edges" in w["params"])
reroll_glide = next(w for w in glides0 if "star" in w["params"])
check((reroll_glide["params"]["star"], reroll_jump["params"]["edges"]) in pairs,
      "re-roll: 🎲 star/edges land as an AUTHORED pair (fresh dice) — "
      "star (registry smooth=true) eases, edges (smooth=false) still "
      "jumps as before")
check(reroll_glide["duration_ms"] == DICE_REROLL_GLIDE_MS,
      "the smoothed re-roll actually glides over DICE_REROLL_GLIDE_MS, "
      "not an instant jump relabeled")
check("star" not in reroll_jump["params"]
      and "edges" not in reroll_glide["params"],
      "each re-rolled param lands on exactly one of jump/glide, never both")
check(all("spin" not in w["params"] for w in jumps + glides0),
      "re-roll leaves ⚡ (non-random) bindings alone")
patch_glides = [w for w in glides0 if "twist" in w["params"]]
check({w["virtual_id"] for w in patch_glides} == {"v-m1", "v-m2", "v-m3"}
      and all(w["params"]["twist"] == 0.9 for w in patch_glides)
      and all(w["duration_ms"] == DICE_REROLL_GLIDE_MS for w in patch_glides),
      "patch broadcast: 'twist' (registry smooth=true) lands on every "
      "virtual whose effect has it, eased over DICE_REROLL_GLIDE_MS — "
      "2026-08-17 fix: an explicit param-patch kind on a smooth param now "
      "glides same as a dice re-roll would, never an instant jump")
check(all("twist" not in w["params"] for w in jumps),
      "'twist' never also lands as an instant jump alongside its glide")
pulse_jumps = [w for w in jumps if set(w["params"]) == {"brightness"}]
check(len(pulse_jumps) == 3 and all(w["params"]["brightness"] == 1.0
                                    for w in pulse_jumps),
      "pulse spike: brightness jumps to baseline×gain clamped (0.65×1.6→1.0)")
check(kind_recs(record, "gain_envelope")[0]["gain_envelope"][0]["peak"] == 1.0,
      "the surge record states the spike peak on its kind")
check(record["color_jump"]["result"] == "jumped"
      and record["color_jump"]["picked_id"] == "set-red",
      "flare colour jump: the selector picked the eligible set")
from spectra.services.scene_response import color_jump_ramp_ms
check(color_jump_ramp_ms(0.0) == 2500 and color_jump_ramp_ms(1.0) == 150
      and color_jump_ramp_ms(0.5) == 1325,
      "colour ramp-in scales INVERSELY with intensity "
      "(2500 ms gentle end → 150 ms hard end, linear)")
grad_glides = [w for w in exec2.writes if w["kind"] == "glide"
               and "gradient" in w["params"]]
check(grad_glides and all(w["params"]["gradient"] == "#ff0000"
                          for w in grad_glides)
      and all(w["duration_ms"] == color_jump_ramp_ms(0.3) == 1795
              for w in grad_glides)
      and record["color_jump"]["ramp_ms"] == 1795,
      "the pick lands with the intensity-scaled ramp-in (0.3 → 1795 ms "
      "hue-arc glide — the owner's jump-not-blend refinement)")
check(room_box[0].active_set_id == "set-red"
      and room_box[0].wheel_position_deg == 10.0,
      "a chromatic pick moves the room's wheel — the journey resumes there")
check(conductor2.virtuals["v-m1"].gradient == "#ff0000"
      and conductor2.virtuals["v-m1"].brightness_baseline == 0.9,
      "colour jump CARRIES: palette + brightness baselines move with it")
released = asyncio.run(responder.flush_releases())
release_glides = [w for w in exec2.writes if w["kind"] == "glide"
                  and "brightness" in w["params"]]
check(released == 3 and all(
    abs(w["params"]["brightness"] - 0.9) < 1e-6 for w in release_glides),
      "pulse release returns to the baseline AS CARRIED (the jump moved it)")
check(surge_broadcasts and surge_broadcasts[-1]["type"] == "surge",
      "surge broadcast emitted with the applied record")

# ── keep-current rung; pulse alone is MOMENTARY ──────────────────────────────
eligible_box[0] = {}
wheel_before = room_box[0].wheel_position_deg
record = asyncio.run(responder.on_event("flare", 0.3))
check(record["color_jump"]["result"] == "kept_current"
      and room_box[0].wheel_position_deg == wheel_before
      and room_box[0].active_set_id == "set-red",
      "terminal rung KEEPS the current colours — never forced churn")
check(abs(conductor2.virtuals["v-m1"].brightness_baseline - 0.9) < 1e-6,
      "pulse without a carried change is MOMENTARY — the baseline holds")
asyncio.run(responder.flush_releases())
eligible_box[0] = {"set-red": 10.0}

# ── charge/lull/drop DRIVE THE REAL PHASE MACHINERY (five-updates item 2) ────
# The fixture's effect is radial — phase-capable — so every phase event
# must arm ({"phase": cls, "phase_progress": 0.0} jump) then ramp
# (phase_progress → 1.0 glide) with the original program's durations.
from spectra.services.scene_response import PHASE_RAMP_MS

record = asyncio.run(responder.on_event("charge", 0.8))
check(sorted(record["phase"]["targets"]) == ["v-m1", "v-m2", "v-m3"]
      and record["phase"]["ramp_ms"] == 4000,
      "charge drives the vendored phase machinery on every phase-capable "
      "virtual (arm + 4000 ms build ramp)")
arm = [w for w in exec2.writes if w["kind"] == "jump"
       and w["params"].get("phase") == "charge"]
ramp = [w for w in exec2.writes if w["kind"] == "glide"
        and w["params"] == {"phase_progress": 1.0}]
check(len(arm) == 3 and all(w["params"]["phase_progress"] == 0.0
                            for w in arm)
      and len(ramp) == 3 and all(w["duration_ms"] == 4000 for w in ramp),
      "the arm write resets phase_progress to 0.0 (re-arms the edge) and "
      "lands before the ramp glide — the legacy _fire_phase order")
held = max(0.0, min(1.0, 0.9 * 1.3))
check(kind_recs(record, "gain_envelope")[0]["gain_envelope"][0]["held"] is True
      and abs(conductor2.virtuals["v-m1"].brightness_baseline - held) < 1e-6,
      "charge ease_in gain lands and HOLDS — the baseline carries (0.9→1.0)")
record = asyncio.run(responder.on_event("lull", 0.2))
check(record["phase"]["ramp_ms"] == 2500,
      "lull suspends over the 2500 ms ramp")
check(abs(conductor2.virtuals["v-m1"].brightness_baseline - held * 0.5) < 1e-6,
      "lull gain 0.5 ducks and holds — surges carry in both directions")

# ── drop: patch, with unknown keys dropped by the registry gate ──────────────
record = asyncio.run(responder.on_event("drop", 0.9))
check(record["phase"]["ramp_ms"] == 400,
      "drop stays short — it's the snap (400 ms ramp)")
drop_glide = [w for w in exec2.writes if w["kind"] == "glide"
              and "spin" in w["params"]][-1]
check(drop_glide["params"]["spin"] == 1.0
      and not any("ghost_param" in w["params"] for w in exec2.writes),
      "drop patch lands 'spin' (registry smooth=true since 2026-08-17) as "
      "a glide; a key no effect carries lands nowhere")
record = asyncio.run(responder.on_event("drop", 0.3))
check(record["result"] == "phase_only",
      "drop below its band: the ARC still runs (the original fired the "
      "phase for every phase event); only the band extras stay silent")
check(asyncio.run(responder.on_event("charge", 0.2))["result"] == "phase_only"
      and len([s for s in responder.surges if s["result"] == "applied"]) == 5,
      "four classes executed; out-of-band moments run phase-only")

# ── track change releases an armed charge/lull (lifecycle guard) ─────────────
check(responder._phase_armed == "charge", "the last charge is still armed")
released = asyncio.run(responder.release_phases())
none_writes = [w for w in exec2.writes if w["kind"] == "jump"
               and w["params"].get("phase") == "none"]
check(released == 3 and len(none_writes) == 3
      and asyncio.run(responder.release_phases()) == 0,
      "track change releases the armed build with an instant phase 'none' "
      "write per virtual — once; a drop already disarms it")

# ── flares never touch the phase machinery ───────────────────────────────────
before_phase_writes = len([w for w in exec2.writes
                           if "phase" in w["params"]])
asyncio.run(responder.on_event("flare", 0.3))
check(len([w for w in exec2.writes if "phase" in w["params"]])
      == before_phase_writes,
      "a flare drives no phase write — charge/lull/drop own the arc")

# ── stepped-effect entries × the engine: selection is FIRE-TIME ONLY;
#    surges follow the selected variant; a new fire re-baselines honestly ─────
stepped = SceneV2(name="Stepped", devices=[SceneDeviceConfig(
    target_kind="category", target="Strips", effect_type="melt",
    params={"reactivity": {"bind": "signal", "signal": "random",
                           "mode": "steps",
                           "steps": [{"threshold": 0.0, "value": 0.2},
                                     {"threshold": 0.5, "value": 0.8}],
                           "fallback": 0.5}},
    effect_steps=[{"threshold": 0.7, "effect_type": "power",
                   "params": {"bass_decay_rate": 0.6,
                              "blur": {"bind": "signal", "signal": "random",
                                       "mode": "steps",
                                       "steps": [{"threshold": 0.0,
                                                  "value": 0.0},
                                                 {"threshold": 0.5,
                                                  "value": 2.0}],
                                       "fallback": 1.0}}}],
    drift={"reactivity": DriftRef(inline=DriftSpec(
        kind="creep", rate_per_min=0.05, lo=0.1, hi=0.9))})],
    responses={"flare": ResponseSpec(reroll_dice=True, bands=[
        FlareBand(intensity_min=0.0, intensity_max=1.0)])})
exec4 = RecordingExecutor()
cond4 = DriftConductor(executor=exec4, drift_profiles=lambda: {},
                       curve_profiles=lambda: {},
                       room_load=lambda: cj.RoomColorState(),
                       room_save=lambda st: None,
                       set_position=lambda sid: None)
resp4 = ResponseEngine(conductor=cond4, executor=exec4, rng=Random(2),
                       sequencer_config=lambda: SequencerConfig(),
                       room_load=lambda: cj.RoomColorState(),
                       room_save=lambda st: None)
hi_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(stepped, FireContext(0.9, rng=Random(1))))
cond4.on_scene_fire(stepped, hi_writes)
check(cond4.virtuals["v-s1"].effect_type == "power",
      "a HIGH fire re-baselines the engine on the SELECTED effect")
check(cond4.mechanisms == [],
      "drift on a base-only param sits out while the step variant holds "
      "(stated, never a glide the live effect can't carry)")
asyncio.run(resp4.on_event("flare", 0.9))
# blur (power) and reactivity (melt) are both registry smooth=true, so a
# re-roll of either eases rather than jumps (DICE_REROLL_GLIDE_MS) — check
# across both write kinds; "did it land" is what this proof is about.
moved4 = [w for w in exec4.writes if w["kind"] in ("jump", "glide")]
check(any("blur" in w["params"] for w in moved4)
      and all("reactivity" not in w["params"] for w in moved4),
      "re-roll follows the SELECTED variant's 🎲 params, never another "
      "variant's — a surge re-rolls dice, it never re-selects the effect")
check(any(w["kind"] == "glide" and "blur" in w["params"]
          and w["duration_ms"] == DICE_REROLL_GLIDE_MS for w in moved4),
      "blur (registry smooth=true) eases on re-roll, not an instant jump")
lo_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(stepped, FireContext(0.3, rng=Random(1))))
cond4.on_scene_fire(stepped, lo_writes)
check(cond4.virtuals["v-s1"].effect_type == "melt"
      and len(cond4.mechanisms) == 1,
      "a LOW fire re-selects: the base effect returns and its drift "
      "mechanism seeds again")
exec4.writes.clear()
asyncio.run(resp4.on_event("flare", 0.3))
moved4 = [w for w in exec4.writes if w["kind"] in ("jump", "glide")]
check(any("reactivity" in w["params"] for w in moved4)
      and all("blur" not in w["params"] for w in moved4),
      "after the re-select the re-roll follows the base variant again")

# ── OVERRIDE BLEND's dynamic half (2026-08-20, Admiral order "fix the lull
#    ramp" — supersedes the 2026-08-14 keep-as-is call, docs/SPECTRA_SPEC.md
#    §11): the charge/lull ramp stretches to ~90% of the real gap_ms it's
#    given, hanging the remaining ~10% at phase_progress=1.0 for free
#    (nothing writes phase_progress again until the next phase event); an
#    UNKNOWN gap (None — no trigger-schedule context, e.g. a bridge-
#    classified legacy event) falls back to the flat class default,
#    honestly, never a silent guess. A static per-scene override number was
#    a porting gap, not a design choice, and was retired rather than kept
#    alongside the dynamic stretch — see models.scene.py's PhaseBlend
#    retirement note. entry_ramp_ms (untouched by this feature) still
#    blends a live fire's writes in via fx_seam instead of an instant jump ──
from spectra.services import fx_seam

check(SceneV2(name="x").entry_ramp_ms == 0,
      "no entry_ramp_ms authored: today's instant-jump behaviour is unchanged")

plain = SceneV2(name="Plain", devices=[SceneDeviceConfig(
    target_kind="category", target="Matrix", effect_type="radial",
    params={})])
exec5 = RecordingExecutor()
cond5 = DriftConductor(executor=exec5, drift_profiles=lambda: {},
                       curve_profiles=lambda: {},
                       room_load=lambda: cj.RoomColorState(),
                       room_save=lambda st: None,
                       set_position=lambda sid: None)
resp5 = ResponseEngine(conductor=cond5, executor=exec5, rng=Random(3),
                       sequencer_config=lambda: SequencerConfig(),
                       room_load=lambda: cj.RoomColorState(),
                       room_save=lambda st: None)
cond5.on_scene_fire(plain, scene_compiler.compile_scene(
    scene_compiler.resolve_scene(plain, FireContext(0.5, rng=Random(1)))))

# his real Dopamine pair (data/charge-lull-drop-timing-blends-and-a-sus-
# 7fm2/rig-capture.jsonl), both on the SAME song: a 6040ms lull and a
# 900ms lull. The flat 2500ms constant used to idle for 3.5s on the first
# and get cut off at 36% on the second — the SAME mechanism, at the SAME
# time, must now fit both.
long_lull = asyncio.run(resp5.on_event("lull", 0.5, gap_ms=6040))
check(long_lull["phase"]["ramp_ms"] == round(6040 * 0.9) == 5436,
      "a 6040ms real gap stretches the lull ramp to 90% of it (5436ms) — "
      "his spec verbatim: 'reach the center just and hang for a moment, "
      "maybe 10%, before the explosion'; the remaining 604ms hangs at "
      "phase_progress=1.0 for free — nothing writes it again before the drop")
short_lull = asyncio.run(resp5.on_event("lull", 0.2, gap_ms=900))
check(short_lull["phase"]["ramp_ms"] == round(900 * 0.9) == 810,
      "the SAME mechanism, the SAME song, an entirely different gap: a "
      "900ms real gap stretches to 810ms — no fixed constant could have "
      "fit both this and the 6040ms case above")
check(long_lull["phase"]["gap_ms"] == 6040 and short_lull["phase"]["gap_ms"] == 900,
      "the resolved gap_ms rides along on the phase record — a starved "
      "or unusually-timed ramp is explainable by looking, not a mystery")

charge_rec = asyncio.run(resp5.on_event("charge", 0.8, gap_ms=4500))
check(charge_rec["phase"]["ramp_ms"] == round(4500 * 0.9) == 4050,
      "charge gets the identical dynamic-stretch treatment as lull — he "
      "named both as carrying Override Blend deliberately")

unknown_rec = asyncio.run(resp5.on_event("lull", 0.5))   # gap_ms omitted
check(unknown_rec["phase"]["ramp_ms"] == 2500
      and unknown_rec["phase"]["gap_ms"] is None,
      "an UNKNOWN gap falls back to the flat 2500ms class default, "
      "honestly, never a silently-reintroduced universal constant")

drop_rec = asyncio.run(resp5.on_event("drop", 0.9, gap_ms=900))
check(drop_rec["phase"]["ramp_ms"] == 400,
      "drop is never stretched, even when a gap is known — it stays the "
      "fixed snap")

tiny_gap_rec = asyncio.run(resp5.on_event("lull", 0.5, gap_ms=100))
check(tiny_gap_rec["phase"]["ramp_ms"] == 200,
      "a gap too small to leave a meaningful 90% ramp floors at 200ms "
      "(legacy's own floor) rather than a near-zero, degenerate glide")

check(fx_seam._body({"effect_type": "radial", "config": {"speed": 1.0}})
      == {"type": "radial", "config": {"speed": 1.0}},
      "entry_ramp_ms=0 (default): the write body carries no transition "
      "keys — an unchanged instant switch")
ramped_body = fx_seam._body(
    {"effect_type": "radial", "config": {"speed": 1.0}}, 2000)
check(ramped_body["transition_ms"] == 2000
      and ramped_body["transition_blend"] == "hue"
      and ramped_body["easing"] == "linear",
      "entry_ramp_ms>0: the write body blends in hue-arc over the ramp — "
      "the same tween shape fx_executor uses for glides, never through grey")

# ── room-control surface (spectra-kept-equivalents): brightness multiplier,
#    ambient state, global transition pace — the legacy Brightness
#    Multiplier / ledfx_ambient* / ledfx_global_transition action
#    equivalents ────────────────────────────────────────────────────────────
from spectra.services import room_controls as rc

check(rc.load_room_controls() == rc.RoomControlState(),
      "no room_controls.json on disk: default state — multiplier 1.0 "
      "(no dimming), no ambient, no global transition default")
scaled = rc.apply_brightness({"brightness": 0.8, "spin": 2.0}, 0.5)
check(scaled == {"brightness": 0.4, "spin": 2.0},
      "apply_brightness scales brightness uniformly, leaves other params alone")
check(rc.apply_brightness({"brightness": 0.8}, 1.0) is not None
      and rc.apply_brightness({"speed": 1.0}, 0.5) == {"speed": 1.0},
      "multiplier 1.0, or no brightness key present: nothing to scale")

exec6 = RecordingExecutor(
    room_controls_load=lambda: rc.RoomControlState(brightness_multiplier=0.5))
asyncio.run(exec6.jump("v-rc", "radial", {"brightness": 0.8, "spin": 1.0}))
check(exec6.writes[-1]["params"] == {"brightness": 0.4, "spin": 1.0},
      "fx_executor applies the room brightness multiplier uniformly at the "
      "one write seam every glide/jump passes through")

dimmed_scene = SceneV2(name="Dimmed RC", devices=[SceneDeviceConfig(
    target_kind="virtual", target="v-rc", effect_type="radial", params={},
    brightness=0.8,
    color={"mode": "fixed"})])   # isolate from any active colour set
rc.save_room_controls(rc.RoomControlState(brightness_multiplier=0.5,
                                          global_transition_ms=1500))
rc_fire_calls: list = []


async def _fake_apply_writes(writes, *, transition_ms=0):
    rc_fire_calls.append((writes, transition_ms))

_orig_apply_writes = fx_seam.apply_writes
fx_seam.apply_writes = _fake_apply_writes
try:
    dimmed_result = asyncio.run(
        scene_compiler.fire_scene(dimmed_scene, dry_run=False))
finally:
    fx_seam.apply_writes = _orig_apply_writes
check(dimmed_result["writes"][0]["config"]["brightness"] == 0.8,
      "the RETURNED/baselined writes stay unscaled — dry-run/live preview parity")
check(rc_fire_calls[0][0][0]["config"]["brightness"] == 0.4,
      "only the bytes actually sent through fx_seam carry the room's "
      "brightness multiplier")
check(rc_fire_calls[0][1] == 1500,
      "a scene with no entry_ramp_ms of its own falls back to the room's "
      "global_transition_ms — the ledfx_global_transition equivalent")
rc.save_room_controls(rc.RoomControlState())   # reset for later sections

# ── Ambient (services/ambient.py): the room bar's Ambient checkbox — a real
#    Hue takeover, freeze before REST write / REST fade before unfreeze,
#    Hue-only (WLED left running its normal show), state-only when dark,
#    a rejected REST write never counts as a success, and reconcile()
#    never reports "on"/"off" with nothing actually held ──────────────────
import httpx

from spectra.services import ambient
from spectra.services.live_host import live as live_stack

check(asyncio.run(ambient.reconcile(True, "#ff0000")) == {"status": "dark"},
      "ambient.reconcile no-ops (status 'dark') when SPECTRA doesn't own "
      "the live stack — this script never activates one, so this is the "
      "path every other check above implicitly exercises too")


def _hue_handler(calls, fail_light_put=False):
    # Tracks each light's actual state so a GET read-back reflects whether
    # a PUT really landed — ambient.reconcile()'s ON path now confirms
    # every hold this way (see spectra/services/ambient.py's module
    # docstring on the live defect this closed: a 2xx PUT only means the
    # bridge accepted the write, not that the bulb took it).
    state = {"on": {"on": False}, "dimming": {"brightness": 1.0},
            "color": {"xy": {"x": 0.3127, "y": 0.3290}}}

    def handler(request):
        path = request.url.path
        calls.append(("REST", request.method, path))
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [{"id": "e1", "owner": {"rid": "d1"}}]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [{"id": "l1", "owner": {"rid": "d1"}}]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [{"members": [
                {"service": {"rtype": "entertainment", "rid": "e1"}}]}]}]})
        if path == "/clip/v2/resource/light/l1" and request.method == "GET":
            return httpx.Response(200, json={"data": [dict(state, id="l1")]})
        if fail_light_put:
            return httpx.Response(400, json={"errors": [{"description": "bad xy"}]})
        body = json.loads(request.content)
        state.update({k: v for k, v in body.items() if k in ("on", "dimming", "color")})
        return httpx.Response(200, json={"data": []})
    return handler


class _FakeHueDevice:
    type = "hue"

    def __init__(self, ip, calls, fail_freeze=False):
        self.config = {"ip_address": ip, "entertainment_id": f"ent-{ip}", "username": "u"}
        self.calls = calls   # shared with the mock bridge handler below
        self.frozen = None
        self._fail_freeze = fail_freeze

    async def set_frozen(self, frozen):
        self.calls.append(("set_frozen", frozen))
        if self._fail_freeze:
            raise RuntimeError("bridge unreachable")
        self.frozen = frozen


class _FakeWledDevice:
    type = "wled"


class _FakeHost:
    def __init__(self, devices):
        self.devices = devices


def _call_index(calls, wanted):
    for i, c in enumerate(calls):
        if c == wanted:
            return i
    raise AssertionError(f"{wanted} not found in {calls}")


def _mock_bridge_client(calls, fail_light_put=False):
    handler = _hue_handler(calls, fail_light_put=fail_light_put)

    def factory(cfg):
        return httpx.AsyncClient(base_url=f"https://{cfg['ip_address']}",
                                 transport=httpx.MockTransport(handler))
    return factory


ambient._light_cache.clear()
bridge_calls = []
hue_dev = _FakeHueDevice("10.0.0.1", bridge_calls)
_orig_host = live_stack.host
_orig_bridge_client = ambient._bridge_client
_orig_transition_ms = ambient.AMBIENT_TRANSITION_MS
_orig_confirm_settle = ambient.AMBIENT_CONFIRM_SETTLE_MS
_orig_write_stagger = ambient.AMBIENT_WRITE_STAGGER_MS
_orig_retry_spacing = ambient.AMBIENT_RETRY_SPACING_MS
live_stack.host = _FakeHost({"hue-lights": hue_dev, "strip": _FakeWledDevice()})
ambient._bridge_client = _mock_bridge_client(bridge_calls)
# Skip the real hold-confirmation pacing sleeps for the spec run (module
# docstring: spaced-not-hammered pacing is proven properly in
# tests/test_ambient.py, not here).
ambient.AMBIENT_CONFIRM_SETTLE_MS = 0
ambient.AMBIENT_WRITE_STAGGER_MS = 0
ambient.AMBIENT_RETRY_SPACING_MS = 0
try:
    on_result = asyncio.run(ambient.reconcile(True, "#00ff00"))
    check(on_result == {"status": "on", "devices": ["hue-lights"],
                        "lights_set": 1, "lights_total": 1},
          "ambient ON holds every live Hue device at the chosen colour, "
          "READ BACK and confirmed from the bridge (not just accepted) — "
          "the WLED device is never touched (Hue-only, matching the "
          "legacy scope this ports)")
    freeze_i = _call_index(bridge_calls, ("set_frozen", True))
    put_i = _call_index(bridge_calls, ("REST", "PUT", "/clip/v2/resource/light/l1"))
    check(freeze_i < put_i,
          "freeze lands before the REST colour write — a live stream frame "
          "must never win the race against REST (legacy's own ordering)")

    bridge_calls.clear()
    ambient.AMBIENT_TRANSITION_MS = 0  # skip the real off-fade sleep for the spec run
    off_result = asyncio.run(ambient.reconcile(False, None))
    check(off_result == {"status": "off", "devices": ["hue-lights"]},
          "ambient OFF releases every held Hue device")
    check(hue_dev.frozen is False,
          "disable ends unfrozen — the room's live scene resumes on its "
          "own, no wake-scene step needed")
    fade_i = _call_index(bridge_calls, ("REST", "PUT", "/clip/v2/resource/light/l1"))
    unfreeze_i = _call_index(bridge_calls, ("set_frozen", False))
    check(fade_i < unfreeze_i,
          "the brightness-only off-fade lands before unfreezing — a soft "
          "handoff, not a hard cut")

    ambient._light_cache.clear()
    rejecting_calls = []
    rejecting_dev = _FakeHueDevice("10.0.0.2", rejecting_calls)
    live_stack.host = _FakeHost({"hue-lights": rejecting_dev})
    ambient._bridge_client = _mock_bridge_client(rejecting_calls, fail_light_put=True)
    rejected_result = asyncio.run(ambient.reconcile(True, "#ff0000"))
    check(rejected_result["status"] == "partial" and rejected_result["lights_set"] == 0
          and rejected_result["unconfirmed"] == ["l1"],
          "a Hue CLIP v2 4xx body is valid JSON but must NOT count as a "
          "successful write — raise_for_status is the gate legacy's own "
          "status_code < 400 check made explicit (the vendored "
          "HueDevice._hue_request has no such gate — see the module "
          "docstring on why this module talks to the bridge directly). "
          "It stays unconfirmed by name through every bounded retry too — "
          "never a false 'on'")

    ambient._light_cache.clear()
    dead_dev = _FakeHueDevice("10.0.0.3", [], fail_freeze=True)
    live_stack.host = _FakeHost({"dead": dead_dev})
    failed_result = asyncio.run(ambient.reconcile(True, "#ff0000"))
    check(failed_result == {"status": "failed", "devices": [], "lights_set": 0},
          "when every live Hue device fails, reconcile reports 'failed' — "
          "never a false 'on' with nothing actually held (the exact "
          "failure shape this feature exists to stop reporting)")
finally:
    live_stack.host = _orig_host
    ambient._bridge_client = _orig_bridge_client
    ambient.AMBIENT_TRANSITION_MS = _orig_transition_ms
    ambient.AMBIENT_CONFIRM_SETTLE_MS = _orig_confirm_settle
    ambient.AMBIENT_WRITE_STAGGER_MS = _orig_write_stagger
    ambient.AMBIENT_RETRY_SPACING_MS = _orig_retry_spacing

# ── Force Scene (legacy Now Playing control, ported verbatim): redirects
#    every automatic scene pick at the one choke point, scene_sequencer.
#    fire_scene_by_id — the sequencer's own rolls and trigger_engine's
#    fire_scene action both call it ──────────────────────────────────────────
from spectra.services.scene_sequencer import fire_scene_by_id

fs_requested = SceneV2(name="FS Requested")
fs_held = SceneV2(name="FS Held")
scene_store.save(fs_requested)
scene_store.save(fs_held)
fs_fired: list[str] = []

_orig_fire_scene = scene_compiler.fire_scene


async def _fake_fire_scene(scene, *, intensity=0.5, color_set=None,
                           dry_run=True, rng=None):
    fs_fired.append(scene.id)
    return {"dry_run": dry_run, "intensity": intensity, "writes": [],
            "resolved_bindings": {}, "dice_rolls": {}}

scene_compiler.fire_scene = _fake_fire_scene
from spectra.services import dwell as _fs_dwell   # reset between steps below —
# this section fires two DIFFERENT scenes back to back; the minimum-dwell
# gate (2026-08-20) would otherwise defer the second one, since it's an
# unrelated mechanism this section never means to exercise.
try:
    _fs_dwell.reset()
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id=fs_held.id))
    asyncio.run(fire_scene_by_id(fs_requested.id, intensity=0.6))
    check(fs_fired[-1] == fs_held.id,
          "Force Scene: the pinned scene fires instead of the one requested "
          "— the sequencer/trigger caller's own intensity still passes through")

    _fs_dwell.reset()
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="missing-scene"))
    asyncio.run(fire_scene_by_id(fs_requested.id, intensity=0.6))
    check(fs_fired[-1] == fs_requested.id,
          "Force Scene: a pinned id pointing at a missing scene is treated "
          "as unset, same as legacy's missing/non-scene event guard")

    _fs_dwell.reset()
    rc.save_room_controls(rc.RoomControlState(force_scene_enabled=False))
    asyncio.run(fire_scene_by_id(fs_requested.id, intensity=0.6))
    check(fs_fired[-1] == fs_requested.id,
          "Force Scene disabled: no redirect")

    # 2026-08-18 fix: the redirect above is passive — it only fires when
    # something else was already about to pick a scene. Enabling never
    # DID that on its own, so on a song with no triggers (his live
    # report) nothing ever fired. reconcile_force_scene_if_changed must
    # fire the pin immediately, right on the enabling edit.
    _fs_dwell.reset()
    fs_prev = rc.RoomControlState(force_scene_enabled=False)
    fs_next = rc.RoomControlState(force_scene_enabled=True, force_scene_scene_id=fs_held.id)
    rc.save_room_controls(fs_next)
    fs_result = asyncio.run(rc.reconcile_force_scene_if_changed(fs_prev, fs_next))
    check(fs_fired[-1] == fs_held.id and fs_result == {
        "status": "fired", "scene_id": fs_held.id, "scene_name": fs_held.name},
        "Force Scene: enabling the pin fires it immediately, not just on the "
        "next automatic pick — his own report was silence, not a wrong scene")

    fs_no_pin_prev = rc.RoomControlState(force_scene_enabled=False)
    fs_no_pin_next = rc.RoomControlState(force_scene_enabled=True, force_scene_scene_id=None)
    fs_no_pin_result = asyncio.run(rc.reconcile_force_scene_if_changed(fs_no_pin_prev, fs_no_pin_next))
    check(fs_no_pin_result == {"status": "skipped", "reason": "no scene pinned"},
          "Force Scene: enabling with nothing pinned states the reason instead "
          "of silently doing nothing")

    fs_unrelated_prev = rc.RoomControlState(force_scene_enabled=True,
                                            force_scene_scene_id=fs_held.id)
    fs_unrelated_next = fs_unrelated_prev.model_copy(update={"brightness_multiplier": 0.4})
    fs_fired_before_unrelated = len(fs_fired)
    fs_unrelated_result = asyncio.run(
        rc.reconcile_force_scene_if_changed(fs_unrelated_prev, fs_unrelated_next))
    check(fs_unrelated_result is None and len(fs_fired) == fs_fired_before_unrelated,
          "Force Scene: an unrelated field re-save with the pin unchanged "
          "does not re-fire")
finally:
    scene_compiler.fire_scene = _orig_fire_scene
    _fs_dwell.reset()
rc.save_room_controls(rc.RoomControlState())   # reset for later sections

# ── MINIMUM DWELL (2026-08-20, data/plan-make-dwell-meaningful-under-the-
#    rea-4p73/{report,HIS-DECISION}.md): a per-scene minimum hold, seconds
#    over intensity, gated at the SAME fire_scene_by_id choke point Force
#    Scene above already proves — see spectra/services/dwell.py ─────────────
from spectra.services import dwell, fire_history as fh
from spectra.models.scene import CurveAttachment as _CurveAttachment

dwell.reset()
dw_a = SceneV2(name="Dwell A")
dw_b = SceneV2(name="Dwell B", dwell_curve=_CurveAttachment(
    inline_points=[{"x": 0.0, "y": 4.0}, {"x": 1.0, "y": 4.0}]))
scene_store.save(dw_a)
scene_store.save(dw_b)

dw_fired: list[tuple] = []
dw_update_calls: list[float] = []

async def _dw_fake_fire_scene(scene, *, intensity=0.5, color_set=None,
                              dry_run=True, rng=None):
    dw_fired.append((scene.id, intensity))
    return {"dry_run": dry_run, "intensity": intensity, "writes": []}

async def _dw_fake_update_event(intensity):
    dw_update_calls.append(intensity)
    return {"result": "no_update_kind"}

from spectra.services import engine as _engine_mod

_orig_fire_scene2 = scene_compiler.fire_scene
_orig_update_event = _engine_mod.fire_scene_update_event
scene_compiler.fire_scene = _dw_fake_fire_scene
_engine_mod.fire_scene_update_event = _dw_fake_update_event
try:
    check(dwell.dwell_seconds(dw_a, 0.0) == 16.0
          and dwell.dwell_seconds(dw_a, 1.0) == 4.0
          and dwell.dwell_seconds(dw_a, 0.5) == 10.0,
          "unset dwell_curve resolves to his exact default: 16s @0, 4s @1, linear")

    asyncio.run(fire_scene_by_id(dw_a.id, intensity=0.0))
    dw_deferred = asyncio.run(fire_scene_by_id(dw_b.id, intensity=0.7))
    check(dw_fired == [(dw_a.id, 0.0)],
          "a scene requested inside the active scene's own dwell window "
          "never reaches scene_compiler.fire_scene")
    check(dw_update_calls == [0.7],
          "the deferral calls the update-effect seam at the REQUEST's own "
          "intensity, not the active scene's")
    check(dw_deferred["skipped"] == "dwell" and dw_deferred["scene_id"] == dw_b.id
          and dw_deferred["remaining_dwell_s"] > 0,
          "the deferred result names what happened, never a bare {} silence")
    check(fh.load_all()["deferred"][dw_b.id]["count"] == 1,
          "a deferral is RECORDED — fire_history's own bucket for it")

    # Answer A: no reset on an update effect — a second deferred request
    # must not touch the latch at all.
    dwell_seconds_before = dwell.status()["dwell_seconds"]
    asyncio.run(fire_scene_by_id(dw_b.id, intensity=1.0))
    check(dwell.active_scene_id() == dw_a.id
          and dwell.status()["dwell_seconds"] == dwell_seconds_before,
          "answer A: a deferral never resets or re-latches the active "
          "scene's own dwell window")
    # Answer B: the intensity is LATCHED at entry, not re-evaluated.
    check(dwell.status()["dwell_seconds"] == 16.0,
          "answer B: dw_a fired at intensity 0.0 (16s) — a later deferred "
          "request at intensity 1.0 must not shrink it to 4s")

    # Force Scene still wins over an active dwell, but names it.
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id=dw_b.id))
    dw_forced = asyncio.run(fire_scene_by_id(dw_a.id, intensity=0.5))
    check(dw_fired[-1] == (dw_b.id, 0.5) and dw_forced.get("overrode_dwell") is True,
          "Force Scene fires through an active dwell but NAMES the "
          "override — the disabled-scene gate's own pattern")
    check(dwell.active_scene_id() == dw_b.id,
          "a Force-Scene fire is a REAL fire — it re-latches like any other")
finally:
    scene_compiler.fire_scene = _orig_fire_scene2
    _engine_mod.fire_scene_update_event = _orig_update_event
    dwell.reset()
    rc.save_room_controls(rc.RoomControlState())   # reset for later sections

# ── item-8 CANONICAL shape: a band SELECTS AND SCALES its named kinds ────────
# The owner's example, executed: the top band fires "Slam" + "Colour Roll"
# at ×1.3 — the param spike lands at baseline + (declared − baseline)·1.3
# (registry-clamped), the envelope at 1 + (gain − 1)·1.3, the colour roll
# still routes the shipped selector, and MOMENTARY means both spikes
# return: the baselines never move.
canon = SceneV2(**{**{k: v for k, v in resp_base.items()
                      if k not in ("responses", "id")},
                   "flare_kinds": [
    {"name": "Slam", "type": "momentary",
     "params": {"twist": 0.9}, "gain": 1.5},
    {"name": "Colour Roll", "type": "drift_jump", "jump": "color_set"},
], "responses": {"flare": {"bands": [
    {"intensity_min": 0.8, "intensity_max": 1.0,
     "kinds": {"Slam": 1.3, "Colour Roll": 1.3}}]}}})
canon_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(canon, FireContext(0.5, rng=Random(3))))
room_box[0] = cj.RoomColorState(wheel_position_deg=220.0,
                                active_set_id="set-blue")
conductor2.on_scene_fire(canon, canon_writes)
eligible_box[0] = {"set-red": 10.0}
exec2.writes.clear()
record = asyncio.run(responder.on_event("flare", 0.9))
by_kind = {k["name"]: k for k in record["kinds"]}
check(set(by_kind) == {"Slam", "Colour Roll"}
      and by_kind["Slam"]["scale"] == 1.3
      and by_kind["Colour Roll"]["scale"] == 1.3,
      "the band SELECTS its named kinds and states their ×1.3 scale")
tw_hi = float(device_model.get_param_meta("radial", "twist")["max"])
expected_twist = min(tw_hi, 0.25 + (0.9 - 0.25) * 1.3)
twist_spike = [w for w in exec2.writes if w["kind"] == "glide"
               and "twist" in w["params"]][0]
check(abs(twist_spike["params"]["twist"] - expected_twist) < 1e-9
      and twist_spike["duration_ms"] == DICE_REROLL_GLIDE_MS,
      f"scale ×1.3 moves the spike PAST the declared value along the "
      f"baseline excursion, registry-clamped ({expected_twist:g}); twist "
      f"is registry smooth=true so the spike itself eases in, not a jump")
peak = max(0.0, min(1.0, 0.65 * (1.0 + 0.5 * 1.3)))
check(by_kind["Slam"]["gain_envelope"][0]["peak"] == round(peak, 4),
      "gain scales by excursion: 1 + (gain − 1)·1.3, clamped at full")
check(record["color_jump"]["result"] == "jumped"
      and record["color_jump"]["picked_id"] == "set-red"
      and record["color_jump"]["ramp_ms"] == 150,
      "the colour roll routes the SHIPPED selector; scale-steered "
      "intensity (0.9×1.3 → 1.0) lands the ramp at its hard end (150 ms)")
st = conductor2.virtuals["v-m1"]
check(st.param_baseline["twist"] == 0.25,
      "MOMENTARY at any scale never moves the param baseline")
check(st.brightness_baseline == 0.9,
      "the colour roll in the same surge CARRIES the pick's brightness")
asyncio.run(responder.flush_releases())
back = [w for w in exec2.writes if w["kind"] == "glide"
        and "twist" in w["params"]][-1]
check(back["params"]["twist"] == 0.25
      and back["params"]["brightness"] == 0.9,
      "the release returns the spike to the baseline AS CARRIED NOW — "
      "twist to its own, brightness to the colour roll's landing")

# ── LANES: pick-one-per-lane pools (owner ask 2026-08-21 — his words: "all
# lanes fire together, but pick one action within each lane... more similar
# to spotfx... randomly pick one of them by some kind of weighting. For
# now, just even weights" — the legacy MorphLane/_pick_morph_lanes shape on
# FlareBand.kind_lanes, resolved fresh EVERY fire by scene_response.
# resolve_lane_picks; a kind with no entry is its own one-member lane, so a
# band with no pools — every band predating the field — fires everything,
# unchanged). ─────────────────────────────────────────────────────────────
lane_kind_hi = {"name": "Twist High", "type": "momentary", "jump": None,
                "params": {"twist": {"mode": "absolute", "value": 0.9}},
                "gain": 1.0, "hold_ms": None}
lane_kind_lo = {"name": "Twist Low", "type": "momentary", "jump": None,
                "params": {"twist": {"mode": "absolute", "value": 0.4}},
                "gain": 1.0, "hold_ms": None}

unpooled = SceneV2(**{**{k: v for k, v in resp_base.items()
                         if k not in ("responses", "id", "flare_kinds")},
                      "flare_kinds": [lane_kind_hi, lane_kind_lo],
                      "responses": {"flare": {"bands": [
                          {"intensity_min": 0.0, "intensity_max": 1.0,
                           "kinds": {"Twist High": 1.0, "Twist Low": 1.0}},
                      ]}}})
conductor2.on_scene_fire(unpooled, scene_compiler.compile_scene(
    scene_compiler.resolve_scene(unpooled, FireContext(0.5, rng=Random(3)))))
exec2.writes.clear()
rec_all = asyncio.run(responder.on_event("flare", 0.5))
check([k["name"] for k in rec_all["kinds"]] == ["Twist High", "Twist Low"]
      and "lane_picks" not in rec_all,
      "THE BLAST RADIUS: a multi-kind band with no kind_lanes fires EVERY "
      "kind, in kinds order, with no lane_picks record — byte-identical to "
      "the pre-lanes engine (25 of his 28 real bands are multi-kind)")
asyncio.run(responder.flush_releases())

pooled = SceneV2(**{**{k: v for k, v in resp_base.items()
                       if k not in ("responses", "id", "flare_kinds")},
                    "flare_kinds": [lane_kind_hi, lane_kind_lo],
                    "responses": {"flare": {"bands": [
                        {"intensity_min": 0.0, "intensity_max": 1.0,
                         "kinds": {"Twist High": 1.0, "Twist Low": 1.0},
                         "kind_lanes": {"Twist High": "colour",
                                        "Twist Low": "colour"}},
                    ]}}})
conductor2.on_scene_fire(pooled, scene_compiler.compile_scene(
    scene_compiler.resolve_scene(pooled, FireContext(0.5, rng=Random(3)))))
lane_winners: set = set()
lane_write_ok = True
for _ in range(24):
    exec2.writes.clear()
    rec_pool = asyncio.run(responder.on_event("flare", 0.5))
    fired = [k["name"] for k in rec_pool["kinds"]]
    if len(fired) != 1 or rec_pool.get("lane_picks") != [{
            "lane": "colour", "picked": fired[0],
            "pool": ["Twist High", "Twist Low"]}]:
        lane_write_ok = False
        break
    spike = [w for w in exec2.writes if w["kind"] == "glide"
             and "twist" in w["params"]][0]
    base_tw = conductor2.virtuals["v-m1"].param_baseline["twist"]
    want = 0.9 if fired[0] == "Twist High" else 0.4
    if abs(spike["params"]["twist"]
           - (base_tw + (want - base_tw))) > 1e-9:
        lane_write_ok = False
        break
    lane_winners.add(fired[0])
    asyncio.run(responder.flush_releases())
    if lane_winners == {"Twist High", "Twist Low"}:
        break
check(lane_write_ok and lane_winners == {"Twist High", "Twist Low"},
      "a pooled lane fires exactly ONE member per fire (the write matches "
      "the winner, the fire record names pick + pool), and the pick is "
      "re-resolved fresh every fire — both members win across fires")

# ── STAR's two reverse flares (owner ask 2026-08-17, mechanism switched to
# the FLIP control 2026-08-20, his words: "use the flip control for star"):
# permanent + 500ms momentary, both now targeting `spin_sign` (radial's
# "Flip") instead of driving `spin` negative directly. spin_sign is
# translated by scene_response._compute_param_moves onto the REAL param
# (spin) with only its sign changed, magnitude preserved, forced INSTANT
# (jump, never glide) on both departure and release — see spin_sign's own
# registry note and the module docstring. Proven here against the SAME
# synthetic radial fixture (resp_base's device shape), not live storage —
# scripts/update_star_reverse_flares_to_flip.py carries the identical kind
# shapes.
reverse_direction_kind = {
    "name": "Reverse Direction", "type": "permanent", "jump": None,
    "params": {"spin_sign": {"mode": "absolute", "value": 0.0}}, "gain": 1.0,
    "hold_ms": None,
}
reverse_momentary_kind = {
    "name": "Reverse Momentarily (500ms)", "type": "momentary", "jump": None,
    "params": {"spin_sign": {"mode": "absolute", "value": 0.0}}, "gain": 1.0,
    "hold_ms": 500,
}
check(FlareKind(**reverse_direction_kind).jump is None
      and FlareKind(**reverse_momentary_kind).jump is None,
      "neither reverse kind carries a jump field — structurally cannot "
      "re-roll STAR's dice-bound star/edges (FlareKind._shape forbids "
      "jump on a non-drift_jump kind)")

rev = SceneV2(**{**{k: v for k, v in resp_base.items()
                    if k not in ("responses", "id", "flare_kinds")},
                 "flare_kinds": [reverse_momentary_kind, reverse_direction_kind],
                 "responses": {"flare": {"bands": [
                     {"intensity_min": 0.0, "intensity_max": 0.5,
                      "kinds": {"Reverse Momentarily (500ms)": 1.0}},
                     {"intensity_min": 0.5, "intensity_max": 1.0,
                      "kinds": {"Reverse Direction": 1.0}},
                 ]}}})
rev_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(rev, FireContext(0.5, rng=Random(3))))
conductor2.on_scene_fire(rev, rev_writes)
spin_before = conductor2.virtuals["v-m1"].param_baseline.get("spin")

exec2.writes.clear()
rec_mom = asyncio.run(responder.on_event("flare", 0.3))
check({k["name"] for k in rec_mom["kinds"]} == {"Reverse Momentarily (500ms)"},
      "Reverse Momentarily (500ms) is the only kind attached at 0.3")
mom_spike = [w for w in exec2.writes if "spin" in w["params"]]
check(len(mom_spike) == 3 and all(w["kind"] == "jump" for w in mom_spike)
      and all(w["params"]["spin"] == -abs(spin_before) for w in mom_spike)
      and all(w["duration_ms"] == JUMP_MS for w in mom_spike),
      "the 500ms reverse JUMPS to -spin_before (the FLIP: magnitude "
      "preserved, sign flipped, no interpolation) — spin is registry "
      "smooth=true, so an ordinary glide here would tween through zero, "
      "the exact freeze the flip control was chosen to avoid")
check(all("spin_sign" not in w["params"] for w in exec2.writes),
      "the write lands on spin itself, never the (structurally inert) "
      "spin_sign key — radial.py's CONFIG_SCHEMA has no such key")
check(conductor2.virtuals["v-m1"].param_baseline.get("spin") == spin_before,
      "MOMENTARY reverse never moves spin's baseline")
check(all("star" not in w["params"] and "edges" not in w["params"]
          for w in exec2.writes),
      "the momentary reverse touches only spin — no star/edges write of "
      "any kind lands, so it cannot reintroduce the dice-reroll snap")
asyncio.run(responder.flush_releases())
mom_release = [w for w in exec2.writes if w["kind"] == "jump"
              and "spin" in w["params"]][-1]
check(mom_release["params"]["spin"] == spin_before
      and mom_release["duration_ms"] == JUMP_MS,
      "the 500ms reverse RELEASES back to spin's carried baseline via a "
      "JUMP too, not a glide — proves the return half of 'no pause': a "
      "glide back would re-cross zero exactly like the bug this flare "
      "exists to fix, just on the way home instead of the way out")

exec2.writes.clear()
rec_perm = asyncio.run(responder.on_event("flare", 0.7))
check({k["name"] for k in rec_perm["kinds"]} == {"Reverse Direction"},
      "Reverse Direction is the only kind attached at 0.7")
perm_writes = [w for w in exec2.writes if "spin" in w["params"]]
check(len(perm_writes) == 3 and all(w["kind"] == "jump" for w in perm_writes)
      and all(w["params"]["spin"] == -abs(spin_before) for w in perm_writes),
      "Reverse Direction JUMPS spin to -spin_before, same forced-instant "
      "transport as the 500ms kind")
check(conductor2.virtuals["v-m1"].param_baseline.get("spin")
      == -abs(spin_before),
      "Reverse Direction CARRIES — the sign-flipped value becomes spin's "
      "new baseline, matching the model's own permanent-kind contract")
check(all("star" not in w["params"] and "edges" not in w["params"]
          for w in exec2.writes),
      "Reverse Direction touches only spin too")

# ── magnitude preservation is DERIVED, not a hardcoded -0.55: prove it
# against a differently-baselined spin, or the assertions above could pass
# by coincidence (his real scene's own baseline happens to be 0.55) ────────
rev2 = SceneV2(**{**{k: v for k, v in resp_base.items()
                     if k not in ("responses", "id", "flare_kinds", "devices")},
                  "devices": [{**resp_base["devices"][0],
                               "params": {**resp_base["devices"][0]["params"],
                                          "spin": 0.2}}],
                  "flare_kinds": [reverse_direction_kind],
                  "responses": {"flare": {"bands": [
                      {"intensity_min": 0.0, "intensity_max": 1.0,
                       "kinds": {"Reverse Direction": 1.0}}]}}})
exec_mag = RecordingExecutor()
cond_mag = DriftConductor(executor=exec_mag, drift_profiles=lambda: {},
                          curve_profiles=lambda: {},
                          room_load=lambda: cj.RoomColorState(),
                          room_save=lambda st: None,
                          set_position=lambda sid: None)
resp_mag = ResponseEngine(conductor=cond_mag, executor=exec_mag, rng=Random(1),
                          sequencer_config=lambda: SequencerConfig(),
                          room_load=lambda: cj.RoomColorState(),
                          room_save=lambda st: None)
rev2_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(rev2, FireContext(0.5, rng=Random(3))))
cond_mag.on_scene_fire(rev2, rev2_writes)
check(cond_mag.virtuals["v-m1"].param_baseline.get("spin") == 0.2,
      "fixture sanity: this scene's spin baseline is 0.2, not 0.55")
asyncio.run(resp_mag.on_event("flare", 0.7))
low_mag_writes = [w for w in exec_mag.writes if "spin" in w["params"]]
check(low_mag_writes and all(w["params"]["spin"] == -0.2
                             for w in low_mag_writes),
      "the flip lands -0.2 here, NOT -0.55 — magnitude tracks spin's own "
      "current carried value, it is never a fixed authored number")

# ── the collision question: can the flip and a plain signed write to spin
# disagree and leave it stuck the wrong way? No — both land on the exact
# SAME (vid, 'spin') carry slot, so they compose by ordinary last-write-
# wins semantics, the same as any two permanent kinds sharing a target
# param; there is no second, independently-tracked "flip bit" that could
# go stale. Proven directly: fire Reverse Direction (flips to negative),
# then an ordinary absolute `spin` patch (mirrors STAR's own untouched
# "Flare/Drop patch" kinds, which always author a POSITIVE spin) — the
# later fire wins outright, exactly as the carry contract already
# guarantees for every other param collision in this engine ─────────────
plain_patch_kind = {
    "name": "Flare patch 0.7–1 (untouched, synthetic)", "type": "permanent",
    "jump": None, "params": {"spin": {"mode": "absolute", "value": 0.55}},
    "gain": 1.0, "hold_ms": None,
}
collide = SceneV2(**{**{k: v for k, v in resp_base.items()
                        if k not in ("responses", "id", "flare_kinds")},
                     "flare_kinds": [reverse_direction_kind, plain_patch_kind],
                     "responses": {"flare": {"bands": [
                         {"intensity_min": 0.0, "intensity_max": 1.0,
                          "kinds": {"Reverse Direction": 1.0}}]}}})
exec_collide = RecordingExecutor()
cond_collide = DriftConductor(executor=exec_collide, drift_profiles=lambda: {},
                              curve_profiles=lambda: {},
                              room_load=lambda: cj.RoomColorState(),
                              room_save=lambda st: None,
                              set_position=lambda sid: None)
resp_collide = ResponseEngine(conductor=cond_collide, executor=exec_collide,
                              rng=Random(1),
                              sequencer_config=lambda: SequencerConfig(),
                              room_load=lambda: cj.RoomColorState(),
                              room_save=lambda st: None)
collide_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(collide, FireContext(0.5, rng=Random(3))))
cond_collide.on_scene_fire(collide, collide_writes)
asyncio.run(resp_collide.on_event("flare", 0.9))   # Reverse Direction fires
check(cond_collide.virtuals["v-m1"].param_baseline.get("spin") < 0,
      "Reverse Direction alone leaves spin negative")
# The plain patch kind is not attached to any band here (STAR's real scene
# never attaches it alongside Reverse Direction on the same band either —
# this is a direct-call proof of the carry mechanics, not a re-enactment
# of STAR's own band layout), so fire it via fire_kind() the same way
# Sonic's flare preview does.
plain_kind_obj = FlareKind(**plain_patch_kind)
asyncio.run(resp_collide.fire_kind(plain_kind_obj, 1.0))
check(cond_collide.virtuals["v-m1"].param_baseline.get("spin") == 0.55,
      "a later plain absolute write to spin wins outright — LAST WRITE "
      "WINS, the same carry semantics every other param collision in "
      "this engine already has; there is no separate spin_sign state "
      "left pointing 'reversed' that could disagree with spin's own "
      "value and strand STAR running the wrong way")

# ── the bridge: classification, feeds, deferral split, RAW section energy ────
from spectra.services import analysis_reader
from spectra.services.bridge import SpotEffectsBridge, classify_event

check(classify_event("charge") == "charge"
      and classify_event("lull") == "lull"
      and classify_event("drop") == "drop",
      "bridge classifies the three phase classes")
check(all(classify_event(t) is None for t in
          ("scene_update", "update_scene", "reset_scene", "scene_group")),
      "scene-family fires are scene CHANGES, never surges")
check(all(classify_event(t) == "flare" for t in
          ("single", "sequence", "beat_sequence", "morph_set", "composite",
           "shape_flare", "color_flare", "combo_flare")),
      "every other trigger fire is a flare (the musical accent)")

scfg.AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
(scfg.AUDIO_SHAPES_DIR / "song1.json").write_text(json.dumps(
    {"spotify_uri": "spotify:track:x1"}))
(scfg.AUDIO_SHAPES_DIR / "song1.librosa.json").write_text(json.dumps({
    "spotify_uri": "spotify:track:x1",
    "librosa_offset_ms": 75308324,   # the poisoned offset — must be IGNORED
    "sections": [
        {"start_ms": 0, "end_ms": 10000, "energy_rms": 0.25},
        {"start_ms": 10000, "end_ms": 20000, "energy_rms": 0.9},
    ]}))
scfg.TRAINING_PROFILES_FILE.write_text(json.dumps({
    "p1": {"name": "House", "genres": ["house"], "is_default": False},
    "p2": {"name": "Default", "genres": [], "is_default": True}}))

events: list[tuple] = []
uris: list = []


async def on_evt(cls_, inten):
    events.append((cls_, inten))


async def on_uri(uri):
    uris.append(uri)

clock_box = [50.0]
br = SpotEffectsBridge(on_response_event=on_evt, on_track_uri=on_uri,
                       clock=lambda: clock_box[0])
state_msg = {"type": "state", "paused": False, "dinner_party_mode": False,
             "ambient_mode_enabled": False, "last_scene_id": "legacy-9",
             "track": {"spotify_uri": "spotify:track:x1", "title": "T",
                       "progress_ms": 12000, "is_playing": True,
                       "genres": ["deep house"]}}
asyncio.run(br.handle_message(state_msg))
check(uris == ["spotify:track:x1"] and br.trigger_scene_id() == "legacy-9",
      "state broadcast feeds the sequencer's transition + trigger observation")
clock_box[0] = 53.0   # 3 s later, playing → position interpolates to 15 000
check(br.track_position_ms() == 15000,
      "track position interpolates from the broadcast while playing")
check(br.intensity() == 0.9,
      "intensity = section energy at the RAW position (offset ignored)")
check(br.genre_bucket() == "House",
      "genre bucket matches training profiles by substring")
asyncio.run(br.handle_message({"type": "trigger_fired", "event_type": "charge",
                               "event_name": "Build", "intensity": 0.82}))
asyncio.run(br.handle_message({"type": "trigger_fired",
                               "event_type": "scene_update",
                               "event_name": "Scene", "intensity": 0.5}))
asyncio.run(br.handle_message({"type": "trigger_fired", "event_type": "single",
                               "event_name": "Hit", "intensity": 0.4}))
check(events == [("charge", 0.82), ("flare", 0.4)]
      and br.counts["scene_changes"] == 1,
      "trigger fires classify and feed the response engine with intensity")
asyncio.run(br.handle_message({**state_msg, "dinner_party_mode": True}))
check(br.conductor_deferral() == "dinner_party"
      and br.sequencer_deferral() == "dinner_party",
      "broadcast flags drive both deferral feeds")
br.force_scene = True
asyncio.run(br.handle_message(state_msg))
check(br.conductor_deferral() is None
      and br.sequencer_deferral() == "force_scene",
      "Force Scene defers the sequencer only — drift keeps running")
check(analysis_reader.section_energy_at("spotify:track:nope", 0) is None
      and SpotEffectsBridge(clock=lambda: 0.0).intensity() is None,
      "no analysis / no track → None (callers hold the stated 0.5 neutral)")

# ── the bridge: xcorr sync port (shape_offset_ms / effective_position_ms) ────
check(br.shape_offset_ms() is None and br.effective_position_ms() == br.track_position_ms(),
      "no 'timing' broadcast yet → offset unknown, effective position == raw (today's pre-port behaviour)")
clock_box[0] = 60.0
asyncio.run(br.handle_message({**state_msg, "timing": {
    "effective_offset_ms": 7052, "shape_offset_ms": 7052,
    "shape_offset_quality": 0.93, "ledfx_trigger_buffer_ms": -800,
    "ledfx_rtt_ms": 0}}))
raw = br.track_position_ms()
check(br.shape_offset_ms() == 7052,
      "shape_offset_ms reads the audio-alignment term off the broadcast timing sibling")
check(br.effective_position_ms() == raw + 7052,
      "effective_position_ms = raw + shape_offset_ms, spot-effects' own effective_now formula — "
      "NOT the full effective_offset_ms (ledfx buffer/rtt don't apply to SPECTRA's own write path)")
asyncio.run(br.handle_message({**state_msg, "timing": None}))
check(br.shape_offset_ms() is None,
      "a later state broadcast with no timing (older spot-effects) clears back to unknown, not stale")

# ── production sequencer defaults read the bridge singleton ──────────────────
from spectra.services import engine as engine_mod
from spectra.services.scene_sequencer import scene_sequencer as seq_singleton
engine_mod.bridge.paused = True
check(seq_singleton._default_deferral() == "paused",
      "sequencer deferral default reads the engine bridge")
engine_mod.bridge.paused = False
check(seq_singleton._default_intensity() == 0.5,
      "sequencer intensity default: bridge silent → 0.5 neutral (stated)")
check(seq_singleton.status()["bridge_connected"] is False,
      "sequencer status reports the real bridge connection state")

# ── engine API: status + dark event injection + baseline adoption ────────────
est = client.get("/api/engine/status").json()
check(est["increment"] == "S3" and est["dark"] is True
      and est["executor"]["mode"] == "recording"
      and est["light_ownership"] == "spot-effects"
      and "conductor" in est and "bridge" in est,
      "GET /api/engine/status serves the whole engine surface, dark, "
      "ownership at the shipped default")
check(client.post("/api/engine/event",
                  json={"class": "sparkle"}).status_code == 422,
      "unknown response class → 422")
rb = client.post(f"/api/engine/baseline/{scene.id}",
                 json={"intensity": 0.9}).json()
check(rb["status"] == "baselined" and rb["virtuals"] == 3,
      "POST /api/engine/baseline adopts a scene without firing anything")
ev = client.post("/api/engine/event",
                 json={"class": "flare", "intensity": 0.4}).json()
check(ev["result"] in ("applied", "no_band", "no_class"),
      "POST /api/engine/event injects a dark response event")
app_status = client.get("/api/status").json()
check(app_status["increment"] == "S3"
      and app_status["light_ownership"] == "spot-effects",
      "app status reports increment S3, ownership at the shipped default")

# ── Mid Group: the seven scenes behave per their rebuild-table intent ────────
live_scenes_file = Path(__file__).parent.parent / "storage" / "spectra" / "scenes.json"
check(live_scenes_file.exists(), "seeded SPECTRA scenes present (S1 output)")
live = {v["name"]: SceneV2(**v)
        for v in json.loads(live_scenes_file.read_text()).values()}
SEVEN = ["Black Hole V2", "Orbits V2", "STAR", "Fireworks V2",
         "Squiggles V2", "Dancers V2", "Eye V2"]   # STAR = renamed Mid Star V2
check(all(name in live for name in SEVEN), "all seven Mid Group scenes seeded")
check(all(any(k.jump == "color_set" for k in live[n].flare_kinds)
          and len(live[n].responses["flare"].bands) == 3 for n in SEVEN),
      "each carries a 3-band flare class with the colour-set jump "
      "(loaded as the auto-named Colour Jump kind)")

def resolved_params(name: str, effect_type: str, intensity, seed: int = 1):
    resolved = scene_compiler.resolve_scene(
        live[name], FireContext(intensity, rng=Random(seed)))
    return next(d.params for d in resolved.devices
                if d.effect_type == effect_type)


seen_pairs = set()
for seed in range(200):
    p = resolved_params("STAR", "radial", 0.5, seed)
    seen_pairs.add((p["star"], p["edges"]))
check(seen_pairs == {(0.3, 6), (-0.3, 3), (0.0, 5)},
      "STAR: raw seeder output still carries the pre-freeze dice pairs "
      "(the S1 seeder ports the legacy world verbatim — see the STAR "
      "edges freeze section below for the migrated, deployed behaviour)")

styles = {inten: resolved_params("Dancers V2", "dancer", inten)["dance_type"]
          for inten in (0.2, 0.5, 0.8)}
check(styles == {0.2: "ballet", 0.5: "cowboy", 0.8: "kpop"},
      f"Dancers: intensity picks the dance style ({styles})")

flips = sum(resolved_params("Orbits V2", "orbits", 0.5, s)["reverse"]
            for s in range(200))
check(40 < flips < 160, f"Orbits: reverse flips ~50/50 per fire ({flips}/200)")

check(resolved_params("Black Hole V2", "blackhole", 1.0)["swirl"] == 6.0,
      "Black Hole: swirl rides the ⚡ map to its ceiling at intensity 1.0")
check(resolved_params("Fireworks V2", "fireworks", 1.0)["burst_size"] == 14,
      "Fireworks: burst_size maps to 14 at full intensity (integer-coerced)")
check(resolved_params("Squiggles V2", "squiggles", 0.0)["beat_burst"] == 1.0,
      "Squiggles: beat_burst maps to its floor at intensity 0")

# The responses ANIMATE: each scene's flare bands execute against the
# engine — the top band's patch lands as jumps on the scene's virtuals
# (one fake virtual per device entry; name-broadcast targeting decides
# which entries each key reaches).
for name in SEVEN:
    sc = live[name]
    resolved_sc = scene_compiler.resolve_scene(sc,
                                               FireContext(0.5, rng=Random(4)))
    fake_writes = [
        {"virtual_id": f"v-{name}-{i}", "effect_type": dev.effect_type,
         "config": dict(dev.params), "entry_id": dev.id,
         "color_mode": dev.color.mode}
        for i, dev in enumerate(resolved_sc.devices)]
    exec3 = RecordingExecutor()
    cond3 = DriftConductor(executor=exec3, drift_profiles=lambda: {},
                           curve_profiles=lambda: {},
                           room_load=lambda: cj.RoomColorState(),
                           room_save=lambda st: None,
                           set_position=lambda sid: None)
    cond3.on_scene_fire(sc, fake_writes)
    resp3 = ResponseEngine(conductor=cond3, executor=exec3, rng=Random(9),
                           sequencer_config=lambda: SequencerConfig(),
                           room_load=lambda: cj.RoomColorState(),
                           room_save=lambda st: None)
    top = max(sc.responses["flare"].bands, key=lambda b: b.intensity_max)
    rec = asyncio.run(resp3.on_event("flare", 0.97))
    declared3 = {k.name: k for k in sc.flare_kinds}
    top_patch = {}
    for kname in top.kinds:
        if declared3[kname].type == "permanent":
            top_patch.update(absolute_params(declared3[kname]))
    expected = {k: v for k, v in top_patch.items()
                if any(device_model.get_param_meta(d.effect_type, k)
                       for d in sc.devices)}
    landed = {}
    for w in exec3.writes:
        if w["kind"] in ("jump", "glide"):   # smooth params glide since 2026-08-17
            landed.update(w["params"])
    check(rec["result"] == "applied" and expected
          and all(landed.get(k) == v for k, v in expected.items()),
          f"{name}: top flare band executes its patch ({sorted(expected)})")

# Every live scene's AUTHORED response data survives migration verbatim:
# each raw band's patch is a permanent kind on that band, each non-neutral
# gain a momentary (pulse) or permanent kind, reroll/colour flags the
# shared drift-jump kinds — and nothing else was invented.
raw_live = json.loads(live_scenes_file.read_text())
verified = 0
for v in raw_live.values():
    sc = SceneV2(**v)
    declared = {k.name: k for k in sc.flare_kinds}
    for cls, spec_raw in (v.get("responses") or {}).items():
        loaded = sc.responses[cls]
        for braw, band in zip(spec_raw.get("bands", []), loaded.bands):
            patch = braw.get("param_patch") or {}
            if patch and not any(
                    declared[n].type == "permanent"
                    and absolute_params(declared[n]) == patch for n in band.kinds):
                raise SystemExit(f"FAIL: {v['name']}/{cls}: authored patch "
                                 f"{patch} lost in migration")
            gain = braw.get("gain", 1.0)
            want = ("momentary" if braw.get("curve") == "pulse"
                    else "permanent")
            if gain != 1.0 and not any(
                    declared[n].type == want and declared[n].gain == gain
                    for n in band.kinds):
                raise SystemExit(f"FAIL: {v['name']}/{cls}: authored gain "
                                 f"{gain} lost in migration")
            if band.gain != 1.0 or band.param_patch:
                raise SystemExit(f"FAIL: {v['name']}/{cls}: legacy band "
                                 f"fields not neutralized")
        if spec_raw.get("reroll_dice", True) != all(
                any(declared[n].jump == "dice" for n in b.kinds)
                for b in loaded.bands):
            raise SystemExit(f"FAIL: {v['name']}/{cls}: reroll flag "
                             f"mis-migrated")
        if cls == "flare" and spec_raw.get("color_set_jump") and not all(
                any(declared[n].jump == "color_set" for n in b.kinds)
                for b in loaded.bands):
            raise SystemExit(f"FAIL: {v['name']}: colour jump lost")
    canon_dump = json.loads(sc.model_dump_json())
    if canon_dump != json.loads(SceneV2(**canon_dump).model_dump_json()):
        raise SystemExit(f"FAIL: {v['name']}: canonical form not stable")
    verified += 1
check(verified == len(raw_live) >= 9,
      f"all {verified} live scenes load unchanged as auto-named kinds "
      f"(authored patches/gains/flags preserved, canonical form stable)")

eye_top = max(live["Eye V2"].responses["flare"].bands,
              key=lambda b: b.intensity_max)
eye_kinds = {k.name: k for k in live["Eye V2"].flare_kinds}
check(any(absolute_params(eye_kinds[n]).get("flames") == 1.0
          for n in eye_top.kinds if eye_kinds[n].type == "permanent"),
      "Eye: the top flare band is the FLAME flare (flames → 1.0)")

# ── the STAR strips migration (the fold's not-foldable row, now foldable) ────
star_mod = importlib.import_module("scripts.seed_star_strips")
star_store = json.loads(live_scenes_file.read_text())
check(star_mod.STAR_ID in star_store,
      "STAR (d3aab04c…) present in the SPECTRA store")
star1 = star_mod.with_star_strips(star_store[star_mod.STAR_ID])
check(star1 == star_mod.with_star_strips(star1),
      "STAR strips migration is idempotent")
star_scene = SceneV2(**star1)
strips_dev = next(d for d in star_scene.devices if d.target == "Strips")
check(strips_dev.effect_type == "melt"
      and strips_dev.effect_steps[0].threshold == 0.7
      and strips_dev.effect_steps[0].effect_type == "power"
      and strips_dev.effect_steps[0].params == {"bass_decay_rate": 0.6},
      "STAR strips declaration: melt below ⚡ 0.7, power (bass_decay_rate "
      "0.6) at/above — exactly as Hype Star had")


def star_strips_effect(inten: float) -> str:
    res = scene_compiler.resolve_scene(star_scene,
                                       FireContext(inten, rng=Random(6)))
    return next(d for d in res.devices if d.target == "Strips").effect_type


check(star_strips_effect(0.5) == "melt"
      and star_strips_effect(0.85) == "power",
      "migrated STAR: strips melt on a MID fire, power on a HIGH fire")

# ── the STAR edges freeze (Admiral order, 2026-08-15: "I do not want any ──
# of the flares in the scene star to change the number of edges.") The new
# rule check_spectra.py must assert instead of the old dice-variance one
# above: nothing moves STAR's edge count anymore, not a flare, not a fresh
# fire. In-memory only, like the strips migration above — never mutates
# live_scenes_file, which stays the raw S1 seeder output.
edges_mod = importlib.import_module("scripts.freeze_star_edges")
edges_store = json.loads(live_scenes_file.read_text())
star_canonical_original = json.loads(
    SceneV2(**edges_store[edges_mod.STAR_ID]).model_dump_json())
star_frozen_raw = edges_mod.with_star_edges_frozen(edges_store[edges_mod.STAR_ID])
check(star_frozen_raw == edges_mod.with_star_edges_frozen(star_frozen_raw),
      "STAR edges freeze is idempotent")
check(edges_mod.with_star_edges_restored(star_frozen_raw) == star_canonical_original,
      "STAR edges restore is the exact inverse of the freeze")
star_frozen = SceneV2(**star_frozen_raw)
matrix_frozen = next(d for d in star_frozen.devices if d.target == "Matrix")
edges_binding = matrix_frozen.params["edges"]
check(isinstance(edges_binding, ValueBinding)
      and edges_binding.sticky is True and edges_binding.dice is None
      and {s.value for s in edges_binding.steps} == {3.0, 4.0, 5.0, 6.0},
      "STAR edges fix: still a signal binding (rolls fresh at every fire), "
      "now sticky (skipped by mid-run re-rolls) and independent (no dice "
      "correlation with star)")
check(all("edges" not in k.params for k in star_frozen.flare_kinds),
      "STAR edges fix: no flare kind (incl. the retired \"Flare patch "
      "0.7–1\"/\"Drop patch 0.7–1\") still patches edges")
seen_edges: set[float] = set()
edges_counts = {v: 0 for v in (3.0, 4.0, 5.0, 6.0)}
for seed in range(4000):
    resolved = scene_compiler.resolve_scene(
        star_frozen, FireContext(0.5, rng=Random(seed)))
    p = next(d.params for d in resolved.devices if d.effect_type == "radial")
    seen_edges.add(p["edges"])
    edges_counts[p["edges"]] += 1
check(seen_edges == {3.0, 4.0, 5.0, 6.0}
      and all(abs(n / 4000 - 0.25) < 0.03 for n in edges_counts.values()),
      f"STAR (migrated): fresh fires roll edges uniformly over 3/4/5/6 "
      f"({edges_counts})")

# ── STAR power/Singles accent must never ride the LedFX schema default ──────
# (white) or a stale prior value — sparks must always be black. Ported from
# spot-effects' trigger_engine.py accent-defaults-to-black-on-fire rule
# (see fx/device_model.accent_param_for + spectra/services/
# scene_compiler._entry_config); regression: reported live 2026-08-15 as
# white power-effect sparks on STAR — first diagnosed against a "radio"
# source that doesn't exist in this system; he corrected it to "radial"
# (real: the Strips category's radial-dummy AND tv-mapper virtuals, both
# promoted to power by effect_steps at fire intensity >= 0.7 — see
# star_strips_effect(0.85) above). Live-fired STAR on his real room at
# 2026-08-15, intensity 0.8, dry_run=False (owner=spectra): the actual write
# delivered to fx_seam for virtual_id "radial-dummy" carried
# sparks_color=#000000 — confirmed, not inferred, against his literal
# report. CORRECTED 2026-08-16 (docs/SPECTRA_SPEC.md §62): radial-dummy has
# no IP and no physical light behind it, so that live-room proof could
# never be what he actually saw — the real fixture is tv-mapper (segments
# span tv-backlight + both kitchen sconces; see storage/device_categories
# .json for the real "Strips" membership — this script's own category
# registry above is a small fake, "v-s1"/"v-single1", so the assertion
# below proves the MECHANISM (every virtual a category resolves to gets
# the same forced-black accent) rather than exercising the literal
# "radial-dummy"/"tv-mapper" ids; that's what the real-room replay in
# §62 is for). Re-proven against his real, unprompted show_log fires (no
# synthetic intensity) in the same pass.
star_power_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(star_frozen, FireContext(0.5, rng=Random(7))))
star_power_write = next(w for w in star_power_writes if w["effect_type"] == "power")
check(star_power_write["config"].get("sparks_color") == "#000000",
      "STAR power/Singles: sparks_color is explicitly forced black on every "
      "compile, never left to LedFX's own white schema default")

# Mid-intensity above only ever reaches the always-power Singles entry —
# the Strips entry stays "melt" below the 0.7 threshold, so it never
# exercises the exact promoted-power path he reported. Re-check at a HIGH
# intensity, where Strips (his "radial" source) is ALSO power, and assert
# every power write — not just the first — is forced black.
star_power_writes_high = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(star_frozen, FireContext(0.8, rng=Random(7))))
star_power_writes_high_only = [w for w in star_power_writes_high
                               if w["effect_type"] == "power"]
check(len(star_power_writes_high_only) >= 2
      and all(w["config"].get("sparks_color") == "#000000"
              for w in star_power_writes_high_only),
      "STAR power at a HIGH fire (Strips promoted to power too, his "
      "'radial' source): every power write is forced black, including "
      "the effect_steps-promoted Strips entry, not just the always-power "
      "Singles entry")


async def _no_flare_moves_star_edges() -> None:
    """The actual guarantee, proven on the response engine, not just the
    data shape: firing EVERY flare/drop band that used to touch edges
    (including the two retired patches' own top bands) never changes it."""
    exec4 = RecordingExecutor()
    cond4 = DriftConductor(executor=exec4, drift_profiles=lambda: {},
                           curve_profiles=lambda: {},
                           room_load=lambda: cj.RoomColorState(),
                           room_save=lambda st: None,
                           set_position=lambda sid: None)
    resolved0 = scene_compiler.resolve_scene(
        star_frozen, FireContext(0.5, rng=Random(1)))
    fake_writes = [
        {"virtual_id": f"v-frozen-{i}", "effect_type": dev.effect_type,
         "config": dict(dev.params), "entry_id": dev.id,
         "color_mode": dev.color.mode}
        for i, dev in enumerate(resolved0.devices)]
    cond4.on_scene_fire(star_frozen, fake_writes)
    resp4 = ResponseEngine(conductor=cond4, executor=exec4, rng=Random(2),
                           sequencer_config=lambda: SequencerConfig(),
                           room_load=lambda: cj.RoomColorState(),
                           room_save=lambda st: None)
    matrix_vid = fake_writes[[d.effect_type for d in resolved0.devices]
                             .index("radial")]["virtual_id"]
    baseline_edges = cond4.virtuals[matrix_vid].param_baseline.get("edges")
    star_reroll_seen = False
    # (event, write-kind) for every star/spin write on the matrix virtual —
    # low/mid bands have no explicit star patch (pure dice re-roll: must
    # ease); the 0.7-1 bands' "Flare/Drop patch 0.7-1" kinds explicitly pin
    # star to 0.0 AND spin to 0.55. Historically the patch still won over
    # the dice re-roll's glide and landed as an instant jump regardless of
    # star's own smooth=true tag — the "unchanged by the smoothing fix"
    # limitation that fix's own spec explicitly called out (the smoothing
    # only touched PURE dice re-rolls, _reroll, never a patch's own
    # ParamTarget write via _move_params). Fixed 2026-08-17 (this same
    # pass, scene_response._move_params): a patch on a registry-smooth
    # param now eases too, closing the door this test used to prove open.
    star_writes: list[tuple[str, float, str]] = []
    spin_writes: list[tuple[str, float, str]] = []
    for cls, intensity in (("flare", 0.1), ("flare", 0.5), ("flare", 0.97),
                           ("drop", 0.97)):
        before = len(exec4.writes)
        await resp4.on_event(cls, intensity)
        for w in list(exec4.writes)[before:]:
            if w["virtual_id"] == matrix_vid and "edges" in w["params"]:
                raise SystemExit(
                    f"FAIL: {cls}@{intensity} moved STAR's edges to "
                    f"{w['params']['edges']!r} on the response engine")
            if w["virtual_id"] == matrix_vid and "star" in w["params"]:
                star_reroll_seen = True
                star_writes.append((cls, intensity, w["kind"]))
            if w["virtual_id"] == matrix_vid and "spin" in w["params"]:
                spin_writes.append((cls, intensity, w["kind"]))
    check(star_reroll_seen,
          "STAR (migrated): 'star' still re-rolls on ordinary flares — "
          "sticky excludes edges specifically, Dice Re-roll otherwise "
          "unchanged")
    check(cond4.virtuals[matrix_vid].param_baseline.get("edges", baseline_edges)
          == baseline_edges,
          "STAR (migrated): no flare/drop band moves edges on the real "
          "response engine (flare 0.1/0.5/0.97 + drop 0.97 all fired, "
          "including both retired patches' own top bands)")
    low_mid = [k for cls, i, k in star_writes if i in (0.1, 0.5)]
    check(low_mid and all(k == "glide" for k in low_mid),
          "STAR (2026-08-17 smoothing fix): a pure dice re-roll of 'star' "
          "(no band patch overrides it at these intensities) eases via "
          "executor.glide, never snaps via executor.jump")
    top = [k for cls, i, k in star_writes if i == 0.97]
    check(top and all(k == "glide" for k in top),
          "STAR (2026-08-17 follow-up fix): the 0.7-1 bands' explicit "
          "'star: 0.0' patch still wins over the dice re-roll's OWN value, "
          "but now also eases — closing the door the first smoothing fix "
          "left open (it only touched pure dice re-rolls, not an explicit "
          "ParamTarget patch on the same registry-smooth param)")
    top_spin = [k for cls, i, k in spin_writes if i == 0.97]
    check(top_spin and all(k == "glide" for k in top_spin),
          "STAR (2026-08-17, spin retagged smooth=true): the same 0.7-1 "
          "patch's 'spin: 0.55' also eases now, not just 'star' — one "
          "gate, every registry-smooth param it touches")


asyncio.run(_no_flare_moves_star_edges())

print("\nALL CHECKS PASSED")
