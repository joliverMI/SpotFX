"""API-layer proof that /flare-preview/open and /flare-preview/fire are
genuinely SEPARATE (2026-08-21, data/preview-loops-and-fires-on-the-
trigger — his report: "the preview only happens once, it should happen
every time, and it should fire with the same timing as if the playhead
was crossing a trigger"). Before this, one endpoint (/open) both computed
the timeline AND fired live, instantly, regardless of the trigger mark.

This file proves the ROUTE SHAPE offline (no hardware, no headless host —
that proof already exists in tests/test_flare_preview_hold.py and is
unchanged, since open_hold() itself was not touched): /open never calls
flare_preview_hold.open_hold at all, /fire is the only route that does,
and both expose the new animation_anchor_s/trigger_mark_s fields the
frontend's playhead loop schedules its live fires from."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    from fx import device_model
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")
    monkeypatch.setattr(scfg, "DRIFT_PROFILES_FILE", tmp_path / "drift_profiles.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "GRADIENT2D_FILE", tmp_path / "gradients2d.json")
    monkeypatch.setattr(scfg, "FIRE_HISTORY_FILE", tmp_path / "fire_history.json")
    monkeypatch.setattr(scfg, "SHOW_LOG_FILE", tmp_path / "show_log.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "FLARE_PREVIEW_HOLD_FILE",
                        tmp_path / "flare_preview_hold.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    import json
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


def _seed_scene():
    from spectra.models.scene import (FlareKind, ParamTarget,
                                      SceneDeviceConfig, SceneV2)
    from spectra.services import scene_store
    scene = SceneV2(
        name="API Split Check Scene",
        devices=[SceneDeviceConfig(
            id="dev1", target_kind="virtual", target="v1",
            effect_type="radial", params={"spin": 0.2})],
        flare_kinds=[FlareKind(name="spin-flare", type="momentary",
                               params={"spin": ParamTarget(mode="absolute", value=0.9)},
                               trigger_offset_ms=-500)],
    )
    scene_store.save(scene)
    return scene


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_open_computes_timeline_and_never_fires_live(monkeypatch):
    """The core regression proof: /open must not touch flare_preview_hold.
    open_hold at all — it only computes the (hardware-free) timeline."""
    from spectra.services import flare_preview_hold

    calls = []
    orig = flare_preview_hold.open_hold

    async def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return await orig(*args, **kwargs)

    monkeypatch.setattr(flare_preview_hold, "open_hold", spy)
    scene = _seed_scene()
    client = _client()

    r = client.post("/api/flare-preview/open",
                    json={"scene_id": scene.id, "kind_name": "spin-flare", "intensity": 1.0})
    assert r.status_code == 200
    body = r.json()
    assert calls == [], "open must never call open_hold — the live fire is a separate call"
    assert "live" not in body, "no more inline live-fire result on /open"
    assert body["animation_anchor_s"] > 0
    # trigger_offset_ms=-500 (fire earlier, his convention) -> mark sits to
    # the RIGHT of the anchor: trigger_mark_s > animation_anchor_s.
    assert body["trigger_mark_s"] > body["animation_anchor_s"]
    assert abs(body["trigger_mark_s"] - body["animation_anchor_s"] - 0.5) < 1e-6


def test_fire_is_the_only_route_that_calls_open_hold(monkeypatch):
    """Stubbed, not delegated: the real open_hold needs a live fx_seam/
    headless host to write to (already proven, hardware-level, in
    tests/test_flare_preview_hold.py — unchanged by this task). This test
    proves only the ROUTE WIRING: /fire is the one and only caller."""
    from spectra.services import flare_preview_hold

    calls = []

    async def spy(scene, kind, intensity, *, heartbeat_timeout_s):
        calls.append((scene.id, kind.name, intensity))
        return {"held": True, "first_open": True, "fire_record": {"result": "applied"}}

    monkeypatch.setattr(flare_preview_hold, "open_hold", spy)
    scene = _seed_scene()
    client = _client()

    r = client.post("/api/flare-preview/fire",
                    json={"scene_id": scene.id, "kind_name": "spin-flare", "intensity": 0.7})
    assert r.status_code == 200
    assert calls == [(scene.id, "spin-flare", 0.7)]
    assert r.json()["held"] is True

    r = client.post("/api/flare-preview/close")
    assert r.status_code == 200


def test_open_and_fire_404_the_same_way_for_an_unknown_scene_or_kind():
    scene = _seed_scene()
    client = _client()

    for path in ("open", "fire"):
        r = client.post(f"/api/flare-preview/{path}",
                        json={"scene_id": "no-such-scene", "kind_name": "spin-flare"})
        assert r.status_code == 404

        r = client.post(f"/api/flare-preview/{path}",
                        json={"scene_id": scene.id, "kind_name": "no-such-kind"})
        assert r.status_code == 404
