"""Unit-level coverage for the intensity-scaled/lead-time-alignment build
(his ask, 2026-08-19): the ported services/transition_phases.py registry,
room_controls.scene_transition_ms's linear interpolation + fire_scene's
fallback chain, and scene_response.momentary_switch_would_glide's read-only
peek. Frame-level proof (the actual glide landing on the trigger, at the
correct frame) lives in tests/test_trigger_engine.py; production-wiring
proof against real scene/room state lives in scripts/check_triggers.py.

The LOOKAHEAD section below (2026-08-19, same day) covers the early-
commitment/reuse-at-fire pin mechanism for an UNRESOLVED fire_scene trigger
(scene_id=None — every one of his real triggers) — see trigger_engine.py's
own LOOKAHEAD module-docstring section for the full design and the danger
it's built against.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from spectra.services import transition_phases


def _run(coro):
    return asyncio.run(coro)


# ═══ transition_phases (ported registry) ════════════════════════════════

def test_registered_pair_keeps_legacy_anchor():
    assert transition_phases.anchor_frac("blackhole", "radial") == 0.45
    assert transition_phases.anchor_frac("radial", "orbits") == 0.45
    assert transition_phases.anchor_frac("pacman", "fireworks") == 0.45


def test_unregistered_pair_and_same_type_are_zero():
    # anchor_frac's OWN fallback stays legacy's 0.0 — the caller (trigger_
    # engine._scene_transition_lead_ms) applies the 0.5 generalization,
    # not this ported module (see its own docstring).
    assert transition_phases.anchor_frac("concentric", "radial") == 0.0
    assert transition_phases.anchor_frac("radial", "radial") == 0.0
    assert transition_phases.anchor_frac(None, "radial") == 0.0
    assert transition_phases.anchor_frac("radial", None) == 0.0


def test_lead_ms_scales_by_crossfade_and_caps_at_max():
    assert transition_phases.lead_ms("blackhole", "radial", 1000) == 450
    assert transition_phases.lead_ms("blackhole", "radial", 0) == 0
    assert transition_phases.lead_ms("concentric", "radial", 1000) == 0
    # MAX_LEAD_MS caps an absurdly long configured crossfade
    assert transition_phases.lead_ms("blackhole", "radial", 100_000) == \
        transition_phases.MAX_LEAD_MS


def test_find_is_directional_not_a_symmetric_relation():
    # pacman->blackhole is registered (pacman->particles' to_types includes
    # every particle effect); blackhole->pacman is NOT — there's no
    # particles->pacman entry, matching legacy exactly (the maze-fade
    # choreography only ever plays one direction).
    assert transition_phases.find("pacman", "blackhole") is not None
    assert transition_phases.find("blackhole", "pacman") is None


# ═══ room_controls.scene_transition_ms (linear interpolation) ═══════════

def test_scene_transition_ms_interpolates_linearly_between_bounds():
    from spectra.services import room_controls as rc

    state = rc.RoomControlState(scene_transition_ms_gentle=300,
                                scene_transition_ms_hard=200)
    assert rc.scene_transition_ms(state, 0.0) == 300
    assert rc.scene_transition_ms(state, 1.0) == 200
    assert rc.scene_transition_ms(state, 0.5) == 250


def test_scene_transition_ms_clamps_out_of_range_intensity():
    from spectra.services import room_controls as rc

    state = rc.RoomControlState(scene_transition_ms_gentle=300,
                                scene_transition_ms_hard=200)
    assert rc.scene_transition_ms(state, -1.0) == 300
    assert rc.scene_transition_ms(state, 2.0) == 200


def test_scene_transition_ms_default_bounds_match_his_named_numbers():
    from spectra.services import room_controls as rc

    state = rc.RoomControlState()
    # his named numbers, wired the physically sensible way: low intensity
    # (0.0) gets the LONGER 300ms transition, high intensity (1.0) the
    # SHORTER 200ms one — see room_controls.py's own docstring for the
    # naming/inversion reasoning.
    assert (state.scene_transition_ms_gentle, state.scene_transition_ms_hard) == (300, 200)


def test_fire_scene_falls_back_to_intensity_scaled_bounds_when_nothing_else_is_set(
    monkeypatch,
):
    """scene.entry_ramp_ms (0) then room.global_transition_ms (0, the
    unmodified default) both fall through to the NEW default —
    room_controls.scene_transition_ms, computed at the fire's own
    intensity — instead of the old flat instant-jump (0ms) behaviour."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler

    rc.save_room_controls(rc.RoomControlState())   # every default, untouched

    scene = SceneV2(name="Fresh Default", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="radial",
        params={}, brightness=0.8)])

    captured = {}

    async def fake_apply_writes(writes, *, transition_ms=0):
        captured["transition_ms"] = transition_ms

    def fake_on_scene_fired(scene, writes, set_id):
        pass

    monkeypatch.setattr(scene_compiler.fx_seam, "apply_writes", fake_apply_writes)
    monkeypatch.setattr("spectra.services.engine.on_scene_fired", fake_on_scene_fired)

    import asyncio
    asyncio.run(scene_compiler.fire_scene(scene, intensity=0.0, dry_run=False))
    assert captured["transition_ms"] == 300, \
        "intensity 0.0 -> the gentle (longer) bound, the new default fallback"

    asyncio.run(scene_compiler.fire_scene(scene, intensity=1.0, dry_run=False))
    assert captured["transition_ms"] == 200, \
        "intensity 1.0 -> the hard (shorter) bound"


