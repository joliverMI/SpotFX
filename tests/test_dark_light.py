"""SPECTRA global Dark/Light room mode (day-one bar, SPECTRA_SPEC.md §9) —
offline proof.

The proofs:
  1. Frame-level: dark_light.reconcile() against a REAL headless dummy host
     (fx.headless + fx.facade, ownership=spectra) actually engages LedFX's
     vendored dark_lock clamp — the virtual's config flips, the ALREADY
     RUNNING effect's background is blacked in place — and reconcile(False)
     repaints the exact pre-dark background from the snapshot it captured.
     This is the mechanism claim (spectra/services/dark_light.py's
     docstring: "the SAME vendored code SPECTRA already writes through")
     proven against the real render pipeline, not a mock.
  2. Shielding: a shielded category/virtual is always pushed dark_lock=False
     regardless of mode, and never snapshotted/restored (mirrors legacy's
     services/display_mode.shielded_virtuals() semantics).
  3. Idempotency: reconciling dark twice never clobbers a good snapshot with
     a black one.
  4. Status shapes: no known virtuals, and light_ownership refusing a write
     (handover in flight / released), never raise — the room-control save
     itself must still succeed.
  5. room_controls.reconcile_dark_light_if_changed only fires on an actual
     mode flip, or a shield-list edit while already dark (mirrors legacy's
     resync() on a shield-setting change) — same wiring test shape as
     test_room_controls.py's ambient/force-scene proofs.
  6. Music-aware repaint gate: while spot-effects reports a track actively
     playing, the light-transition does NOT force the stale pre-dark
     snapshot back (dark_lock still clears) — the room's own live show is
     left to repaint it on its next natural fire, same lesson as Ambient
     holding a room static through a song. With nothing playing (paused, or
     no track — the room-proof's own condition), the snapshot restore
     proceeds exactly as in proof 1.

No LedFX HTTP, no audio hardware. Bridge state is touched via
monkeypatch.setattr only (auto-reverted per test, never a raw mutation) —
see test_bridge_gates_repaint_on_music_playing below.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "DARK_LIGHT_SNAPSHOT_FILE", tmp_path / "dark_light_snapshot.json")


def _own(monkeypatch, tmp_path, owner: str) -> None:
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": owner}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)


def _categories(monkeypatch, tmp_path, cats: dict) -> None:
    from fx import device_model
    path = tmp_path / "device_categories.json"
    path.write_text(json.dumps(cats))
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", path)
    device_model.refresh()


VID = headless.DEFAULT_VIRTUAL_ID


# ── 1. frame-level: the real dark_lock clamp, real repaint ─────────────────

def test_reconcile_engages_real_dark_lock_and_repaints_on_release(tmp_path, monkeypatch):
    from spectra.services import dark_light

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        headless.attach_effect(host, virtual, "concentric",
                               {"background_color": "#ff0000",
                                "background_brightness": 1.0})
        assert virtual.active_effect.config["background_color"] == "#ff0000"

        dark_result = await dark_light.reconcile(True, [], [])
        assert dark_result["status"] == "dark"
        assert dark_result["locked"] == [VID]
        assert not dark_result.get("unconfirmed")
        # the real vendored mechanism: virtual config flipped...
        assert virtual.config["dark_lock"] is True
        # ...and the ALREADY-RUNNING effect was blacked in place immediately
        # (fx/virtuals.py's dark_lock_turned_on branch), not on the next fire.
        assert virtual.active_effect.config["background_color"] == "#000000"
        assert virtual.active_effect.config["background_brightness"] == 0.0

        # a write attempting to relight the background while locked is
        # clamped too (fx/effects/__init__.py's _apply_config guard) —
        # proves the "no write path" half of the claim, not just the
        # on-lock snap.
        virtual.active_effect.update_config({"background_color": "#00ff00"})
        assert virtual.active_effect.config["background_color"] == "#000000"

        light_result = await dark_light.reconcile(False, [], [])
        assert light_result["status"] == "light"
        assert light_result["restored"] == [VID]
        assert virtual.config["dark_lock"] is False
        # repainted from the pre-dark snapshot, not left black
        assert virtual.active_effect.config["background_color"] == "#ff0000"
        assert virtual.active_effect.config["background_brightness"] == 1.0

        await host.shutdown()

    _run(main())


def test_reconcile_dark_twice_does_not_clobber_snapshot_with_black(tmp_path, monkeypatch):
    from spectra.services import dark_light

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        headless.attach_effect(host, virtual, "concentric",
                               {"background_color": "#123456", "background_brightness": 0.7})

        await dark_light.reconcile(True, [], [])
        await dark_light.reconcile(True, [], [])  # already dark — must not re-snapshot black
        result = await dark_light.reconcile(False, [], [])
        assert result["restored"] == [VID]
        assert virtual.active_effect.config["background_color"] == "#123456"
        assert virtual.active_effect.config["background_brightness"] == 0.7

        await host.shutdown()

    _run(main())


# ── 1b. music-aware repaint gate ────────────────────────────────────────────

def _set_playing(monkeypatch, playing: bool) -> None:
    """Point the S2 bridge singleton (spectra.services.engine.bridge) at a
    playing/not-playing state via monkeypatch.setattr ONLY — auto-reverted
    at test teardown regardless of pass/fail, never a raw mutation of the
    shared singleton (the exact class of state leak a real incident traced
    back to test_ambient.py's own live_host singleton, 2026-08-15).
    bridge.is_playing() (spectra/services/bridge.py) returns None (not
    False) until _last_message_at is set — a fresh/never-fed bridge must
    also be set here or "confirmed playing" is indistinguishable from
    "no signal yet"."""
    from spectra.services.engine import bridge
    monkeypatch.setattr(bridge, "_last_message_at", 1000.0)
    monkeypatch.setattr(bridge, "_track",
                        {"is_playing": playing, "spotify_uri": "spotify:track:x"}
                        if playing else None)


def test_bridge_gates_repaint_on_music_playing(tmp_path, monkeypatch):
    from spectra.services import dark_light

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        headless.attach_effect(host, virtual, "concentric",
                               {"background_color": "#ff0000", "background_brightness": 1.0})

        await dark_light.reconcile(True, [], [])
        assert virtual.active_effect.config["background_color"] == "#000000"

        _set_playing(monkeypatch, True)
        result = await dark_light.reconcile(False, [], [])
        assert result["status"] == "light"
        assert result["restored"] == []
        assert result["repaint_skipped"] == "music_playing"
        # dark_lock still clears — nothing is left forced black...
        assert virtual.config["dark_lock"] is False
        # ...but the stale snapshot was NOT forced back over a live show
        assert virtual.active_effect.config["background_color"] == "#000000"

        await host.shutdown()

    _run(main())


def test_bridge_not_playing_still_repaints_as_before(tmp_path, monkeypatch):
    """Paused, and no track at all, both count as "not playing" — the
    ordinary snapshot-restore proceeds in either case (the room-proof's own
    condition: no music authorised, nothing playing)."""
    from spectra.services import dark_light

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        headless.attach_effect(host, virtual, "concentric",
                               {"background_color": "#00ff00", "background_brightness": 1.0})

        await dark_light.reconcile(True, [], [])

        _set_playing(monkeypatch, False)  # confirmed not-playing, not just unknown
        result = await dark_light.reconcile(False, [], [])
        assert result["restored"] == [VID]
        assert "repaint_skipped" not in result
        assert virtual.active_effect.config["background_color"] == "#00ff00"

        await host.shutdown()

    _run(main())


def test_bridge_unknown_playback_still_repaints_not_skips(tmp_path, monkeypatch):
    """bridge.is_playing() returning None (no signal yet — a fresh bridge,
    e.g. right after a SPECTRA restart with no broadcast received) must
    NOT be treated as "confirmed playing": unlike ambient_music_gate's own
    fail-safe (unknown carries the existing hold forward), this repaint
    has no continuous state to carry forward, so an unresolved read
    defaults to proceeding — the room must still visually recover from
    dark on a fresh process, not silently stay black forever."""
    from spectra.services import dark_light
    from spectra.services.engine import bridge

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        headless.attach_effect(host, virtual, "concentric",
                               {"background_color": "#0000ff", "background_brightness": 1.0})

        await dark_light.reconcile(True, [], [])

        monkeypatch.setattr(bridge, "_last_message_at", None)  # never received a broadcast
        assert bridge.is_playing() is None
        result = await dark_light.reconcile(False, [], [])
        assert result["restored"] == [VID]
        assert "repaint_skipped" not in result
        assert virtual.active_effect.config["background_color"] == "#0000ff"

        await host.shutdown()

    _run(main())


# ── 2. shielding ─────────────────────────────────────────────────────────

def test_shielded_virtual_never_locked_and_never_snapshotted(tmp_path, monkeypatch):
    from spectra.services import dark_light

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]},
        "c2": {"id": "c2", "name": "Singles", "parent_id": None,
               "virtuals": ["singles-dummy"], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        main_v = host.virtuals.get(VID)
        headless.attach_effect(host, main_v, "concentric", {"background_color": "#ff0000"})

        result = await dark_light.reconcile(True, ["Singles"], [])
        assert result["status"] == "dark"
        assert result["locked"] == [VID]
        assert "singles-dummy" not in result["locked"]
        # declared (device_model knows about it via the category) but
        # shielded — always pushed dark_lock=False, never in `locked`
        assert result["shielded"] == ["singles-dummy"]

        await host.shutdown()

    _run(main())


def test_shield_virtuals_field_exempts_by_id_without_a_category(tmp_path, monkeypatch):
    from spectra.services import dark_light

    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "host"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        headless.attach_effect(host, virtual, "concentric", {"background_color": "#ff0000"})

        result = await dark_light.reconcile(True, [], [VID])
        assert result["locked"] == []
        assert result["shielded"] == [VID]
        assert virtual.config["dark_lock"] is False

        await host.shutdown()

    _run(main())


# ── 3/4. status shapes: no devices, mid-handover, released ─────────────────

def test_reconcile_no_known_virtuals_reports_no_devices(tmp_path, monkeypatch):
    from spectra.services import dark_light
    _own(monkeypatch, tmp_path, "spectra")
    _categories(monkeypatch, tmp_path, {})

    result = _run(dark_light.reconcile(True, [], []))
    assert result == {"status": "no-devices"}


def test_reconcile_mid_handover_and_released_never_raise(tmp_path, monkeypatch):
    from fx import light_ownership as lo
    from spectra.services import dark_light
    _categories(monkeypatch, tmp_path, {
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}})

    ownership_path = tmp_path / "ownership.json"
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", ownership_path)
    # a bare "handing-over" owner with no handover block is treated as the
    # shipped default (spot-effects) by light_ownership.load()'s own error
    # path — a well-formed handing-over record is needed to actually
    # exercise HandoverInProgress.
    ownership_path.write_text(json.dumps({
        "owner": "handing-over",
        "handover": {"from": "spot-effects", "to": "spectra", "step": "quiesce",
                     "started_at": 0.0, "token": "t"},
    }))
    result = _run(dark_light.reconcile(True, [], []))
    assert result["status"] == "handover-in-progress"

    ownership_path.write_text(json.dumps({"owner": "released"}))
    result = _run(dark_light.reconcile(True, [], []))
    assert result["status"] == "released"


# ── 5. room_controls wiring ─────────────────────────────────────────────────

def test_reconcile_dark_light_if_changed_only_fires_on_flip_or_shield_edit_while_dark(monkeypatch):
    from spectra.services import room_controls as rc

    calls = []

    async def fake_reconcile(enabled, shield_categories, shield_virtuals):
        calls.append((enabled, tuple(shield_categories), tuple(shield_virtuals)))
        return {"status": "dark" if enabled else "light"}

    from spectra.services import dark_light
    monkeypatch.setattr(dark_light, "reconcile", fake_reconcile)

    base = rc.RoomControlState()

    # no change at all — no call
    result = _run(rc.reconcile_dark_light_if_changed(base, base))
    assert result is None
    assert calls == []

    # flips on — calls
    on = base.model_copy(update={"dark_mode_enabled": True})
    result = _run(rc.reconcile_dark_light_if_changed(base, on))
    assert result == {"status": "dark"}
    assert calls == [(True, ("Singles",), ())]

    # shield list edited while OFF — no call (nothing live to react to)
    calls.clear()
    off_edit = base.model_copy(update={"dark_light_shield_categories": ["Singles", "Extra"]})
    result = _run(rc.reconcile_dark_light_if_changed(base, off_edit))
    assert result is None
    assert calls == []

    # shield list edited while ALREADY dark — calls (mirrors legacy resync())
    calls.clear()
    on_edit = on.model_copy(update={"dark_light_shield_categories": ["Singles", "Extra"]})
    result = _run(rc.reconcile_dark_light_if_changed(on, on_edit))
    assert result == {"status": "dark"}
    assert calls == [(True, ("Singles", "Extra"), ())]


def test_room_control_state_dark_light_defaults_and_round_trip(tmp_path, monkeypatch):
    from spectra.services import room_controls as rc

    state = rc.RoomControlState()
    assert state.dark_mode_enabled is False
    assert state.dark_light_shield_categories == ["Singles"]
    assert state.dark_light_shield_virtuals == []

    custom = rc.RoomControlState(dark_mode_enabled=True,
                                 dark_light_shield_categories=["Singles", "Accents"],
                                 dark_light_shield_virtuals=["v1"])
    rc.save_room_controls(custom)
    assert rc.load_room_controls() == custom
