"""Flare preview LIVE hold (spectra/services/flare_preview_hold.py) — proves
his own real complaint is fixed: "i have tested some of the flares and
they do not actually change anything on the lights." Every assertion here
reads a REAL headless dummy device's `virtual.active_effect.config` (fx.headless
+ fx.facade, ownership=spectra — the same rig test_room_preview.py already
uses), never a RecordingExecutor's own write log — the proof bar this
feature exists to meet is that his fixtures changed, not that a call was
recorded.

A facade PUT with transition_ms>0 does NOT update effect.config
synchronously — fx/effects/__init__.py's start_param_transitions stores a
per-param tween, advanced once per RENDERED FRAME (_advance_tweens, called
from _render). A live process has a render thread continuously doing this;
this offline harness doesn't, so _pump_frames_for stands in for it —
sleeping real wall-clock time while periodically stepping the real
assemble/flush pipeline, so a tween lands here exactly the way it would on
a real device, not merely on a RecordingExecutor's model.

Covers: opening fires the scene then the kind for real; a momentary kind's
release lands for real after its hold; closing reverts to EXACTLY the
pre-preview live state; a second /open in the same session (an intensity
change) re-fires without re-snapshotting; a lapsed heartbeat (browser
closed / connection dropped) auto-reverts; and recover_stale_hold() lands
a snapshot left over from a prior process life (the service-restart case)."""
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


async def _pump_frames_for(virtual, seconds: float, hz: float = 60.0) -> None:
    """Advance the real render pipeline through actual elapsed wall-clock
    time — see the module docstring above for why this is necessary."""
    step = 1.0 / hz
    elapsed = 0.0
    while elapsed < seconds:
        await asyncio.sleep(step)
        headless.render_frames(virtual, 1)
        elapsed += step


async def _land_revert(virtual) -> None:
    """A revert write (flare_preview_hold.REVERT_TRANSITION_MS=1) is still
    a real tween, not a synchronous config write — it needs at least one
    rendered frame, real elapsed time since the write, to land. Call this
    right after close_hold()/sweep_once()/recover_stale_hold() before
    asserting the config settled."""
    await _pump_frames_for(virtual, 0.05)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")
    monkeypatch.setattr(scfg, "DRIFT_PROFILES_FILE", tmp_path / "drift_profiles.json")
    monkeypatch.setattr(scfg, "GRADIENT2D_FILE", tmp_path / "gradients2d.json")
    monkeypatch.setattr(scfg, "FIRE_HISTORY_FILE", tmp_path / "fire_history.json")
    monkeypatch.setattr(scfg, "SHOW_LOG_FILE", tmp_path / "show_log.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "FLARE_PREVIEW_HOLD_FILE",
                        tmp_path / "flare_preview_hold.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


@pytest.fixture(autouse=True)
def _reset_hold_state():
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    fph._snapshot = None
    fph._deadline = None
    fph._release_tasks = []
    preview_pause.clear()
    yield
    for t in fph._release_tasks:
        t.cancel()
    fph._snapshot = None
    fph._deadline = None
    fph._release_tasks = []
    preview_pause.clear()


def _own(monkeypatch, tmp_path) -> None:
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)


VID = headless.DEFAULT_VIRTUAL_ID

# Comfortably longer than BOTH the scene's own entry-ramp fallback (an
# unset SceneV2.entry_ramp_ms/room.global_transition_ms falls through to
# room_controls.scene_transition_ms — up to ~300ms) AND the flare kind's
# own DICE_REROLL_GLIDE_MS (220ms) — both PUTs land within one real-time
# window after open_hold() returns.
LAND_S = 0.5


async def _start_host(tmp_path):
    host = await headless.start_headless_host(str(tmp_path / "host"))
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    headless.attach_effect(host, virtual, "radial",
                           {"background_color": "#111111",
                            "background_brightness": 1.0,
                            "spin": 0.1})
    return host, virtual


