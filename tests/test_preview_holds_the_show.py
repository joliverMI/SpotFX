"""PROVE EVERY PREVIEW HOLD FROM THE SHOW SIDE (2026-08-27,
fm/flare-preview-offsets-everywhere) — the proof bar the founding defect
of this whole system earns.

THE HISTORICAL FAILURE, verbatim from his own live report (2026-08-21,
fm/preview-must-hold-scene-changes): "I was using spectra, playing music,
and tried to preview. now it won't even hold... The music show is playing
regardless of the fact that I have the preview window open and it says
'deferred by preview.'" The hold REPORTED itself as set — bridge.py's
conductor_deferral/sequencer_deferral read preview_pause.active() and said
so, out loud, in the UI — while scene_sequencer.fire_scene_by_id, the ONE
choke point his authored fire_scene triggers actually route through, never
consulted preview_pause at all. Every test that existed at the time asked
the PREVIEW side ("is the hold armed?", "did close revert?") and every one
of them passed throughout.

So the bar here is deliberately the other way round: drive the REAL
trigger engine over a REAL position feed with a REAL trigger corpus while
a hold is open, and measure THE ENGINE'S OWN OUTPUT —

  * zero writes reach the ONE seam a light byte can leave SPECTRA through
    (fx_seam.apply_writes), counted only across the tick sweep, so the
    hold's own opening fire can't be mistaken for the show;
  * zero response surges recorded on the response engine;
  * the deferrals that DID happen are present and named in fire_history's
    "deferred" bucket (never a silent hold — a room that goes quiet
    because triggers broke and a room that goes quiet because it is held
    must not look identical);
  * and the SAME sweep, replayed after release, fires for real — otherwise
    "nothing fired" proves only that the corpus was inert.

Nothing here reads a preview module's own report of itself. Every fire
path is the production default (TriggerEngine's own _default_fire_scene /
_default_fire_response / _default_select_color_set /
_default_fire_scene_update), so every real gate is exercised.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model


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
def _reset_preview_state():
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


VID = "v1"


class _SeamRecorder:
    """Stands in for fx_seam — the ONE place a light byte leaves SPECTRA.
    Counting calls here is the show-side measurement: it does not care
    which module decided to write, only that something did."""

    def __init__(self) -> None:
        self.writes: list[dict] = []

    async def apply_writes(self, writes, *, transition_ms: int = 0) -> None:
        for w in writes:
            self.writes.append({"virtual_id": w["virtual_id"],
                                "transition_ms": transition_ms})

    async def get_virtuals(self) -> dict:
        # Two live virtuals: the snapshot must be able to cover a virtual
        # that only an INCOMING scene touches (see the transition revert
        # test below). A virtual with no live effect is deliberately
        # unsnapshotable — there is nothing to give back.
        effect = {"type": "radial",
                  "config": {"spin": 0.1, "background_color": "#111111"}}
        return {VID: {"effect": dict(effect, config=dict(effect["config"]))},
                "v2": {"effect": dict(effect, config=dict(effect["config"]))}}

    def reset(self) -> None:
        self.writes.clear()


@pytest.fixture
def seam(monkeypatch):
    from spectra.services import fx_seam
    rec = _SeamRecorder()
    monkeypatch.setattr(fx_seam, "apply_writes", rec.apply_writes)
    monkeypatch.setattr(fx_seam, "get_virtuals", rec.get_virtuals)
    return rec


def _scene_and_kind(name="Show Hold Scene"):
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kind = FlareKind(name="spin-flare", type="momentary",
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    return SceneV2(
        name=name,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial",
                                   params={"spin": 0.2})],
        flare_kinds=[kind],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"spin-flare": 1.0})])},
    ), kind


def _corpus(scene_id: str):
    """A trigger of every action kind, spread across the sweep window —
    so the measurement covers all four production fire paths, not just the
    one the historical defect happened to leak through."""
    from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                        FireSceneUpdateAction, SpectraTrigger)
    return [
        SpectraTrigger(timestamp_ms=1000,
                       action=FireSceneAction(scene_id=scene_id, intensity=0.6)),
        SpectraTrigger(timestamp_ms=2000,
                       action=FireResponseAction(event_class="flare",
                                                 intensity=0.6)),
        SpectraTrigger(timestamp_ms=3000,
                       action=FireSceneUpdateAction(intensity=0.6)),
        SpectraTrigger(timestamp_ms=4000,
                       action=FireSceneAction(scene_id=scene_id, intensity=0.9)),
    ]


def _engine(triggers):
    """Production defaults for every fire path — the whole point: each one
    must hit its own real gate, not a stub that can't be gated."""
    from spectra.services.trigger_engine import TriggerEngine
    return TriggerEngine(list_triggers=lambda uri: list(triggers),
                         scene_change_mode=lambda: "full",
                         sequencer_enabled=lambda: False)


