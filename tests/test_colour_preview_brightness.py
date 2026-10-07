"""A COLOUR-SET PREVIEW LOOKS LIKE NORMAL PLAYBACK AT HIS BRIGHTNESS.

The Admiral, 2026-10-07: "when i preview a color set, it pushes to 100%
brightness (or otherwise just seems to wash out in a way that doesn't
happen normally)".

Root cause: a colour preview (spectra/services/room_preview.py) counts as a
stand-down, and the Light Show supervisor (show_output.tick) suspended the
per-device output layer for EVERY stand-down. That layer is where the house
mode's resting levels live — his live Standard mode holds the crystal at 12%
— so for the length of every preview the crystal ran at full, and a fixture
the mode had switched off was streamed again. A second, smaller divergence:
the preview's own writes skipped the room dimmer (brightness_multiplier)
and display mode that every real landing of a set applies.

Measured AT THE TRANSPORT on the real render pipeline (fx.headless, a real
FxHost, fx.facade, ownership=spectra — the rig test_room_preview.py uses),
with the real room_preview.start and the real show_output.tick. Each frame
assertion has a control that recreates the old rule and goes RED.
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from fx import device_model, device_output, facade, headless

VID = headless.DEFAULT_VIRTUAL_ID
DEV = headless.DEFAULT_DEVICE_ID
HOUSE_LEVEL = 0.12      # his live Standard mode's crystal level


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import preview_pause, room_preview, show_output
    from fx import light_ownership as lo
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Main", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"]}}))
    device_model.refresh()
    own = tmp_path / "ownership.json"
    own.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", own)
    # The stack is up and the engine is live (what ownership_refusal reads
    # off the live process); this suite is about the stand-downs.
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: None)
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
    device_output.suspend(False)


def _card(**entry_kw):
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    entry = ColorSetEntry(scope=SetScope(virtual_ids=[VID]), color_kind="solid",
                          color_value="#00ff00", bg_color="#0000ff",
                          background_brightness=1.0, **entry_kw)
    return ColorSetCard(id="preview-set", name="preview-set", kind="set",
                        entries=[entry])


class _Rig:
    """A real headless host with every frame its device's flush() is handed."""

    def __init__(self, host):
        self.host = host
        self.virtual = host.virtuals.get(VID)
        self.frames: list[np.ndarray] = []
        dev = host.devices.get(DEV)
        real = dev.flush

        def flush(data):
            self.frames.append(np.array(data, dtype=float, copy=True))
            return real(data)
        dev.flush = flush

    def frame(self, clock, n=90) -> np.ndarray:
        headless.render_frames(self.virtual, n, clock=clock)
        return self.frames[-1]


async def _rig(tmp_path, *, brightness=1.0, background_brightness=1.0):
    host = await headless.start_headless_host(str(tmp_path / "host"))
    facade.set_host(host)
    headless.attach_effect(host, host.virtuals.get(VID), "concentric",
                           {"background_color": "#ff0000",
                            "background_brightness": background_brightness,
                            "brightness": brightness,
                            "gradient": "linear-gradient(90deg, #111111 0%, #222222 100%)"})
    return _Rig(host)


def _peaks(frame) -> list[float]:
    return [float(v) for v in np.asarray(frame).max(axis=0)]


async def _close(rig):
    facade.set_host(None)
    await rig.host.shutdown()


# ── 1. the founding reproduction ───────────────────────────────────────────

