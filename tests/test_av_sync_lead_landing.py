"""THE PROOF BAR FOR THE A/V-SYNC LEAD (owner ask 2026-08-28): a setting
that reads back is not evidence.

A room-controls PUT round-tripping its own value proves the JSON survived
a save. It proves nothing at all about whether the lights moved — which
is the entire claim the Apply dialogue makes to him in plain words
("lights will fire 120 ms EARLIER than they do now"). So this measures
that sentence, on the real pipeline, the way the AV instrument itself
measures: it watches WHEN THE LIGHT ACTUALLY CHANGES relative to the
trigger mark, and asks whether the gap moved by exactly the amount set.

The instrument, mirroring tests/test_scene_entry_ramp_landing.py's
pattern (§84's landing instrument): the whole production chain runs for
real — av_sync_lead.show_clock_ms (the SAME function engine.py's trigger
poll calls, not a re-implementation) -> TriggerEngine.tick -> its own
lead system -> fire_scene_by_id -> scene_compiler.fire_scene -> fx_seam
-> facade -> start_param_transitions -> Effect._advance_tweens, stepped
once per rendered frame through fx.headless's real assemble/flush. Song
position and wall clock advance 1:1, which is what puts "where the light
moved" and "where the mark is" on one axis.

To isolate the lead's own effect from the transition machinery, the scene
fires with NO entry ramp: the light's value steps at the fire, so
"onset" is the write landing, and the AV instrument's own light-side
quantity (a light EDGE) is what is being timed.

NEGATIVE CONTROL: an uncalibrated room (av_sync_lead_ms=None, the
shipped default) must land the edge on the mark and move NOTHING — if the
harness cannot tell the two apart it is decoration.

Still NOT a room proof, and not claimed as one: his fixtures are
untouched, nothing here reaches :8000/:8010, and the real transport to
hardware plus the perceptual question both still need the room.
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
# The engine can only fire on a tick, and the sampler can only see a value
# once a frame advanced it. Same two terms the §84 instrument allows.
TOLERANCE_MS = TICK_MS + FRAME_MS


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


def _seed_scene(lead_ms):
    """Seed the room WITH the lead under test, through the real model —
    so the value the observation reads is one a PUT /api/room-controls
    could have written, not a test-local variable."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import room_controls, scene_store
    room_controls.save_room_controls(room_controls.RoomControlState(
        global_transition_ms=0, scene_change_mode="full",
        av_sync_lead_ms=lead_ms))
    scene = SceneV2(
        name="AV Lead Landing", entry_ramp_ms=0,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial",
                                   params={PARAM: TO_VALUE})])
    scene_store.save(scene)
    return scene


async def _observe(tmp_path, trig, *, uri, end_ms=6000):
    """Run the show for `end_ms` of song, sampling the light every frame.
    Returns the song time at which the light's value first moved — the
    'light edge' the AV instrument's camera side times."""
    from spectra.services import av_sync_lead
    from spectra.services.trigger_engine import TriggerEngine

    lead = av_sync_lead.current_lead_ms()
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
                sequencer_enabled=lambda: False)
            await engine.on_track_state(uri)
            song_ms, next_tick_ms = 0.0, 0.0
            samples: list[tuple[float, float]] = []
            while song_ms <= end_ms:
                if song_ms >= next_tick_ms - 1e-9:
                    # PRODUCTION'S OWN CALL, verbatim: engine.py's trigger
                    # poll is `tick(show_clock_ms(position, lead))`.
                    await engine.tick(av_sync_lead.show_clock_ms(
                        int(round(next_tick_ms)), lead))
                    next_tick_ms += TICK_MS
                headless.render_frames(virtual, 1, clock=clock, dt=1.0 / FRAME_HZ)
                song_ms += FRAME_MS
                samples.append((song_ms, float(effect.config.get(PARAM, FROM_VALUE))))
    finally:
        facade.set_host(None)
        await host.shutdown()
    return {
        "edge_ms": next((t for t, v in samples if v > FROM_VALUE + 1e-9), None),
        "final": samples[-1][1] if samples else None,
    }