def test_fire_scene_global_transition_ms_still_wins_over_the_new_default(
    monkeypatch,
):
    """An explicit flat global_transition_ms (his past manual override, if
    he ever set one) still wins over the intensity-scaled bounds — the new
    default only kicks in when he's never touched it (0, unmodified)."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler

    rc.save_room_controls(rc.RoomControlState(global_transition_ms=1500))

    scene = SceneV2(name="Manual Override", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="radial", params={})])

    captured = {}

    async def fake_apply_writes(writes, *, transition_ms=0):
        captured["transition_ms"] = transition_ms

    monkeypatch.setattr(scene_compiler.fx_seam, "apply_writes", fake_apply_writes)
    monkeypatch.setattr("spectra.services.engine.on_scene_fired", lambda *a: None)

    import asyncio
    asyncio.run(scene_compiler.fire_scene(scene, intensity=1.0, dry_run=False))
    assert captured["transition_ms"] == 1500, \
        "an explicit flat override wins regardless of intensity"


# ═══ scene_response.momentary_switch_would_glide (read-only peek) ═══════

def _scene_with_momentary(param_target, band_range=(0.5, 1.0)):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    lo, hi = band_range
    return SceneV2(
        name="Momentary Probe",
        devices=[SceneDeviceConfig(target_kind="virtual", target="v1",
                                   effect_type="concentric", params={})],
        flare_kinds=[FlareKind(name="Pulse", type="momentary",
                               params={"gradient_scale": param_target})],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=lo, intensity_max=hi, kinds={"Pulse": 1.0})])})


def test_momentary_smooth_param_would_glide():
    from spectra.models.scene import ParamTarget
    from spectra.services.scene_response import momentary_switch_would_glide

    scene = _scene_with_momentary(ParamTarget(mode="absolute", value=1.8))
    virtuals = {"v1": SimpleNamespace(effect_type="concentric")}
    # gradient_scale is registry smooth=true on concentric (same param
    # test_trigger_engine.py's own proofs use).
    assert momentary_switch_would_glide(scene, "flare", 0.8, virtuals) is True


def test_permanent_kind_never_counts_as_a_momentary_switch():
    from spectra.models.scene import FlareBand, FlareKind, ParamTarget, ResponseSpec, SceneDeviceConfig, SceneV2
    from spectra.services.scene_response import momentary_switch_would_glide

    scene = SceneV2(
        name="Permanent Probe",
        devices=[SceneDeviceConfig(target_kind="virtual", target="v1",
                                   effect_type="concentric", params={})],
        flare_kinds=[FlareKind(name="Patch", type="permanent",
                               params={"gradient_scale": ParamTarget(
                                   mode="absolute", value=1.8)})],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.5, intensity_max=1.0, kinds={"Patch": 1.0})])})
    virtuals = {"v1": SimpleNamespace(effect_type="concentric")}
    assert momentary_switch_would_glide(scene, "flare", 0.8, virtuals) is False


def test_momentary_gain_only_kind_never_glides_its_switch():
    """A momentary GAIN's spike is always an instant jump (scene_response.
    _gain) — a kind with no params, only a gain, has nothing to glide."""
    from spectra.models.scene import FlareBand, FlareKind, ResponseSpec, SceneDeviceConfig, SceneV2
    from spectra.services.scene_response import momentary_switch_would_glide

    scene = SceneV2(
        name="Gain Probe",
        devices=[SceneDeviceConfig(target_kind="virtual", target="v1",
                                   effect_type="concentric", params={})],
        flare_kinds=[FlareKind(name="Duck", type="momentary", gain=0.5)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.5, intensity_max=1.0, kinds={"Duck": 1.0})])})
    virtuals = {"v1": SimpleNamespace(effect_type="concentric")}
    assert momentary_switch_would_glide(scene, "flare", 0.8, virtuals) is False


def test_momentary_non_smooth_param_does_not_glide():
    """A momentary move onto a NON-smooth (toggle/enum/integer) param —
    e.g. blackhole's edges — still jumps; nothing to land early for."""
    from spectra.models.scene import ParamTarget
    from spectra.services.scene_response import momentary_switch_would_glide

    scene = _scene_with_momentary(ParamTarget(mode="absolute", value=6))
    scene.flare_kinds[0].params = {"edges": ParamTarget(mode="absolute", value=6)}
    virtuals = {"v1": SimpleNamespace(effect_type="blackhole")}
    assert momentary_switch_would_glide(scene, "flare", 0.8, virtuals) is False