async def _sweep(engine, uri: str, stop=5000, step=200) -> int:
    """Drive tick() at the production 200ms cadence over the whole corpus
    window; return how many triggers the engine believed it fired."""
    await engine.on_track_state(uri)
    n = 0
    for pos in range(0, stop + 1, step):
        n += len(await engine.tick(pos))
    return n


def _deferred_preview_records() -> list[dict]:
    from spectra.services import fire_history
    log = fire_history.load_show_log()
    return [e for e in log
            if e.get("bucket") == "deferred"
            and (e.get("detail") or {}).get("reason") == "preview"]


def _seed_scene(scene):
    from spectra.services import scene_store
    scene_store.save(scene)
    return scene


def _install_scratch_responder(monkeypatch, scene):
    """Point engine.responses at a scratch pair (RecordingExecutor) seeded
    with the scene, so a response fire is observable as a real surge
    record without a live host — the production choke point
    engine.fire_response_event is untouched and still does the gating."""
    from random import Random
    from spectra.services import engine as engine_mod
    from spectra.services import flare_preview
    from spectra.services.fx_executor import RecordingExecutor

    clock = flare_preview._FakeClock()
    executor = RecordingExecutor(clock=clock)
    _cond, responder, _writes = flare_preview._scratch_engine(
        scene, 1.0, clock, executor)
    responder._rng = Random(7)
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
    return responder, executor


# ═══════════════════════════════════════════════════════════════════════════
#  The reusable measurement — every hold in this system is held to it.
# ═══════════════════════════════════════════════════════════════════════════

async def _measure_show(engine, responder, executor, seam, uri: str) -> dict:
    """Run one full sweep and report what the SHOW did, from the show's own
    instruments only."""
    from spectra.services import fire_history
    before_deferred = len(_deferred_preview_records())
    seam.reset()
    executor.writes.clear()
    surges_before = len(responder.surges)
    fired = await _sweep(engine, uri)
    return {
        "engine_fired": fired,
        "seam_writes": len(seam.writes),
        "executor_writes": len(executor.writes),
        "new_surges": len(responder.surges) - surges_before,
        "new_deferred_preview": len(_deferred_preview_records()) - before_deferred,
    }


# ═══ 1. flare preview hold: the show goes silent, visibly ══════════════════

def test_flare_hold_silences_every_trigger_and_says_so(monkeypatch, seam):
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    scene, kind = _scene_and_kind()
    _seed_scene(scene)
    responder, executor = _install_scratch_responder(monkeypatch, scene)

    async def main():
        # Open the hold exactly the way spectra/api/flare_preview.py does:
        # the live fire AND the pause that refuses his show.
        await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=60.0)
        preview_pause.start(60.0)
        assert preview_pause.active() is True

        held = await _measure_show(_engine(_corpus(scene.id)), responder,
                                   executor, seam, "song:held")

        # THE MEASUREMENT — the engine's own output, not the hold's report.
        # The engine DID cross all four marks (the gate is downstream, at
        # the production choke points) — so "nothing reached the lights"
        # below is a real refusal, not a corpus that never triggered.
        assert held["engine_fired"] == 4, held
        assert held["seam_writes"] == 0, (
            "a light byte left SPECTRA while the preview claimed to hold "
            f"the room: {seam.writes}")
        assert held["new_surges"] == 0, "a response surge fired under a hold"
        assert held["executor_writes"] == 0, "the response engine wrote under a hold"
        # ...and it is NOT silent about it: a held room and a broken room
        # must not look the same in the log.
        assert held["new_deferred_preview"] >= 1, (
            "the hold refused scene changes without recording a single "
            "deferral — indistinguishable from triggers having stopped working")

        # RELEASE, then replay the SAME sweep: proves the corpus was live
        # all along and "nothing fired" was the hold, not an inert fixture.
        preview_pause.clear()
        await fph.close_hold()
        freed = await _measure_show(_engine(_corpus(scene.id)), responder,
                                    executor, seam, "song:freed")
        assert freed["engine_fired"] == 4, freed
        assert freed["seam_writes"] > 0, "the released show wrote nothing — inert corpus?"
        assert freed["new_surges"] >= 1, "the released show fired no response"
        assert freed["new_deferred_preview"] == 0

    asyncio.run(main())


