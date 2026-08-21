"""Preview must hold SCENE CHANGES, not just flares/responses (2026-08-21,
fm/preview-must-hold-scene-changes — his live report: "the music show is
playing regardless of the fact that I have the preview window open and it
says 'deferred by preview'").

Root cause: spectra/services/bridge.py's conductor_deferral/
sequencer_deferral both already checked preview_pause.active() (that's the
"deferred by preview" string he saw), but scene_sequencer.fire_scene_by_id
— the ONE choke point every scene change funnels through, including his
authored fire_scene triggers — never consulted it at all, so a
trigger-driven scene fire sailed straight through while the sequencer's own
rolls (gated one level up, at _on_change_moment's self._deferral() call)
and every flare/response (engine.fire_response_event/
fire_scene_update_event) correctly went silent. preview_pause.py's own
docstring already NAMED fire_scene_by_id as one of the choke points it
outranks — the documentation described a gate that didn't exist.

Proves:
  1. Preview inactive: fire_scene_by_id fires normally (baseline).
  2. Preview active: a scene fire is skipped="preview", recorded to
     fire_history's "deferred" bucket (never silent, matching the dwell
     precedent), and does NOT fire an update effect — deliberate, opposite
     of dwell's placeholder flare: dwell's update-effect exists to make an
     otherwise-invisible hold visible, but a preview's whole point is an
     isolated, motionless room, so an update effect would fight the exact
     thing he opened the preview to judge.
  3. Preview OUTRANKS Force Scene here too — matching preview_pause's own
     documented precedence at bridge.py's conductor_deferral/
     sequencer_deferral (preview beats pause/dinner_party/ambient/
     force_scene there). A hand-held preview is the most explicit,
     momentary override a room can be under; a Force Scene reassert landing
     on top of the exact flare he opened the preview to judge would defeat
     the preview's whole purpose.
  4. A preview-skipped request never touches dwell's own latch (same "a
     declined fire must not move state" rule dwell's own gate already
     follows for its neighbours).
  5. ABANDONMENT, not clean close: preview_pause is a plain deadline
     (time.monotonic() comparison), never a boolean somebody has to
     remember to clear. Once the deadline lapses — browser closed,
     connection dropped, heartbeats simply stop — the NEXT fire_scene_by_id
     call fires normally with no explicit preview_pause.clear() ever
     called. This is the safety property that matters more than the hold
     itself: a hold that can outlive the preview is worse than no hold —
     his show must resume on its own, never stay frozen because a window
     went away.
"""
from __future__ import annotations

import asyncio
import sys
import time as time_mod
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.scene import SceneV2
from spectra.services import dwell, fire_history, preview_pause, scene_store


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")


def _run(coro):
    return asyncio.run(coro)


def _scene(id_, **kw) -> SceneV2:
    return SceneV2(id=id_, name=id_, **kw)


def _fake_scene_compiler(monkeypatch, fired: list):
    from spectra.services import scene_compiler

    async def fake_fire_scene(scene, *, intensity=0.5, color_set=None,
                              dry_run=True, rng=None):
        fired.append((scene.id, intensity))
        return {"dry_run": dry_run, "intensity": intensity, "writes": [],
                "resolved_bindings": {}, "dice_rolls": {}}
    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)


def _fake_update_seam(monkeypatch, calls: list, result=None):
    from spectra.services import engine

    async def fake_update_event(intensity):
        calls.append(intensity)
        return result
    monkeypatch.setattr(engine, "fire_scene_update_event", fake_update_event)


# ── 1/2. the gate itself ─────────────────────────────────────────────────

def test_fires_normally_when_preview_inactive(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)

    result = _run(fire_scene_by_id("a", intensity=0.5))
    assert "skipped" not in result
    assert fired == [("a", 0.5)]


