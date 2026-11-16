"""THE SCENES PAGE'S WORDS TAB (Word Shapes row W2.1).

Two halves, both offline:

FRONTEND — scripts/check_scenes_words_tab.mjs, run below so the proof fires
on every full test run: the five-versus-four response-class lists (and that
neither trigger picker reaches for the five), the preview's shape picker and
its three ruler marks, the no-knobs Word Shape kind, the save's advisory
notes, and the help topic the tab links. Skipped (not failed) with no
frontend toolchain, the posture every .mjs check in this repo takes.

IN A REAL BROWSER — scripts/render_words_tab.py drives the REAL tab and the
REAL preview overlay against a mocked backend and measures what a
screenshot hides, above all that the "forms" span ENDS ON the word's own
mark. It skips, saying why, with no Chromium or no harness build.

BACKEND — the two wires the UI depends on, exercised through the HTTP routes
the editor itself calls:

  * POST /api/scenes round-trips a scene carrying a Words section and
    RETURNS its advisory warnings (scene_store.scene_warnings), which the
    editor shows as inline notes. Advisory, never a refusal — the scene is
    stored either way, because refusing it would lose his drag.
  * POST /api/flare-preview/open takes the picker's `shape` and answers with
    that shape's own envelope; POST /api/flare-preview/fire takes it too, so
    the live fire draws what the ruler draws rather than the server's
    default (W2.1's one deliberate widening past W0.3 — without it the
    picker would be the preview lying about what it fires).

NO LIVE ACCESS: storage is redirected into tmp_path, the device registry is
emptied, and the preview's /fire is never called against a real seam — the
one test that touches the fire path monkeypatches the hold open.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from fx import device_model

REPO = pathlib.Path(__file__).resolve().parent.parent
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


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
    yield tmp_path
    from spectra.services import flare_preview_hold, preview_pause
    preview_pause.clear()
    flare_preview_hold.clear_ceiling_lock()
    device_model.CATEGORIES_FILE = real_categories
    device_model.refresh()


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _words_scene(*, flare_too: bool = False, offset_ms: int = 0):
    """A scene shaped the way the Words tab builds one: one Word Shape kind
    (no knobs) on one full-range Words band."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Word Shape", type="word_shape",
                       trigger_offset_ms=offset_ms)]
    responses = {"word": ResponseSpec(bands=[FlareBand(
        intensity_min=0.0, intensity_max=1.0, kinds={"Word Shape": 1.0})])}
    if flare_too:
        responses["flare"] = ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Word Shape": 1.0})])
    return SceneV2(name="Words Scene", flare_kinds=kinds, responses=responses,
                   devices=[SceneDeviceConfig(id="d1", target_kind="virtual",
                                              target="v1",
                                              effect_type="blackhole", params={})])


