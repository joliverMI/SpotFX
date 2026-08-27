"""The TRANSITION and DROP-SEQUENCE previews on a REAL fixture (2026-08-27,
fm/flare-preview-offsets-everywhere).

THE PROOF BAR THIS FILE MEETS is the one his own report set for the flare
preview: "i have tested some of the flares and they do not actually change
anything on the lights." Every assertion below reads a real headless dummy
device's `virtual.active_effect.config` through fx.headless + fx.facade
with ownership=spectra — the same rig tests/test_flare_preview_hold.py and
test_room_preview.py use — never a RecordingExecutor's own write log. A
preview that records a call it never made is exactly the failure mode this
system exists to prevent.

A facade PUT with transition_ms > 0 does not update effect.config
synchronously (fx/effects/__init__.py's start_param_transitions stores a
per-param tween advanced once per RENDERED FRAME), so _pump_frames_for
stands in for the render thread this offline harness does not have —
copied deliberately from test_flare_preview_hold.py rather than invented,
since it is the same mechanism.

Covers, for BOTH new programs: the step really reaches the device; the
drop sequence drives the REAL vendored phase machinery (the effect's own
`phase`/`phase_progress`, not a mimic) and releases it; a transition's lap
reset really puts the outgoing scene back; and closing reverts to exactly
the pre-preview state on every virtual the session touched.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model, facade, headless

VID = headless.DEFAULT_VIRTUAL_ID
LAND_S = 0.5


def _run(coro):
    return asyncio.run(coro)


async def _pump_frames_for(virtual, seconds: float, hz: float = 60.0) -> None:
    step = 1.0 / hz
    elapsed = 0.0
    while elapsed < seconds:
        await asyncio.sleep(step)
        headless.render_frames(virtual, 1)
        elapsed += step


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("FIRE_HISTORY_FILE", "fire_history.json"),
                     ("SHOW_LOG_FILE", "show_log.json"),
                     ("COLOR_SETS_FILE", "color_sets.json"),
                     ("FLARE_PREVIEW_HOLD_FILE", "flare_preview_hold.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
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
        for t in fph._release_tasks:
            t.cancel()
        fph._release_tasks = []
        preview_pause.clear()

    _reset()
    yield
    _reset()


def _own(monkeypatch, tmp_path) -> None:
    from fx import light_ownership as lo
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({"owner": "spectra"}))
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", path)


async def _start_host(tmp_path, effect_type="radial", config=None):
    host = await headless.start_headless_host(str(tmp_path / "host"))
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    headless.attach_effect(host, virtual, effect_type,
                           config or {"background_color": "#111111",
                                      "background_brightness": 1.0,
                                      "spin": 0.1})
    return host, virtual


def _scene(name, effect_type, params, *, entry_ramp_ms=0):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    return SceneV2(name=name, entry_ramp_ms=entry_ramp_ms,
                   devices=[SceneDeviceConfig(
                       id="d1", target_kind="virtual", target=VID,
                       effect_type=effect_type, params=params)])


# ═══ 1. the TRANSITION really crosses, on a real fixture ═══════════════════

def test_transition_fire_lands_the_incoming_scene_for_real(tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    from spectra.services import transition_preview
    _own(monkeypatch, tmp_path)
    from_scene = _scene("From", "radial", {"spin": 0.2})
    to_scene = _scene("To", "radial", {"spin": 0.9}, entry_ramp_ms=200)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            program = transition_preview.TransitionProgram(from_scene, to_scene)
            await fph.open_program_hold(program, 1.0, step="rearm",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, LAND_S)
            assert virtual.active_effect.config["spin"] == pytest.approx(0.2, abs=0.01)

            await fph.open_program_hold(program, 1.0, step="fire",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, LAND_S)
            assert virtual.active_effect.config["spin"] == pytest.approx(0.9, abs=0.01), (
                "the transition never reached the fixture")

            # the lap reset really puts the outgoing scene back, so the NEXT
            # lap has something to transition FROM
            await fph.open_program_hold(program, 1.0, step="rearm",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, LAND_S)
            assert virtual.active_effect.config["spin"] == pytest.approx(0.2, abs=0.01)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_closing_a_transition_preview_reverts_to_the_pre_preview_state(
        tmp_path, monkeypatch):
    from spectra.services import flare_preview_hold as fph
    from spectra.services import transition_preview
    _own(monkeypatch, tmp_path)
    from_scene = _scene("From", "radial", {"spin": 0.2})
    to_scene = _scene("To", "radial", {"spin": 0.9}, entry_ramp_ms=200)

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            before = float(virtual.active_effect.config["spin"])
            program = transition_preview.TransitionProgram(from_scene, to_scene)
            await fph.open_program_hold(program, 1.0, step="fire",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, LAND_S)
            assert virtual.active_effect.config["spin"] != pytest.approx(before, abs=0.01)

            await fph.close_hold()
            await _pump_frames_for(virtual, 0.05)
            assert virtual.active_effect.config["spin"] == pytest.approx(before, abs=0.01), (
                "what we take, we give back")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ═══ 2. the DROP SEQUENCE drives the REAL phase machinery ══════════════════

def test_the_sequence_drives_the_effects_own_phase_and_releases_it(
        tmp_path, monkeypatch):
    """`phase`/`phase_progress` are the vendored effects' OWN keys — the
    choreography (blackhole's swallow, the burst) is their code, not
    anything re-invented here. Proving the preview sets them on a real
    effect instance is proving it drives the real machinery."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview
    _own(monkeypatch, tmp_path)
    scene = _scene("Sequence", "blackhole", {"reverse": False})

    async def main():
        host, virtual = await _start_host(
            tmp_path, "blackhole", {"background_color": "#000000"})
        try:
            program = phase_preview.PhaseSequenceProgram(scene)
            for cls in ("charge", "lull", "drop"):
                await fph.open_program_hold(program, 0.8, step=cls,
                                            heartbeat_timeout_s=30.0)
                await _pump_frames_for(virtual, 0.1)
                assert virtual.active_effect.config["phase"] == cls, (
                    f"{cls} never reached the real effect")
                assert virtual.active_effect.config["phase_progress"] >= 0.0

            await fph.open_program_hold(program, 0.8, step="release",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 0.1)
            assert virtual.active_effect.config["phase"] == "none", (
                "the lap ended with the phase still armed — the next lap "
                "would inherit a charge that never finished")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_a_charge_ramp_really_advances_phase_progress_on_the_device(
        tmp_path, monkeypatch):
    """The stretch is the feature; this proves the ramp is a real,
    frame-advanced tween on the device rather than an instant write the
    ruler merely draws as a ramp."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview
    _own(monkeypatch, tmp_path)
    scene = _scene("Sequence", "blackhole", {"reverse": False})

    async def main():
        host, virtual = await _start_host(
            tmp_path, "blackhole", {"background_color": "#000000"})
        try:
            # a short gap so the ramp completes inside the test's own window
            program = phase_preview.PhaseSequenceProgram(scene, {"charge": 400})
            await fph.open_program_hold(program, 0.5, step="charge",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 0.05)
            early = float(virtual.active_effect.config["phase_progress"])
            await _pump_frames_for(virtual, 0.6)
            late = float(virtual.active_effect.config["phase_progress"])
            assert early < late, "phase_progress never advanced"
            assert late == pytest.approx(1.0, abs=0.05), (
                "the ramp never reached its end — it is not a real tween")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_a_charge_really_engages_the_vendored_choreography_not_a_mimic(
        tmp_path, monkeypatch):
    """The strongest evidence that this drives the REAL machinery rather
    than writing two keys that look like it: blackhole's own _enter_phase
    FORCES `reverse` to False for a charge ("charge always falls inward")
    and remembers the configured value to restore when the phase ends. So
    a scene that authors reverse=True lands True, and then the EFFECT
    overrides it the moment the charge arms — behaviour nothing in
    spectra/ knows about or could have faked."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview
    _own(monkeypatch, tmp_path)
    scene = _scene("Sequence", "blackhole", {"reverse": True})

    async def main():
        host, virtual = await _start_host(
            tmp_path, "blackhole", {"background_color": "#000000",
                                    "reverse": False})
        try:
            program = phase_preview.PhaseSequenceProgram(scene)
            await fph.open_program_hold(program, 0.8, step="charge",
                                        heartbeat_timeout_s=30.0)
            # the scene's authored value reached the effect...
            assert virtual.active_effect.config["reverse"] is True
            # ...and the vendored charge choreography then took it over
            await _pump_frames_for(virtual, 0.1)
            assert virtual.active_effect.config["reverse"] is False, (
                "blackhole's own charge override never ran — this is not "
                "the real phase machinery")
            assert virtual.active_effect.config["phase"] == "charge"

            # and the effect gives it back when the phase is released,
            # through its own _restore_phase_overrides
            await fph.open_program_hold(program, 0.8, step="release",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 0.1)
            assert virtual.active_effect.config["phase"] == "none"
            assert virtual.active_effect.config["reverse"] is True
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_closing_a_sequence_preview_reverts_the_fixture(tmp_path, monkeypatch):
    """"What we take, we give back" — on a param the vendored phase
    choreography does NOT itself override, so the revert write is what is
    being proven rather than an effect-side restore."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview
    _own(monkeypatch, tmp_path)
    scene = _scene("Sequence", "blackhole", {"horizon_scale": 0.9})

    async def main():
        host, virtual = await _start_host(
            tmp_path, "blackhole", {"background_color": "#000000",
                                    "horizon_scale": 0.2})
        try:
            before = float(virtual.active_effect.config["horizon_scale"])
            program = phase_preview.PhaseSequenceProgram(scene)
            await fph.open_program_hold(program, 0.8, step="charge",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 0.2)
            assert virtual.active_effect.config["horizon_scale"] == pytest.approx(
                0.9, abs=0.02), "the scene never reached the fixture"

            await fph.close_hold()
            await _pump_frames_for(virtual, 0.1)
            assert virtual.active_effect.config["horizon_scale"] == pytest.approx(
                before, abs=0.02)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_the_release_step_clears_the_phase_even_after_a_drop(tmp_path, monkeypatch):
    """A drop arms NOTHING by production's own rule (_drive_phase only arms
    charge/lull — a drop is one-shot), and each preview step runs on a
    fresh scratch pair, so the guarded release_phases() would no-op at
    exactly the moment a sequence ends. The preview's release forces it;
    this is the regression that catches the guard creeping back."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview
    _own(monkeypatch, tmp_path)
    scene = _scene("Sequence", "blackhole", {})

    async def main():
        host, virtual = await _start_host(
            tmp_path, "blackhole", {"background_color": "#000000"})
        try:
            program = phase_preview.PhaseSequenceProgram(scene)
            await fph.open_program_hold(program, 0.8, step="drop",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 0.05)
            assert virtual.active_effect.config["phase"] == "drop"
            await fph.open_program_hold(program, 0.8, step="release",
                                        heartbeat_timeout_s=30.0)
            await _pump_frames_for(virtual, 0.05)
            assert virtual.active_effect.config["phase"] == "none", (
                "the lap ended with the phase still armed — the next lap "
                "would inherit a drop that never ended")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ═══ 3. one lap's steps do not cancel each other's pending releases ════════

