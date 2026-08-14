"""Executable spec for the S2 drift conductor (report §2.5, §2.8 + the
destination-journey rework): leg targets through the executor seam,
bounce/wrap identities, follow slew, the DESTINATION-DRIVEN colour journey
(selection via the shipped selector, per-destination pace from distance,
travel along the shortest arc, palette rotation WITH the wheel, arrival
landing exactly and reselecting, no-eligible-destination hold), journey
custody through the conductor (into/out of an override picking within its
own palette bounds — the binding transition semantics), re-baseline on
scene fire clearing the bearing, carry semantics, the deferral matrix
(pause/Dinner Party/Ambient hold everything; Force Scene continues), and
the production DARK discipline (the wired engine records, never executes).

Run from repo root: .venv/bin/python scripts/check_drift.py
Isolated: temp stores, fake clock, in-memory room — no LedFX I/O, no audio.
"""
from __future__ import annotations

import asyncio
import colorsys
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


td = Path(tempfile.mkdtemp(prefix="spectra-drift-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({
    "c1": {"id": "c1", "name": "Matrix", "parent_id": None,
           "virtuals": ["v-m1", "v-m2"], "effects": ["radial"], "role": None},
}))

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.FIRE_HISTORY_FILE = scfg.SPECTRA_STORAGE / "fire_history.json"
scfg.SHOW_LOG_FILE = scfg.SPECTRA_STORAGE / "show_log.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"

from spectra.models.scene import (ColorJourneySpec, CurveMapPoint, DriftRef,
                                  DriftSpec, SceneColorJourney,
                                  SceneDeviceConfig, SceneV2)
from spectra.services import color_journey, color_rotate, scene_compiler
from spectra.services.binding_resolver import FireContext
from spectra.services.drift_conductor import DriftConductor, Mechanism
from spectra.services.fx_executor import RecordingExecutor

run = asyncio.run

# ── harness: fake clock, in-memory room, injectable feeds ────────────────────
from random import Random

from spectra.models.sequencer import SequencerConfig

clock = [1000.0]
room_box = [color_journey.RoomColorState(wheel_position_deg=100.0,
                                         active_set_id="set-blue")]
intensity_box: list = [None]
deferral_box: list = [None]
set_positions = {"set-blue": 220.0,   # chromatic; overwrite for rainbow cases
                 "set-green": 130.0,
                 "set-red": 10.0}
cards_box: list[list] = [[]]          # the destination pool per section
broadcasts: list[dict] = []


async def capture(payload):
    broadcasts.append(payload)

executor = RecordingExecutor(clock=lambda: clock[0])
conductor = DriftConductor(
    executor=executor,
    clock=lambda: clock[0],
    leg_s=20.0,
    intensity=lambda: intensity_box[0],
    deferral=lambda: deferral_box[0],
    broadcast=capture,
    drift_profiles=lambda: {},
    curve_profiles=lambda: {},
    room_load=lambda: room_box[0],
    room_save=lambda st: room_box.__setitem__(0, st),
    set_position=lambda sid: set_positions.get(sid),
    set_cards=lambda: cards_box[0],
    sequencer_config=lambda: SequencerConfig(),   # selector unconfigured →
    genre_bucket=lambda: None,                    # neutral-entry fallback
    rng=Random(7),
)

GRADIENT = "linear-gradient(90deg, #0000ff 0%, #4000ff 100%)"
scene = SceneV2(name="Drifting", devices=[SceneDeviceConfig(
    target_kind="category", target="Matrix", effect_type="radial",
    params={"spin": 0.5, "twist": 0.2},
    drift={
        "spin": DriftRef(inline=DriftSpec(kind="creep", rate_per_min=0.3,
                                          lo=0.2, hi=0.8, motion="bounce")),
        "twist": DriftRef(inline=DriftSpec(
            kind="follow", slew_s=5.0,
            inline_points=[CurveMapPoint(x=0.0, y=0.1),
                           CurveMapPoint(x=1.0, y=0.9)])),
    },
    brightness=0.8)])


def fire(sc, color_set=None, color_set_id=None):
    resolved = scene_compiler.resolve_scene(sc, FireContext(0.5))
    writes = scene_compiler.compile_scene(resolved, color_set)
    conductor.on_scene_fire(sc, writes, color_set_id)
    return writes