def _scene_and_kind():
    from spectra.models.binding import ValueBinding
    from spectra.models.scene import (FlareKind, ParamTarget,
                                      SceneDeviceConfig, SceneV2)
    scene = SceneV2(
        name="Hold Check Scene",
        devices=[SceneDeviceConfig(
            id="dev1", target_kind="virtual", target=VID, effect_type="radial",
            params={"spin": 0.2,
                   "twist": ValueBinding(signal="random", mode="map",
                                         out_min=0.0, out_max=1.0)})],
    )
    kind = FlareKind(name="spin-flare", type="momentary",
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    return scene, kind


# ── 1. opening fires the SCENE then the KIND for real, on a real fixture ───

def test_open_fires_scene_then_kind_on_real_fixture(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    from spectra.services import scene_response
    # spin-flare is momentary — hold this test's assertion window clear of
    # its own PULSE_HOLD_S release-glide start (a separate, dedicated test
    # below already proves that release lands correctly).
    monkeypatch.setattr(scene_response, "PULSE_HOLD_S", 10.0)
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            result = await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=5.0)
            assert result["held"] is True
            assert result["first_open"] is True
            assert virtual.active_effect.type == "radial"

            # both the scene's own fire (its entry ramp) and the flare
            # kind's own spike (its glide) land for real within LAND_S —
            # not a RecordingExecutor entry
            await _pump_frames_for(virtual, LAND_S)
            assert virtual.active_effect.config["spin"] == pytest.approx(0.9, abs=0.01)
            assert fph.active() is True
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 2. a momentary kind's release lands for real after its hold ────────────

def test_momentary_release_lands_live_after_its_hold(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    from spectra.services.scene_response import (DICE_REROLL_GLIDE_MS,
                                                  PULSE_HOLD_S, PULSE_RELEASE_S)
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=5.0)
            # the spike itself landing is already covered by test 1 above
            # (with PULSE_HOLD_S patched wide so the two windows don't
            # race); here, pump straight through the WHOLE real-timed
            # cycle — glide-up, PULSE_HOLD_S, PULSE_RELEASE_S — at
            # production's own unpatched constants.
            await _pump_frames_for(
                virtual, DICE_REROLL_GLIDE_MS / 1000.0 + PULSE_HOLD_S
                + PULSE_RELEASE_S + 0.2)
            # released back to the entry's own authored baseline (0.2),
            # carried by the scratch conductor — a REAL glide, not a
            # RecordingExecutor entry
            assert virtual.active_effect.config["spin"] == pytest.approx(0.2, abs=0.01)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 3. close() reverts to EXACTLY the pre-preview live state ───────────────

def test_close_reverts_to_exact_pre_preview_state(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    from spectra.services.scene_response import DICE_REROLL_GLIDE_MS
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_spin = virtual.active_effect.config["spin"]
            orig_bg = virtual.active_effect.config["background_color"]
            preview_pause.start(5.0)
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=5.0)
            await _pump_frames_for(virtual, DICE_REROLL_GLIDE_MS / 1000.0 + 0.1)
            assert virtual.active_effect.config["spin"] != orig_spin

            release = await fph.close_hold()
            await _land_revert(virtual)
            assert release["reverted"] is True
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin)
            assert virtual.active_effect.config["background_color"] == orig_bg
            assert fph.active() is False
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 4. re-opening at a new intensity (mid-session) re-fires but does NOT
#      re-snapshot — a later close still restores the ORIGINAL pre-preview
#      state, not the first fire's ─────────────────────────────────────────