# ═══ 2. the same measurement catches the ACTUAL historical defect ══════════

def test_the_measurement_would_have_caught_the_ungated_scene_fire(monkeypatch, seam):
    """Re-create the pre-2026-08-21 world — fire_scene_by_id not consulting
    preview_pause — and prove THIS harness goes red on it. A proof bar that
    cannot fail on the defect it was written for is decoration."""
    from spectra.services import preview_pause, scene_sequencer
    scene, _kind = _scene_and_kind()
    _seed_scene(scene)
    responder, executor = _install_scratch_responder(monkeypatch, scene)

    real = scene_sequencer.fire_scene_by_id

    async def ungated(scene_id, color_set_id=None, intensity=0.5, **kw):
        # the pre-fix shape: no preview_pause check at all
        pp_active = preview_pause.active
        preview_pause.active = lambda: False
        try:
            return await real(scene_id, color_set_id, intensity, **kw)
        finally:
            preview_pause.active = pp_active

    monkeypatch.setattr(scene_sequencer, "fire_scene_by_id", ungated)

    async def main():
        preview_pause.start(60.0)
        held = await _measure_show(_engine(_corpus(scene.id)), responder,
                                   executor, seam, "song:ungated")
        assert held["seam_writes"] > 0, (
            "the regressed world wrote nothing — this harness would not have "
            "caught the defect it exists for")

    asyncio.run(main())
    # and the real, gated function is untouched by the experiment
    assert scene_sequencer.fire_scene_by_id is not None


# ═══ 3. an ABANDONED hold releases the show with no /close ever arriving ═══

def test_an_abandoned_hold_gives_the_show_back_on_its_own(monkeypatch, seam):
    """The self-heal path, measured from the show side: heartbeats simply
    stop (browser closed, connection dropped), nothing calls clear(), and
    the very next sweep fires normally once the deadline lapses."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    scene, kind = _scene_and_kind()
    _seed_scene(scene)
    responder, executor = _install_scratch_responder(monkeypatch, scene)

    async def main():
        await fph.open_hold(scene, kind, 1.0, heartbeat_timeout_s=0.05)
        preview_pause.start(0.05)
        await asyncio.sleep(0.12)          # heartbeats stop; nothing calls clear()
        assert await fph.sweep_once() is True
        freed = await _measure_show(_engine(_corpus(scene.id)), responder,
                                    executor, seam, "song:abandoned")
        assert freed["engine_fired"] == 4
        assert freed["seam_writes"] > 0
        assert freed["new_deferred_preview"] == 0

    asyncio.run(main())


# ═══ 4. the TRANSITION hold: same measurement, same silence ════════════════

def test_transition_hold_silences_every_trigger_and_says_so(monkeypatch, seam):
    """The transition preview is a NEW hold-user (2026-08-27) — and a new
    hold-user is exactly what leaked last time. It is held to the same
    show-side bar, not to "it reuses the shared hold, so it must be fine."
    """
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause, transition_preview
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    scene, _kind = _scene_and_kind("Transition From")
    _seed_scene(scene)
    to_scene = SceneV2(
        name="Transition To", entry_ramp_ms=1200,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial", params={"spin": 0.8})])
    _seed_scene(to_scene)
    responder, executor = _install_scratch_responder(monkeypatch, scene)
    program = transition_preview.TransitionProgram(scene, to_scene)

    async def main():
        assert await fph.open_program_hold(
            program, 1.0, step="fire", heartbeat_timeout_s=60.0)
        preview_pause.start(60.0)
        held = await _measure_show(_engine(_corpus(scene.id)), responder,
                                   executor, seam, "song:transition-held")
        assert held["engine_fired"] == 4, held
        assert held["seam_writes"] == 0, (
            f"the transition preview let his show write: {seam.writes}")
        assert held["new_surges"] == 0
        assert held["new_deferred_preview"] >= 1, "held, but silently"

        preview_pause.clear()
        await fph.close_hold()
        freed = await _measure_show(_engine(_corpus(scene.id)), responder,
                                    executor, seam, "song:transition-freed")
        assert freed["engine_fired"] == 4 and freed["seam_writes"] > 0

    asyncio.run(main())


def test_the_transition_hold_reverts_every_virtual_it_touched(monkeypatch, seam):
    """The snapshot has to cover the INCOMING scene's virtuals too — it can
    reach ones the outgoing scene never touches, and a snapshot taken from
    the held scene alone would hand some virtuals back and silently keep
    the rest."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import transition_preview
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from_scene = SceneV2(
        name="Only v1",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial", params={"spin": 0.2})])
    to_scene = SceneV2(
        name="v1 and v2", entry_ramp_ms=800,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial", params={"spin": 0.9}),
                 SceneDeviceConfig(id="d2", target_kind="virtual", target="v2",
                                   effect_type="radial", params={"spin": 0.9})])

    async def main():
        program = transition_preview.TransitionProgram(from_scene, to_scene)
        await fph.open_program_hold(program, 1.0, step="fire",
                                   heartbeat_timeout_s=60.0)
        assert set(fph._snapshot or {}) >= {VID, "v2"}, (
            "a virtual only the INCOMING scene touches was left out of the "
            f"snapshot: {sorted(fph._snapshot or {})}")
        seam.reset()
        await fph.close_hold()
        reverted = {w["virtual_id"] for w in seam.writes}
        assert reverted >= {VID, "v2"}, (
            f"close() handed back only {sorted(reverted)}")

    asyncio.run(main())


