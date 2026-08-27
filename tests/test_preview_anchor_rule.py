"""The flare scrubbing-preview honours the DROP START anchor (2026-08-27,
fm/flare-preview-offsets-everywhere).

THE GAP: trigger_engine._response_switch_lead_ms decides which of the three
settled anchor families governs a fire from its EVENT CLASS — `event_class
== "drop"` returns 0 unconditionally, ahead of every other branch, because
"an explosion begins on the trigger mark rather than before it" (his
ruling, settled 2026-08-20). scene_response.kind_lead_ms is class-BLIND by
construction: it answers "what would this kind need under the MOMENTARY
END-anchor rule". Its own docstring justified that with "a flare kind
previewed in isolation is never a drop/explosion, only ever the momentary/
permanent/dice/gain/color_rotate family" — a statement about the kind's
TYPE, which is not the question: a MOMENTARY kind attached to a DROP band
fires under the drop rule.

So a momentary, registry-smooth kind attached only to drop bands previewed
as firing DICE_REROLL_GLIDE_MS early while production fired it with zero
lead. The preview lying about when his flare lands is the one thing the
preview exists not to do. Latent rather than live in his stored data (no
real drop band attaches a qualifying kind today) — closed for exactly the
reason _response_switch_lead_ms made its own drop branch unconditional
rather than resting on that fact.

The proof below runs the REAL preview builder against the REAL response
engine (no re-derived timing) and pins the divergence in both directions:
the same kind, same intensity, same virtuals, differing ONLY in which
band attaches it.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    for name, fn in (("SPECTRA_STORAGE", ""), ("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("FIRE_HISTORY_FILE", "fire_history.json"),
                     ("SHOW_LOG_FILE", "show_log.json"),
                     ("COLOR_SETS_FILE", "color_sets.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn if fn else tmp_path)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


VID = "v1"


def _scene(*, attach_to: str | None):
    """The SAME kind — a momentary move onto radial's registry-smooth
    `spin` — attached to whichever class the caller names (or nowhere)."""
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kind = FlareKind(name="spin-flare", type="momentary",
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    responses = {}
    if attach_to is not None:
        responses[attach_to] = ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"spin-flare": 1.0})])
    scene = SceneV2(
        name=f"Anchor scene ({attach_to})",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial", params={"spin": 0.2})],
        flare_kinds=[kind], responses=responses)
    return scene, kind


def _timeline(scene, kind, intensity=0.8):
    from spectra.services import flare_preview
    return asyncio.run(flare_preview.build_timeline(scene, kind, intensity))


# ═══ 1. the anchor rule itself ═════════════════════════════════════════════

def test_kind_attached_only_to_drop_takes_the_drop_start_anchor():
    from spectra.services.scene_response import (ANCHOR_DROP_START,
                                                 kind_anchor_rule)
    scene, kind = _scene(attach_to="drop")
    assert kind_anchor_rule(scene, kind) == ANCHOR_DROP_START


def test_kind_attached_to_a_flare_band_keeps_the_switch_end_anchor():
    from spectra.services.scene_response import (ANCHOR_SWITCH_END,
                                                 kind_anchor_rule)
    scene, kind = _scene(attach_to="flare")
    assert kind_anchor_rule(scene, kind) == ANCHOR_SWITCH_END


def test_kind_attached_nowhere_keeps_the_switch_end_anchor():
    """Declared-but-unattached is his data's common case (a script declares,
    a human attaches later from the lane rack). Isolated has no class, so
    the momentary rule — what fire_kind actually simulates — is the honest
    answer, never the drop exception applied speculatively."""
    from spectra.services.scene_response import (ANCHOR_SWITCH_END,
                                                 kind_anchor_rule)
    scene, kind = _scene(attach_to=None)
    assert kind_anchor_rule(scene, kind) == ANCHOR_SWITCH_END


def test_a_mixed_attachment_keeps_the_switch_end_anchor():
    """A kind on BOTH a flare and a drop band really does fire early under
    its flare band; reporting the momentary lead is the conservative
    reading, with the drop exception named alongside it via
    attached_classes rather than silently applied to both."""
    from spectra.models.scene import FlareBand, ResponseSpec
    from spectra.services.scene_response import (ANCHOR_SWITCH_END,
                                                 kind_anchor_rule)
    scene, kind = _scene(attach_to="drop")
    scene.responses["flare"] = ResponseSpec(bands=[
        FlareBand(intensity_min=0.0, intensity_max=1.0,
                  kinds={"spin-flare": 1.0})])
    assert kind_anchor_rule(scene, kind) == ANCHOR_SWITCH_END


# ═══ 2. the preview timeline, through the REAL builder ═════════════════════

def test_drop_attached_kind_previews_with_zero_lead_and_fires_on_the_anchor():
    scene, kind = _scene(attach_to="drop")
    tl = _timeline(scene, kind)
    assert tl["anchor_rule"] == "drop_start"
    assert tl["attached_classes"] == ["drop"]
    assert tl["lead_ms"] == 0, "a drop BEGINS on the mark — never a head start"
    assert tl["fire_at_s"] == pytest.approx(tl["animation_anchor_s"], abs=1e-6)


def test_the_same_kind_on_a_flare_band_previews_with_the_momentary_lead():
    from spectra.services.scene_response import DICE_REROLL_GLIDE_MS
    scene, kind = _scene(attach_to="flare")
    tl = _timeline(scene, kind)
    assert tl["anchor_rule"] == "switch_end"
    assert tl["lead_ms"] == DICE_REROLL_GLIDE_MS
    assert tl["fire_at_s"] == pytest.approx(
        tl["animation_anchor_s"] - DICE_REROLL_GLIDE_MS / 1000.0, abs=1e-6)


def test_the_two_timelines_differ_only_in_which_band_attaches_the_kind():
    """The divergence is the whole finding: identical kind, identical
    intensity, identical virtuals — a different fire moment, because the
    ANCHOR FAMILY is a property of the class, not of the kind."""
    drop_tl = _timeline(*_scene(attach_to="drop"))
    flare_tl = _timeline(*_scene(attach_to="flare"))
    assert drop_tl["fire_at_s"] > flare_tl["fire_at_s"]
    assert drop_tl["animation_anchor_s"] == flare_tl["animation_anchor_s"]


def test_the_preview_lead_matches_what_the_engine_would_compute_for_that_class():
    """The claim that actually matters: preview lead == production lead,
    read from trigger_engine._response_switch_lead_ms itself (the real
    dispatcher), for both classes — never two independent numbers that
    happen to agree today."""
    from types import SimpleNamespace
    from spectra.services import engine as engine_mod
    from spectra.services.trigger_engine import TriggerEngine

    for cls in ("drop", "flare"):
        scene, kind = _scene(attach_to=cls)
        tl = _timeline(scene, kind)
        eng = TriggerEngine(render_intensity=lambda raw: raw)
        virtuals = {VID: SimpleNamespace(effect_type="radial",
                                         param_baseline={"spin": 0.2})}
        eng._active_scene = staticmethod(lambda: scene)
        eng._live_virtuals = staticmethod(lambda: virtuals)
        production = eng._response_switch_lead_ms(
            SimpleNamespace(event_class=cls, intensity=0.8))
        assert tl["lead_ms"] == production, (
            f"{cls}: preview {tl['lead_ms']}ms vs production {production}ms")
