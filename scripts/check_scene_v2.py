"""Executable spec for SPECTRA SceneV2 (design answers 1–3 + compiler + API).
Run from repo root: .venv/bin/python scripts/check_scene_v2.py
Isolated: temp files for the store and device categories; no LedFX I/O."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError

from models.color_set import ColorSetCard, ColorSetEntry
from models.scene_v2 import (FlareBand, SceneColorAssignment, SceneDeviceConfig,
                             SceneV2)
from services import color_wheel, device_category_service, effect_params


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def expect_invalid(label, **kwargs):
    try:
        SceneV2(**kwargs)
        raise SystemExit(f"FAIL: {label} — accepted")
    except ValidationError:
        print(f"ok: {label} rejected")


# ── answer 1: multi-effect scenes valid; malformed scenes rejected ───────────
scene = SceneV2(
    name="Spec Multi",
    devices=[
        SceneDeviceConfig(target_kind="category", target="Matrix", effect_type="radial",
                          params={"spin": 0.5}, brightness=0.8),
        SceneDeviceConfig(target_kind="category", target="Strips", effect_type="power",
                          color=SceneColorAssignment(mode="fixed", color_kind="solid",
                                                     color_value="#ff0000", bg_color="#000080")),
        SceneDeviceConfig(target_kind="virtual", target="v-solo", effect_type="orbits"),
    ],
    flare_bands=[FlareBand(intensity_min=0.0, intensity_max=0.5, curve="ease_in"),
                 FlareBand(intensity_min=0.5, intensity_max=1.0, curve="pulse", gain=1.5)],
    accept_all_sets=False, accepted_set_ids=["set-a"],
)
check(len({d.effect_type for d in scene.devices}) == 3, "answer 1: three effects in one scene")
expect_invalid("overlapping flare bands", name="bad",
               flare_bands=[FlareBand(intensity_min=0.0, intensity_max=0.6),
                            FlareBand(intensity_min=0.5, intensity_max=1.0)])
expect_invalid("missing effect_type", name="bad",
               devices=[SceneDeviceConfig(target="Matrix")])
expect_invalid("duplicate target", name="bad",
               devices=[SceneDeviceConfig(target="Matrix", effect_type="radial"),
                        SceneDeviceConfig(target="Matrix", effect_type="power")])
expect_invalid("all-devices entry naming a target", name="bad",
               devices=[SceneDeviceConfig(target_kind="all", target="Matrix",
                                          effect_type="radial")])
expect_invalid("duplicate all-devices entries", name="bad",
               devices=[SceneDeviceConfig(target_kind="all", effect_type="radial"),
                        SceneDeviceConfig(target_kind="all", effect_type="power")])

# ── answer 2: wheel position + automatic rainbow tagging ─────────────────────
def set_of(colors):
    return ColorSetCard(name="t", entries=[
        ColorSetEntry(color_kind="solid", color_value=c) for c in colors])

p = color_wheel.wheel_position(set_of(["#ff0000", "#ff2010"]))
check(not p.rainbow and p.position_deg is not None
      and (p.position_deg < 15 or p.position_deg > 345),
      f"tight red set → position {p.position_deg}°")
p = color_wheel.wheel_position(set_of(["#ff0000", "#00ff00", "#0000ff"]))
check(p.rainbow and p.position_deg is None and p.span_deg > 180,
      f"R/G/B set → rainbow, span {p.span_deg}°, no position")
p = color_wheel.wheel_position(ColorSetCard(name="g", entries=[ColorSetEntry(
    color_kind="gradient",
    color_value="linear-gradient(90deg, #000000 0%, #00ff00 50%, #008000 100%)")]))
check(not p.rainbow and p.position_deg is not None and abs(p.position_deg - 120) < 5,
      f"gradient stops parsed, black stop ignored → {p.position_deg}°")
p = color_wheel.wheel_position(set_of(["#000000", "#ffffff"]))
check(p.position_deg is None and not p.rainbow, "achromatic set → no position, not rainbow")
p = color_wheel.wheel_position(set_of(["#ff0000", "#00ffff"]))
check(not p.rainbow and abs(p.span_deg - 180) < 0.1,
      "exactly 180° span not rainbow (rainbow needs MORE than 180°)")

# ── answer 3: two-way set filtering ──────────────────────────────────────────
s_open = ColorSetCard(name="open")
s_out = ColorSetCard(name="opted", scene_v2_opt_out=True)
wide = SceneV2(name="wide")
narrow = SceneV2(name="narrow", accept_all_sets=False, accepted_set_ids=[s_open.id])
check(wide.accepts_color_set(s_open), "accept-all takes non-opted set")
check(not wide.accepts_color_set(s_out), "global opt-out beats accept-all")
check(narrow.accepts_color_set(s_open), "narrowed scene takes listed set")
check(not narrow.accepts_color_set(ColorSetCard(name="other")), "narrowed scene rejects unlisted set")
s_open.scene_v2_opt_out = True
check(not narrow.accepts_color_set(s_open), "global opt-out beats explicit accept")
check(ColorSetCard(**json.loads('{"name": "legacy"}')).scene_v2_opt_out is False,
      "legacy color_set JSON loads, flag defaults False")

# ── compiler: category expansion, virtual override, color/brightness keys ────
with tempfile.TemporaryDirectory() as td:
    device_category_service.CATEGORIES_FILE = Path(td) / "device_categories.json"
    device_category_service._save_raw({
        "c1": {"id": "c1", "name": "Matrix", "virtuals": ["v-m1", "v-m2"], "effects": ["radial"]},
        "c2": {"id": "c2", "name": "MatrixChild", "parent_id": "c1", "virtuals": ["v-m3"], "effects": ["orbits", "blackhole"]},
        "c3": {"id": "c3", "name": "Strips", "virtuals": ["v-s1"], "effects": ["power"]},
    })
    effect_params.load()
    from services import scene_v2_compiler

    writes = {w["virtual_id"]: w for w in scene_v2_compiler.compile_scene(scene)}
    check(set(writes) == {"v-m1", "v-m2", "v-m3", "v-s1", "v-solo"},
          "category subtree expansion + virtual entry")
    check(writes["v-m1"]["config"] == {"spin": 0.5, "brightness": 0.8},
          "params + brightness compiled; mode='set' leaves colors alone")
    check(writes["v-s1"]["config"]["gradient"] == "#ff0000"
          and writes["v-s1"]["config"]["background_color"] == "#000080",
          "fixed colors land on gradient/background_color")
    ov = SceneV2(name="ov", devices=[
        SceneDeviceConfig(target_kind="category", target="Matrix", effect_type="radial"),
        SceneDeviceConfig(target_kind="virtual", target="v-m2", effect_type="pacman")])
    ow = {w["virtual_id"]: w for w in scene_v2_compiler.compile_scene(ov)}
    check(ow["v-m2"]["effect_type"] == "pacman", "virtual entry overrides category")

    # effect vocabulary parity: a category target fires the whole subtree of
    # virtuals, so its effects union must cover descendants too (the effect
    # picker sources from this resolution — child-category effects must not
    # vanish when the parent is targeted).
    check(effect_params.get_effects_for_category("Matrix") == ["radial", "orbits", "blackhole"],
          "category effects cover the subtree, parent-first")

    # all-devices target: every imported virtual, overridden by narrower entries
    allscene = SceneV2(name="all", devices=[
        SceneDeviceConfig(target_kind="all", effect_type="noise", brightness=0.3),
        SceneDeviceConfig(target_kind="category", target="Strips", effect_type="power"),
        SceneDeviceConfig(target_kind="virtual", target="v-m2", effect_type="pacman")])
    aw = {w["virtual_id"]: w for w in scene_v2_compiler.compile_scene(allscene)}
    check(set(aw) == {"v-m1", "v-m2", "v-m3", "v-s1"},
          "all-devices entry expands to every imported virtual")
    check(aw["v-m1"]["effect_type"] == "noise" and aw["v-s1"]["effect_type"] == "power"
          and aw["v-m2"]["effect_type"] == "pacman",
          "override layering: all < category < virtual")
    check(aw["v-m1"]["config"] == {"brightness": 0.3},
          "all-devices entry carries params/brightness like any other entry")

    # colour set riding a compile (the sequencer's colour-set selector):
    # mode="set" entries take the picked palette; fixed entries stay pinned.
    from models.music_event import MorphScope
    palette = ColorSetCard(name="palette", entries=[
        ColorSetEntry(color_kind="solid", color_value="#00ff00",
                      bg_color="#000040", brightness=0.5),
        ColorSetEntry(scope=MorphScope(virtual_ids=["v-m2"]),
                      color_kind="solid", color_value="#0000ff"),
    ])
    cw = {w["virtual_id"]: w for w in scene_v2_compiler.compile_scene(scene, palette)}
    check(cw["v-m1"]["config"]["gradient"] == "#00ff00"
          and cw["v-m1"]["config"]["brightness"] == 0.5
          and cw["v-m3"]["config"]["gradient"] == "#00ff00",
          "set-mode entries take the colour set's palette (global scope)")
    check("background_color" not in cw["v-m1"]["config"],
          "set bg_color respects the effect's no_background_color block "
          "(radial), same as the fixed path")
    check(cw["v-m2"]["config"]["gradient"] == "#0000ff"
          and "background_color" not in cw["v-m2"]["config"],
          "a narrower set entry overrides the global one on its virtuals only")
    check(cw["v-s1"]["config"]["gradient"] == "#ff0000",
          "fixed-mode entries pin their own colours regardless of the set")
    check("gradient" not in cw["v-solo"]["config"],
          "un-imported virtuals get no set colours (scope resolution owns "
          "nothing outside the category tree)")

    res = asyncio.run(scene_v2_compiler.fire_scene(scene, dry_run=True))
    check(res["dry_run"] is True and len(res["writes"]) == 5, "dry-run fire: writes only, no I/O")
    res = asyncio.run(scene_v2_compiler.fire_scene(scene, color_set=palette, dry_run=True))
    check(res["dry_run"] is True and len(res["writes"]) == 5,
          "dry-run fire with a colour set: writes only, no I/O")

    # ── store CRUD + API router ──────────────────────────────────────────────
    from services import scene_v2_store
    scene_v2_store.SCENES_V2_FILE = Path(td) / "scenes_v2.json"
    scene_v2_store.save(scene)
    check(scene_v2_store.get_by_id(scene.id).name == "Spec Multi", "store round-trip")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import scenes_v2_router
    app = FastAPI()
    app.include_router(scenes_v2_router.router)
    client = TestClient(app)

    check(len(client.get("/api/scenes-v2").json()) == 1, "GET list")
    sid = client.post("/api/scenes-v2", json=json.loads(SceneV2(
        name="From API",
        devices=[SceneDeviceConfig(target="Matrix", effect_type="melt")],
    ).model_dump_json())).json()["id"]
    check(client.get(f"/api/scenes-v2/{sid}").json()["name"] == "From API", "POST + GET one")
    fire = client.post(f"/api/scenes-v2/{sid}/fire").json()
    check(fire["dry_run"] is True and len(fire["writes"]) == 3, "fire defaults to dry run")
    check(client.get("/api/scenes-v2/wheel-positions").status_code == 200, "GET wheel-positions")
    check(client.delete(f"/api/scenes-v2/{sid}").json()["status"] == "deleted", "DELETE")
    check(client.get(f"/api/scenes-v2/{sid}").status_code == 404, "GET deleted → 404")
    check(client.post("/api/scenes-v2", json={"name": "bad", "devices": [
        {"target": "Matrix", "effect_type": "radial"},
        {"target": "Matrix", "effect_type": "power"}]}).status_code == 422,
        "invalid scene → 422 at API boundary")

print("\nALL CHECKS PASSED")
