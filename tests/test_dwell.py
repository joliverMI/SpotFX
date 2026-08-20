"""Minimum dwell (2026-08-20, data/plan-make-dwell-meaningful-under-the-
rea-4p73/{report,HIS-DECISION}.md) — dwell rebuilt under the real
definition of a song transition. Proves:

  1. SceneV2.dwell_curve resolution: default (16s/4s), inline, named
     profile, dangling ref, curve mutual-exclusivity validation.
  2. spectra/services/dwell.py's process-global latch: note_fired latches
     once from the intensity handed to it (answer B); remaining_s decays
     from that latch; reset() clears it.
  3. fire_scene_by_id's dwell gate: cold start fires normally; a request
     inside an active dwell window is DEFERRED — the update-effect seam
     (engine.fire_scene_update_event) is called instead of
     scene_compiler.fire_scene, and the deferral is recorded to
     fire_history's "deferred" bucket, never silent; a request after the
     window elapsed fires normally.
  4. No reset on a deferred request (answer A): only a real fire ever
     calls dwell.note_fired.
  5. Force Scene wins over an active dwell but NAMES it
     (overrode_dwell=True), same pattern as overrode_disabled.
  6. SceneSequencer._roll() never adopts a scene fire_scene_by_id declined
     — the exact staleness dwell.py's own docstring exists to avoid.

No live access — storage isolated the same way test_scene_disable.py does.
tests/conftest.py's autouse _isolated_dwell resets spectra.services.dwell's
process-global state before/after every test.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.models.scene import CurveAttachment, FlareKind, SceneV2
from spectra.services import dwell, fire_history
from spectra.services import scene_store


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "FIRE_HISTORY_FILE", tmp_path / "fire_history.json")
    monkeypatch.setattr(scfg, "SHOW_LOG_FILE", tmp_path / "show_log.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


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


# ── 1. curve resolution ─────────────────────────────────────────────────

def test_default_dwell_curve_when_unset():
    s = _scene("s1")
    assert s.dwell_curve is None
    assert dwell.dwell_seconds(s, 0.0) == 16.0
    assert dwell.dwell_seconds(s, 1.0) == 4.0
    assert dwell.dwell_seconds(s, 0.5) == 10.0


def test_inline_dwell_curve_overrides_default():
    s = _scene("s1", dwell_curve=CurveAttachment(
        inline_points=[{"x": 0.0, "y": 20.0}, {"x": 1.0, "y": 2.0}]))
    assert dwell.dwell_seconds(s, 0.0) == 20.0
    assert dwell.dwell_seconds(s, 1.0) == 2.0


def test_named_profile_dwell_curve():
    from spectra.models.sequencer import CurvePoint, CurveProfile
    from spectra.services import sequencer_store
    sequencer_store.save_curves({"p1": CurveProfile(
        id="p1", name="Slow", points=[CurvePoint(x=0.0, y=30.0), CurvePoint(x=1.0, y=30.0)])})
    s = _scene("s1", dwell_curve=CurveAttachment(curve_ref="p1"))
    assert dwell.dwell_seconds(s, 0.3) == 30.0


def test_dangling_curve_ref_falls_back_to_default():
    s = _scene("s1", dwell_curve=CurveAttachment(curve_ref="does-not-exist"))
    assert dwell.dwell_seconds(s, 0.0) == 16.0


def test_curve_attachment_rejects_both_curve_ref_and_inline_points():
    with pytest.raises(Exception):
        CurveAttachment(curve_ref="p1", inline_points=[{"x": 0.0, "y": 1.0}])


def test_dwell_curve_falls_back_on_a_bare_scene_like_object():
    """resolve_dwell_curve_points must never assume a real SceneV2 —
    fire_history.py's own tests fire a plain id/name object through
    fire_scene_by_id."""
    class FakeScene:
        id = "x"
        name = "X"
    assert dwell.dwell_seconds(FakeScene(), 0.5) == 10.0


# ── 2. the process-global latch ─────────────────────────────────────────

def test_remaining_s_zero_when_nothing_tracked():
    assert dwell.remaining_s() == 0.0
    assert dwell.active_scene_id() is None
    assert dwell.status() == {
        "active_scene_id": None, "active_scene_name": None,
        "dwell_seconds": None, "remaining_s": None,
    }


def test_note_fired_latches_from_the_given_intensity_once():
    s = _scene("s1")
    dwell.note_fired(s, 0.0, now_ms=1_000_000)
    assert dwell.active_scene_id() == "s1"
    assert dwell.status()["dwell_seconds"] == 16.0
    # 5s later: 11s still owed.
    assert dwell.remaining_s(now_ms=1_005_000) == pytest.approx(11.0)
    # 16s later: fully cleared, floored at 0.
    assert dwell.remaining_s(now_ms=1_016_000) == 0.0
    assert dwell.remaining_s(now_ms=1_030_000) == 0.0


def test_reset_clears_the_latch():
    dwell.note_fired(_scene("s1"), 0.0)
    assert dwell.active_scene_id() == "s1"
    dwell.reset()
    assert dwell.active_scene_id() is None
    assert dwell.remaining_s() == 0.0


# ── 3. fire_scene_by_id's gate ──────────────────────────────────────────

def test_fire_scene_by_id_cold_start_fires_and_latches(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)

    result = _run(fire_scene_by_id("s1", intensity=0.0))
    assert "skipped" not in result
    assert fired == [("s1", 0.0)]
    assert dwell.active_scene_id() == "s1"
    assert dwell.status()["dwell_seconds"] == 16.0


def test_fire_scene_by_id_defers_a_different_scene_inside_the_dwell_window(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    update_calls: list = []
    _fake_update_seam(monkeypatch, update_calls, result={"result": "no_update_kind"})

    _run(fire_scene_by_id("a", intensity=0.0))
    result = _run(fire_scene_by_id("b", intensity=0.7))

    assert fired == [("a", 0.0)], "the deferred scene must never reach scene_compiler.fire_scene"
    assert update_calls == [0.7], "the update-effect seam fires at the DEFERRED request's own intensity"
    assert result["skipped"] == "dwell"
    assert result["scene_id"] == "b"
    assert result["scene_name"] == "b"
    assert result["remaining_dwell_s"] > 0
    assert result["update_result"] == {"result": "no_update_kind"}
    assert dwell.active_scene_id() == "a", "the deferred request must not move the active scene"


def test_fire_scene_by_id_defers_even_the_same_scene_requested_again(monkeypatch):
    """The literal design: dwell governs whether the room may change AT
    ALL during the window, not only a switch to a DIFFERENT scene."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    update_calls: list = []
    _fake_update_seam(monkeypatch, update_calls)

    _run(fire_scene_by_id("a", intensity=0.0))
    result = _run(fire_scene_by_id("a", intensity=0.0))
    assert fired == [("a", 0.0)]
    assert result["skipped"] == "dwell"