# Colour set fixtures: blue is the active palette set-mode virtuals rotate;
# green/red are destination candidates on the wheel (positions injected).
from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
blue_set = ColorSetCard(id="set-blue", name="Blues", entries=[
    ColorSetEntry(scope=SetScope(categories=["Matrix"]),
                  color_kind="gradient", color_value=GRADIENT)])
green_set = ColorSetCard(id="set-green", name="Greens", entries=[])
red_set = ColorSetCard(id="set-red", name="Reds", entries=[])
cards_box[0] = [blue_set, green_set]

# ── re-baseline builds mechanisms per WINNING virtual ────────────────────────
writes = fire(scene, blue_set, "set-blue")
check(len(conductor.mechanisms) == 4
      and {m.vid for m in conductor.mechanisms} == {"v-m1", "v-m2"}
      and {m.kind for m in conductor.mechanisms} == {"creep", "follow"},
      "re-baseline: drift declarations expand per virtual (2 params × 2 vids)")
check(conductor.virtuals["v-m1"].gradient == GRADIENT
      and conductor.virtuals["v-m1"].set_mode,
      "re-baseline seeds palette + set-mode from the compiled writes")
check(conductor._last_rebaseline["mechanisms"] == 4
      and conductor._last_rebaseline["journey_custody"] == "room",
      "re-baseline record carries mechanism count + journey custody")

# ── leg targets: creep advances by rate·leg, follow glides over slew ─────────
intensity_box[0] = 1.0
leg = run(conductor.tick())
glides = [w for w in executor.writes if w["kind"] == "glide"]
spin_leg = next(w for w in glides if "spin" in w["params"])
check(abs(spin_leg["params"]["spin"] - 0.6) < 1e-9
      and spin_leg["duration_ms"] == 20000,
      "creep leg: target = position + rate·leg (0.5 → 0.6) over the leg")
twist_leg = next(w for w in glides if "twist" in w["params"])
check(abs(twist_leg["params"]["twist"] - 0.9) < 1e-9
      and twist_leg["duration_ms"] == 5000,
      "follow leg: curve(intensity 1.0) = 0.9, glide over slew_s not leg_s")
check(len({(w["virtual_id"], w["duration_ms"]) for w in glides})
      == len(glides),
      "one glide per virtual per duration — few small calls per leg")
check(broadcasts and broadcasts[-1]["type"] == "drift_leg"
      and broadcasts[-1]["legs"], "drift_leg broadcast carries the leg detail")

# ── follow re-asserts the arc as intensity moves; neutral without a feed ─────
intensity_box[0] = 0.0
run(conductor.tick())
twist_leg = [w for w in executor.writes if "twist" in w["params"]][-1]
check(abs(twist_leg["params"]["twist"] - 0.1) < 1e-9,
      "follow tracks the arc down (curve(0.0) = 0.1)")
intensity_box[0] = None
run(conductor.tick())
twist_leg = [w for w in executor.writes if "twist" in w["params"]][-1]
check(abs(twist_leg["params"]["twist"] - 0.5) < 1e-9,
      "no music feed → follow holds the 0.5 neutral point (stated)")

# ── bounce identity: reflect at the bounds, never outside ────────────────────
spin_mech = next(m for m in conductor.mechanisms
                 if m.vid == "v-m1" and m.param == "spin")
seen = []
for _ in range(12):
    run(conductor.tick())
    seen.append(round(spin_mech.position, 6))
check(all(0.2 <= p <= 0.8 for p in seen), "creep bounce stays inside [lo, hi]")
check(max(seen) == 0.8 and any(a > b for a, b in zip(seen, seen[1:])),
      f"creep reflects at hi and walks back down ({seen[:8]}...)")

# ── wrap identity ────────────────────────────────────────────────────────────
wrap_scene = SceneV2(name="Wrap", devices=[SceneDeviceConfig(
    target_kind="virtual", target="v-m1", effect_type="radial",
    params={"spin": 0.75},
    drift={"spin": DriftRef(inline=DriftSpec(
        kind="creep", rate_per_min=0.3, lo=0.0, hi=0.8, motion="wrap"))})])
