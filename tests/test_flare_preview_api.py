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
def _reset_hold_and_pause_state():
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause

    def _reset():
        fph._snapshot = None
        fph._deadline = None
        fph._session_started_at = None
        fph._locked_until_reopen = False
        preview_pause.clear()

    _reset()
    yield
    _reset()


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


# ── MAXIMUM HOLD CEILING (fm/preview-hold-needs-a-ceiling) — the OTHER
#    half of the ceiling: preview_pause, armed independently by this
#    router on every /heartbeat, is what actually refuses his scene
#    changes (fire_history's "deferred"/"preview" bucket). It must expire
#    at the SAME ceiling as the light hold even though nothing here ever
#    calls flare_preview_hold.sweep_once()/run_supervised() — capped_pause_s()
#    alone (consulted by /heartbeat and /fire) is what has to make this
#    true, since a real deployment's sweep task runs on its own separate
#    clock. The light-hold hardware proof (does the REVERT actually land
#    on a real fixture) lives in tests/test_flare_preview_hold.py — this
#    file's job is proving the ROUTE WIRING respects the same ceiling. ────

def test_heartbeat_stops_arming_preview_pause_at_the_ceiling_despite_continuous_beats(
        monkeypatch):
    import time as time_mod
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    monkeypatch.setattr(fph, "MAX_HOLD_DURATION_S", 0.3)
    client = _client()

    # Simulate a session already in progress (a real /fire already landed
    # a hold and armed both deadlines) without needing a real device host —
    # that hardware-level proof already exists, unchanged, in
    # test_flare_preview_hold.py.
    fph._snapshot = {"v1": {"type": "radial", "config": {}}}
    fph._session_started_at = time_mod.monotonic()
    fph._deadline = time_mod.monotonic() + 1.0
    preview_pause.start(1.0)

    # Heartbeat continuously — every 30ms, much faster than the 0.3s
    # ceiling, and NEVER letting it lapse. If preview_pause could be kept
    # armed by a heartbeat alone, it would still be active well past the
    # ceiling; his scene changes would stay refused indefinitely.
    elapsed = 0.0
    tick = 0.03
    last = None
    while elapsed < 0.5:
        r = client.post("/api/flare-preview/heartbeat")
        assert r.status_code == 200
        last = r.json()
        time_mod.sleep(tick)
        elapsed += tick

    assert last["active"] is False
    assert last["expired"] is True
    assert last["reason"] == "max_duration"
    assert preview_pause.active() is False, (
        "preview_pause must not stay armed past the same ceiling that "
        "bounds the light hold — his scene changes must resume together "
        "with the lights, not up to another HEARTBEAT_TIMEOUT_S later")


def test_fire_stops_arming_preview_pause_once_open_hold_reports_expired(monkeypatch):
    """/fire's own capping: once flare_preview_hold.open_hold reports the
    session locked (expired), /fire must not re-arm preview_pause on top
    of a fire that itself refused to do anything."""
    from spectra.services import flare_preview_hold, preview_pause

    async def spy(*args, **kwargs):
        return {"held": False, "expired": True, "reason": "max_duration"}
    monkeypatch.setattr(flare_preview_hold, "open_hold", spy)
    scene = _seed_scene()
    client = _client()
    preview_pause.clear()

    r = client.post("/api/flare-preview/fire",
                    json={"scene_id": scene.id, "kind_name": "spin-flare", "intensity": 0.7})
    assert r.status_code == 200
    assert r.json() == {"held": False, "expired": True, "reason": "max_duration"}
    assert preview_pause.active() is False


def test_open_clears_the_ceiling_lock_and_arms_a_fresh_pause(monkeypatch):
    """A genuine fresh /open — never a bare heartbeat/re-fire — is always
    allowed to clear a prior ceiling lock and start a new look."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    fph._locked_until_reopen = True
    scene = _seed_scene()
    client = _client()

    r = client.post("/api/flare-preview/open",
                    json={"scene_id": scene.id, "kind_name": "spin-flare", "intensity": 1.0})
    assert r.status_code == 200
    assert fph.locked_until_reopen() is False
    assert preview_pause.active() is True