def test_preview_active_skips_the_fire_and_records_it_never_silent(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    update_calls: list = []
    _fake_update_seam(monkeypatch, update_calls)

    preview_pause.start(30.0)
    result = _run(fire_scene_by_id("a", intensity=0.7))

    assert fired == [], "the scene must never reach scene_compiler.fire_scene"
    assert result == {"skipped": "preview", "scene_id": "a", "scene_name": "a"}
    assert update_calls == [], \
        "a preview skip must NOT fire an update effect — the preview's " \
        "whole point is an isolated, motionless room; an update effect " \
        "would put motion into the exact thing he's trying to judge"

    data = fire_history.load_all()
    assert data["deferred"]["a"]["count"] == 1
    log = fire_history.load_show_log()
    deferred_entries = [e for e in log if e["bucket"] == "deferred"]
    assert len(deferred_entries) == 1
    assert deferred_entries[0]["key"] == "a"
    assert deferred_entries[0]["detail"] == {"scene_name": "a", "reason": "preview"}
    assert list(data["scenes"].keys()) == [], "no real scene fire happened"


def test_preview_active_skip_uses_scene_name_when_scene_exists(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(SceneV2(id="a", name="Black Hole V2"))
    preview_pause.start(30.0)
    result = _run(fire_scene_by_id("a", intensity=0.5))
    assert result["scene_name"] == "Black Hole V2"


def test_preview_active_skip_survives_an_unknown_scene_id(monkeypatch):
    """disabled/mode_availability/dwell all require the scene to already
    exist (fire_scene_by_id raises ValueError for an unknown id past this
    point) — the preview gate runs BEFORE that lookup even matters, so an
    id that doesn't resolve to a stored scene must not raise."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    preview_pause.start(30.0)
    result = _run(fire_scene_by_id("does-not-exist", intensity=0.5))
    assert result == {"skipped": "preview", "scene_id": "does-not-exist",
                      "scene_name": "does-not-exist"}


# ── 3. outranks Force Scene ──────────────────────────────────────────────

def test_preview_outranks_force_scene(monkeypatch):
    """Matches preview_pause's own documented precedence at bridge.py's
    conductor_deferral/sequencer_deferral (preview beats force_scene
    there too) — the one gate in fire_scene_by_id Force Scene does NOT
    override. The pin's own redirect must never even apply: the skip
    reports the ORIGINALLY requested scene_id, not the pinned one."""
    from spectra.services import room_controls as rc
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("requested"))
    scene_store.save(_scene("pinned"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="pinned"))

    preview_pause.start(30.0)
    result = _run(fire_scene_by_id("requested", intensity=0.5))

    assert fired == [], "Force Scene's reassert must not land on top of a preview"
    assert result["skipped"] == "preview"
    assert result["scene_id"] == "requested"
    assert "overrode_disabled" not in result
    assert "overrode_dwell" not in result


# ── 4. dwell is untouched by a preview skip ──────────────────────────────

def test_preview_skip_never_touches_dwell(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)

    _run(fire_scene_by_id("a", intensity=0.0))  # latches dwell on "a"
    assert dwell.active_scene_id() == "a"

    preview_pause.start(30.0)
    result = _run(fire_scene_by_id("b", intensity=0.7))
    assert result["skipped"] == "preview"
    assert dwell.active_scene_id() == "a", \
        "a preview skip must not disturb dwell's own latch either way"


# ── 5. abandonment: the deadline self-heals with no explicit close ──────

def test_abandoned_preview_self_heals_without_ever_calling_clear(monkeypatch):
    """The safety property that matters more than the hold itself: a hold
    that can outlive the preview is worse than no hold at all. preview_pause
    is a plain time.monotonic() deadline, not a flag someone has to
    remember to clear — so simulate exactly the failure mode that would
    strand his room (browser closed, connection dropped, heartbeats just
    stop) by starting the pause and then letting real time pass IT, never
    calling preview_pause.clear() or preview_pause touch/heartbeat again.
    The next fire_scene_by_id call must fire normally on its own."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)

    base = time_mod.monotonic()
    clock = {"t": base}
    monkeypatch.setattr(time_mod, "monotonic", lambda: clock["t"])

    preview_pause.start(15.0)  # matches flare_preview_hold.HEARTBEAT_TIMEOUT_S
    result = _run(fire_scene_by_id("a", intensity=0.5))
    assert result["skipped"] == "preview"
    assert fired == []

    # No heartbeat ever arrives — the browser is gone. Advance real time
    # (via the monkeypatched clock) past the deadline, exactly as would
    # happen if nobody ever called /close.
    clock["t"] = base + 16.0
    assert preview_pause.active() is False, \
        "active() is a pure deadline comparison — it must lapse on its " \
        "own, no sweep/task/explicit clear required to observe this"

    result = _run(fire_scene_by_id("a", intensity=0.5))
    assert "skipped" not in result, \
        "his show must resume on its own once the deadline lapses — " \
        "never stay frozen because a window went away with no explicit close"
    assert fired == [("a", 0.5)]


def test_explicit_close_also_resumes_fires_immediately(monkeypatch):
    """The easy path, for completeness — a clean preview_pause.clear() (what
    POST /api/flare-preview/close and /api/room-preview/close both call)
    resumes fires immediately too, same as the abandonment path above."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    _fake_scene_compiler(monkeypatch, [])

    preview_pause.start(30.0)
    result = _run(fire_scene_by_id("a", intensity=0.5))
    assert result["skipped"] == "preview"

    preview_pause.clear()
    result = _run(fire_scene_by_id("a", intensity=0.5))
    assert "skipped" not in result
