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

    def _reset():
        fph._snapshot = None
        fph._deadline = None
        fph._session_started_at = None
        fph._locked_until_reopen = False
        fph._release_tasks = []
        preview_pause.clear()

    _reset()
    yield
    for t in fph._release_tasks:
        t.cancel()
    _reset()


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


def _permanent_scene_and_kind():
    """A CARRYING (permanent) kind, unlike _scene_and_kind's momentary one —
    it never self-releases, so a later "did the revert actually happen"
    assertion proves the explicit revert write did it, not a coincidental
    momentary release landing around the same time."""
    from spectra.models.binding import ValueBinding
    from spectra.models.scene import (FlareKind, ParamTarget,
                                      SceneDeviceConfig, SceneV2)
    scene = SceneV2(
        name="Ceiling Check Scene",
        devices=[SceneDeviceConfig(
            id="dev1", target_kind="virtual", target=VID, effect_type="radial",
            params={"spin": 0.2,
                   "twist": ValueBinding(signal="random", mode="map",
                                         out_min=0.0, out_max=1.0)})],
    )
    kind = FlareKind(name="spin-carry", type="permanent",
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


# ── 7b. the colour ROTATE-AND-BACK flare in a LIVE preview: the fade-back
#      must actually land on the fixture (his report, 2026-08-21: "when I
#      change the intensity on the flare preview specifically for color
#      rotate and back it no longer runs as the playhead crosses the
#      trigger"). color_rotate releases through its OWN queue
#      (pending_color_rotate_holds/flush_color_rotates — see
#      scene_response._color_rotate's docstring), which engine.py's
#      fire_response_event and flare_preview.build_timeline both drain —
#      open_hold() scheduled only pending_hold_groups() (written in #163,
#      before this kind existed), so a live-previewed rotation ramped in
#      and NEVER faded back: the gradient sat rotated between laps, and
#      every later /fire re-targeted the same rotated value — zero visible
#      change on every crossing after the first. The drawn ruler promised
#      the full ramp/dwell/fade the whole time. ──────────────────────────

ORIGINAL_GRADIENT = "#3366cc"


def _rotate_categories(tmp_path) -> None:
    """The colour-set entry below scopes VID explicitly, and
    device_model.resolve_scope intersects with the imported set — an empty
    categories file (the autouse fixture's default) resolves it to nothing."""
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["blackhole"], "role": None}}))
    device_model.refresh()


def _rotate_room_storage() -> None:
    """A set-mode scene entry only carries a gradient once the room wears a
    colour set — seed the isolated storage with one scoping VID, exactly
    what scene_compiler.room_active_set() reads on a real fire."""
    from spectra import config as scfg
    scfg.COLOR_SETS_FILE.write_text(json.dumps({
        "cs1": {"id": "cs1", "name": "Rotate Set", "kind": "set",
                "entries": [{"scope": {"virtual_ids": [VID]},
                             "color_kind": "solid",
                             "color_value": ORIGINAL_GRADIENT}]}}))
    scfg.ROOM_COLOR_FILE.write_text(json.dumps({"active_set_id": "cs1"}))


def _rotate_scene_and_kind():
    from spectra.models.scene import FlareKind, SceneDeviceConfig, SceneV2
    # color defaults to mode="set" — the active set above supplies the
    # gradient, making VID a set-mode virtual with something to rotate.
    scene = SceneV2(
        name="Rotate Hold Scene",
        devices=[SceneDeviceConfig(
            id="dev1", target_kind="virtual", target=VID,
            effect_type="blackhole", params={"swirl": 3.0})],
    )
    kind = FlareKind(name="Colour Rotate & Back", type="color_rotate")
    return scene, kind


async def _start_rotate_host(tmp_path):
    host = await headless.start_headless_host(str(tmp_path / "host"))
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    headless.attach_effect(host, virtual, "blackhole",
                           {"gradient": "#101010", "swirl": 1.0})
    return host, virtual


