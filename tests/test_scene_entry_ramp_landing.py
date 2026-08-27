"""§84's missing instrument, as a regression test (2026-08-27,
fm/flare-preview-offsets-everywhere).

docs/SPECTRA_SPEC.md §84 and trigger_engine.py's own module docstring both
say the same thing: nothing in this codebase observes a scene-entry ramp AT
the moment of a real fire, so the lead system's actual claim — THE
CROSSFADE'S MIDPOINT LANDS ON THE TRIGGER MARK — was only ever proven as
"the right number came out of the right function" or with an INJECTED lead.

This watches the ramp with the mechanism the light itself is driven by:
Effect._advance_tweens, stepped once per rendered frame through
fx.headless's real assemble/flush pipeline, at the end of the real
production chain (tick() -> its own _default_lead_ms -> fire_scene_by_id ->
scene_compiler.fire_scene -> fx_seam -> facade -> start_param_transitions).
Song position and wall clock advance 1:1 — the deliberate simplification a
real room does not get (no bridge, no xcorr, no audio latency; each of
those is its own row in docs/SPECTRA_TIMING_CONVENTIONS.md) — which is what
puts "where the ramp crossed half" and "where the mark is" on one axis.

Still NOT a room proof, and not claimed as one: his fixtures are untouched.
The perceptual question and the live transport to real hardware both still
need the room. Everything between "the engine decided" and "the frame
carries the value" is settled here.

The fuller instrument, including the LOOKAHEAD-pinned shape 100% of his
real triggers actually have and the authored-offset case, prints its real
numbers in scripts/check_scene_entry_ramp_landing.py.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model, facade, headless

VID = headless.DEFAULT_VIRTUAL_ID
PARAM = "spin"
FROM_VALUE, TO_VALUE = 0.0, 1.0
TICK_MS = 200
FRAME_HZ = 60.0
FRAME_MS = 1000.0 / FRAME_HZ
MARK_MS = 4000
CROSSFADE_MS = 1200
TOLERANCE_MS = TICK_MS + FRAME_MS   # one tick (the engine can only fire on
                                    # one) + one frame (the sampler can only
                                    # see a value once a frame advanced it)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from fx import light_ownership as lo
    from spectra import config as scfg
    from spectra.services import dwell
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("FIRE_HISTORY_FILE", "fire_history.json"),
                     ("SHOW_LOG_FILE", "show_log.json"),
                     ("COLOR_SETS_FILE", "color_sets.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
    own = tmp_path / "ownership.json"
    own.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", own)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    headless.silence_audio()
    dwell.reset()
    yield
    dwell.reset()


def _seed_scene():
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import room_controls, scene_store
    room_controls.save_room_controls(room_controls.RoomControlState(
        global_transition_ms=0, scene_change_mode="full"))
    scene = SceneV2(
        name="Ramp Landing", entry_ramp_ms=CROSSFADE_MS,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial",
                                   params={PARAM: TO_VALUE})])
    scene_store.save(scene)
    return scene


async def _observe(tmp_path, trig, *, uri, no_lead=False, end_ms=6000):
    from spectra.services.trigger_engine import TriggerEngine
    host = await headless.start_headless_host(str(tmp_path / f"h-{uri}"))
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    try:
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "radial",
                                            {PARAM: FROM_VALUE})
            engine = TriggerEngine(
                list_triggers=lambda _u: [trig],
                scene_change_mode=lambda: "full",
                sequencer_enabled=lambda: False,
                lead_ms=(lambda _t: 0) if no_lead else None)
            await engine.on_track_state(uri)
            wall_ms, next_tick_ms = 0.0, 0.0
            samples: list[tuple[float, float]] = []
            while wall_ms <= end_ms:
                if wall_ms >= next_tick_ms - 1e-9:
                    await engine.tick(int(round(next_tick_ms)))
                    next_tick_ms += TICK_MS
                headless.render_frames(virtual, 1, clock=clock, dt=1.0 / FRAME_HZ)
                wall_ms += FRAME_MS
                samples.append((wall_ms, float(effect.config.get(PARAM, FROM_VALUE))))
    finally:
        facade.set_host(None)
        await host.shutdown()
    half = (FROM_VALUE + TO_VALUE) / 2.0
    return {
        "half_crossed_ms": next((t for t, v in samples if v >= half), None),
        "started_ms": next((t for t, v in samples if v > FROM_VALUE + 1e-9), None),
        "final": samples[-1][1] if samples else None,
    }


def _trig(scene_id, offset_ms=0):
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    return SpectraTrigger(timestamp_ms=MARK_MS, trigger_offset_ms=offset_ms,
                          action=FireSceneAction(scene_id=scene_id, intensity=0.5))


def test_the_crossfade_midpoint_lands_on_the_trigger_mark(tmp_path):
    scene = _seed_scene()
    obs = asyncio.run(_observe(tmp_path, _trig(scene.id), uri="song:named"))
    assert obs["final"] == pytest.approx(TO_VALUE), "the ramp never completed"
    assert obs["started_ms"] is not None and obs["started_ms"] < MARK_MS, (
        "the ramp did not begin before the mark — no lead engaged")
    assert obs["half_crossed_ms"] == pytest.approx(MARK_MS, abs=TOLERANCE_MS), (
        f"midpoint landed at {obs['half_crossed_ms']}ms, mark is {MARK_MS}ms")


def test_with_no_lead_the_midpoint_misses_by_half_the_crossfade(tmp_path):
    """The negative control. An instrument that cannot go red on the thing
    it measures is decoration — this proves the tolerance above is not
    simply generous enough to pass either way."""
    scene = _seed_scene()
    obs = asyncio.run(_observe(tmp_path, _trig(scene.id), uri="song:no-lead",
                               no_lead=True))
    miss = obs["half_crossed_ms"] - MARK_MS
    assert miss > TOLERANCE_MS, f"no-lead fire still landed on the mark ({miss}ms)"
    assert miss == pytest.approx(CROSSFADE_MS / 2, abs=TOLERANCE_MS), (
        "with no lead the midpoint should miss by exactly half the crossfade")
    assert obs["started_ms"] >= MARK_MS, (
        "with no lead the ramp must only START at the mark")


def test_an_authored_negative_offset_renders_the_midpoint_earlier(tmp_path):
    """His own sign law, observed on the renderer rather than asserted
    about a returned number: negative = earlier."""
    scene = _seed_scene()
    plain = asyncio.run(_observe(tmp_path, _trig(scene.id), uri="song:plain"))
    from spectra.services import dwell
    dwell.reset()   # process-global; each observation is its own "song"
    shifted = asyncio.run(_observe(tmp_path, _trig(scene.id, offset_ms=-600),
                                   uri="song:shifted"))
    assert shifted["half_crossed_ms"] < plain["half_crossed_ms"]
    assert shifted["half_crossed_ms"] == pytest.approx(MARK_MS - 600,
                                                       abs=TOLERANCE_MS)