def _trig(scene_id):
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    return SpectraTrigger(timestamp_ms=MARK_MS,
                          action=FireSceneAction(scene_id=scene_id, intensity=0.5))


def _edge_for(tmp_path, lead_ms, uri):
    from spectra.services import dwell
    dwell.reset()   # process-global; each observation is its own "song"
    scene = _seed_scene(lead_ms)
    obs = asyncio.run(_observe(tmp_path, _trig(scene.id), uri=uri))
    assert obs["final"] == pytest.approx(TO_VALUE), "the scene never landed"
    assert obs["edge_ms"] is not None, "the light never moved"
    return obs["edge_ms"]


def test_uncalibrated_room_lands_the_edge_on_the_mark(tmp_path):
    """THE NEGATIVE CONTROL. av_sync_lead_ms=None is the shipped default,
    and hold (1) is that nothing about his show changes until his first
    apply. If this drifts, every measurement below is meaningless."""
    edge = _edge_for(tmp_path, None, "song:uncalibrated")
    assert edge == pytest.approx(MARK_MS, abs=TOLERANCE_MS), (
        f"an uncalibrated room moved the fire: edge {edge}ms vs mark {MARK_MS}ms")


def test_zero_is_indistinguishable_from_never_calibrated_at_the_light(tmp_path):
    """None and 0 differ only in what the DIALOGUE says. At the light they
    must be the same — proven, not asserted in a docstring."""
    none_edge = _edge_for(tmp_path, None, "song:none")
    zero_edge = _edge_for(tmp_path, 0, "song:zero")
    assert zero_edge == pytest.approx(none_edge, abs=FRAME_MS)


@pytest.mark.parametrize("lead_ms", [120, 400])
def test_a_positive_lead_fires_the_light_earlier_by_exactly_that_much(tmp_path, lead_ms):
    """His sign law, measured on the renderer: positive = EARLIER, and by
    exactly the amount set — which is the literal claim the Apply dialogue
    makes ("lights will fire 120 ms EARLIER than they do now")."""
    baseline = _edge_for(tmp_path, None, f"song:base-{lead_ms}")
    shifted = _edge_for(tmp_path, lead_ms, f"song:lead-{lead_ms}")
    moved = baseline - shifted
    assert shifted < baseline, "a positive lead did not fire earlier"
    assert moved == pytest.approx(lead_ms, abs=TOLERANCE_MS), (
        f"lead {lead_ms}ms moved the light edge by {moved:.1f}ms")


@pytest.mark.parametrize("lead_ms", [-150, -300])
def test_a_negative_lead_fires_the_light_later_by_exactly_that_much(tmp_path, lead_ms):
    """The other direction, on the same instrument — because a sign law
    proven in one direction is half a proof, and this fleet's most
    repeated failure is exactly the other half."""
    baseline = _edge_for(tmp_path, None, f"song:base{lead_ms}")
    shifted = _edge_for(tmp_path, lead_ms, f"song:lead{lead_ms}")
    moved = shifted - baseline
    assert shifted > baseline, "a negative lead did not fire later"
    assert moved == pytest.approx(abs(lead_ms), abs=TOLERANCE_MS), (
        f"lead {lead_ms}ms moved the light edge by {moved:.1f}ms")


def test_the_worked_example_from_the_conventions_row_lands_on_the_light(tmp_path):
    """End to end, in his own units: a room measured at +120 ms BEHIND,
    calibrated through the real translation, must land its light edge
    120 ms earlier than the uncalibrated room did.

    This is the whole feature in one assertion — the measurement, the
    add-don't-assign translation, the setting, the single application
    point, and the rendered light."""
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(
        {"ok": True, "av_offset_ms": 120.0, "sigma_ms": 9.0,
         "systematic_bound_ms": 25.0, "statement": ""}, None)
    assert prop.applicable and prop.proposed_lead_ms == 120
    assert prop.direction_sentence == "Lights will fire 120 ms EARLIER than they do now."

    baseline = _edge_for(tmp_path, None, "song:worked-base")
    applied = _edge_for(tmp_path, prop.proposed_lead_ms, "song:worked-applied")
    assert (baseline - applied) == pytest.approx(120, abs=TOLERANCE_MS)
