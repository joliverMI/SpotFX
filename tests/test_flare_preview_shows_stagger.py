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
a real band, on the one path that staggers at all (a fire tick() already
relocated by the band's anchor) — for every kind, since the band's anchor
is the min over every declared kind's offset, so no kind's stagger delay is
ever clamped.

The invariant covers the AUTHORED OFFSET component of a kind's moment ONLY.
One pre-existing, out-of-scope preview/production parity gap sits outside
it, left for a later decision rather than fixed here:
  * trigger_engine._response_switch_lead_ms's AUTOMATIC lead stays
    band-wide — a max over every attached kind's smooth glide / colour
    rotate ramp, subtracted once from the whole fire's start — where each
    kind's isolated preview applies only its own kind_lead_ms. A kind that
    shares a band with a gliding or rotating kind therefore fires earlier
    than its preview's fire_at_s. Every band here carries permanent kinds
    only, so both leads are 0 and that gap is deliberately not exercised.

An all-positive band used to clamp a 0-offset kind to the band's later
moment while its preview drew it on the mark — a real preview/production
disagreement, FIXED 2026-09-16 (spotfx-zero-offset-fires-on-mark):
_band_anchor_ms's min is now taken over EVERY declared offset, zero
included, not just the nonzero ones, so an all-positive band anchors on 0
and a 0-offset kind fires exactly where its preview already drew it (the
last test, below)."""
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


def _real_fire_moments_ms(scene, intensity=0.8) -> dict[str, int]:
    """Each attached kind's moment relative to the nominal trigger from its
    AUTHORED OFFSET alone, as the engine itself schedules it: tick()
    relocates the whole fire by the band's anchor (band_trigger_offset_ms),
    then the relocated fire runs a kind inline (record["kinds"]) or queues
    it `delay_ms` later (record["deferred_kinds"]). The band-wide automatic
    lead tick() also subtracts is not part of this number (module
    docstring)."""
    from spectra.services import flare_preview, scene_response
    from spectra.services.fx_executor import RecordingExecutor

    async def main():
        clock = flare_preview._FakeClock()
        _c, responder, _w = flare_preview._scratch_engine(
            scene, intensity, clock, RecordingExecutor(clock=clock))
        return await responder.on_event("flare", intensity,
                                        anchor_relocated=True)

    record = asyncio.run(main())
    anchor_ms = scene_response.band_trigger_offset_ms(scene, "flare", intensity)
    moments = {k["name"]: anchor_ms for k in record["kinds"]}
    for d in record.get("deferred_kinds", []):
        moments[d["name"]] = anchor_ms + d["delay_ms"]
    return moments


def _preview_write_minus_mark_ms(scene, kind) -> int:
    tl = _timeline(scene, kind)
    return round((tl["animation_anchor_s"] - tl["trigger_mark_s"]) * 1000)


def test_the_preview_reflects_the_same_real_fire_moment_the_stagger_computes():
    """For a kind whose stagger delay is NOT clamped by max(0, ...) — its
    offset at or after the band's anchor — its fire moment from the authored
    offset, read off the engine's own schedule, equals its own
    trigger_offset_ms, which is exactly what its single-kind preview draws
    (`write - mark == offset`). [-100, 0] is that case for both kinds: the
    -100 kind IS the anchor, the 0 kind waits 100ms behind it. Neither kind
    here carries an automatic lead; the band-wide lead gap is outside this
    claim (module docstring)."""
    scene, kind_a, kind_b = _band_scene(offset_a=-100, offset_b=0)
    moments = _real_fire_moments_ms(scene)
    assert moments == {"Kind A": -100, "Kind B": 0}
    for kind in (kind_a, kind_b):
        assert moments[kind.name] == kind.trigger_offset_ms
        assert _preview_write_minus_mark_ms(scene, kind) == kind.trigger_offset_ms


def test_an_all_positive_band_now_fires_its_zero_offset_kind_on_the_mark():
    """The invariant above now extends to a band whose every authored
    offset is zero-or-positive too (fixed 2026-09-16,
    spotfx-zero-offset-fires-on-mark). The anchor is min over EVERY
    declared offset, zero included, so [0, +50] anchors on 0 — tick()
    never relocates the fire — and Kind A (0) fires ON the mark while
    Kind B (+50) is deferred 50ms behind it, matching both kinds' own
    preview exactly (write - mark == offset, same as the [-100, 0] case
    above)."""
    scene, kind_a, kind_b = _band_scene(offset_a=0, offset_b=50)
    moments = _real_fire_moments_ms(scene)
    assert moments == {"Kind A": 0, "Kind B": 50}
    for kind in (kind_a, kind_b):
        assert moments[kind.name] == kind.trigger_offset_ms
        assert _preview_write_minus_mark_ms(scene, kind) == kind.trigger_offset_ms