def test_fire_scene_by_id_fires_normally_once_the_window_has_elapsed(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)

    dwell.note_fired(scene_store.get_by_id("a"), 1.0, now_ms=1_000_000)  # 4s minimum
    assert dwell.remaining_s(now_ms=1_005_000) == 0.0

    import time as time_mod
    monkeypatch.setattr(time_mod, "time", lambda: 1_005_000 / 1000.0)
    result = _run(fire_scene_by_id("b", intensity=0.5))
    assert "skipped" not in result
    assert fired == [("b", 0.5)]
    assert dwell.active_scene_id() == "b"


def test_deferral_never_relatches_dwell_no_reset_on_update_effect(monkeypatch):
    """Answer A: dwell.note_fired must be called ONLY on a real fire — a
    deferred request (however many times it's retried) must never extend
    or restart the active scene's own window."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    _fake_update_seam(monkeypatch, [])

    note_fired_calls: list = []
    orig_note_fired = dwell.note_fired

    def spy_note_fired(scene, intensity, **kw):
        note_fired_calls.append(scene.id)
        return orig_note_fired(scene, intensity, **kw)
    monkeypatch.setattr(dwell, "note_fired", spy_note_fired)

    _run(fire_scene_by_id("a", intensity=0.0))
    _run(fire_scene_by_id("b", intensity=0.5))
    _run(fire_scene_by_id("b", intensity=0.9))
    assert note_fired_calls == ["a"], \
        "two deferred requests must not touch the latch at all"


def test_intensity_latched_at_entry_not_reevaluated(monkeypatch):
    """Answer B: dwell_seconds is fixed at the intensity the scene actually
    fired at — a later deferred request at a different intensity must not
    change it."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    _fake_update_seam(monkeypatch, [])

    _run(fire_scene_by_id("a", intensity=0.0))  # latches 16.0s
    assert dwell.status()["dwell_seconds"] == 16.0
    _run(fire_scene_by_id("b", intensity=1.0))  # deferred; must not relatch to 4.0
    assert dwell.status()["dwell_seconds"] == 16.0