def test_no_band_selected_means_no_glide():
    from spectra.models.scene import ParamTarget
    from spectra.services.scene_response import momentary_switch_would_glide

    scene = _scene_with_momentary(ParamTarget(mode="absolute", value=1.8),
                                  band_range=(0.7, 1.0))
    virtuals = {"v1": SimpleNamespace(effect_type="concentric")}
    assert momentary_switch_would_glide(scene, "flare", 0.2, virtuals) is False


def test_no_active_scene_or_no_responses_class_means_no_glide():
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services.scene_response import momentary_switch_would_glide

    bare = SceneV2(name="Bare", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="concentric")])
    virtuals = {"v1": SimpleNamespace(effect_type="concentric")}
    assert momentary_switch_would_glide(bare, "flare", 0.8, virtuals) is False


# ═══ LOOKAHEAD: early scene-pick commitment for scene_id=None triggers ═══
#
# The danger his ask names explicitly: a lookahead is a PREDICTION, and a
# prediction can be wrong. These prove the actual safety property is that
# there's only ever ONE draw for a given trigger (never a redraw to
# disagree with), plus that an invalidated pin degrades to today's exact
# behaviour (a fresh draw, fired late, never the stale/invalid scene).

@pytest.fixture()
def _iso(tmp_path, monkeypatch):
    """Isolates scene_store/room_controls storage, and detaches the lead
    calculation from the real spectra.services.engine singleton (every test
    below either forces crossfade_ms=0, never reaching the virtuals lookup,
    or doesn't care about the exact lead value — only which scene fires and
    how many times the kernel/pool was actually drawn from)."""
    from spectra import config as scfg
    from spectra.services.trigger_engine import TriggerEngine
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(TriggerEngine, "_live_virtuals", staticmethod(lambda: {}))


def _zero_crossfade_room():
    from spectra.services import room_controls as rc
    rc.save_room_controls(rc.RoomControlState(
        global_transition_ms=0, scene_transition_ms_gentle=0,
        scene_transition_ms_hard=0))


def test_lookahead_horizon_reuses_max_lead_ms_not_a_second_constant():
    from spectra.services import transition_phases
    from spectra.services.trigger_engine import LOOKAHEAD_HORIZON_MS
    assert LOOKAHEAD_HORIZON_MS == transition_phases.MAX_LEAD_MS, \
        "no lead this feature can ever compute exceeds MAX_LEAD_MS, so the " \
        "horizon must be at least that — and more buys nothing, so it's " \
        "exactly that, not a separately-tuned number"


def test_pin_for_resolves_once_and_caches_across_many_calls(_iso):
    from spectra.models.scene import SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services import scene_store
    from spectra.services.trigger_engine import TriggerEngine

    _zero_crossfade_room()
    scene = SceneV2(name="Pinned")
    scene_store.save(scene)

    calls = []

    def fake_select(intensity):
        calls.append(intensity)
        return scene.id

    trig = SpectraTrigger(timestamp_ms=6000,
                          action=FireSceneAction(scene_id=None, intensity=0.7))
    engine = TriggerEngine(select_scene=fake_select)

    pins = [engine._pin_for(trig) for _ in range(5)]
    assert len(calls) == 1, "the kernel is drawn from exactly once, not per call"
    assert all(p is not None and p.scene_id == scene.id for p in pins), \
        "every call reuses the SAME committed pick"