fire(wrap_scene)
wrap_mech = conductor.mechanisms[0]
run(conductor.tick())
check(abs(wrap_mech.position - 0.05) < 1e-9,
      "creep wrap folds through hi back to lo (0.75 + 0.1 → 0.05)")

# ── degeneracy floor/ceiling: Orbits' particle size never shrinks past its
# own registered legal range, however the drift spec was authored ──────────
# (owner defect fix, 2026-08-14) orbits.blob_size is REAL registry data —
# config/effect_params.json declares min=0.5, max=6.0 (fx/effects/orbits.py's
# own CONFIG_SCHEMA Range). A creep spec shaped like DriftSpec's bare
# pydantic defaults (lo=0.0, hi=1.0) — exactly what an under-specified
# "put a slow wander on it" declaration would carry — must never be allowed
# to wander the light below 0.5: every glide below that line is silently
# rejected by the effect's own config schema (fx.effects._apply_config logs
# and no-ops), so the conductor's position model would drift out of step
# with the real, stuck light. The mechanism must clamp itself, not rely on
# the far side to reject.
size_scene = SceneV2(name="Orbits Size", devices=[SceneDeviceConfig(
    target_kind="virtual", target="v-m1", effect_type="orbits",
    params={"blob_size": 1.0},
    drift={"blob_size": DriftRef(inline=DriftSpec(
        kind="creep", rate_per_min=0.3, lo=0.0, hi=1.0, motion="bounce"))})])
fire(size_scene)
size_mech = conductor.mechanisms[0]
check(abs(size_mech.eff_lo - 0.5) < 1e-9 and abs(size_mech.eff_hi - 1.0) < 1e-9,
      "orbits.blob_size creep: [0.0, 1.0] intersects the registered "
      "[0.5, 6.0] legal range down to [0.5, 1.0] — never the bare spec's 0.0")
seen = []
for _ in range(10):
    run(conductor.tick())
    seen.append(round(size_mech.position, 6))
check(all(0.5 <= p <= 1.0 for p in seen) and min(seen) == 0.5,
      f"orbits.blob_size wanders down to its registered floor and no "
      f"further — never invisible, never illegal ({seen})")

# follow: the default identity curve (no curve_ref/inline_points) glides
# toward y = intensity, so silent quiet passages (intensity 0) would target
# the bare 0.0 without the same registry clamp — one glide, not a wander,
# so it must clamp the resolved target every leg.
follow_scene = SceneV2(name="Orbits Size Follow", devices=[SceneDeviceConfig(
    target_kind="virtual", target="v-m1", effect_type="orbits",
    params={"blob_size": 2.0},
    drift={"blob_size": DriftRef(inline=DriftSpec(
        kind="follow", slew_s=4.0))})])
fire(follow_scene)
intensity_box[0] = 0.0
executor.writes.clear()
run(conductor.tick())
follow_write = next(w for w in executor.writes if "blob_size" in w["params"])
check(follow_write["params"]["blob_size"] == 0.5,
      "orbits.blob_size follow: the identity curve's 0.0 target at silence "
      "clamps to the registered floor 0.5, never the raw 0.0")
intensity_box[0] = None

# hold: parks at whichever bound it reaches and stays — never oscillates
# back into a state a bounce/wrap motion would revisit.
hold_scene = SceneV2(name="Orbits Size Hold", devices=[SceneDeviceConfig(
    target_kind="virtual", target="v-m1", effect_type="orbits",
    params={"blob_size": 0.9},
    drift={"blob_size": DriftRef(inline=DriftSpec(
        kind="creep", rate_per_min=60.0, lo=0.5, hi=1.5, motion="hold"))})])
fire(hold_scene)
hold_mech = conductor.mechanisms[0]
for _ in range(3):
    run(conductor.tick())
check(hold_mech.position == 1.5 and hold_mech.direction == 0,
      "creep hold: parks at the bound it reaches and stops (no bounce back)")
run(conductor.tick())
check(hold_mech.position == 1.5,
      "creep hold: stays parked on later legs")

# a spec authored entirely outside the registered range (e.g. an agent
# guessing units wrong) falls back to the FULL registered range rather than
# producing an empty/zero-span window.
bad_scene = SceneV2(name="Orbits Size Bad", devices=[SceneDeviceConfig(
    target_kind="virtual", target="v-m1", effect_type="orbits",
    params={"blob_size": 1.0},
    drift={"blob_size": DriftRef(inline=DriftSpec(
        kind="creep", rate_per_min=1.0, lo=10.0, hi=20.0))})])