def test_deferred_fires_are_recorded_never_silent(monkeypatch):
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    _fake_update_seam(monkeypatch, [], result={"result": "updated"})

    _run(fire_scene_by_id("a", intensity=0.0))
    _run(fire_scene_by_id("b", intensity=0.5))

    data = fire_history.load_all()
    assert data["deferred"]["b"]["count"] == 1
    log = fire_history.load_show_log()
    deferred_entries = [e for e in log if e["bucket"] == "deferred"]
    assert len(deferred_entries) == 1
    assert deferred_entries[0]["key"] == "b"
    assert deferred_entries[0]["detail"]["update_result"] == "updated"
    # The scenes bucket only ever records the ONE real fire (a), not b.
    assert list(data["scenes"].keys()) == ["a"]


# ── 3b. the update seam's own gate, post-#148 (his room's live mode) ────

def test_fire_scene_update_event_runs_under_triggers_only(monkeypatch):
    """engine.fire_scene_update_event gained a second caller here (dwell's
    deferral) the same week #148 widened its own internal gate from
    literal "full" to ("full", "triggers_only") for the pre-existing
    trigger-driven caller. His room runs "triggers_only" live — dwell's
    deferral must still reach on_update there, not just under "full"."""
    from spectra.services import engine, room_controls as rc

    calls: list = []

    async def fake_on_update(intensity):
        calls.append(intensity)
        return {"result": "updated", "intensity": intensity}
    # Patched on the INSTANCE, not the class: an instance attribute is
    # called exactly as given (no implicit self-binding), unlike a class
    # attribute accessed through the instance.
    monkeypatch.setattr(engine.responses, "on_update", fake_on_update)

    for mode in ("full", "triggers_only"):
        calls.clear()
        rc.save_room_controls(rc.RoomControlState(scene_change_mode=mode))
        result = _run(engine.fire_scene_update_event(0.6))
        assert calls == [0.6], f"on_update must run under {mode!r}"
        assert result == {"result": "updated", "intensity": 0.6}

    for mode in ("analysed", "transitions"):
        calls.clear()
        rc.save_room_controls(rc.RoomControlState(scene_change_mode=mode))
        result = _run(engine.fire_scene_update_event(0.6))
        assert calls == [], f"on_update must NOT run under {mode!r}"
        assert result is None


def test_dwell_defers_correctly_regardless_of_scene_change_mode(monkeypatch):
    """The dwell gate itself (fire_scene_by_id) never reads scene_change_mode
    at all — his decision C, every automatic path gated uniformly. Proven
    under his room's real live mode, "triggers_only", not just the "full"
    default every other test in this file runs under."""
    from spectra.services import room_controls as rc
    from spectra.services.scene_sequencer import fire_scene_by_id
    rc.save_room_controls(rc.RoomControlState(scene_change_mode="triggers_only"))
    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    update_calls: list = []
    _fake_update_seam(monkeypatch, update_calls, result={"result": "updated"})

    _run(fire_scene_by_id("a", intensity=0.0))
    result = _run(fire_scene_by_id("b", intensity=0.7))
    assert fired == [("a", 0.0)]
    assert update_calls == [0.7]
    assert result["skipped"] == "dwell"


# ── 4. Force Scene wins but names the override ──────────────────────────

def test_force_scene_overrides_active_dwell_and_names_it(monkeypatch):
    from spectra.services import room_controls as rc
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("pinned"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    _fake_update_seam(monkeypatch, [])

    _run(fire_scene_by_id("a", intensity=0.0))
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="pinned"))
    result = _run(fire_scene_by_id("a", intensity=0.5))

    assert fired[-1] == ("pinned", 0.5), "the pin wins even mid-dwell"
    assert result.get("overrode_dwell") is True
    assert dwell.active_scene_id() == "pinned", \
        "a forced fire still re-latches — it's a real fire, not a deferral"


