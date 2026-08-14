"""Executable spec for the SPECTRA model + engine: value bindings in scene
params, dice-correlated randomness, intensity-conditional EFFECT SELECTION
(effect_steps: fire-time variant pick, load-unchanged guarantee, preview
parity, the engine interplay, the STAR strips migration), the four-class
responses block (legacy flare_bands shim), drift declarations, the colour-journey OVERRIDE
semantics (into/out-of custody transfer), binding resolution + dry-run
compile through the shared device model, store/API round-trips, the
sequencer engine on SPECTRA stores, the Mid Group seeder, and the S2
evolution engine: the response engine (band selection, patch broadcast
targeting, gain envelopes, dice re-rolls, the flare colour jump with the
keep-current rung and the journey resuming from the new point), the
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
}))

from fx import light_ownership
light_ownership.OWNERSHIP_FILE = td / "ownership.json"

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
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
check(list(ls.responses) == ["flare"] and len(ls.responses["flare"].bands) == 2
      and ls.responses["flare"].bands[1].param_patch == {"flames": 1.0},
      "legacy flare_bands loads unchanged as the flare class (patches kept)")
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
check(ms.responses["flare"].color_set_jump is True,
      "seeder: flare class seeds color_set_jump=True")
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
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.scene_response import ResponseEngine, select_band
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

resp_scene = scene.model_copy(deep=True)
resp_scene.responses = {
    "flare": ResponseSpec(bands=[
        FlareBand(intensity_min=0.0, intensity_max=0.5, curve="pulse",
                  gain=1.6, param_patch={"twist": 0.9}),
        FlareBand(intensity_min=0.5, intensity_max=1.0, curve="pulse",
                  gain=2.0)], color_set_jump=True),
    "charge": ResponseSpec(bands=[
        FlareBand(intensity_min=0.5, intensity_max=1.0, curve="ease_in",
                  gain=1.3)], reroll_dice=False),
    "lull": ResponseSpec(bands=[
        FlareBand(intensity_min=0.0, intensity_max=1.0, curve="linear",
                  gain=0.5)], reroll_dice=False),
    "drop": ResponseSpec(bands=[
        FlareBand(intensity_min=0.7, intensity_max=1.0,
                  param_patch={"spin": 1.0, "ghost_param": 5.0})]),
}
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
      and record["band"]["gain"] == 1.6,
      "flare at 0.3 lands in its band and applies")
pairs = {(0.3, 6), (-0.3, 3), (0.0, 5)}
jumps = [w for w in exec2.writes if w["kind"] == "jump"]
reroll_jump = next(w for w in jumps if "star" in w["params"])
check((reroll_jump["params"]["star"], reroll_jump["params"]["edges"]) in pairs,
      "re-roll: 🎲 star/edges jump as an AUTHORED pair (fresh dice)")
check(all("spin" not in w["params"] for w in jumps),
      "re-roll leaves ⚡ (non-random) bindings alone")
patch_jumps = [w for w in jumps if "twist" in w["params"]]
check({w["virtual_id"] for w in patch_jumps} == {"v-m1", "v-m2", "v-m3"}
      and all(w["params"]["twist"] == 0.9 for w in patch_jumps),
      "patch broadcast: 'twist' lands on every virtual whose effect has it")
pulse_jumps = [w for w in jumps if set(w["params"]) == {"brightness"}]
check(len(pulse_jumps) == 3 and all(w["params"]["brightness"] == 1.0
                                    for w in pulse_jumps),
      "pulse spike: brightness jumps to baseline×gain clamped (0.65×1.6→1.0)")
check(record["gain_envelope"][0]["peak"] == 1.0,
      "the surge record states the spike peak")
check(record["color_jump"]["result"] == "jumped"
      and record["color_jump"]["picked_id"] == "set-red",
      "flare colour jump: the selector picked the eligible set")
grad_jumps = [w for w in jumps if "gradient" in w["params"]]
check(grad_jumps and all(w["params"]["gradient"] == "#ff0000"
                         for w in grad_jumps),
      "colour jump is a JUMP: the pick's colours land as instant writes")
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
check(record["gain_envelope"][0]["held"] is True
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
drop_jump = [w for w in exec2.writes if w["kind"] == "jump"
             and "spin" in w["params"]][-1]
check(drop_jump["params"]["spin"] == 1.0
      and not any("ghost_param" in w["params"] for w in exec2.writes),
      "drop patch lands 'spin'; a key no effect carries lands nowhere")
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
    responses={"flare": ResponseSpec(bands=[
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
jumps4 = [w for w in exec4.writes if w["kind"] == "jump"]
check(any("blur" in w["params"] for w in jumps4)
      and all("reactivity" not in w["params"] for w in jumps4),
      "re-roll follows the SELECTED variant's 🎲 params, never another "
      "variant's — a surge re-rolls dice, it never re-selects the effect")
lo_writes = scene_compiler.compile_scene(
    scene_compiler.resolve_scene(stepped, FireContext(0.3, rng=Random(1))))
cond4.on_scene_fire(stepped, lo_writes)
check(cond4.virtuals["v-s1"].effect_type == "melt"
      and len(cond4.mechanisms) == 1,
      "a LOW fire re-selects: the base effect returns and its drift "
      "mechanism seeds again")
exec4.writes.clear()
asyncio.run(resp4.on_event("flare", 0.3))
jumps4 = [w for w in exec4.writes if w["kind"] == "jump"]
check(any("reactivity" in w["params"] for w in jumps4)
      and all("blur" not in w["params"] for w in jumps4),
      "after the re-select the re-roll follows the base variant again")

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
SEVEN = ["Black Hole V2", "Orbits V2", "Mid Star V2", "Fireworks V2",
         "Squiggles V2", "Dancers V2", "Eye V2"]
check(all(name in live for name in SEVEN), "all seven Mid Group scenes seeded")
check(all(live[n].responses["flare"].color_set_jump and
          len(live[n].responses["flare"].bands) == 3 for n in SEVEN),
      "each carries a 3-band flare class with the colour-set jump")

def resolved_params(name: str, effect_type: str, intensity, seed: int = 1):
    resolved = scene_compiler.resolve_scene(
        live[name], FireContext(intensity, rng=Random(seed)))
    return next(d.params for d in resolved.devices
                if d.effect_type == effect_type)


seen_pairs = set()
for seed in range(200):
    p = resolved_params("Mid Star V2", "radial", 0.5, seed)
    seen_pairs.add((p["star"], p["edges"]))
check(seen_pairs == {(0.3, 6), (-0.3, 3), (0.0, 5)},
      "Mid Star: dice variants land ONLY as the three authored pairs")

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
    expected = {k: v for k, v in top.param_patch.items()
                if any(device_model.get_param_meta(d.effect_type, k)
                       for d in sc.devices)}
    landed = {}
    for w in exec3.writes:
        if w["kind"] == "jump":
            landed.update(w["params"])
    check(rec["result"] == "applied" and expected
          and all(landed.get(k) == v for k, v in expected.items()),
          f"{name}: top flare band executes its patch ({sorted(expected)})")

eye_top = max(live["Eye V2"].responses["flare"].bands,
              key=lambda b: b.intensity_max)
check(eye_top.param_patch.get("flames") == 1.0,
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

print("\nALL CHECKS PASSED")