def test_a_later_step_does_not_strand_an_earlier_steps_momentary_release(
        tmp_path, monkeypatch):
    """The hold cancels pending release tasks on a re-fire so an intensity
    change cannot race its own earlier release. A DIFFERENT step of the
    same program is not a re-fire — it is the next beat of one lap (charge,
    then lull, then drop) — and cancelling there would strand a momentary
    spike from the previous phase whose authored hold outlives the gap to
    the next one. This pins the distinction: same step cancels, different
    step does not."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview
    _own(monkeypatch, tmp_path)
    scene = _scene("Sequence", "blackhole", {})

    async def main():
        host, virtual = await _start_host(
            tmp_path, "blackhole", {"background_color": "#000000"})
        try:
            program = phase_preview.PhaseSequenceProgram(scene)
            await fph.open_program_hold(program, 0.8, step="charge",
                                        heartbeat_timeout_s=30.0)
            # stand a long-lived task in for a pending momentary release
            held = asyncio.create_task(asyncio.sleep(30))
            fph._release_tasks.append(held)

            await fph.open_program_hold(program, 0.8, step="lull",
                                        heartbeat_timeout_s=30.0)
            # task.cancel() only REQUESTS cancellation — a task does not
            # report cancelled() until it has actually processed it, so
            # yield first. Without this the assertion passes even against
            # the always-cancel behaviour it exists to catch.
            await asyncio.sleep(0)
            assert not held.cancelled() and not held.done(), (
                "the lull step cancelled the charge step's pending release")

            await fph.open_program_hold(program, 0.8, step="lull",
                                        heartbeat_timeout_s=30.0)
            await asyncio.sleep(0)
            assert held.cancelled(), (
                "a RE-FIRE of the same step must still cancel its own "
                "pending releases — that guard is why this exists")
        finally:
            for t in fph._release_tasks:
                t.cancel()
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_a_flare_refire_still_cancels_its_own_pending_release(tmp_path, monkeypatch):
    """The flare preview has ONE step, so every /fire is a re-fire and the
    original cancellation behaviour is unchanged — the property the
    intensity-change race depends on."""
    from spectra.services import flare_preview_hold as fph
    from spectra.models.scene import (FlareKind, ParamTarget,
                                      SceneDeviceConfig, SceneV2)
    _own(monkeypatch, tmp_path)
    kind = FlareKind(name="spin-flare", type="momentary",
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    scene = SceneV2(name="Flare", devices=[SceneDeviceConfig(
        id="d1", target_kind="virtual", target=VID, effect_type="radial",
        params={"spin": 0.2})], flare_kinds=[kind])

    async def main():
        host, virtual = await _start_host(tmp_path)
        try:
            await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=30.0)
            held = asyncio.create_task(asyncio.sleep(30))
            fph._release_tasks.append(held)
            await fph.open_hold(scene, kind, 0.4, heartbeat_timeout_s=30.0)
            await asyncio.sleep(0)
            assert held.cancelled()
        finally:
            for t in fph._release_tasks:
                t.cancel()
            facade.set_host(None)
            await host.shutdown()

    _run(main())