# ═══ 5. the DROP SEQUENCE hold: same measurement, same silence ═════════════

def test_drop_sequence_hold_silences_every_trigger_and_says_so(monkeypatch, seam):
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview, preview_pause
    scene, _kind = _scene_and_kind("Sequence Scene")
    _seed_scene(scene)
    responder, executor = _install_scratch_responder(monkeypatch, scene)
    program = phase_preview.PhaseSequenceProgram(scene)

    async def main():
        for step in ("charge", "lull", "drop"):
            assert await fph.open_program_hold(
                program, 1.0, step=step, heartbeat_timeout_s=60.0)
        preview_pause.start(60.0)
        held = await _measure_show(_engine(_corpus(scene.id)), responder,
                                   executor, seam, "song:sequence-held")
        assert held["engine_fired"] == 4, held
        assert held["seam_writes"] == 0, (
            f"the drop-sequence preview let his show write: {seam.writes}")
        assert held["new_surges"] == 0
        assert held["new_deferred_preview"] >= 1, "held, but silently"

        preview_pause.clear()
        await fph.close_hold()
        freed = await _measure_show(_engine(_corpus(scene.id)), responder,
                                    executor, seam, "song:sequence-freed")
        assert freed["engine_fired"] == 4 and freed["seam_writes"] > 0

    asyncio.run(main())


def test_every_new_hold_user_obeys_the_absolute_ceiling(monkeypatch, seam):
    """The 13m54s incident's fix is a property of the HOLD, not of the
    flare route that happened to be written first — so a transition and a
    drop sequence must both refuse once the ceiling has fired, however
    hard their client keeps calling /fire."""
    from spectra.services import flare_preview_hold as fph
    from spectra.services import phase_preview, transition_preview
    scene, _kind = _scene_and_kind("Ceiling Scene")
    _seed_scene(scene)

    async def main():
        for program in (transition_preview.TransitionProgram(scene, scene),
                        phase_preview.PhaseSequenceProgram(scene)):
            fph._locked_until_reopen = True
            got = await fph.open_program_hold(
                program, 1.0, step=program.steps[0], heartbeat_timeout_s=60.0)
            assert got == {"held": False, "expired": True,
                           "reason": "max_duration"}, got
            assert fph.capped_pause_s(15.0) == 0.0
            fph.clear_ceiling_lock()

    asyncio.run(main())
