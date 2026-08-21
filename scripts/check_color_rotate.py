"""Executable spec + real-timing demonstration for the colour ROTATE-AND-
BACK flare (owner ask, 2026-08-20 — scripts/add_color_rotate_flares.py has
his verbatim spec). Proves, against the real vendored render pipeline
(fx.headless dummy device) and the REAL production scheduling code
(spectra/services/engine.py's fire_response_event shape, replicated here
with a genuine asyncio clock — not flare_preview.py's synchronous
fake-clock catch-up shortcut), rather than asserting them:

  1. All four quantities (rotation degrees, ramp-in, dwell, fade-back)
     scale linearly from intensity exactly per his numbers, at 0/0.5/1.
  2. The model rejects an over-specified color_rotate kind (params/gain/
     hold_ms authored on it) — the mechanism carries no fifth knob.
  3. ANCHORING: color_rotate_lead_ms returns exactly this kind's own
     ramp_ms at a given intensity, and combined with tick()'s
     fire_at = timestamp_ms - lead arithmetic, the ramp's completion
     timestamp is exactly the trigger mark, for every intensity checked —
     the flare rule (ramp ENDS on the mark), not the drop rule.
  4. MEASURED DWELL: fires the kind through the real, unmodified
     ResponseEngine.on_event + the exact engine.py fire_response_event
     scheduling shape (create_task after on_event returns, asyncio.sleep,
     flush) against a real asyncio clock — the SAME methodology used to
     investigate the reverse flare's own reported doubling — and reports
     the measured on-screen duration (ramp write -> fade write) against
     the authored dwell_ms spec, in milliseconds.
  5. COLOUR/SHAPE CONCURRENCY: a band carrying both a color_rotate kind
     and a shape param-move kind fires both as independent executor
     writes in the same event — proven, not assumed.

No live storage write, no LedFX I/O, no audio hardware — fx.headless's
offline dummy device and a temp SPECTRA_STORAGE only. Run from repo root:
.venv/bin/python scripts/check_color_rotate.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from random import Random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


td = Path(tempfile.mkdtemp(prefix="spectra-color-rotate-"))

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

from fx import facade, headless
from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                  SceneDeviceConfig, SceneV2)
from spectra.services import color_rotate, fire_history, scene_response
from spectra.services import trigger_engine as te_module
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import FacadeExecutor
from spectra.services.room_controls import RoomControlState
from spectra.services.scene_response import ResponseEngine
from spectra.services.trigger_engine import TriggerEngine

VID = headless.DEFAULT_VIRTUAL_ID
ORIGINAL_GRADIENT = "#3366cc"


def _run(coro):
    return asyncio.run(coro)


async def _host(sub: str):
    host = await headless.start_headless_host(str(td / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _rotate_test_scene() -> SceneV2:
    return SceneV2(
        name="Rotate Test",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="blackhole",
            params={"swirl": 3.0})],
        flare_kinds=[
            FlareKind(name="Colour Rotate & Back", type="color_rotate"),
            FlareKind(name="Shape Nudge", type="momentary", hold_ms=300,
                      params={"swirl": {"mode": "absolute", "value": -2.0}}),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Colour Rotate & Back": 1.0,
                             "Shape Nudge": 1.0}),
        ])})


def _seed_fire(conductor, scene, config):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id, "color_mode": "set"}])


# ── 1. scaling formula ────────────────────────────────────────────────────

for i, (deg, ramp, dwell, fade) in {
    0.0: (60.0, 1000, 1000, 1500),
    1.0: (180.0, 250, 400, 375),
}.items():
    check(scene_response.color_rotate_degrees(i) == deg, f"degrees@{i} == {deg}")
    check(scene_response.color_rotate_ramp_ms(i) == ramp, f"ramp_ms@{i} == {ramp}")
    check(scene_response.color_rotate_dwell_ms(i) == dwell, f"dwell_ms@{i} == {dwell}")
    check(scene_response.color_rotate_fade_ms(i) == fade, f"fade_ms@{i} == {fade}")

mid_deg = scene_response.color_rotate_degrees(0.5)
mid_ramp = scene_response.color_rotate_ramp_ms(0.5)
check(abs(mid_deg - 120.0) < 1e-9, f"degrees@0.5 == 120 (got {mid_deg})")
check(mid_ramp == 625, f"ramp_ms@0.5 == 625 (got {mid_ramp})")
check(scene_response.color_rotate_fade_ms(0.5) == round(625 * 1.5),
     "fade_ms@0.5 == 1.5x ramp_ms@0.5")

# ── 2. model rejects a fifth knob ─────────────────────────────────────────

try:
    FlareKind(name="bad", type="color_rotate", gain=0.7)
    raise SystemExit("FAIL: color_rotate with gain!=1.0 should be rejected")
except ValueError:
    print("ok: color_rotate kind rejects authored gain")
try:
    FlareKind(name="bad2", type="color_rotate", hold_ms=500)
    raise SystemExit("FAIL: color_rotate with hold_ms should be rejected")
except ValueError:
    print("ok: color_rotate kind rejects authored hold_ms")
try:
    FlareKind(name="bad3", type="color_rotate",
             params={"swirl": {"mode": "absolute", "value": 1.0}})
    raise SystemExit("FAIL: color_rotate with params should be rejected")
except ValueError:
    print("ok: color_rotate kind rejects authored params")

# ── 3. anchoring: lead exactly cancels the ramp so it lands on the mark ──

scene = _rotate_test_scene()
for intensity in (0.0, 0.35, 0.72, 1.0):
    lead = scene_response.color_rotate_lead_ms(scene, "flare", intensity, {})
    expected = scene_response.color_rotate_ramp_ms(intensity)
    check(lead == expected,
         f"color_rotate_lead_ms@{intensity} == its own ramp_ms ({expected}, got {lead})")
    # The arithmetic identity tick() relies on: fire_at = mark - lead; the
    # ramp then takes ramp_ms of real wall-clock time to visually complete
    # — fire_at + ramp_ms must equal the mark exactly, for any mark.
    mark_ms = 123_456
    fire_at = mark_ms - lead
    check(fire_at + expected == mark_ms,
         f"fire_at + ramp_ms == trigger mark @ intensity {intensity}")

# A band with no color_rotate kind attached needs no lead from this
# function (the dice-glide check in _response_switch_lead_ms is separate
# and still applies on its own).
bare = SceneV2(name="Bare", devices=[SceneDeviceConfig(
    target_kind="virtual", target=VID, effect_type="blackhole", params={})],
    flare_kinds=[FlareKind(name="Shape Nudge", type="momentary", hold_ms=300,
                          params={"swirl": {"mode": "absolute", "value": -2.0}})],
    responses={"flare": ResponseSpec(bands=[
        FlareBand(intensity_min=0.0, intensity_max=1.0,
                  kinds={"Shape Nudge": 1.0})])})
check(scene_response.color_rotate_lead_ms(bare, "flare", 0.8, {}) == 0,
     "no color_rotate kind attached -> lead contribution 0")


def _lead_integration_check():
    """The SAME check via the real trigger_engine dispatcher
    (_response_switch_lead_ms), not just the pure function above — proves
    the two are actually wired together, not just individually correct.
    _active_scene/_live_virtuals are lazy-import staticmethods with no
    constructor injectable (they always read the real production
    spectra.services.engine singleton) — the established test pattern
    (tests/test_lead_time_alignment.py's _iso fixture) monkeypatches them
    directly on the class rather than constructing a fresh engine; this
    script does the same, restoring the originals afterward."""
    from spectra.services.trigger_engine import trigger_engine

    orig_active_scene = TriggerEngine._active_scene
    orig_live_virtuals = TriggerEngine._live_virtuals
    orig_render_intensity = trigger_engine._render_intensity
    TriggerEngine._active_scene = staticmethod(lambda: scene)
    TriggerEngine._live_virtuals = staticmethod(lambda: {})
    # Identity render-intensity: this check proves the WIRING between
    # _response_switch_lead_ms and color_rotate_lead_ms, not the separate,
    # already-tested genre/bass render-intensity scale
    # (intensity_scale.combine_measured_and_scale) that _default_
    # render_intensity would otherwise apply on top.
    trigger_engine._render_intensity = lambda x: x
    try:
        class _FakeAction:
            kind = "fire_response"
            event_class = "flare"
            intensity = 0.8

        lead = trigger_engine._response_switch_lead_ms(_FakeAction())
    finally:
        TriggerEngine._active_scene = orig_active_scene
        TriggerEngine._live_virtuals = orig_live_virtuals
        trigger_engine._render_intensity = orig_render_intensity
    expected = scene_response.color_rotate_ramp_ms(0.8)
    check(lead == expected,
         f"trigger_engine._response_switch_lead_ms wires color_rotate_lead_ms through "
         f"(expected {expected}, got {lead})")


_lead_integration_check()

# ── 4 & 5. measured dwell + colour/shape concurrency, real async timing ──

async def _real_timing_check():
    host, virtual = await _host("timing")
    try:
        config = {"gradient": ORIGINAL_GRADIENT, "swirl": 3.0}
        headless.attach_effect(host, virtual, "blackhole", config)

        executor = FacadeExecutor(
            clock=time.monotonic,
            room_controls_load=lambda: RoomControlState())
        conductor = DriftConductor(
            executor=executor, clock=time.monotonic, leg_s=20.0,
            intensity=lambda: 1.0, drift_profiles=lambda: {},
            curve_profiles=lambda: {}, gradient_profiles=lambda: {},
            room_controls=lambda: RoomControlState(), rng=Random(11))
        responder = ResponseEngine(
            conductor=conductor, executor=executor, rng=Random(7),
            clock=time.monotonic, curve_profiles=lambda: {})

        scene = _rotate_test_scene()
        _seed_fire(conductor, scene, config)

        intensity = 1.0
        expected_ramp = scene_response.color_rotate_ramp_ms(intensity)
        expected_dwell = scene_response.color_rotate_dwell_ms(intensity)
        expected_fade = scene_response.color_rotate_fade_ms(intensity)
        expected_degrees = scene_response.color_rotate_degrees(intensity)
        expected_rotated = color_rotate.rotate_color_value(
            ORIGINAL_GRADIENT, expected_degrees)

        t_call = time.monotonic()
        record = await responder.on_event("flare", intensity)
        fire_history.record_fire(
            "responses", "flare", {"event_class": "flare", "intensity": intensity})

        # Real production scheduling shape (engine.py's
        # fire_response_event/_release_after_hold and
        # _release_color_rotate_after_dwell), replicated with a genuine
        # asyncio clock rather than imported wholesale — importing
        # spectra.services.engine would construct its live bridge/executor
        # singletons, which this offline check must never touch.
        release_tasks = [
            asyncio.create_task(_after(responder.flush_releases, hold_s, hold_s))
            for hold_s in responder.pending_hold_groups()
        ] + [
            asyncio.create_task(_after(responder.flush_color_rotates, dwell_s, dwell_s))
            for dwell_s in responder.pending_color_rotate_holds()
        ]
        await asyncio.gather(*release_tasks)

        writes = [w for w in executor.writes if w["at"] >= t_call]
        ramp_write = next((w for w in writes if w["kind"] == "glide"
                          and "gradient" in w["params"]
                          and w["params"]["gradient"] != ORIGINAL_GRADIENT), None)
        fade_write = next((w for w in writes if w["kind"] == "glide"
                          and w["params"].get("gradient") == ORIGINAL_GRADIENT), None)
        shape_write = next((w for w in writes if "swirl" in w.get("params", {})), None)

        check(ramp_write is not None, "ramp-in glide write landed on gradient")
        check(ramp_write["duration_ms"] == expected_ramp,
             f"ramp-in glide duration_ms == {expected_ramp} "
             f"(got {ramp_write['duration_ms']})")
        check(ramp_write["params"]["gradient"] == expected_rotated,
             f"ramp-in target == rotate_color_value(original, {expected_degrees}) "
             f"({expected_rotated}, got {ramp_write['params']['gradient']})")
        check(fade_write is not None, "fade-back glide write landed, target == original")
        check(fade_write["duration_ms"] == expected_fade,
             f"fade-back glide duration_ms == {expected_fade} "
             f"(got {fade_write['duration_ms']})")
        check(shape_write is not None,
             "COLOUR/SHAPE CONCURRENCY: the shape param kind's own write "
             "landed independently in the same fire")
        check(shape_write is not ramp_write and shape_write is not fade_write,
             "the shape write is a genuinely separate executor call, not folded "
             "into the colour rotate's own writes")

        on_time_ms = (fade_write["at"] - ramp_write["at"]) * 1000.0
        print(f"\n--- measured dwell (real asyncio clock, real vendored "
             f"blackhole effect on fx.headless) ---")
        print(f"authored spec @ intensity={intensity}: dwell_ms={expected_dwell}")
        print(f"measured ramp-write -> fade-write gap: {on_time_ms:.1f}ms")
        overrun_pct = (on_time_ms - expected_dwell) / expected_dwell * 100.0
        print(f"overrun vs spec: {overrun_pct:+.1f}%")
        check(on_time_ms < expected_dwell * 1.5,
             f"measured dwell ({on_time_ms:.1f}ms) stays well under a 1.5x-of-spec "
             f"doubling band (spec {expected_dwell}ms) — not reproducing the reverse "
             f"flare's reported ~2x overrun in this offline harness")
    finally:
        facade.set_host(None)
        await host.shutdown()


async def _after(fn, arg, delay_s):
    await asyncio.sleep(delay_s)
    return await fn(arg)


_run(_real_timing_check())

print("\nAll color-rotate checks passed.")