def _house_level_run(tmp_path, monkeypatch, *, tick):
    """(before, normal, previewed, after) frames with the house base at 12%.
    `tick` is the supervisor pass that decides suspension. concentric's rings
    move with time, so frames are compared by per-channel peak (the
    background, which is the set's colour at the fixture's level), never
    byte for byte."""
    from spectra.services import fx_seam, room_preview, scene_compiler, show_output
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 30.0)

    async def main():
        rig = await _rig(tmp_path)
        try:
            with headless.fake_clock() as clock:
                show_output.set_base({DEV: HOUSE_LEVEL}, {})   # house._enter's call
                tick()
                before = rig.frame(clock)
                # NORMAL PLAYBACK: the same colours landed with no preview.
                card = _card()
                cfg = dict(rig.virtual.active_effect.config)
                landed = scene_compiler._apply_set_colors(
                    cfg, "concentric", card.entries[0])
                await fx_seam.apply_writes(
                    [{"virtual_id": VID, "effect_type": "concentric",
                      "config": landed}], transition_ms=0)
                tick()
                normal = rig.frame(clock)
                await fx_seam.apply_writes(
                    [{"virtual_id": VID, "effect_type": "concentric",
                      "config": cfg}], transition_ms=0)
                tick()
                assert _peaks(rig.frame(clock)) == pytest.approx(_peaks(before), abs=1.0)
                # THE PREVIEW of the same set.
                out = await room_preview.start(card, hold=True)
                assert out["applied"] is True
                tick()
                previewed = rig.frame(clock)
                await room_preview.release()
                tick()
                after = rig.frame(clock)
            return before, normal, previewed, after
        finally:
            await _close(rig)

    return asyncio.run(main())


def test_colour_preview_keeps_the_house_level_at_the_transport(tmp_path, monkeypatch):
    from spectra.services import show_output
    before, normal, previewed, after = _house_level_run(
        tmp_path, monkeypatch, tick=show_output.tick)
    # the house level is really in force on the normal picture (the set's
    # blue background at 12%)
    assert normal.max() == pytest.approx(255 * HOUSE_LEVEL, abs=1.0)
    assert _peaks(normal)[2] == pytest.approx(255 * HOUSE_LEVEL, abs=1.0)
    # the preview looks like the same colours landed normally
    assert _peaks(previewed) == pytest.approx(_peaks(normal), abs=1.0), (
        f"preview peak {previewed.max():.1f} vs normal {normal.max():.1f}")
    assert _peaks(after) == pytest.approx(_peaks(before), abs=1.0)


def test_the_instrument_goes_red_under_the_old_rule(tmp_path, monkeypatch):
    """Re-create the pre-fix supervisor (suspend for every stand-down): the
    preview runs at full while the normal landing sits at the house level —
    the Admiral's report, reproduced."""
    from spectra.services import show_output

    def old_tick():
        device_output.suspend(show_output.refusal() is not None)

    _before, normal, previewed, _after = _house_level_run(
        tmp_path, monkeypatch, tick=old_tick)
    assert normal.max() == pytest.approx(255 * HOUSE_LEVEL, abs=1.0)
    assert previewed.max() == pytest.approx(255.0, abs=1.0)


def test_a_fixture_the_mode_has_off_stays_dark_through_a_preview(tmp_path, monkeypatch):
    """A house mode's "off" (base state dark) must not light up because a
    colour preview opened — the night rule, one door over."""
    from spectra.services import room_preview, show_output
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 30.0)

    async def main():
        rig = await _rig(tmp_path)
        try:
            with headless.fake_clock() as clock:
                show_output.set_base({}, {DEV: device_output.STATE_DARK})
                show_output.tick()
                assert rig.frame(clock).max() == 0.0
                await room_preview.start(_card(), hold=True)
                show_output.tick()
                lit = rig.frame(clock).max()
                await room_preview.release()
            return lit
        finally:
            await _close(rig)

    assert asyncio.run(main()) == 0.0


# ── 2. what still stands down ──────────────────────────────────────────────

def test_the_colour_preview_still_stands_everything_else_down(monkeypatch):
    """Only the output layer changed: the Light Show still refuses fires and
    the house still goes to standby (it writes nothing over a preview)."""
    from spectra.services import house, room_preview, show_output
    monkeypatch.setattr(room_preview, "active", lambda: True)
    assert show_output.refusal() is not None
    assert show_output.suspension_reason() is None
    assert house.gate()[0] == "standby"
    show_output.tick()
    assert device_output.suspended() is False