def test_reopen_midsession_refires_without_resnapshotting(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_spin = virtual.active_effect.config["spin"]
            r1 = await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=5.0)
            assert r1["first_open"] is True
            r2 = await fph.open_hold(scene, kind, 0.4, heartbeat_timeout_s=5.0)
            assert r2["first_open"] is False

            release = await fph.close_hold()
            await _land_revert(virtual)
            assert release["reverted"] is True
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 5. a lapsed heartbeat (browser closed / connection dropped — both look
#      identical from here): active() reports false the instant the
#      deadline passes — a pure read, like preview_pause's own — and
#      sweep_once() (what run_supervised() calls on its own clock) is what
#      actually reverts the lights, deadline-driven, never depending on an
#      explicit /close ever arriving ────────────────────────────────────────

def test_lapsed_heartbeat_deadline_then_sweep_reverts(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_spin = virtual.active_effect.config["spin"]
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=0.1)
            # renders frames while real time passes — both lets the deadline
            # (0.1s) lapse AND lets the fire's own writes actually land, so
            # "the lights changed" below is a real, observed fact
            await _pump_frames_for(virtual, 0.2)
            # the deadline itself has already lapsed — reported immediately,
            # with no dependency on a sweep tick having run yet
            assert fph.active() is False
            # NOTHING has reverted the lights yet — no /close ever arrived,
            # and no sweep has ticked. Proves the light state alone can't be
            # trusted; only the deadline-driven sweep below actually acts.
            assert virtual.active_effect.config["spin"] != orig_spin

            reverted = await fph.sweep_once()
            await _land_revert(virtual)
            assert reverted is True
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 6. touch() (the heartbeat) keeps a hold alive past what its original
#      deadline would have allowed — a sweep before the touch must NOT
#      revert an actively-heartbeating session ─────────────────────────────

def test_touch_rearms_and_prevents_premature_revert(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=0.2)
            await asyncio.sleep(0.1)
            await fph.touch(0.2)
            await asyncio.sleep(0.15)
            assert fph.active() is True, "touch() must re-arm past the original window"
            assert await fph.sweep_once() is False, "must not revert a live session"

            await asyncio.sleep(0.3)
            assert fph.active() is False
            assert await fph.sweep_once() is True
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 6b. run_supervised() itself, as a REAL background task — the actual
#      autonomous mechanism, not just its sweep_once() building block: no
#      explicit close, no explicit sweep call, just the process's own
#      always-on task noticing and reverting on its own clock ─────────────

def test_run_supervised_autonomously_reverts_a_lapsed_hold(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    monkeypatch.setattr(fph, "SWEEP_INTERVAL_S", 0.05)
    _own(monkeypatch, tmp_path)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        sweep_task = asyncio.create_task(fph.run_supervised())
        try:
            orig_spin = virtual.active_effect.config["spin"]
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=0.2)
            # the fire itself lands well before the 0.2s deadline — proof
            # this test is exercising a REAL change, not asserting a no-op
            await _pump_frames_for(virtual, 0.1)
            assert virtual.active_effect.config["spin"] != orig_spin

            # no /close, no explicit sweep_once() from here — just render
            # frames while real time passes the deadline plus a couple of
            # sweep ticks; the process's own always-on task does the rest
            await _pump_frames_for(virtual, 0.3)
            assert fph.active() is False
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin)
        finally:
            sweep_task.cancel()
            try:
                await sweep_task
            except asyncio.CancelledError:
                pass
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 7. recover_stale_hold(): the service-restart case. A snapshot left on
#      disk from a prior process life (in-memory state wiped, simulating a
#      restart) still lands the room back — same shape as fx/light_ownership
#      .recover_stale_handover(), unconditionally (no age gate — see the
#      module docstring for why none applies here) ─────────────────────────

def test_recover_stale_hold_lands_a_leftover_snapshot(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    from spectra import config as scfg
    from spectra.services import scene_response
    _own(monkeypatch, tmp_path)
    monkeypatch.setattr(scene_response, "PULSE_HOLD_S", 10.0)
    scene, kind = _scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_spin = virtual.active_effect.config["spin"]
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=5.0)
            await _pump_frames_for(virtual, LAND_S)
            assert virtual.active_effect.config["spin"] != orig_spin
            assert scfg.FLARE_PREVIEW_HOLD_FILE.exists()

            # simulate a fresh process: the in-memory deadline/session is
            # gone, but the persisted snapshot survives on disk
            for t in fph._release_tasks:
                t.cancel()
            fph._snapshot = None
            fph._deadline = None
            fph._release_tasks = []

            landed = await fph.recover_stale_hold()
            await _land_revert(virtual)
            assert landed is True
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin)
            assert not scfg.FLARE_PREVIEW_HOLD_FILE.exists()

            # idempotent: nothing left to recover a second time
            assert await fph.recover_stale_hold() is False
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