def test_force_scene_no_override_flag_when_dwell_not_active(monkeypatch):
    from spectra.services import room_controls as rc
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("pinned"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="pinned"))
    result = _run(fire_scene_by_id("requested-does-not-matter", intensity=0.5))
    assert "overrode_dwell" not in result


def test_reconcile_force_scene_forwards_overrode_dwell(monkeypatch):
    from spectra.services import room_controls as rc
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("a"))
    scene_store.save(_scene("pinned"))
    fired: list = []
    _fake_scene_compiler(monkeypatch, fired)
    _fake_update_seam(monkeypatch, [])

    _run(fire_scene_by_id("a", intensity=0.0))
    prev = rc.RoomControlState(force_scene_enabled=False)
    new = rc.RoomControlState(force_scene_enabled=True, force_scene_scene_id="pinned")
    rc.save_room_controls(new)
    result = _run(rc.reconcile_force_scene_if_changed(prev, new))
    assert result["status"] == "fired"
    assert result.get("overrode_dwell") is True


# ── 5. SceneSequencer._roll() never adopts a fire fire_scene_by_id declined ─

def test_roll_does_not_adopt_a_scene_that_was_declined():
    from spectra.models.sequencer import SelectorEntry
    from spectra.services import sequencer_store
    from spectra.services.scene_sequencer import SceneSequencer

    scene_store.save(_scene("a"))
    scene_store.save(_scene("b"))

    async def fake_fire(scene_id, color_set_id, intensity):
        # Simulate dwell declining every fire — the exact shape
        # fire_scene_by_id returns on a deferral.
        return {"skipped": "dwell", "scene_id": scene_id, "scene_name": scene_id,
               "remaining_dwell_s": 12.0, "update_result": None}

    seq = SceneSequencer(fire=fake_fire, intensity=lambda: 0.5,
                         deferral_fn=lambda: None, genre_bucket=lambda: None,
                         trigger_scene_id=lambda: None)
    cfg = sequencer_store.load_config()
    cfg.entries = {"a": SelectorEntry(), "b": SelectorEntry()}
    sequencer_store.save_config(cfg)

    _run(seq._roll(cfg, "test"))
    assert seq._active_id is None, \
        "a declined fire must never be adopted as the sequencer's current scene"
    assert seq._last_moment["result"].startswith("skipped:")


def test_roll_adopts_normally_when_the_fire_actually_lands():
    from spectra.models.sequencer import SelectorEntry
    from spectra.services import sequencer_store
    from spectra.services.scene_sequencer import SceneSequencer

    scene_store.save(_scene("a"))

    async def fake_fire(scene_id, color_set_id, intensity):
        return {"dry_run": False, "intensity": intensity, "writes": []}

    seq = SceneSequencer(fire=fake_fire, intensity=lambda: 0.5,
                         deferral_fn=lambda: None, genre_bucket=lambda: None,
                         trigger_scene_id=lambda: None)
    cfg = sequencer_store.load_config()
    cfg.entries = {"a": SelectorEntry()}
    sequencer_store.save_config(cfg)

    _run(seq._roll(cfg, "test"))
    assert seq._active_id == "a"
    assert seq._last_moment["result"] == "picked"


# ── 6. manual editor Fire bypasses the gate entirely (structural, unchanged) ─

def test_manual_editor_fire_bypasses_dwell(monkeypatch):
    """POST /scenes/{id}/fire calls scene_compiler.fire_scene directly,
    never fire_scene_by_id — same bypass disabled/mode-availability already
    document (test_scene_disable.py's own proof). The dwell gate lives
    entirely inside fire_scene_by_id (spectra/api/scenes.py is untouched by
    this module), so the REAL scene_compiler.fire_scene must still fire
    immediately even while another scene's minimum dwell is actively held."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    from spectra.services import scene_compiler

    scene_b = _scene("b")
    scene_store.save(_scene("a"))
    scene_store.save(scene_b)
    fired: list = []
    orig_fire_scene = scene_compiler.fire_scene
    _fake_scene_compiler(monkeypatch, fired)

    _run(fire_scene_by_id("a", intensity=0.0))
    assert dwell.remaining_s() > 0

    monkeypatch.setattr(scene_compiler, "fire_scene", orig_fire_scene)
    result = _run(scene_compiler.fire_scene(scene_b, intensity=0.5, dry_run=True))
    assert "skipped" not in result