def test_pin_for_caches_a_negative_result_without_retrying(_iso):
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    _zero_crossfade_room()
    calls = []

    def fake_select(intensity):
        calls.append(intensity)
        return None  # ladder terminated at stay

    trig = SpectraTrigger(timestamp_ms=6000,
                          action=FireSceneAction(scene_id=None, intensity=0.5))
    engine = TriggerEngine(select_scene=fake_select)

    for _ in range(5):
        assert engine._pin_for(trig) is None
    assert len(calls) == 1, \
        "a 'nothing to fire' draw is never retried — repeating it would " \
        "quietly raise how often this trigger fires at all, versus today's " \
        "single draw at the nominal time"


def test_resolved_scene_id_trigger_never_touches_the_pin_cache(_iso):
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    trig = SpectraTrigger(timestamp_ms=6000, action=FireSceneAction(
        scene_id="already-known", intensity=0.5))
    engine = TriggerEngine()
    assert engine._pin_for(trig) is None
    assert engine._pins == {}, \
        "a hand-picked scene_id needs no lookahead — _pin_for is a no-op " \
        "and caches nothing for it"


def test_fire_reuses_the_pinned_scene_never_redrawing_at_fire_time(_iso):
    from spectra.models.scene import SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services import scene_store
    from spectra.services.trigger_engine import LOOKAHEAD_HORIZON_MS, TriggerEngine

    _zero_crossfade_room()
    scene = SceneV2(name="Committed")
    scene_store.save(scene)

    draw_calls = []

    def fake_select(intensity):
        draw_calls.append(intensity)
        return scene.id

    fired = []

    async def fake_fire_scene(scene_id, color_set_id, intensity):
        fired.append(scene_id)

    trig = SpectraTrigger(timestamp_ms=6000,
                          action=FireSceneAction(scene_id=None, intensity=0.7))
    engine = TriggerEngine(list_triggers=lambda uri: [trig],
                           select_scene=fake_select,
                           fire_scene=fake_fire_scene,
                           render_intensity=lambda x: x)
    _run(engine.on_track_state("song:committed"))

    # Step ticks at TICK_S's own 200ms cadence, song start to the trigger's
    # nominal timestamp — the same way services/engine.py's poll loop
    # actually drives tick(), rather than jumping straight to one boundary
    # (tick()'s crossing check reads the PREVIOUS tick's position, so the
    # exact tick a guard flips on is a step-cadence detail, not the thing
    # this test is proving).
    horizon_entry = 6000 - LOOKAHEAD_HORIZON_MS
    result = []
    for pos in range(0, 6001, 200):
        result = _run(engine.tick(pos))
        if pos <= horizon_entry - 200:
            assert draw_calls == [], f"nothing resolved yet at {pos}, still outside the horizon"
        elif pos >= horizon_entry + 400:
            assert len(draw_calls) == 1, f"resolved once by {pos}, inside the horizon"
    assert len(result) == 1 and fired == [scene.id]
    assert len(draw_calls) == 1, \
        "the fire reused the pinned pick verbatim — one draw, total, for " \
        "the whole trigger's lifetime"


def test_invalidated_pin_degrades_to_a_fresh_draw_never_fires_the_stale_scene(_iso):
    """The core misprediction guarantee: a scene pinned early, then made
    illegitimate to fire (disabled) before the trigger crosses, must NEVER
    be the thing that fires — the trigger instead gets a fresh, correct
    draw, late (zero lead) but right, exactly today's behaviour."""
    from spectra.models.scene import SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services import scene_store
    from spectra.services.trigger_engine import LOOKAHEAD_HORIZON_MS, TriggerEngine

    _zero_crossfade_room()
    stale = SceneV2(name="Will Be Disabled")
    fallback = SceneV2(name="Fresh Fallback")
    scene_store.save(stale)
    scene_store.save(fallback)

    draw_calls = []
    picks = [stale.id, fallback.id]

    def fake_select(intensity):
        draw_calls.append(intensity)
        return picks[len(draw_calls) - 1]

    fired = []

    async def fake_fire_scene(scene_id, color_set_id, intensity):
        fired.append(scene_id)

    trig = SpectraTrigger(timestamp_ms=6000,
                          action=FireSceneAction(scene_id=None, intensity=0.5))
    engine = TriggerEngine(list_triggers=lambda uri: [trig],
                           select_scene=fake_select,
                           fire_scene=fake_fire_scene,
                           render_intensity=lambda x: x)
    _run(engine.on_track_state("song:invalidated"))

    horizon_entry = 6000 - LOOKAHEAD_HORIZON_MS
    for pos in range(0, horizon_entry + 401, 200):
        _run(engine.tick(pos))
    assert len(draw_calls) == 1, "the pin's own resolve draw happened"
    assert engine._pins[trig.id].scene_id == stale.id

    # the world moves: the pinned scene gets disabled before the trigger fires.
    stale.disabled = True
    scene_store.save(stale)

    result = _run(engine.tick(6000))
    assert len(result) == 1
    assert fired == [fallback.id], \
        "never the disabled, stale pick — a fresh draw supplied the " \
        "correct alternative instead"
    assert len(draw_calls) == 2, \
        "exactly one extra draw happened, at fire time, because the " \
        "pinned commitment was no longer valid to reuse"