def test_the_editors_own_save_round_trips_a_words_band():
    """The exact call the page makes (useSaveScene → POST /api/scenes), and
    the exact read it makes after (GET /api/scenes)."""
    client = _client()
    scene = _words_scene()
    r = client.post("/api/scenes", json=scene.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == [], "a Words band alone warns about nothing"
    got = next(s for s in client.get("/api/scenes").json() if s["id"] == scene.id)
    [band] = got["responses"]["word"]["bands"]
    assert band["kinds"] == {"Word Shape": 1.0}
    [kind] = got["flare_kinds"]
    assert kind["type"] == "word_shape"
    # NO KNOBS — what the editor must never send (models/scene.py refuses them)
    assert kind["jump"] is None and kind["params"] == {}
    assert kind["gain"] == 1.0 and kind["hold_ms"] is None


def test_the_save_surfaces_both_advisory_warnings():
    """ADVISORY, never a refusal: the scene is stored, and the editor is
    told what will quietly do nothing (scene_store.scene_warnings)."""
    client = _client()
    scene = _words_scene(flare_too=True, offset_ms=-250)
    r = client.post("/api/scenes", json=scene.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    warnings = r.json()["warnings"]
    assert len(warnings) == 2, warnings
    joined = " | ".join(warnings)
    assert "is a word_shape" in joined and "does nothing" in joined
    assert "trigger_offset_ms -250" in joined and "not applied there" in joined
    # Every one names its kind in single quotes — how the editor decides
    # which card a note belongs on (wordShapePreview.warningsForKind).
    assert all("'Word Shape'" in w for w in warnings)
    # ... and it really was stored, not refused.
    from spectra.services import scene_store
    assert set(scene_store.get_by_id(scene.id).responses) == {"word", "flare"}


def test_a_word_shape_kind_with_a_knob_is_refused_so_the_editor_must_not_send_one():
    client = _client()
    body = _words_scene().model_dump(mode="json")
    body["flare_kinds"][0]["gain"] = 1.5
    r = client.post("/api/scenes", json=body)
    assert r.status_code == 422
    assert "word_shape" in r.text


def test_the_preview_open_draws_the_shape_the_picker_asks_for():
    """The picker's wire: `shape` in, that shape's envelope out — the three
    marks the ruler draws (wordShapePreview.wordShapeMarks)."""
    from spectra.services import scene_store
    scene = _words_scene()
    scene_store.save(scene)
    client = _client()
    for shape in ("heart", "star", "diamond"):
        r = client.post("/api/flare-preview/open", json={
            "scene_id": scene.id, "kind_name": "Word Shape",
            "intensity": 0.8, "shape": shape})
        assert r.status_code == 200, r.text
        tl = r.json()
        assert tl["kind_type"] == "word_shape"
        assert tl["word_shape"]["shape"] == shape
        env = tl["word_shape"]
        # FORMS ends ON the word: the write goes out a form before the mark.
        assert tl["fire_at_s"] == pytest.approx(
            tl["trigger_mark_s"] - env["form_s"])
        assert tl["lead_ms"] == round(env["form_s"] * 1000)
        assert tl["effect_animation_ms"] == pytest.approx(
            1000 * (env["form_s"] + env["hold_s"] + env["release_s"]))
        # The Words section ignores a per-kind offset, so the drawn mark is
        # the anchor itself — the ruler never claims an offset it won't get.
        assert tl["trigger_mark_s"] == tl["animation_anchor_s"]
    # No shape named at all = the server's own default (heart), which is
    # also what the picker preselects.
    r = client.post("/api/flare-preview/open", json={
        "scene_id": scene.id, "kind_name": "Word Shape", "intensity": 0.8})
    assert r.json()["word_shape"]["shape"] == "heart"


def test_the_live_fire_draws_the_picked_shape_not_the_default(monkeypatch):
    """W2.1's one widening past W0.3: /fire carries the picker's shape
    through FlareKindProgram to scene_response.fire_kind, so the room draws
    what the ruler draws. The hold itself is stubbed — no seam, no fixture,
    nothing live — this asserts only the value that reaches it."""
    from spectra.services import flare_preview_hold, scene_store
    scene = _words_scene()
    scene_store.save(scene)
    seen: list[str | None] = []

    async def fake_open_program_hold(program, intensity, **kw):
        seen.append(getattr(program, "shape", "MISSING"))
        return {"held": True}

    monkeypatch.setattr(flare_preview_hold, "open_program_hold",
                        fake_open_program_hold)
    client = _client()
    r = client.post("/api/flare-preview/fire", json={
        "scene_id": scene.id, "kind_name": "Word Shape",
        "intensity": 0.6, "shape": "diamond"})
    assert r.status_code == 200, r.text
    assert seen == ["diamond"]
    client.post("/api/flare-preview/fire", json={
        "scene_id": scene.id, "kind_name": "Word Shape", "intensity": 0.6})
    assert seen[-1] is None, "no picker, no shape — the default stays the server's"


def test_the_program_hands_the_shape_to_the_fire():
    """FlareKindProgram.execute → fire_kind(shape=...), the other end of the
    same wire, with no HTTP in the way."""
    import asyncio

    from spectra.services.flare_preview_hold import FlareKindProgram
    scene = _words_scene()
    program = FlareKindProgram(scene, scene.flare_kinds[0], "star")

    class _Ctx:
        intensity = 0.5

        def __init__(self) -> None:
            self.fired: list = []
            outer = self

            class _Responder:
                async def fire_kind(self, kind, intensity, shape=None):
                    outer.fired.append((kind.name, intensity, shape))
                    return {"result": "applied"}

            self.responder = _Responder()

        async def apply_scene(self):
            return None

    ctx = _Ctx()
    assert asyncio.run(program.execute("fire", ctx))["result"] == "applied"
    assert ctx.fired == [("Word Shape", 0.5, "star")]
    # An ordinary kind's program carries no shape and nothing changes for it.
    plain = FlareKindProgram(scene, scene.flare_kinds[0])
    ctx2 = _Ctx()
    asyncio.run(plain.execute("fire", ctx2))
    assert ctx2.fired == [("Word Shape", 0.5, None)]


@pytest.mark.skipif(not ESBUILD.exists() or shutil.which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_the_words_tab_and_the_shape_picker():
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_scenes_words_tab.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_the_words_tab_in_a_real_browser():
    """The ruler's own geometry — the form ending ON the word — plus the
    picker, the add flow and the inline note, at 1440/820/390. The script
    skips cleanly (exit 0, saying why) with no Chromium or harness build."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "render_words_tab.py"), "--no-shots"],
        cwd=REPO, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
