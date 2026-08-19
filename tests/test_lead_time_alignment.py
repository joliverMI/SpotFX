"""Unit-level coverage for the intensity-scaled/lead-time-alignment build
(his ask, 2026-08-19): the ported services/transition_phases.py registry,
room_controls.scene_transition_ms's linear interpolation + fire_scene's
fallback chain, and scene_response.momentary_switch_would_glide's read-only
peek. Frame-level proof (the actual glide landing on the trigger, at the
correct frame) lives in tests/test_trigger_engine.py; production-wiring
proof against real scene/room state lives in scripts/check_triggers.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from spectra.services import transition_phases


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