def test_pin_still_valid_checks_disabled_mode_availability_and_force_scene(_iso):
    from spectra.models.scene import SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_store
    from spectra.services.trigger_engine import TriggerEngine, _PinnedPick

    scene = SceneV2(name="Guarded")
    scene_store.save(scene)
    rc.save_room_controls(rc.RoomControlState())
    engine = TriggerEngine()
    pin = _PinnedPick(scene_id=scene.id, lead_ms=0, force_scene=(False, None))
    assert engine._pin_still_valid(pin) is True

    scene.disabled = True
    scene_store.save(scene)
    assert engine._pin_still_valid(pin) is False, "a disabled scene invalidates the pin"
    scene.disabled = False
    scene_store.save(scene)
    assert engine._pin_still_valid(pin) is True

    scene.display_availability = "dark"
    scene_store.save(scene)
    rc.save_room_controls(rc.RoomControlState(display_mode="light"))
    assert engine._pin_still_valid(pin) is False, \
        "a room mode the scene is no longer available in invalidates the pin"
    rc.save_room_controls(rc.RoomControlState())
    scene.display_availability = "default"
    scene_store.save(scene)
    assert engine._pin_still_valid(pin) is True

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="some-other-scene"))
    assert engine._pin_still_valid(pin) is False, \
        "Force Scene changing since the pin was made invalidates it too " \
        "(timing-quality only — see _PinnedPick.force_scene's docstring)"


def test_rewind_clears_every_pin(_iso):
    from spectra.models.scene import SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services import scene_store
    from spectra.services.trigger_engine import LOOKAHEAD_HORIZON_MS, TriggerEngine

    _zero_crossfade_room()
    scene = SceneV2(name="Rewind Target")
    scene_store.save(scene)
    trig = SpectraTrigger(timestamp_ms=6000,
                          action=FireSceneAction(scene_id=None, intensity=0.5))
    engine = TriggerEngine(list_triggers=lambda uri: [trig],
                           select_scene=lambda i: scene.id)
    _run(engine.on_track_state("song:rewind"))
    horizon_entry = 6000 - LOOKAHEAD_HORIZON_MS
    for pos in range(0, horizon_entry + 401, 200):
        _run(engine.tick(pos))
    assert engine._pins, "the trigger got pinned"

    _run(engine.tick(500))  # a big rewind, well before the pinned position
    assert engine._pins == {}, "a rewind drops every pin rather than trust a stale one"


def test_song_change_clears_every_pin(_iso):
    from spectra.models.scene import SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services import scene_store
    from spectra.services.trigger_engine import LOOKAHEAD_HORIZON_MS, TriggerEngine

    _zero_crossfade_room()
    scene = SceneV2(name="Old Song Target")
    scene_store.save(scene)
    trig = SpectraTrigger(timestamp_ms=6000,
                          action=FireSceneAction(scene_id=None, intensity=0.5))
    engine = TriggerEngine(list_triggers=lambda uri: [trig] if uri == "song:a" else [],
                           select_scene=lambda i: scene.id)
    _run(engine.on_track_state("song:a"))
    horizon_entry = 6000 - LOOKAHEAD_HORIZON_MS
    for pos in range(0, horizon_entry + 401, 200):
        _run(engine.tick(pos))
    assert engine._pins, "the trigger got pinned on song:a"

    _run(engine.on_track_state("song:b"))
    assert engine._pins == {}, \
        "a new song's trigger list is unrelated — the old pin is dead weight"