def test_measurements_and_other_previews_still_suspend(monkeypatch):
    """Anything that must see raw frames — or a scene/flare preview — keeps
    the old suspension, alone or beside a colour preview."""
    from spectra.services import (av_sync_pattern, capture_runs, flare_preview_hold,
                                  preview_pause, room_preview, show_output)
    preview_pause.start(30.0)

    # a flare/scene preview alone: unchanged
    monkeypatch.setattr(flare_preview_hold, "active", lambda: True)
    assert show_output.suspension_reason() is not None
    # …and beside a colour preview
    monkeypatch.setattr(room_preview, "active", lambda: True)
    assert show_output.suspension_reason() is not None
    monkeypatch.setattr(flare_preview_hold, "active", lambda: False)
    assert show_output.suspension_reason() is None

    monkeypatch.setattr(type(av_sync_pattern.driver), "active",
                        property(lambda self: True))
    assert show_output.suspension_reason() is not None
    monkeypatch.setattr(type(av_sync_pattern.driver), "active",
                        property(lambda self: False))

    monkeypatch.setattr(capture_runs, "current_run", lambda: object())
    assert show_output.suspension_reason() is not None
    monkeypatch.setattr(capture_runs, "current_run", lambda: None)
    assert show_output.suspension_reason() is None

    # a room that is not ours always suspends
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: "not ours")
    assert show_output.suspension_reason() == "not ours"


# ── 3. the room dimmer and the display mode ────────────────────────────────

def _save_controls(**kw):
    from spectra.services import room_controls
    room_controls.save_room_controls(room_controls.RoomControlState(**kw))


def test_preview_writes_take_the_room_dimmer_like_a_real_landing(tmp_path, monkeypatch):
    """A set authoring brightness 1.0 under a room dimmer of 0.5 lands at
    0.5 — never full. A value the set does NOT author is copied from the
    live config, which the write seams already scaled, so it is left alone
    (scaling it again would dim it twice)."""
    from spectra.services import room_preview
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 30.0)
    _save_controls(brightness_multiplier=0.5)
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    card = ColorSetCard(id="s", name="s", kind="set", entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=[VID]), color_kind="solid",
        color_value="#00ff00", brightness=1.0)])

    async def main():
        # live as a real fire left it: authored 1.0 / 0.8, dimmed by 0.5
        rig = await _rig(tmp_path, brightness=0.5, background_brightness=0.4)
        try:
            await room_preview.start(card, hold=True)
            during = dict(rig.virtual.active_effect.config)
            await room_preview.update(card)
            dragged = dict(rig.virtual.active_effect.config)
            await room_preview.release()
            reverted = dict(rig.virtual.active_effect.config)
            return during, dragged, reverted
        finally:
            await _close(rig)

    during, dragged, reverted = asyncio.run(main())
    assert during["brightness"] == pytest.approx(0.5)
    assert during["background_brightness"] == pytest.approx(0.4)
    assert dragged["brightness"] == pytest.approx(0.5)
    assert reverted["brightness"] == pytest.approx(0.5)
    assert reverted["background_brightness"] == pytest.approx(0.4)


def test_preview_takes_light_modes_background_like_a_real_landing(tmp_path, monkeypatch):
    from spectra.services import room_preview
    monkeypatch.setattr(room_preview, "HOLD_HOLD_S", 30.0)
    _save_controls(display_mode="light", display_light_bg_color="#201830")
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    card = ColorSetCard(id="s", name="s", kind="set", entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=[VID]), color_kind="solid",
        color_value="#00ff00", bg_color="#000000")])

    async def main():
        rig = await _rig(tmp_path)
        try:
            await room_preview.start(card, hold=True)
            bg = rig.virtual.active_effect.config["background_color"]
            await room_preview.release()
            return bg
        finally:
            await _close(rig)

    assert asyncio.run(main()) == "#201830"
