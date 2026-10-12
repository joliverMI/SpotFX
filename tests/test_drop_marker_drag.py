"""THE DRAGGABLE DROP MARK on a scene's drop-sequence preview (2026-10-12,
the Admiral: "I wanted to be able to edit red line for the drop in the
preview drop sequence page for a scene, but I cannot click it and drag it
... it should work on a touch screen (tablet)").

Backend half: the per-scene SceneV2.drop_timing_offset_ms the drag writes
persists through the ordinary scene save path (POST /api/scenes) and reads
back; the preview's open request may carry the DRAFT value (so an unsaved
drag plays at once) and writes nothing; the timeline carries what the drag
needs (music_mark_s, the room's value, the lull floor); and Sonic reads and
sets it through set_scene_setting (null = back to the room's).

Frontend half: scripts/check_drop_marker_drag.mjs (the real PreviewRuler
and SequencePreviewOverlay under jsdom, touch drags included), run at the
bottom — skipped when the frontend toolchain or the dev-only jsdom is
missing.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import subprocess

import pytest

from fx import device_model
from spectra.services.room_controls import RoomControlState

pytestmark = pytest.mark.drop_timing_live

REPO = pathlib.Path(__file__).resolve().parent.parent
VID = "v1"


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("COLOR_SETS_FILE", "color_sets.json"),
                     ("SCENE_AGENT_LOG_FILE", "scene_agent_log.json"),
                     ("SCENE_BACKUPS_FILE", "scene_backups.json"),
                     ("SCENE_GENESIS_FILE", "scene_genesis.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
    real_categories = device_model.CATEGORIES_FILE
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    from spectra.services import room_controls
    room_controls.save_room_controls(RoomControlState(drop_timing_offset_ms=-400))
    yield tmp_path
    from spectra.services import flare_preview_hold, preview_pause
    preview_pause.clear()
    flare_preview_hold.clear_ceiling_lock()
    # leave the shared category cache as the next test expects to find it
    device_model.CATEGORIES_FILE = real_categories
    device_model.refresh()


def _scene(**kw):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    return SceneV2(name="Drag Scene",
                   devices=[SceneDeviceConfig(id="d1", target_kind="virtual",
                                              target=VID, effect_type="blackhole",
                                              params={})], **kw)


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _open(client, scene_id, **extra):
    r = client.post("/api/preview/sequence/open", json={
        "scene_id": scene_id, "intensity": 0.7, "charge_gap_ms": 4000,
        "lull_gap_ms": 3000, "drop_switch": False, **extra})
    assert r.status_code == 200, r.text
    tl = r.json()
    return tl, {m["event_class"]: m for m in tl["marks"]}


def test_the_scene_save_path_persists_the_drop_timing_and_reads_it_back():
    from spectra.services import scene_store
    scene = _scene()
    scene_store.save(scene)
    client = _client()
    body = {**scene.model_dump(mode="json"), "drop_timing_offset_ms": -620}
    r = client.post("/api/scenes", json=body)
    assert r.status_code == 200, r.text
    assert scene_store.get_by_id(scene.id).drop_timing_offset_ms == -620
    got = next(s for s in client.get("/api/scenes").json() if s["id"] == scene.id)
    assert got["drop_timing_offset_ms"] == -620
    # null puts it back on the room's
    r = client.post("/api/scenes", json={**body, "drop_timing_offset_ms": None})
    assert r.status_code == 200
    assert scene_store.get_by_id(scene.id).drop_timing_offset_ms is None
    # out of range is refused, not clamped silently
    r = client.post("/api/scenes", json={**body, "drop_timing_offset_ms": -5000})
    assert r.status_code == 422


def test_the_timeline_carries_what_the_drag_needs():
    from spectra.services import scene_store
    scene = _scene()
    scene_store.save(scene)
    tl, marks = _open(_client(), scene.id)
    dt = tl["drop_timing"]
    assert dt["source"] == "room" and dt["offset_ms"] == -400
    assert dt["scene_offset_ms"] is None
    assert dt["room_offset_ms"] == -400
    assert (dt["min_ms"], dt["max_ms"]) == (-2000, 2000)
    # a 3000 ms lull gap: the drop can move at most to 100 ms after the lull
    assert dt["floor_applied_ms"] == -2000
    drop = marks["drop"]
    assert drop["music_mark_s"] == pytest.approx(drop["mark_s"] + 0.4)
    for cls in ("charge", "lull"):
        assert marks[cls]["music_mark_s"] == pytest.approx(marks[cls]["mark_s"])


def test_the_lull_floor_is_reported_on_a_short_gap():
    from spectra.services import scene_store
    scene = _scene()
    scene_store.save(scene)
    tl, _ = _open(_client(), scene.id, lull_gap_ms=600)
    assert tl["drop_timing"]["floor_applied_ms"] == -500


def test_a_draft_value_previews_without_being_saved():
    from spectra.services import scene_store
    scene = _scene()
    scene_store.save(scene)
    client = _client()
    _tl, room = _open(client, scene.id)
    tl, draft = _open(client, scene.id, drop_timing_offset_ms=-900)
    assert tl["drop_timing"]["source"] == "scene"
    assert tl["drop_timing"]["offset_ms"] == -900
    assert draft["drop"]["mark_s"] == pytest.approx(room["drop"]["mark_s"] - 0.5)
    assert draft["drop"]["music_mark_s"] == pytest.approx(room["drop"]["music_mark_s"])
    assert scene_store.get_by_id(scene.id).drop_timing_offset_ms is None, \
        "previewing a draft writes nothing"
    # an explicit null previews the room's even for a scene with its own value
    scene_store.save(scene.model_copy(update={"drop_timing_offset_ms": -700}))
    tl, _ = _open(client, scene.id, drop_timing_offset_ms=None)
    assert tl["drop_timing"]["source"] == "room" and tl["drop_timing"]["offset_ms"] == -400
    # absent = the stored scene's own
    tl, _ = _open(client, scene.id)
    assert tl["drop_timing"]["source"] == "scene" and tl["drop_timing"]["offset_ms"] == -700


def test_the_live_fire_uses_the_draft_too():
    from spectra.api.preview import SequenceRequest
    from spectra.services import phase_preview
    scene = _scene()
    body = SequenceRequest(scene_id=scene.id, lull_gap_ms=3000, drop_timing_offset_ms=-1000)
    drafted = body.scene_for_preview(scene)
    assert drafted.drop_timing_offset_ms == -1000
    assert scene.drop_timing_offset_ms is None, "the stored scene object is not mutated"
    program = phase_preview.PhaseSequenceProgram(drafted, body.gaps())
    assert program.gaps["lull"] == 2000, "the live lull builds to the drafted drop"
    assert SequenceRequest(scene_id=scene.id).scene_for_preview(scene) is scene


def test_sonic_reads_and_sets_this_scenes_drop_timing():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    scene = _scene()
    scene_store.save(scene)
    spec = sc.SCENE_SETTINGS_REGISTRY["drop_timing_offset_ms"]
    assert (spec.min, spec.max, spec.nullable, spec.kind) == (-2000, 2000, True, "int")
    settings = sc.get_scene_settings(scene.id)["settings"]
    assert settings["drop_timing_offset_ms"]["value"] is None
    res = asyncio.run(sc.apply_scene_setting(scene.id, "drop_timing_offset_ms", -550))
    assert res["status"] == "applied"
    assert scene_store.get_by_id(scene.id).drop_timing_offset_ms == -550
    res = asyncio.run(sc.apply_scene_setting(scene.id, "drop_timing_offset_ms", None))
    assert res["status"] == "applied"
    assert scene_store.get_by_id(scene.id).drop_timing_offset_ms is None
    with pytest.raises(sc.SceneOpError):
        asyncio.run(sc.apply_scene_setting(scene.id, "drop_timing_offset_ms", 2500))


ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"
JSDOM = REPO / "spectra" / "web" / "node_modules" / "jsdom"


@pytest.mark.skipif(
    not ESBUILD.exists() or not JSDOM.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild + dev-only jsdom) not installed",
)
def test_the_drop_mark_drags_under_a_finger():
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_drop_marker_drag.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout
