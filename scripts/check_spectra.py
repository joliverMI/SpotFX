"""Executable spec for the SPECTRA S1 model growth: value bindings in scene
params, dice-correlated randomness, the four-class responses block (legacy
flare_bands shim), drift declarations, the colour-journey OVERRIDE
semantics (into/out-of custody transfer), binding resolution + dry-run
compile through the shared device model, store/API round-trips, the
sequencer engine on SPECTRA stores, and the Mid Group seeder's S1 half.

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

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"

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
      and color_journey.active_journey(room, inherit_scene).degrees_per_min == 2.0,
      "inherit scene rides the room journey (default pace)")
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
check(entered.custody == "scene" and entered.degrees_per_min == -30.0,
      "INTO override: the scene steers, at its own pace/direction")
pos = room.wheel_position_deg
pos2 = color_journey.step(entered, pos, dt_s=60.0)
check(pos2 == (200.0 - 30.0) % 360.0,
      "override walks FROM the room's current position — no snap in")
# OUT: the room adopts the override's final position and resumes its pace.
room2 = color_journey.on_scene_exit(room, pos2)
check(room2.wheel_position_deg == pos2,
      "OUT of override: room resumes from where the override left the wheel")
resumed = color_journey.active_journey(room2, inherit_scene)
check(resumed.custody == "room" and resumed.degrees_per_min == 2.0,
      "OUT of override: the room's own pace/direction steer again")
check(color_journey.step(resumed, room2.wheel_position_deg, 60.0,
                         palette_rainbow=True) == room2.wheel_position_deg,
      "rainbow palette pauses the walk (binding exemption)")
check(color_journey.step(resumed, None, 60.0) is None,
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
check(rj["journey"]["degrees_per_min"] == 2.0, "room journey served")
client.put("/api/room-journey", json={
    "journey": {"degrees_per_min": -5.0}, "wheel_position_deg": 123.0})
rj = client.get("/api/room-journey").json()
check(rj["journey"]["degrees_per_min"] == -5.0
      and rj["wheel_position_deg"] != 123.0,
      "journey PUT updates the declaration, never teleports the wheel")

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

print("\nALL CHECKS PASSED")
