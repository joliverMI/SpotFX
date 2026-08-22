"""Executable spec for the flare scrubbing-preview timeline (owner ask,
data/timeline-preview-scrub-flares-and-drop-sequences — "flares first").

Proves spectra/services/flare_preview.build_timeline against the REAL
ResponseEngine execution model (scene_response.py's fixed dice/moves/gain/
colour order, the registry smooth gate, hold/release timing) rather than a
re-derived approximation: a momentary glide param's animation_end_s lands
exactly at hold_s + PULSE_RELEASE_S, a momentary non-smooth (jump) param
lands instantly and — matching real production behaviour, not a defect
this feature introduces — a boolean param never gets a resolved release
target so it silently never returns to baseline, a permanent gain glides
once and holds, and no live storage write happens anywhere in the run.

Run from repo root: .venv/bin/python scripts/check_flare_preview.py
Isolated: temp categories fixture — no LedFX I/O, no audio, no live storage
write (room_controls/color_sets/room_color are read live per the module's
own docstring, exactly like a dry-run scene test-fire; asserted un-mutated
below).
"""
from __future__ import annotations

import asyncio
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


td = Path(tempfile.mkdtemp(prefix="spectra-flare-preview-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

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

from spectra.models.binding import ValueBinding
from spectra.models.scene import (FlareKind, ParamTarget, SceneDeviceConfig,
                                  SceneV2)
from spectra.services import flare_preview, scene_response

run = asyncio.run

VID = "v1"
scene = SceneV2(
    name="Preview Check Scene",
    devices=[SceneDeviceConfig(
        id="dev1", target_kind="virtual", target=VID, effect_type="radial",
        # "spin" is the entry's own authored baseline (0.2) — a momentary
        # spike on it has a resolvable release target, matching realistic
        # authoring (a flare patches a param the base effect already
        # declares); "twist" carries the random binding dice-roll exercises.
        params={"spin": 0.2,
                "twist": ValueBinding(signal="random", mode="map",
                                      out_min=0.0, out_max=1.0)})],
    flare_kinds=[
        FlareKind(name="spin-flare", type="momentary",
                  params={"spin": ParamTarget(mode="absolute", value=0.9)}),
        FlareKind(name="polygon-flare", type="momentary",
                 params={"polygon": ParamTarget(mode="absolute", value=True)}),
        FlareKind(name="gain-pulse", type="momentary", gain=1.5),
        FlareKind(name="gain-hold", type="permanent", gain=0.6),
        FlareKind(name="dice-roll", type="drift_jump", jump="dice"),
        FlareKind(name="unregistered-kind", type="permanent",
                 params={"no_such_param": ParamTarget(mode="absolute", value=1.0)}),
    ],
)
kinds = {k.name: k for k in scene.flare_kinds}

# ── 1. momentary glide param: lands over DICE_REROLL_GLIDE_MS, releases at
#    hold_s (PULSE_HOLD_S default) over PULSE_RELEASE_S ─────────────────────
tl = run(flare_preview.build_timeline(scene, kinds["spin-flare"], 1.0))
check(tl["result"] == "applied", "spin-flare: applied")
check(len(tl["writes"]) == 2, f"spin-flare: 2 writes (land + release), got {len(tl['writes'])}")
land, release = sorted(tl["writes"], key=lambda w: w["at_s"])
check(land["at_s"] == 0.0 and land["kind"] == "glide"
     and land["duration_ms"] == scene_response.DICE_REROLL_GLIDE_MS,
     "spin-flare: lands as a glide at t=0 over DICE_REROLL_GLIDE_MS")
check(land["params"].get("spin") == 0.9, "spin-flare: lands at the declared value")
expected_hold = scene_response.PULSE_HOLD_S
check(abs(release["at_s"] - expected_hold) < 1e-6,
     f"spin-flare: release starts at PULSE_HOLD_S ({expected_hold})")
check(release["kind"] == "glide"
     and release["duration_ms"] == int(scene_response.PULSE_RELEASE_S * 1000),
     "spin-flare: release glides over PULSE_RELEASE_S")
expected_end = expected_hold + scene_response.PULSE_RELEASE_S
check(abs(tl["animation_end_s"] - expected_end) < 1e-6,
     f"spin-flare: animation_end_s == hold_s + PULSE_RELEASE_S ({expected_end})")
check(tl["animation_start_s"] == 0.0, "spin-flare: animation_start_s == 0")
check(tl["duration_s"] >= 6.0, "spin-flare: timeline never shorter than his 6s example")

# ── 1b. animation_anchor_s / trigger_mark_s, HIS sign convention (ruling
#    2026-08-21, data/preview-loops-and-fires-on-the-trigger): 0 offset =
#    coincident with the anchor; negative offset (fire earlier) moves the
#    mark to the RIGHT of the anchor; positive (fire later) moves it LEFT.
#    Both fields are what the frontend's ruler draw AND its live-fire loop
#    both read — one source of truth for "where does the animation start." ─
anchor = flare_preview.animation_anchor_s(tl["duration_s"])
check(abs(tl["animation_anchor_s"] - anchor) < 1e-9,
     "spin-flare: animation_anchor_s == animation_anchor_s(duration_s)")
check(abs(tl["trigger_mark_s"] - anchor) < 1e-9,
     "spin-flare: trigger_mark_s == animation_anchor_s at offset 0 (coincident)")

neg_kind = kinds["spin-flare"].model_copy(update={"trigger_offset_ms": -500})
tl_neg = run(flare_preview.build_timeline(scene, neg_kind, 1.0))
check(tl_neg["trigger_mark_s"] > tl_neg["animation_anchor_s"],
     "negative offset (fire earlier): mark sits to the RIGHT of the anchor")
check(abs(tl_neg["trigger_mark_s"] - tl_neg["animation_anchor_s"] - 0.5) < 1e-6,
     "negative offset -500ms: mark is exactly 500ms right of the anchor")

pos_kind = kinds["spin-flare"].model_copy(update={"trigger_offset_ms": 500})
tl_pos = run(flare_preview.build_timeline(scene, pos_kind, 1.0))
check(tl_pos["trigger_mark_s"] < tl_pos["animation_anchor_s"],
     "positive offset (fire later): mark sits to the LEFT of the anchor")
check(abs(tl_pos["animation_anchor_s"] - tl_pos["trigger_mark_s"] - 0.5) < 1e-6,
     "positive offset +500ms: mark is exactly 500ms left of the anchor")

# ── 1c. FIRE-TIME LEAD (2026-08-21, fm/preview-must-hold-scene-changes):
#    fire_at_s reuses scene_response.kind_lead_ms — the SAME automatic lead
#    trigger_engine._response_switch_lead_ms would compute for this exact
#    kind (DICE_REROLL_GLIDE_MS for a registry-smooth momentary glide, 0 for
#    a non-smooth/toggle target) — never a hardcoded number. spin-flare's
#    own "spin" target IS registry-smooth (radial's spin, retagged
#    smooth=true), so it must carry the full 220ms lead. ───────────────────
check(tl["lead_ms"] == scene_response.DICE_REROLL_GLIDE_MS,
     f"spin-flare: lead_ms == DICE_REROLL_GLIDE_MS ({scene_response.DICE_REROLL_GLIDE_MS})")
check(abs(tl["fire_at_s"] - (tl["animation_anchor_s"] - scene_response.DICE_REROLL_GLIDE_MS / 1000)) < 1e-9,
     "spin-flare: fire_at_s == animation_anchor_s - lead_ms/1000")
check(tl["fire_at_s"] < tl["animation_anchor_s"],
     "spin-flare: a positive lead always fires strictly before the anchor")

# fire_at_s must compose with his OWN trigger_offset_ms exactly like #172's
# target-then-lead formula (target := timestamp_ms + trigger_offset_ms;
# fire_at := target - lead_ms) — proven here as target ≡ animation_anchor_s
# for ANY offset (trigger_mark_s's own formula bakes it in by construction:
# trigger_mark_s + offset_ms/1000 == animation_anchor_s always), so
# fire_at_s must equal animation_anchor_s - lead_ms/1000 regardless of which
# offset produced that particular anchor — proven at both sign extremes,
# not just offset=0 above.
check(abs(tl_neg["fire_at_s"] - (tl_neg["animation_anchor_s"] - scene_response.DICE_REROLL_GLIDE_MS / 1000)) < 1e-9,
     "negative offset (-500ms): fire_at_s still == anchor - lead_ms/1000 (offset already baked into anchor)")
check(abs(tl_pos["fire_at_s"] - (tl_pos["animation_anchor_s"] - scene_response.DICE_REROLL_GLIDE_MS / 1000)) < 1e-9,
     "positive offset (+500ms): fire_at_s still == anchor - lead_ms/1000 (offset already baked into anchor)")

# A color_rotate kind's lead is the intensity-scaled ramp (color_rotate_
# ramp_ms), not the fixed dice-glide constant — same function production's
# own color_rotate_lead_ms calls, just invoked per-kind instead of per-band.
rotate_kind = FlareKind(name="rotate", type="color_rotate")
tl_rotate = run(flare_preview.build_timeline(scene, rotate_kind, 0.6))
expected_rotate_lead = scene_response.color_rotate_ramp_ms(0.6)
check(tl_rotate["lead_ms"] == expected_rotate_lead,
     f"color_rotate kind: lead_ms == color_rotate_ramp_ms(0.6) ({expected_rotate_lead})")

# ── 2. momentary NON-smooth (toggle) param on a NEVER-AUTHORED key: instant
#    jump in, and — since 2026-08-21 (scene_response.py "RELEASE OWNERSHIP")
#    — an instant jump BACK at hold_s to the param's resting value (the
#    effect's own schema default; radial's `polygon` rests True) instead
#    of the old silent skip that stranded a spike with no tracked baseline.
#    A toggle's return is a JUMP, never a PULSE_RELEASE_S glide, so the
#    ruler's END marker is the hold itself, not hold+1.5s ─────────────────
tl2 = run(flare_preview.build_timeline(scene, kinds["polygon-flare"], 1.0))
check(len(tl2["writes"]) == 2, f"polygon-flare: 2 writes (jump in, jump back), got {len(tl2['writes'])}")
w, w_back = sorted(tl2["writes"], key=lambda w: w["at_s"])
check(w["kind"] == "jump" and w["at_s"] == 0.0, "polygon-flare: instant jump at t=0")
check(w_back["kind"] == "jump" and abs(w_back["at_s"] - scene_response.PULSE_HOLD_S) < 1e-6,
     "polygon-flare: the release is an instant JUMP at hold_s, never a glide")
check(w_back["params"].get("polygon") is True,
     "polygon-flare: releases to radial's own resting value for polygon (schema default True) — never stranded for lack of a baseline")
check(abs(tl2["animation_end_s"] - (scene_response.PULSE_HOLD_S + w_back["duration_ms"] / 1000.0)) < 1e-6,
     "polygon-flare: animation_end_s == hold + the jump's own (near-zero) duration — no phantom 1.5s glide-back on the ruler")
check(tl2["lead_ms"] == 0 and tl2["fire_at_s"] == tl2["animation_anchor_s"],
     "polygon-flare: a toggle target needs no lead — fires exactly at the anchor")

# ── 3. momentary gain: spike jump + release glide, same hold/release shape ──
tl3 = run(flare_preview.build_timeline(scene, kinds["gain-pulse"], 1.0))
check(len(tl3["writes"]) == 2, "gain-pulse: 2 writes (spike + release)")
spike, grelease = sorted(tl3["writes"], key=lambda w: w["at_s"])
check(spike["at_s"] == 0.0 and spike["kind"] == "jump"
     and "brightness" in spike["params"], "gain-pulse: instant brightness spike")
check(abs(grelease["at_s"] - scene_response.PULSE_HOLD_S) < 1e-6
     and grelease["duration_ms"] == int(scene_response.PULSE_RELEASE_S * 1000),
     "gain-pulse: release at PULSE_HOLD_S over PULSE_RELEASE_S")

# ── 4. permanent gain: glides once over GAIN_GLIDE_S and holds — no release ─
tl4 = run(flare_preview.build_timeline(scene, kinds["gain-hold"], 1.0))
check(len(tl4["writes"]) == 1, "gain-hold: 1 write, no release (permanent carries)")
check(tl4["writes"][0]["duration_ms"] == int(scene_response.GAIN_GLIDE_S * 1000),
     "gain-hold: glides over GAIN_GLIDE_S")
check(abs(tl4["animation_end_s"] - scene_response.GAIN_GLIDE_S) < 1e-6,
     "gain-hold: animation_end_s == GAIN_GLIDE_S")

# ── 5. dice re-roll: the scene's one signal=random binding (on a smooth
#    param) re-resolves and glides, no release (dice always carries) ───────
tl5 = run(flare_preview.build_timeline(scene, kinds["dice-roll"], 1.0))
check(len(tl5["writes"]) == 1, "dice-roll: 1 write (the re-rolled twist binding)")
check(tl5["writes"][0]["kind"] == "glide"
     and tl5["writes"][0]["duration_ms"] == scene_response.DICE_REROLL_GLIDE_MS,
     "dice-roll: re-rolled smooth param glides over DICE_REROLL_GLIDE_MS")

# ── 6. a kind whose only param isn't registered on any live virtual
#    produces no writes — honest empty result, never a fabricated
#    zero-length animation window ───────────────────────────────────────────
tl6 = run(flare_preview.build_timeline(scene, kinds["unregistered-kind"], 1.0))
check(tl6["writes"] == [] and tl6["animation_start_s"] is None
     and tl6["animation_end_s"] is None, "unregistered-kind: no writes, no markers")
check(tl6["duration_s"] == flare_preview.MIN_TIMELINE_S,
     "unregistered-kind: falls back to the minimum timeline length")
check(tl6["animation_anchor_s"] == flare_preview.animation_anchor_s(flare_preview.MIN_TIMELINE_S)
     and tl6["trigger_mark_s"] == tl6["animation_anchor_s"],
     "unregistered-kind: anchor/mark still computed even with no writes")
check(tl6["lead_ms"] == 0 and tl6["fire_at_s"] == tl6["animation_anchor_s"],
     "unregistered-kind: no writes at all still gets a real lead_ms/fire_at_s (0/anchor)")

# ── 7. no live storage write: room_controls/color_sets/room_color files
#    the module read from during the runs above were never created ────────
check(not scfg.ROOM_CONTROLS_FILE.exists(), "no write: room_controls.json untouched")
check(not scfg.COLOR_SETS_FILE.exists(), "no write: color_sets.json untouched")
check(not scfg.ROOM_COLOR_FILE.exists(), "no write: room_color.json untouched")

print("\nAll flare-preview checks passed.")