fire(bad_scene)
bad_mech = conductor.mechanisms[0]
check(abs(bad_mech.eff_lo - 0.5) < 1e-9 and abs(bad_mech.eff_hi - 6.0) < 1e-9,
      "a spec entirely outside the registered range falls back to the "
      "FULL registered range, never a zero-span window")

# an unregistered effect/param is untouched — the floor is additive, never
# a new restriction where none existed.
dummy_mech = Mechanism("v-x", "made_up_param",
                       DriftSpec(kind="creep", lo=-5.0, hi=-1.0), -3.0,
                       effect_type="not-a-real-effect")
check(dummy_mech.eff_lo == -5.0 and dummy_mech.eff_hi == -1.0,
      "an unregistered effect/param is left exactly as authored")

# restore the wrap scene's live mechanism for the carry checks below.
fire(wrap_scene)
wrap_mech = conductor.mechanisms[0]
run(conductor.tick())

# ── carry: a surge moves the wander position; bounds still clamp ─────────────
conductor.on_surge({("v-m1", "spin"): 0.3})
check(abs(wrap_mech.position - 0.3) < 1e-9,
      "surge carries: creep resumes from the surged value")
conductor.on_surge({("v-m1", "spin"): 7.0})
check(wrap_mech.position == 0.8, "surge carry clamps into the creep bounds")
conductor.on_surge({("v-m1", "brightness"): 0.4,
                    ("v-m1", "gradient"): "#ff0000"})
check(conductor.virtuals["v-m1"].brightness_baseline == 0.4
      and conductor.virtuals["v-m1"].gradient == "#ff0000",
      "surge carry updates brightness + palette baselines")

# ── destination journey: selection, per-destination pace, travel ─────────────
# Pool: blue (active — excluded from selection) + green @ 130. From 100° the
# only pick is Greens: 30° away → pace = 30 × clamp(30/90, 0.5, 2) = 15°/min
# → 5° per 20 s leg. The default room reference pace is the owner's live 30.
fire(scene, blue_set, "set-blue")
check(room_box[0].destination is None,
      "a scene fire clears the journey's bearing (reselect under new custody)")
room_box[0] = room_box[0].model_copy(update={"wheel_position_deg": 100.0})
executor.writes.clear()
run(conductor.tick())
dest = room_box[0].destination
check(dest is not None and dest.set_id == "set-green"
      and abs(dest.pace_deg_per_min - 15.0) < 1e-9
      and dest.from_deg == 100.0,
      "the room picks a DESTINATION set; the destination fixes its own pace "
      "from its distance (30° away → half the 30°/min reference)")
check(abs(room_box[0].wheel_position_deg - 105.0) < 1e-6,
      "travel starts the same leg: 5° toward the destination")
leg_rec = broadcasts[-1]["journey"]
check(leg_rec["destination"]["set_name"] == "Greens"
      and abs(leg_rec["destination"]["progress"] - (5.0 / 30.0)) < 1e-3
      and leg_rec["arrived"] is False,
      "the leg record shows the destination and progress toward it")

# ── travel continues; ARRIVAL lands exactly and reselects ────────────────────
for _ in range(4):
    run(conductor.tick())
check(abs(room_box[0].wheel_position_deg - 125.0) < 1e-6,
      "steady travel: 5°/leg along the shortest arc")
run(conductor.tick())   # the arrival leg
check(room_box[0].wheel_position_deg == 130.0
      and broadcasts[-1]["journey"]["arrived"] is True,
      "ON ARRIVAL the wheel lands EXACTLY on the destination position")
dest = room_box[0].destination
check(dest is not None and dest.set_id == "set-blue"
      and dest.from_deg == 130.0
      and abs(dest.pace_deg_per_min - 30.0) < 1e-9,
      "…and the next destination is selected at once (arrived set excluded; "
      "Blues 90° away → full reference pace) — the walk sets off again")
