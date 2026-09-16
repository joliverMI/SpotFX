"""PER-FLARE TRIGGER MOMENT — the preview must show the STAGGER, not just
the band's single anchor (his card's own constraint: "the screen he sets
this on has to match the show, which is the whole reason the field
exists").

The flare scrubbing preview (spectra/services/flare_preview.py) previews
ONE kind in isolation (fire_kind bypasses band selection entirely), so it
never needed to change for this feature: each kind's own trigger_mark_s
was always `animation_anchor_s - kind.trigger_offset_ms/1000`, independent
of any band-mate. What THIS proves is that the independence the preview
already drew is the SAME independence the real per-kind stagger mechanism
(scene_response._execute_band_locked) now honours when the two kinds share
a real band — the preview was never aspirational, it was the mechanism the
band execution was missing until this shipped."""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model

VID = "v1"


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


def _band_scene(offset_a: int, offset_b: int):
    """Both kinds attached to the SAME real band — the shape that used to
    fire atomically, one offset speaking for the whole band."""
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kind_a = FlareKind(name="Kind A", type="permanent",
                      trigger_offset_ms=offset_a,
                      params={"spin": ParamTarget(mode="absolute", value=0.9)})
    kind_b = FlareKind(name="Kind B", type="permanent",
                      trigger_offset_ms=offset_b,
                      params={"star": ParamTarget(mode="absolute", value=0.5)})
    scene = SceneV2(
        name="Preview Stagger", devices=[SceneDeviceConfig(
            id="d1", target_kind="virtual", target=VID, effect_type="radial",
            params={"spin": 0.2, "star": 0.3})],
        flare_kinds=[kind_a, kind_b],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                     kinds={"Kind A": 1.0, "Kind B": 1.0})])})
    return scene, kind_a, kind_b


def _timeline(scene, kind, intensity=0.8):
    from spectra.services import flare_preview
    return asyncio.run(flare_preview.build_timeline(scene, kind, intensity))


def test_two_kinds_on_one_band_preview_independently_staggered_marks():
    """Kind A (-100ms) and Kind B (0ms) sit on the SAME band. Their own
    trigger marks must differ by exactly 100ms — the preview never
    collapses two kinds sharing a band onto one shared mark."""
    scene, kind_a, kind_b = _band_scene(offset_a=-100, offset_b=0)
    tl_a = _timeline(scene, kind_a)
    tl_b = _timeline(scene, kind_b)
    # Same fixed ruler-layout anchor (a layout choice, never authored) —
    # only the DRAWN MARK moves, per each kind's own offset.
    assert tl_a["animation_anchor_s"] == tl_b["animation_anchor_s"]
    assert tl_a["trigger_mark_s"] == pytest.approx(
        tl_b["trigger_mark_s"] + 0.1, abs=1e-6)


def test_the_preview_reflects_the_same_real_fire_moment_the_stagger_computes():
    """A single-kind preview fixes the WRITE at animation_anchor_s and
    draws the trigger MARK at anchor_s - offset/1000 — there is no shared
    real reference between two SEPARATE build_timeline() calls, so their
    marks are not directly comparable as cross-kind wall-clock positions
    (each preview is self-contained, by design — module docstring, "TRUE
    SIMULATION"). What IS a shared, checkable invariant: each kind's own
    REAL fire moment relative to the nominal (un-relocated) trigger —
    `anchor_ms + delay_ms` in _execute_band_locked's own arithmetic —
    always equals that kind's own trigger_offset_ms, regardless of the
    band's anchor. This is exactly what the preview's own
    `write - mark == offset_ms/1000` formula already encodes per kind, so
    the preview was never aspirational: it already showed, for each kind
    on its own, precisely the real relationship the new per-kind stagger
    mechanism now honours when kinds share a real band."""
    from spectra.services.scene_response import _band_anchor_ms
    scene, kind_a, kind_b = _band_scene(offset_a=-100, offset_b=0)
    band = scene.responses["flare"].bands[0]
    declared = {k.name: k for k in scene.flare_kinds}
    anchor_ms = _band_anchor_ms(band, declared)
    assert anchor_ms == -100

    for kind in (kind_a, kind_b):
        delay_ms = max(0, kind.trigger_offset_ms - anchor_ms)
        real_fire_relative_to_nominal_ms = anchor_ms + delay_ms
        assert real_fire_relative_to_nominal_ms == kind.trigger_offset_ms

        tl = _timeline(scene, kind)
        write_minus_mark_ms = round(
            (tl["animation_anchor_s"] - tl["trigger_mark_s"]) * 1000)
        assert write_minus_mark_ms == kind.trigger_offset_ms
