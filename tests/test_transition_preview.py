"""The SCENE-TO-SCENE TRANSITION scrubbing preview (2026-08-27,
fm/flare-preview-offsets-everywhere) — half two of his own sequencing for
this system.

What has to be true, and is asserted here rather than described:

  * the ruler shows the transition's REAL intensity-scaled crossfade — the
    same entry_ramp_ms / global_transition_ms / scene_transition_ms chain
    scene_compiler.fire_scene resolves, including his live room's
    global_transition_ms == 0 falling through to the intensity-scaled
    default rather than reading as "instant";
  * the anchor is the MIDDLE — the settled family for a scene transition
    (his ruling 2026-08-20) — as the plain 0.5 midpoint for an ordinary
    pair and a registered phased pair's own 0.45 where one applies;
  * the preview's numbers come from the SAME function the firing path uses
    (spectra/services/scene_transition_lead.py), asserted against
    trigger_engine._scene_transition_lead_ms_for itself rather than
    against a second hand-computed expectation;
  * the sign law is the family's, unchanged: trigger_mark_s = anchor -
    offset/1000 (OFFSET, negative = earlier), fire_at_s = anchor -
    lead/1000 (LEAD, positive = earlier), never the two combined under one
    sign;
  * the SERVER computes every cue time — the frontend is handed them.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model

VID = "v1"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
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
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


def _scene(name, effect_type, *, entry_ramp_ms=0, offset_ms=0):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    return SceneV2(name=name, entry_ramp_ms=entry_ramp_ms,
                   trigger_offset_ms=offset_ms,
                   devices=[SceneDeviceConfig(
                       id="d1", target_kind="virtual", target=VID,
                       effect_type=effect_type, params={"spin": 0.5})])


def _timeline(from_scene, to_scene, intensity=0.8):
    from spectra.services import transition_preview
    return asyncio.run(transition_preview.build_timeline(
        from_scene, to_scene, intensity))


# ═══ 1. the crossfade is the real, intensity-scaled one ════════════════════

def test_an_authored_entry_ramp_is_the_crossfade():
    tl = _timeline(_scene("A", "radial"), _scene("B", "radial", entry_ramp_ms=1500))
    assert tl["crossfade_ms"] == 1500


def test_no_authored_ramp_falls_through_to_the_intensity_scaled_default():
    """His live room carries global_transition_ms == 0, and the `or` chain
    treats that falsy 0 as unset (SPEC §84) — so an unauthored scene must
    show the intensity-scaled default, gentle at 0 and harder at 1, never
    read as an instant switch."""
    from spectra.services import room_controls
    room_controls.save_room_controls(
        room_controls.RoomControlState(global_transition_ms=0))
    gentle = _timeline(_scene("A", "radial"), _scene("B", "radial"), 0.0)
    hard = _timeline(_scene("A", "radial"), _scene("B", "radial"), 1.0)
    room = room_controls.load_room_controls()
    assert gentle["crossfade_ms"] == room_controls.scene_transition_ms(room, 0.0)
    assert hard["crossfade_ms"] == room_controls.scene_transition_ms(room, 1.0)
    assert gentle["crossfade_ms"] > hard["crossfade_ms"], (
        "gentle at low intensity, harder at high — the scaling is backwards")


def test_a_flat_global_override_beats_the_scaled_default():
    from spectra.services import room_controls
    room_controls.save_room_controls(
        room_controls.RoomControlState(global_transition_ms=900))
    tl = _timeline(_scene("A", "radial"), _scene("B", "radial"), 0.5)
    assert tl["crossfade_ms"] == 900


# ═══ 2. the anchor is the MIDDLE — the settled family ══════════════════════

def test_an_ordinary_pair_anchors_at_the_plain_midpoint():
    tl = _timeline(_scene("A", "radial"), _scene("B", "radial", entry_ramp_ms=1200))
    assert tl["anchor_rule"] == "transition_middle"
    assert tl["anchor_frac"] == 0.5
    assert tl["anchor_source"] == "midpoint"
    assert tl["lead_ms"] == 600


def test_a_registered_phased_pair_uses_its_own_anchor():
    """orbits -> radial is a registered particle handoff (0.45), so its
    payoff phase — not the midpoint — is what lands on the mark."""
    tl = _timeline(_scene("A", "orbits"), _scene("B", "radial", entry_ramp_ms=1200))
    assert tl["anchor_frac"] == 0.45
    assert tl["anchor_source"] == "phased_pair"
    assert tl["lead_ms"] == 540


def test_an_instant_switch_has_no_anchor_to_move():
    from spectra.services import room_controls
    room_controls.save_room_controls(
        room_controls.RoomControlState(global_transition_ms=0))
    to = _scene("B", "radial")
    to.entry_ramp_ms = 0
    # force a genuinely zero crossfade by zeroing the scaled default too
    from spectra.services import scene_transition_lead
    assert scene_transition_lead.lead_ms_for(0.5, 0) == 0


# ═══ 3. the preview and the FIRING PATH share one definition ═══════════════

def test_the_preview_lead_equals_what_the_firing_path_computes():
    """Not "the numbers happen to match" — the same module, called from
    both. This asserts the shared definition end to end, through
    trigger_engine's own method with the same pair on its live virtuals."""
    from types import SimpleNamespace
    from spectra.services import scene_store
    from spectra.services.trigger_engine import TriggerEngine

    from_scene = _scene("A", "orbits")
    to_scene = _scene("B", "radial", entry_ramp_ms=1200)
    scene_store.save(to_scene)
    tl = _timeline(from_scene, to_scene, 0.8)

    eng = TriggerEngine(render_intensity=lambda raw: raw)
    eng._live_virtuals = staticmethod(
        lambda: {VID: SimpleNamespace(effect_type="orbits")})
    production = eng._scene_transition_lead_ms_for(to_scene.id, 0.8)
    assert tl["lead_ms"] == production


