"""THE PRE-DROP IN THE DROP-SEQUENCE PREVIEW (predrop plan step 5, §3.4:
"a pre-drop cue with a kind switch and a gap slider inside that kind's
min/max, so he watches each look on the real lights").

The ruler places the pre-drop the slider's gap before the drop's mark —
moved with the drop by the drop timing offset — and carries the verdict
the lull would reach on this scene (spectra/services/pre_drop_play.py, the
show's own rule). The live program's LULL step hands the response engine
the same candidate the trigger clock would, so a member effect (none
until step 6) plays its look in the preview exactly as in the show.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

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


def _scene(**extra):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    return SceneV2(name="Phase Scene", devices=[SceneDeviceConfig(
        id="d1", target_kind="virtual", target=VID, effect_type="blackhole")],
        **extra)


def _timeline(scene, **kw):
    from spectra.services import phase_preview
    return asyncio.run(phase_preview.build_timeline(
        scene, 0.7, gaps={"charge": 4000, "lull": 3200}, drop_switch_enabled=False,
        **kw))


def _marks(tl):
    return {m["event_class"]: m for m in tl["marks"]}


def test_no_kind_no_pre_drop():
    assert _timeline(_scene())["pre_drop"] is None


def test_the_pre_drop_sits_its_gap_before_the_drop_and_plays():
    tl = _timeline(_scene(), pre_drop_kind="spike", pre_drop_gap_ms=800)
    pd, drop = tl["pre_drop"], _marks(tl)["drop"]
    assert pd["mark_s"] == pytest.approx(drop["mark_s"] - 0.8)
    assert pd["plays"] and pd["reason"] == "plays" and pd["kind"] == "spike"
    assert pd["gap_ms"] == 800
    assert pd["told"] == [] and pd["member_lull"] is None, "no member yet"
    assert "plays" in pd["sentence"]


@pytest.mark.drop_timing_live
def test_the_pre_drop_moves_with_the_drop():
    """A scene's own drop timing offset moves the drop's mark, and the
    pre-drop rides with it: the gap between them stays the music's."""
    tl = _timeline(_scene(drop_timing_offset_ms=-300), pre_drop_kind="intro",
                   pre_drop_gap_ms=2000)
    pd, drop = tl["pre_drop"], _marks(tl)["drop"]
    assert drop["drop_timing_offset_ms"] == -300
    assert pd["mark_s"] == pytest.approx(drop["mark_s"] - 2.0)


def test_the_gap_is_held_inside_the_scenes_window():
    tl = _timeline(_scene(), pre_drop_kind="spike", pre_drop_gap_ms=5000)
    assert tl["pre_drop"]["gap_ms"] == 2000
    tl = _timeline(_scene(), pre_drop_kind="spike")
    assert tl["pre_drop"]["gap_ms"] == 800, "the spike's default"
    tl = _timeline(_scene(), pre_drop_kind="intro")
    assert tl["pre_drop"]["gap_ms"] == 2000, "the vocal intro's default"


def test_a_kind_off_on_the_scene_says_so():
    tl = _timeline(_scene(pre_drop_spike={"enabled": False, "min_ms": 350,
                                          "max_ms": 2000}),
                   pre_drop_kind="spike", pre_drop_gap_ms=800)
    pd = tl["pre_drop"]
    assert not pd["plays"] and pd["reason"] == "kind_off"
    assert "off" in pd["sentence"]


def test_a_member_is_shown_its_lull_measured_to_the_pre_drop(monkeypatch):
    monkeypatch.setattr(device_model, "PRE_DROP_EFFECTS", frozenset({"blackhole"}))
    tl = _timeline(_scene(), pre_drop_kind="spike", pre_drop_gap_ms=800)
    pd = tl["pre_drop"]
    lull = _marks(tl)["lull"]
    at_ms = lull["gap_ms"] - 800
    assert pd["at_ms"] == at_ms
    assert pd["told"] == [VID]
    assert pd["member_lull"]["ramp_ms"] == round(at_ms * 0.9)
    assert pd["member_lull"]["breath_at_s"] + pd["member_lull"]["breath_s"] == \
        pytest.approx(at_ms / 1000.0)


def test_the_live_lull_step_carries_the_candidate(monkeypatch):
    """PhaseSequenceProgram's lull hands on_event the same candidate the
    trigger clock would — decided on the scene the scratch engine holds."""
    from spectra.services import flare_preview, phase_preview
    from spectra.services.fx_executor import RecordingExecutor
    monkeypatch.setattr(device_model, "PRE_DROP_EFFECTS", frozenset({"blackhole"}))
    scene = _scene()
    clock = flare_preview._FakeClock()
    conductor, responder, _writes = flare_preview._scratch_engine(
        scene, 0.7, clock, RecordingExecutor(clock=clock))
    program = phase_preview.PhaseSequenceProgram(
        scene, {"charge": 4000, "lull": 3200}, pre_drop=("spike", 800))

    async def apply_scene(**_k):
        return None

    ctx = SimpleNamespace(first_open=False, responder=responder,
                          conductor=conductor, intensity=0.7,
                          apply_scene=apply_scene)
    out = asyncio.run(program.execute("lull", ctx))
    pd = out["record"]["phase"]["pre_drop"]
    assert pd["plays"] and pd["kind"] == "spike" and pd["gap_ms"] == 800
    assert pd["at_ms"] == program.gaps["lull"] - 800
    assert pd["told"] == [VID]


def test_without_a_kind_the_live_lull_is_todays(monkeypatch):
    from spectra.services import flare_preview, phase_preview
    from spectra.services.fx_executor import RecordingExecutor
    scene = _scene()
    clock = flare_preview._FakeClock()
    conductor, responder, _writes = flare_preview._scratch_engine(
        scene, 0.7, clock, RecordingExecutor(clock=clock))
    program = phase_preview.PhaseSequenceProgram(scene, {"lull": 3200})

    async def apply_scene(**_k):
        return None

    ctx = SimpleNamespace(first_open=False, responder=responder,
                          conductor=conductor, intensity=0.7,
                          apply_scene=apply_scene)
    out = asyncio.run(program.execute("lull", ctx))
    assert "pre_drop" not in out["record"]["phase"]


def test_the_open_route_uses_the_drafted_window_and_looks():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    from spectra.services import scene_store
    scene = _scene()
    scene_store.save(scene)
    client = TestClient(create_app())
    body = {"scene_id": scene.id, "intensity": 0.7, "charge_gap_ms": 4000,
            "lull_gap_ms": 3200, "drop_switch": False,
            "pre_drop_kind": "spike", "pre_drop_gap_ms": 1800,
            "pre_drop_spike": {"enabled": True, "min_ms": 350, "max_ms": 1500},
            "pre_drop_looks": {"d1": {"spike": "auto", "intro": "same"}}}
    r = client.post("/api/preview/sequence/open", json=body)
    assert r.status_code == 200, r.text
    pd = r.json()["pre_drop"]
    assert pd["gap_ms"] == 1500, "held inside the DRAFTED window"
    assert pd["window"] == {"enabled": True, "min_ms": 350, "max_ms": 1500}
    bad = {**body, "pre_drop_spike": {"enabled": True, "min_ms": 1500, "max_ms": 900}}
    assert client.post("/api/preview/sequence/open", json=bad).status_code == 422
