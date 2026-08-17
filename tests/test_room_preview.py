"""Room-colour Preview (owner ask, 2026-08-17, spectra/services/
room_preview.py) — proves the three acceptance criteria against a REAL
headless dummy host (fx.headless + fx.facade, ownership=spectra), the same
frame-level rig test_dark_light.py uses:

  1. Revert restores EXACTLY what was live the instant the preview
     started (proof 1/2 below) — never a computed/assumed state.
  2. The pause (spectra/services/preview_pause.py) releases on the timer
     (proof 1), an explicit release (proof 3), and — via bridge wiring
     proven separately in test_bridge.py's own deferral tests — outranks
     every existing deferral reason.
  3. A live-drag update() re-applies colours without touching the snapshot
     or the timer (proof 4/5): the ORIGINAL pre-preview state is still
     what a later revert restores, not the mid-drag colour.

TAP_HOLD_S/HOLD_HOLD_S are monkeypatched to millisecond durations so the
timer proofs run fast; the mechanism under test is otherwise untouched.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, facade, headless


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
              "virtuals": [headless.DEFAULT_VIRTUAL_ID], "effects": ["concentric"]}}))
    device_model.refresh()


@pytest.fixture(autouse=True)
def _reset_preview_state():
    from spectra.services import preview_pause, room_preview
    room_preview._snapshot = None
    room_preview._hold = False
    room_preview._revert_task = None
    preview_pause.clear()
    yield
    if room_preview._revert_task is not None:
        room_preview._revert_task.cancel()
    room_preview._snapshot = None
    room_preview._hold = False
    room_preview._revert_task = None
    preview_pause.clear()


def _own(monkeypatch, tmp_path) -> None:
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)


VID = headless.DEFAULT_VIRTUAL_ID


async def _start_host(tmp_path):
    host = await headless.start_headless_host(str(tmp_path / "host"))
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    headless.attach_effect(host, virtual, "concentric",
                           {"background_color": "#ff0000",
                            "background_brightness": 1.0,
                            "gradient": "linear-gradient(90deg, #111111 0%, #222222 100%)"})
    return host, virtual


def _set_card(**kw):
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    entry = kw.pop("entry", None) or ColorSetEntry(
        scope=SetScope(virtual_ids=[VID]), color_kind="solid",
        color_value="#00ff00", bg_color="#0000ff")
    return ColorSetCard(id="preview-set", name="preview-set", kind="set",
                        entries=[entry], **kw)


# ── 1. tap: applies, then auto-reverts to EXACTLY the live pre-preview state ─

def test_tap_preview_applies_then_auto_reverts_to_live_snapshot(tmp_path, monkeypatch):
    from spectra.services import preview_pause, room_preview
    monkeypatch.setattr(room_preview, "TAP_HOLD_S", 0.05)
    _own(monkeypatch, tmp_path)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_bg = virtual.active_effect.config["background_color"]
            orig_gradient = virtual.active_effect.config["gradient"]

            result = await room_preview.start(_set_card(), hold=False)
            assert result["applied"] is True
            assert result["virtuals"] == [VID]
            # applied live, immediately, over the real render pipeline
            assert virtual.active_effect.config["gradient"] == "#00ff00"
            assert virtual.active_effect.config["background_color"] == "#0000ff"
            assert preview_pause.active() is True
            assert room_preview.active() is True

            await asyncio.sleep(0.15)   # past TAP_HOLD_S

            assert room_preview.active() is False
            assert preview_pause.active() is False
            # reverted to the EXACT pre-preview live config, not a guess
            assert virtual.active_effect.config["background_color"] == orig_bg
            assert virtual.active_effect.config["gradient"] == orig_gradient
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 2. hold: pauses/applies and STAYS past the tap window ──────────────────

def test_hold_preview_outlasts_tap_window_until_released(tmp_path, monkeypatch):
    from spectra.services import preview_pause, room_preview
    monkeypatch.setattr(room_preview, "TAP_HOLD_S", 0.02)
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 0.3)
    _own(monkeypatch, tmp_path)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            result = await room_preview.start(_set_card(), hold=True)
            assert result["hold"] is True
            await asyncio.sleep(0.05)   # well past the tap window
            assert room_preview.active() is True, "a hold must outlast the tap window"
            assert preview_pause.active() is True

            release = await room_preview.release()
            assert release["reverted"] is True
            assert room_preview.active() is False
            assert preview_pause.active() is False
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 3. explicit release cancels the pending auto-revert (no double-write) ──

def test_release_cancels_pending_auto_revert(tmp_path, monkeypatch):
    from spectra.services import room_preview
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 5.0)
    _own(monkeypatch, tmp_path)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            await room_preview.start(_set_card(), hold=True)
            task = room_preview._revert_task
            assert task is not None and not task.done()
            await room_preview.release()
            await asyncio.sleep(0)
            assert task.cancelled() or task.done()
            assert room_preview._revert_task is None
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 4/5. live-drag update(): re-applies without touching snapshot/timer ────

def test_update_applies_live_without_disturbing_snapshot_or_timer(tmp_path, monkeypatch):
    from spectra.services import preview_pause, room_preview
    monkeypatch.setattr(room_preview, "TAP_HOLD_S", 0.15)
    _own(monkeypatch, tmp_path)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_bg = virtual.active_effect.config["background_color"]
            await room_preview.start(_set_card(), hold=False)
            remaining_after_start = preview_pause.remaining_s()

            from spectra.services.color_sets import ColorSetEntry, SetScope
            dragged_entry = ColorSetEntry(scope=SetScope(virtual_ids=[VID]),
                                          color_kind="solid", color_value="#abcdef")
            upd = await room_preview.update(_set_card(entry=dragged_entry))
            assert upd["applied"] is True
            assert virtual.active_effect.config["gradient"] == "#abcdef"
            # dragging did not restart the pause clock
            assert preview_pause.remaining_s() <= remaining_after_start

            await asyncio.sleep(0.25)   # past the ORIGINAL tap window
            assert room_preview.active() is False
            # revert restores the ORIGINAL pre-preview state, not the dragged colour
            assert virtual.active_effect.config["background_color"] == orig_bg
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_update_after_session_ended_is_a_noop(tmp_path, monkeypatch):
    from spectra.services import room_preview
    _own(monkeypatch, tmp_path)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            before = dict(virtual.active_effect.config)
            result = await room_preview.update(_set_card())
            assert result == {"applied": False, "virtuals": []}
            assert virtual.active_effect.config == before
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 6. starting a new preview while one is active reverts the old first ────

def test_starting_new_preview_reverts_the_old_one_first(tmp_path, monkeypatch):
    from spectra.services import room_preview
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 5.0)
    _own(monkeypatch, tmp_path)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_bg = virtual.active_effect.config["background_color"]
            await room_preview.start(_set_card(), hold=True)
            assert virtual.active_effect.config["background_color"] == "#0000ff"

            from spectra.services.color_sets import ColorSetEntry, SetScope
            second_entry = ColorSetEntry(scope=SetScope(virtual_ids=[VID]),
                                         color_kind="solid", color_value="#123456",
                                         bg_color="#654321")
            result = await room_preview.start(_set_card(entry=second_entry), hold=True)
            assert result["applied"] is True
            # the SECOND preview's colour is live now...
            assert virtual.active_effect.config["background_color"] == "#654321"
            # ...and the snapshot held for revert is the ORIGINAL live state,
            # not the first preview's colour (proves the old session actually
            # reverted before the new one snapshotted, rather than stacking).
            release = await room_preview.release()
            assert release["reverted"] is True
            assert virtual.active_effect.config["background_color"] == orig_bg
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 7. bridge deferral wiring: preview outranks pause/dinner_party/ambient/
#      force_scene ──────────────────────────────────────────────────────────

def test_bridge_deferral_reports_preview_first():
    from spectra.services import preview_pause
    from spectra.services.bridge import SpotEffectsBridge
    b = SpotEffectsBridge()
    b.paused = True
    b.dinner_party = True
    b.ambient = True
    b.force_scene = True
    assert b.conductor_deferral() == "paused"
    assert b.sequencer_deferral() == "force_scene"
    preview_pause.start(5.0)
    try:
        assert b.conductor_deferral() == "preview"
        assert b.sequencer_deferral() == "preview"
    finally:
        preview_pause.clear()