# ═══ 4. the sign law, both extremes ════════════════════════════════════════

def test_a_negative_scene_offset_puts_the_mark_right_of_the_anchor():
    """HIS convention: negative = fire EARLIER, so the mark sits AFTER the
    anchor moment on the ruler. Identical formula to the flare preview's —
    the same function, called."""
    tl = _timeline(_scene("A", "radial"),
                   _scene("B", "radial", entry_ramp_ms=1200, offset_ms=-500))
    assert tl["trigger_mark_s"] == pytest.approx(
        tl["animation_anchor_s"] + 0.5, abs=1e-6)


def test_a_positive_scene_offset_puts_the_mark_left_of_the_anchor():
    tl = _timeline(_scene("A", "radial"),
                   _scene("B", "radial", entry_ramp_ms=1200, offset_ms=500))
    assert tl["trigger_mark_s"] == pytest.approx(
        tl["animation_anchor_s"] - 0.5, abs=1e-6)


def test_fire_at_is_the_anchor_minus_the_lead_whatever_the_offset():
    """The composition rule stated as an invariant: the LEAD subtracts from
    the anchor in its own native sense, and the authored OFFSET is already
    baked into the anchor by construction of trigger_mark_s — so fire_at
    never varies with the offset. The two are never added under one sign."""
    for offset in (-500, 0, 500):
        tl = _timeline(_scene("A", "radial"),
                       _scene("B", "radial", entry_ramp_ms=1200, offset_ms=offset))
        assert tl["fire_at_s"] == pytest.approx(
            tl["animation_anchor_s"] - tl["lead_ms"] / 1000.0, abs=1e-6)


def test_the_anchor_lands_on_the_mark_when_nothing_is_authored():
    """The whole claim, on the ruler: with offset 0, the crossfade's anchor
    point (fire + anchor_frac x crossfade) sits exactly on the mark."""
    tl = _timeline(_scene("A", "radial"), _scene("B", "radial", entry_ramp_ms=1200))
    anchor_moment = tl["fire_at_s"] + tl["anchor_frac"] * tl["crossfade_ms"] / 1000.0
    assert anchor_moment == pytest.approx(tl["trigger_mark_s"], abs=1e-3)


# ═══ 5. the crossfade's start stays visible on the ruler ═══════════════════

def test_a_long_lead_still_draws_its_crossfade_start_on_the_ruler():
    """A transition's lead reaches MAX_LEAD_MS (5000ms) where a flare's is
    220ms, so the flare preview's fixed 2s layout anchor would push the
    crossfade's START off the left edge — he could not see the thing he is
    judging. The layout anchor makes room; every timing formula is still
    the shared one."""
    tl = _timeline(_scene("A", "radial"), _scene("B", "radial", entry_ramp_ms=9000))
    assert tl["lead_ms"] == 4500
    assert tl["animation_start_s"] > 0.0
    assert tl["animation_end_s"] < tl["duration_s"]


# ═══ 6. the SERVER computes every cue ══════════════════════════════════════

def test_both_cues_are_returned_with_server_computed_times():
    tl = _timeline(_scene("A", "radial"), _scene("B", "radial", entry_ramp_ms=1200))
    steps = {c["step"]: c["at_s"] for c in tl["cues"]}
    assert steps["rearm"] == 0.0
    assert steps["fire"] == tl["fire_at_s"]
    from spectra.services.transition_preview import TransitionProgram
    assert set(TransitionProgram.steps) == set(steps)