n_legs = 6
grad_writes = [w for w in executor.writes if "gradient" in w["params"]]
check(len(grad_writes) == 2 * n_legs,
      "palette rotation glides land on every set-mode virtual each leg")


def first_stop_hue(gradient: str) -> float:
    hex_color = gradient.split("#")[1][:6]
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360.0


rotated_hue = first_stop_hue(conductor.virtuals["v-m1"].gradient)
hue_diff = (rotated_hue - (first_stop_hue(GRADIENT) + 30.0)) % 360.0
check(min(hue_diff, 360.0 - hue_diff) < 3.0,
      "rotation accounting: cumulative palette hue matches the wheel travel "
      "(100° → 130°)")

# ── no eligible destination → the walk HOLDS (never aimless creep) ───────────
fire(scene, blue_set, "set-blue")           # bearing cleared
cards_box[0] = [blue_set]                    # only the active set remains
held = room_box[0].wheel_position_deg
executor.writes.clear()
run(conductor.tick())
check(room_box[0].wheel_position_deg == held
      and room_box[0].destination is None
      and not [w for w in executor.writes if "gradient" in w["params"]],
      "no eligible destination: the wheel and palette hold — a target or "
      "nothing, never aimless creep")
cards_box[0] = [blue_set, green_set]

# ── rainbow exemption: the walk pauses, nothing rotates ──────────────────────
run(conductor.tick())                        # re-acquire a bearing first
check(room_box[0].destination is not None, "bearing re-acquired")
set_positions["set-blue"] = None   # the active set is now rainbow/achromatic
held = room_box[0].wheel_position_deg
kept = room_box[0].destination
executor.writes.clear()
run(conductor.tick())
check(room_box[0].wheel_position_deg == held
      and room_box[0].destination == kept
      and not [w for w in executor.writes if "gradient" in w["params"]],
      "rainbow palette pauses the walk — wheel, palette, and bearing hold")
set_positions["set-blue"] = 220.0

# ── journey custody: INTO and OUT OF an override, no snap either way ─────────
# The override follows the SAME destination model within its own palette
# bounds: it accepts only Reds, so its bearing must be set-red — picked by
# the same selector, at the override's own reference pace (|−30| = 30).
override_scene = SceneV2(
    name="Override", color_journey=SceneColorJourney(
        mode="override", journey=ColorJourneySpec(degrees_per_min=-30.0)),
    accept_all_sets=False, accepted_set_ids=["set-red"],
    devices=[SceneDeviceConfig(target_kind="virtual", target="v-m1",
                               effect_type="radial", params={"spin": 0.5})])
cards_box[0] = [blue_set, green_set, red_set]
fire(override_scene, blue_set, "set-blue")
room_box[0] = room_box[0].model_copy(update={"wheel_position_deg": 100.0})
before = room_box[0].wheel_position_deg
check(room_box[0].destination is None,
      "INTO override: custody transfers, the wheel does not move, the room "
      "bearing is dropped for the override to pick its own")
run(conductor.tick())
dest = room_box[0].destination
check(dest is not None and dest.set_id == "set-red"
      and abs(dest.pace_deg_per_min - 30.0) < 1e-9,
      "the override picks WITHIN ITS OWN PALETTE BOUNDS (only Reds "
      "accepted), 90° away → its full 30°/min reference pace")
check(abs(room_box[0].wheel_position_deg - 90.0) < 1e-6,
      "…and steers from the room's position along the shortest arc "
      "(100° → 90°, heading for 10°): no snap in")
exit_deg = room_box[0].wheel_position_deg
cards_box[0] = [blue_set, green_set]
fire(scene, blue_set, "set-blue")   # back to an inherit scene
check(room_box[0].wheel_position_deg == exit_deg
      and room_box[0].destination is None,
      "OUT of override: the room resumes from where the override left it "
      "(no snap back) and picks a fresh room bearing")
run(conductor.tick())
dest = room_box[0].destination
check(dest is not None and dest.set_id == "set-green"
      and abs(room_box[0].wheel_position_deg
              - (exit_deg + dest.pace_deg_per_min * (20.0 / 60.0))) < 1e-6,
      "the room's own destination steers again — one story, custody handed "
      "back")

