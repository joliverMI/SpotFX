"""The CHARGE / LULL / DROP SEQUENCE scrubbing preview (2026-08-27,
fm/flare-preview-offsets-everywhere) — the second half he deferred with
"start with the flares, then we will do lull charge drop".

What has to be true, asserted rather than described:

  * each ramp is production's own — scene_response._phase_ramp_ms, the
    function the show calls — including the 2026-08-20 dynamic STRETCH to
    ~90% of the real gap, with the remaining ~10% drawn as a HANG. That
    hang is his own spec ("the single blob waiting in lull should reach the
    center just and hang for just a moment, maybe 10% of the lull time"),
    and the ruler existing to show it is the point of this preview;
  * DROP IS NEVER STRETCHED, and its anchor is its START — lead 0,
    unconditionally, ahead of every other branch, exactly as
    trigger_engine._response_switch_lead_ms does it. Asserted against that
    method itself, not against a second expectation;
  * charge and lull keep the END anchor: his 2026-08-20 settlement was
    about drop specifically and "must not leak into" the wider phase
    family;
  * each mark honours its band's authored FlareKind.trigger_offset_ms in
    HIS sign, the same relocation tick() performs;
  * the SERVER computes every cue time.
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


def _scene(*, effect_type="blackhole", kinds=None, attach=None):
    """A phase-capable scene. `attach` maps a response class to the kinds
    its single full-range band carries."""
    from spectra.models.scene import (FlareBand, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    responses = {}
    for cls, kind_names in (attach or {}).items():
        responses[cls] = ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0,
            kinds={n: 1.0 for n in kind_names})])
    return SceneV2(
        name="Phase Scene",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type=effect_type,
                                   params={"spin": 0.2})],
        flare_kinds=list(kinds or []), responses=responses)


def _timeline(scene, intensity=0.7, **kw):
    from spectra.services import phase_preview
    return asyncio.run(phase_preview.build_timeline(scene, intensity, **kw))


def _marks(tl):
    return {m["event_class"]: m for m in tl["marks"]}


# ═══ 1. the ramps are production's own, stretch included ═══════════════════

def test_each_ramp_is_scene_responses_own_phase_ramp():
    from spectra.services.phase_preview import DEFAULT_GAP_MS
    from spectra.services.scene_response import _phase_ramp_ms
    tl = _timeline(_scene())
    for cls, m in _marks(tl).items():
        assert m["ramp_ms"] == _phase_ramp_ms(cls, DEFAULT_GAP_MS.get(cls))


def test_charge_and_lull_stretch_to_the_gap_and_hang_the_rest():
    from spectra.services.scene_response import PHASE_RAMP_HANG_FRACTION
    tl = _timeline(_scene(), gaps={"charge": 8000, "lull": 6000})
    marks = _marks(tl)
    for cls, gap in (("charge", 8000), ("lull", 6000)):
        m = marks[cls]
        assert m["stretched"] is True
        assert m["ramp_ms"] == round(gap * (1.0 - PHASE_RAMP_HANG_FRACTION))
        assert m["hang_ms"] == gap - m["ramp_ms"]
        # his own words: "hang for just a moment, maybe 10% of the lull time"
        assert m["hang_ms"] == pytest.approx(gap * PHASE_RAMP_HANG_FRACTION, rel=0.02)


def test_a_longer_gap_really_produces_a_longer_ramp():
    """The stretch is the whole reason this ruler exists — a single tuned
    constant could not fit his own two real lull gaps on one song (6040ms
    and 900ms), which is why the per-scene knob was retired for it."""
    short = _marks(_timeline(_scene(), gaps={"lull": 900}))["lull"]
    long = _marks(_timeline(_scene(), gaps={"lull": 6040}))["lull"]
    assert long["ramp_ms"] > short["ramp_ms"] * 5


def test_the_defaults_reproduce_the_tuned_unknown_gap_ramps():
    """Opening the preview shows the shape the show falls back to when the
    gap is unknowable — so the default is derived from PHASE_RAMP_MS, never
    a fourth number to keep in sync."""
    from spectra.services.scene_response import PHASE_RAMP_MS
    tl = _timeline(_scene())
    marks = _marks(tl)
    assert marks["charge"]["ramp_ms"] == PHASE_RAMP_MS["charge"]
    assert marks["lull"]["ramp_ms"] == PHASE_RAMP_MS["lull"]


def test_drop_is_never_stretched_and_never_hangs():
    from spectra.services.scene_response import PHASE_RAMP_MS
    tl = _timeline(_scene(), gaps={"charge": 9000, "lull": 9000})
    drop = _marks(tl)["drop"]
    assert drop["stretched"] is False
    assert drop["ramp_ms"] == PHASE_RAMP_MS["drop"]
    assert drop["hang_ms"] == 0


# ═══ 2. the anchors, and that they match the firing path ═══════════════════

def test_the_drop_begins_on_its_mark():
    tl = _timeline(_scene())
    drop = _marks(tl)["drop"]
    assert drop["anchor_rule"] == "drop_start"
    assert drop["lead_ms"] == 0
    assert drop["fire_at_s"] == drop["mark_s"]
    assert drop["ramp_start_s"] == drop["mark_s"]


def test_charge_and_lull_keep_the_end_anchor_family():
    tl = _timeline(_scene())
    for cls in ("charge", "lull"):
        assert _marks(tl)[cls]["anchor_rule"] == "switch_end"


def test_every_class_lead_matches_the_firing_paths_own():
    """Including the case that would have caught a drop leak: a momentary,
    registry-smooth kind attached to EVERY class. Charge and lull take
    DICE_REROLL_GLIDE_MS; drop still takes zero, structurally."""
    from types import SimpleNamespace
    from spectra.models.scene import FlareKind, ParamTarget
    from spectra.services.phase_preview import class_lead_ms
    from spectra.services.scene_response import DICE_REROLL_GLIDE_MS
    from spectra.services.trigger_engine import TriggerEngine

    kind = FlareKind(name="spin-flare", type="momentary",
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    scene = _scene(effect_type="radial", kinds=[kind],
                   attach={c: ["spin-flare"] for c in ("charge", "lull", "drop")})
    virtuals = {VID: SimpleNamespace(effect_type="radial",
                                     param_baseline={"spin": 0.2})}
    eng = TriggerEngine(render_intensity=lambda raw: raw)
    eng._active_scene = staticmethod(lambda: scene)
    eng._live_virtuals = staticmethod(lambda: virtuals)

    for cls in ("charge", "lull", "drop"):
        mine = class_lead_ms(scene, cls, 0.7, virtuals)
        production = eng._response_switch_lead_ms(
            SimpleNamespace(event_class=cls, intensity=0.7))
        assert mine == production, f"{cls}: {mine} vs production {production}"
    assert class_lead_ms(scene, "charge", 0.7, virtuals) == DICE_REROLL_GLIDE_MS
    assert class_lead_ms(scene, "drop", 0.7, virtuals) == 0, (
        "a drop must take zero lead even with a qualifying kind attached — "
        "structurally, not because his data happens not to have one")


# ═══ 3. authored offsets relocate the marks, in his sign ═══════════════════

def test_a_bands_authored_offset_moves_that_classs_mark_earlier():
    from spectra.models.scene import FlareKind, ParamTarget
    kind = FlareKind(name="k", type="momentary", trigger_offset_ms=-400,
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    plain = _timeline(_scene())
    shifted = _timeline(_scene(kinds=[kind], attach={"drop": ["k"]}))
    assert _marks(shifted)["drop"]["trigger_offset_ms"] == -400
    assert (_marks(shifted)["drop"]["mark_ms"]
            == _marks(plain)["drop"]["mark_ms"] - 400)


def test_a_drop_bands_authored_offset_is_honoured_even_though_its_lead_is_zero():
    """The distinction the firing path already draws and this ruler must
    not blur: the drop rule pins the AUTOMATIC anchor-family lead, never
    his explicit hand on a marker."""
    from spectra.models.scene import FlareKind, ParamTarget
    kind = FlareKind(name="k", type="momentary", trigger_offset_ms=-350,
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    tl = _timeline(_scene(effect_type="radial", kinds=[kind],
                          attach={"drop": ["k"]}))
    drop = _marks(tl)["drop"]
    assert drop["trigger_offset_ms"] == -350
    assert drop["lead_ms"] == 0
    assert drop["fire_at_s"] == drop["mark_s"]


# ═══ 4. the SERVER computes every cue, and the marks are ordered ═══════════

def test_cues_cover_every_step_with_server_computed_times():
    from spectra.services.phase_preview import PhaseSequenceProgram
    tl = _timeline(_scene())
    steps = {c["step"]: c["at_s"] for c in tl["cues"]}
    assert set(steps) == set(PhaseSequenceProgram.steps)
    for m in tl["marks"]:
        assert steps[m["event_class"]] == m["fire_at_s"]
    assert steps["release"] < tl["duration_s"]
    assert steps["release"] > steps["drop"]


def test_the_sequence_runs_charge_then_lull_then_drop_and_fits_the_ruler():
    tl = _timeline(_scene())
    order = [m["event_class"] for m in tl["marks"]]
    assert order == ["charge", "lull", "drop"]
    times = [m["mark_s"] for m in tl["marks"]]
    assert times == sorted(times)
    assert all(0 <= m["fire_at_s"] < tl["duration_s"] for m in tl["marks"])


def test_a_scene_with_no_phase_capable_effect_says_so_rather_than_pretending():
    """concentric is not in PHASE_EFFECTS, so the sequence would drive
    nothing — the overlay needs to say that instead of looping an
    invisible preview."""
    tl = _timeline(_scene(effect_type="concentric"))
    assert tl["phase_targets"] == []
    assert _timeline(_scene())["phase_targets"] == [VID]