def test_color_rotate_fade_back_lands_live_in_a_preview_hold(tmp_path, monkeypatch):
    """Production parity: engine.fire_response_event schedules
    flush_color_rotates after the dwell; the live preview hold must too, or
    the previewed rotation is a one-way trip the drawn timeline never
    promised."""
    from spectra.services import color_rotate
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    _rotate_categories(tmp_path)
    _rotate_room_storage()
    scene, kind = _rotate_scene_and_kind()
    # intensity 1.0: ramp 250ms, dwell 400ms (fade launches dwell after the
    # fire, engine.py's own convention), fade 375ms — fully settled ~775ms.
    expected_rotated = color_rotate.rotate_color_value(ORIGINAL_GRADIENT, 180.0)
    assert expected_rotated != ORIGINAL_GRADIENT

    async def main():
        host, virtual = await _start_rotate_host(tmp_path)
        try:
            result = await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=30.0)
            assert result["held"] is True
            rec = result["fire_record"]["color_rotate"]
            assert rec["virtuals"] == 1, \
                "the rotate must genuinely fire — otherwise this test " \
                "asserts a no-op faded back, which proves nothing"

            # the ramp lands the rotation for real first (also proves the
            # fire itself is visible on the fixture)
            await _pump_frames_for(virtual, 0.35)
            assert virtual.active_effect.config["gradient"] == expected_rotated

            # ...and after its own dwell + fade the gradient must be back at
            # the EXACT original — the "and back" half of the kind's name
            await _pump_frames_for(virtual, 0.9)
            assert virtual.active_effect.config["gradient"] == ORIGINAL_GRADIENT, \
                "the fade-back never ran: open_hold scheduled only " \
                "pending_hold_groups(), not pending_color_rotate_holds()"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_color_rotate_still_visibly_fires_after_an_intensity_change(tmp_path, monkeypatch):
    """His exact reported sequence: fires at the mark, nudge the intensity
    slider, and every later crossing must STILL show a full rotate-and-back
    — possible only because the fade-back (above) parks the gradient at the
    original between laps, so each re-fire has a real visible delta."""
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    _rotate_categories(tmp_path)
    _rotate_room_storage()
    scene, kind = _rotate_scene_and_kind()

    async def main():
        host, virtual = await _start_rotate_host(tmp_path)
        try:
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 1.3)   # full ramp+dwell+fade cycle
            assert virtual.active_effect.config["gradient"] == ORIGINAL_GRADIENT

            # the intensity nudge — the next lap's /fire at the new value
            result = await fph.open_hold(scene, kind, 0.8, heartbeat_timeout_s=30.0)
            assert result["fire_record"]["color_rotate"]["virtuals"] == 1

            # sample every rendered frame across the whole cycle: the
            # crossing must be VISIBLE (some frame away from the original)
            # and must SETTLE back at the exact original for the next lap
            seen: set[str] = set()
            for _ in range(int(2.2 * 60)):
                await asyncio.sleep(1 / 60)
                headless.render_frames(virtual, 1)
                seen.add(virtual.active_effect.config["gradient"])
            assert any(g != ORIGINAL_GRADIENT for g in seen), \
                "the post-nudge crossing rendered no visible change at all"
            assert virtual.active_effect.config["gradient"] == ORIGINAL_GRADIENT
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 8. MAXIMUM HOLD CEILING (fm/preview-hold-needs-a-ceiling): fires even
#      while a client keeps heartbeating THE WHOLE TIME — this is the
#      exact reported failure mode (a client that never stopped
#      heartbeating held his room 13m54s, refusing 85 scene changes). A
#      test where heartbeats STOP only proves the earlier, pre-existing
#      abandonment bound (tests 5/6 above) — it teaches nothing about this
#      ceiling. This test never lets the heartbeat lapse even once. ───────

def test_ceiling_fires_despite_continuous_heartbeating(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    # A tiny ceiling so the test runs fast — the real 180s value is
    # asserted separately below; what matters here is the MECHANISM.
    monkeypatch.setattr(fph, "MAX_HOLD_DURATION_S", 0.3)
    scene, kind = _permanent_scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            orig_spin = virtual.active_effect.config["spin"]
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=1.0)
            await _pump_frames_for(virtual, 0.05)
            assert virtual.active_effect.config["spin"] != orig_spin, \
                "the fire must have really landed — this is a genuine " \
                "hold, not a no-op, before we prove it can't be extended"

            # Heartbeat continuously — every 30ms, much faster than both
            # HEARTBEAT_TIMEOUT_S (1.0s) and MAX_HOLD_DURATION_S (0.3s).
            # If a heartbeat could extend the deadline even slightly, this
            # hold would still read active() well past the ceiling; it
            # must not. The heartbeat NEVER lapses in this test — that is
            # the whole point.
            elapsed = 0.0
            tick = 0.03
            while elapsed < 0.5:
                await fph.touch(1.0)
                await _pump_frames_for(virtual, tick)
                elapsed += tick

            assert fph.active() is False, (
                "continuous heartbeating for 0.5s (with a 1.0s heartbeat "
                "timeout) must not keep a 0.3s ceiling active — a bound a "
                "live client can push out forever is not a bound")

            reverted = await fph.sweep_once()
            await _land_revert(virtual)
            assert reverted is True
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin), \
                "the ceiling's own revert must land for real, on the " \
                "actual fixture — not merely flip an in-memory flag"

            # LOCKED: a client that keeps calling /fire or /heartbeat after
            # the ceiling (exactly today's reported failure mode — no
            # further /open ever arrives) must not silently re-establish a
            # new hold and restart the clock.
            assert fph.locked_until_reopen() is True
            result = await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=1.0)
            assert result == {"held": False, "expired": True, "reason": "max_duration"}
            await fph.touch(1.0)
            assert fph.active() is False
            await _pump_frames_for(virtual, 0.05)
            assert virtual.active_effect.config["spin"] == pytest.approx(orig_spin), \
                "a locked /fire must not touch the lights at all"

            # Only a genuine fresh /open (clear_ceiling_lock — never a bare
            # heartbeat or re-fire) lets a new session begin.
            fph.clear_ceiling_lock()
            result = await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=1.0)
            assert result["held"] is True
            assert result["first_open"] is True
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 9. the real ceiling value and its capped_pause_s() sibling (used by
#      spectra/api/flare_preview.py to keep preview_pause — what actually
#      blocks his scene changes — from ever outliving this module's own
#      light-hold deadline) ────────────────────────────────────────────────

def test_max_hold_duration_is_three_minutes():
    from spectra.services import flare_preview_hold as fph
    assert fph.MAX_HOLD_DURATION_S == 180.0


def test_capped_pause_s_reaches_zero_at_the_ceiling_and_locks(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    _own(monkeypatch, tmp_path)
    monkeypatch.setattr(fph, "MAX_HOLD_DURATION_S", 0.2)
    scene, kind = _permanent_scene_and_kind()

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=5.0)
            # requested far more than remains until the ceiling — capped
            assert 0 < fph.capped_pause_s(5.0) <= 0.2
            await _pump_frames_for(virtual, 0.25)
            assert await fph.sweep_once() is True
            await _land_revert(virtual)
            # locked: even a modest request is refused outright
            assert fph.capped_pause_s(1.0) == 0.0
            assert fph.locked_until_reopen() is True
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