# ── pace_factor 0 holds the walk while the scene shows ───────────────────────
hold_scene = SceneV2(name="Hold", color_journey=SceneColorJourney(
    mode="inherit", pace_factor=0.0),
    devices=[SceneDeviceConfig(target_kind="virtual", target="v-m1",
                               effect_type="radial", params={"spin": 0.5})])
fire(hold_scene, blue_set, "set-blue")
held = room_box[0].wheel_position_deg
run(conductor.tick())
check(room_box[0].wheel_position_deg == held
      and room_box[0].destination is None,
      "inherit pace_factor 0 holds the room walk — no destinations picked")

# ── a room is NEVER set-less: the journey bootstraps its first set ───────────
# Wiped room state (no set, no wheel — the live defect): the first leg
# selects a first set with the shipped selector and APPLIES it — active
# set, wheel anchor, colours landed on live set-mode virtuals.
cards_box[0] = [blue_set]
fire(scene, blue_set, "set-blue")
room_box[0] = color_journey.RoomColorState()
executor.writes.clear()
run(conductor.tick())
check(room_box[0].active_set_id == "set-blue"
      and room_box[0].wheel_position_deg == 220.0,
      "set-less room: the first leg selects and APPLIES a first set — "
      "active set + wheel anchor (a room is never set-less)")
boot_jumps = [w for w in executor.writes
              if w["kind"] == "jump" and "gradient" in w["params"]]
check(len(boot_jumps) == 2
      and all(w["params"]["gradient"] == GRADIENT for w in boot_jumps),
      "bootstrap lands the set's colours on live set-mode virtuals as a "
      "JUMP, not effect defaults")

# ── manual apply-this-set (the supported owner/fleet surface) ────────────────
result = run(conductor.apply_set_directly(green_set))
check(result["applied"] == "set-green"
      and room_box[0].active_set_id == "set-green"
      and room_box[0].wheel_position_deg == 130.0
      and room_box[0].destination is None,
      "apply-this-set: active set + wheel anchor move, the bearing clears "
      "so the journey travels on from the new point")
cards_box[0] = [blue_set, green_set]

# ── deferral matrix: pause/dinner/ambient hold everything ────────────────────
fire(scene, blue_set, "set-blue")
for reason in ("paused", "dinner_party", "ambient"):
    deferral_box[0] = reason
    executor.writes.clear()
    held = room_box[0].wheel_position_deg
    result = run(conductor.tick())
    check(result is None and not executor.writes
          and room_box[0].wheel_position_deg == held
          and conductor.status()["deferred_by"] == reason,
          f"deferral '{reason}': no legs, no walk, stated in status")
deferral_box[0] = None

# ── Force Scene does NOT defer drift (bridge-level contract) ─────────────────
from spectra.services.bridge import SpotEffectsBridge
b = SpotEffectsBridge(clock=lambda: clock[0])
b.force_scene = True
check(b.conductor_deferral() is None
      and b.sequencer_deferral() == "force_scene",
      "Force Scene defers the sequencer but drift keeps running")
b.paused = True
check(b.conductor_deferral() == "paused",
      "pause holds drift through the same bridge feed")

# ── status surface ───────────────────────────────────────────────────────────
st = conductor.status()
check(st["executor_mode"] == "recording" and st["leg_s"] == 20.0
      and st["active_scene"]["name"] == "Drifting"
      and len(st["mechanisms"]) == 4
      and st["journey"]["custody"] == "room"
      and "destination" in st["journey"]
      and st["last_leg"] is not None,
      "conductor status: executor mode, scene, mechanisms, journey incl. "
      "destination, last leg")

# ── the production wiring is DARK ────────────────────────────────────────────
from spectra.services import engine
check(engine.executor.mode == "recording"
      and engine.conductor.executor is engine.executor
      and engine.responses.executor is engine.executor
      and engine.status()["dark"] is True,
      "production engine records only — dark against real lights until S3")
import spectra.services.drift_conductor as dc_mod
import spectra.services.fx_executor as fxe_mod
import spectra.services.scene_response as sr_mod
for mod in (dc_mod, sr_mod, fxe_mod):
    src = Path(mod.__file__).read_text()
    check("fx_seam.apply_writes" not in src and "import fx_seam" not in src,
          f"{mod.__name__.split('.')[-1]} never touches the live HTTP seam")

print("\nALL CHECKS PASSED")
