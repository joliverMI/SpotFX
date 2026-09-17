"""PER-FLARE TRIGGER MOMENT — the LIFECYCLE of a staggered kind batch
(scene_response.py's module docstring, "PER-FLARE TRIGGER MOMENT"): when it
is due, what schedules what it arms, which gates it re-checks when it
wakes, when it refuses to fire, and how every outcome is recorded.

Wherever scheduling is the claim, these drive the REAL production entry
points — services/engine.fire_response_event / fire_scene_update_event,
flare_preview_hold.open_program_hold, POST /api/engine/event — against a
scratch responder installed in place of the engine singleton (the
tests/test_preview_holds_the_show.py precedent), never a copy of their
scheduling shape. The show-side gate proof counts writes at fx_seam AND on
the response engine's own executor, the standing "prove every hold from
the show side" bar.

A batch only exists on a fire tick() already relocated by the band's
anchor — fire_response_event(via_trigger=True) and the drop-sequence
preview; section 9 proves every other entry point fires the band
atomically."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest

from fx import device_model

VID = "v1"
SPIN_BASE, SPIN_SPIKE = 0.2, 0.9
STAR_BASE, STAR_TARGET = 0.3, 0.5


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
        fph._release_step = None
        for t in fph._release_tasks:
            t.cancel()
        fph._release_tasks = []
        preview_pause.clear()

    _reset()
    yield
    _reset()


class _SeamRecorder:
    """Stands in for fx_seam — the ONE place a light byte leaves SPECTRA."""

    def __init__(self) -> None:
        self.writes: list[dict] = []

    async def apply_writes(self, writes, *, transition_ms: int = 0) -> None:
        for w in writes:
            self.writes.append({"virtual_id": w["virtual_id"],
                                "config": dict(w.get("config") or {}),
                                "transition_ms": transition_ms})

    async def get_virtuals(self) -> dict:
        return {VID: {"effect": {"type": "radial",
                                 "config": {"spin": 0.1, "star": 0.0}}}}

    def with_value(self, param: str, value: float) -> list[dict]:
        return [w for w in self.writes
                if w["config"].get(param) == pytest.approx(value)]


@pytest.fixture
def seam(monkeypatch):
    from spectra.services import fx_seam
    rec = _SeamRecorder()
    monkeypatch.setattr(fx_seam, "apply_writes", rec.apply_writes)
    monkeypatch.setattr(fx_seam, "get_virtuals", rec.get_virtuals)
    return rec


def _scene(*, event_class="flare", type_b="permanent", hold_b=None,
           offset_a=-100, offset_b=0, name="Batch Scene"):
    """Kind A (star, the anchor) runs inline; Kind B (spin) is staggered
    `offset_b - offset_a` ms behind it."""
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kind_a = FlareKind(name="Kind A", type="permanent",
                       trigger_offset_ms=offset_a,
                       params={"star": ParamTarget(mode="absolute",
                                                   value=STAR_TARGET)})
    kind_b = FlareKind(name="Kind B", type=type_b, hold_ms=hold_b,
                       trigger_offset_ms=offset_b,
                       params={"spin": ParamTarget(mode="absolute",
                                                   value=SPIN_SPIKE)})
    return SceneV2(
        name=name,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial",
                                   params={"spin": SPIN_BASE, "star": STAR_BASE})],
        flare_kinds=[kind_a, kind_b],
        responses={event_class: ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Kind A": 1.0, "Kind B": 1.0})])})


def _scratch(scene, clock, executor):
    from spectra.services import flare_preview
    _c, responder, writes = flare_preview._scratch_engine(
        scene, 0.8, clock, executor)
    return responder, writes


def _install(monkeypatch, scene, executor=None):
    """A real-clock scratch responder in place of engine.responses."""
    from spectra.services import engine as engine_mod
    from spectra.services.fx_executor import RecordingExecutor
    executor = executor or RecordingExecutor(clock=time.monotonic)
    responder, _writes = _scratch(scene, time.monotonic, executor)
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
    return responder, executor


def _written(executor, param: str) -> list[float]:
    return [w["params"][param] for w in executor.writes if param in w["params"]]


def _deferred_batch_records() -> list[dict]:
    from spectra.services import fire_history
    return [e for e in fire_history.load_show_log()
            if e.get("bucket") == "deferred" and e.get("key") == "kind_batch"]


# ── 1. due_at is measured from the fire's START ─────────────────────────────

@pytest.mark.parametrize("event_class", ["flare", "charge"])
def test_a_batch_is_due_from_the_fire_start_not_the_end_of_its_burst(event_class):
    """Every write costs 250ms on this clock (his live room's ~30ms/write,
    exaggerated so the burst dwarfs the 100ms stagger). A charge also drives
    the phase machinery before the band runs. The staggered kind must still
    be due exactly 100ms after the fire started."""
    from spectra.services import flare_preview
    from spectra.services.fx_executor import RecordingExecutor

    class _SlowExecutor(RecordingExecutor):
        async def glide(self, *a, **kw):
            clock.advance_to(clock.t + 0.25)
            await super().glide(*a, **kw)

        async def jump(self, *a, **kw):
            clock.advance_to(clock.t + 0.25)
            await super().jump(*a, **kw)

    clock = flare_preview._FakeClock()
    responder, _ = _scratch(_scene(event_class=event_class), clock,
                            _SlowExecutor(clock=clock))
    clock.advance_to(10.0)

    record = asyncio.run(responder.on_event(event_class, 0.8,
                                            anchor_relocated=True))

    batches = responder.take_kind_batch_schedule()
    assert len(batches) == 1
    assert record["at"] == 10.0
    assert batches[0].due_at == pytest.approx(10.1)
    assert clock.t > 10.1, "the burst must outlast the stagger for this to prove anything"
    assert record["deferred_kinds"] == [
        {"name": "Kind B", "type": "permanent", "delay_ms": 100}]


# ── 2. what a batch arms is scheduled, through the real engine ─────────────

def test_a_staggered_momentary_kind_releases_on_schedule(monkeypatch):
    from spectra.services import engine
    scene = _scene(type_b="momentary", hold_b=100)
    responder, executor = _install(monkeypatch, scene)

    async def main():
        await engine.fire_response_event("flare", 0.8, via_trigger=True)
        assert _written(executor, "spin") == []
        await asyncio.sleep(0.6)

    asyncio.run(main())
    assert _written(executor, "spin") == [pytest.approx(SPIN_SPIKE),
                                          pytest.approx(SPIN_BASE)]
    assert responder.pending_release_keys() == set()
    assert [e["outcome"] for e in responder.kind_batch_log] == ["landed"]


# ── 3. a woken batch re-checks the gate its fire passed — show side ───────

def test_a_preview_hold_opened_mid_stagger_stops_the_batch_at_the_seam(monkeypatch, seam):
    from spectra.services import engine
    from spectra.services import flare_preview_hold as fph
    from spectra.services import preview_pause
    scene = _scene()
    responder, executor = _install(monkeypatch, scene)
    held_kind = scene.flare_kinds[0]

    async def main():
        await engine.fire_response_event("flare", 0.8, via_trigger=True)
        # The hold opens INSIDE the batch's 100ms delay window, exactly the
        # way spectra/api/flare_preview.py opens one.
        await fph.open_hold(scene, held_kind, 0.8, heartbeat_timeout_s=60.0)
        preview_pause.start(60.0)
        seam.writes.clear()
        executor_before = len(executor.writes)
        await asyncio.sleep(0.3)

        assert seam.writes == [], f"a light byte left SPECTRA under a hold: {seam.writes}"
        assert len(executor.writes) == executor_before, "the response engine wrote under a hold"
        assert _written(executor, "spin") == []
        assert responder.kind_batch_log[-1]["outcome"] == "skipped_preview"
        assert [r["detail"]["reason"] for r in _deferred_batch_records()] == ["preview"]

        # Released, the same fire's batch lands — the corpus was live.
        preview_pause.clear()
        await fph.close_hold()
        await engine.fire_response_event("flare", 0.8, via_trigger=True)
        await asyncio.sleep(0.3)
        assert _written(executor, "spin") == [pytest.approx(SPIN_SPIKE)]
        assert responder.kind_batch_log[-1]["outcome"] == "landed"

    asyncio.run(main())


def test_a_scene_change_mode_closed_mid_stagger_stops_the_batch(monkeypatch):
    from spectra.services import engine, room_controls
    scene = _scene()
    responder, executor = _install(monkeypatch, scene)

    async def main():
        await engine.fire_response_event("flare", 0.8, via_trigger=True)
        assert _written(executor, "star")
        room_controls.save_room_controls(
            room_controls.RoomControlState(scene_change_mode="transitions"))
        await asyncio.sleep(0.3)

    asyncio.run(main())
    assert _written(executor, "spin") == []
    assert responder.kind_batch_log[-1]["outcome"] == "skipped_scene_change_mode"
    assert [r["detail"]["reason"] for r in _deferred_batch_records()] == [
        "scene_change_mode"]


# ── 4. a batch never fires onto a scene the room has moved on from ─────────

@pytest.mark.parametrize("refire", [False, True])
def test_a_batch_is_skipped_when_the_scene_changed_before_it_woke(refire):
    from spectra.services import flare_preview
    from spectra.services.fx_executor import RecordingExecutor
    clock = flare_preview._FakeClock()
    executor = RecordingExecutor(clock=clock)
    responder, _ = _scratch(_scene(), clock, executor)
    other = _scene(name="The Next Scene")
    _o, other_writes = _scratch(other, clock, RecordingExecutor(clock=clock))

    async def main():
        await responder.on_event("flare", 0.8, anchor_relocated=True)
        (batch,) = responder.take_kind_batch_schedule()
        if refire:
            responder.conductor.on_scene_fire(other, other_writes)
        return await responder.run_kind_batch(batch)

    entry = asyncio.run(main())
    if refire:
        assert entry["outcome"] == "skipped_stale_scene"
        assert entry["current_scene_id"] == other.id
        assert _written(executor, "spin") == []
    else:
        assert entry["outcome"] == "landed"
        assert _written(executor, "spin") == [pytest.approx(SPIN_SPIKE)]
    assert list(responder.kind_batch_log) == [entry]


# ── 5. a failing batch is logged and recorded, never lost in its task ──────

def test_a_batch_that_raises_is_logged_and_recorded(monkeypatch, caplog):
    from spectra.services import engine
    from spectra.services.fx_executor import RecordingExecutor

    class _SpinFails(RecordingExecutor):
        async def glide(self, virtual_id, effect_type, params, duration_ms):
            if "spin" in params:
                raise RuntimeError("fixture unreachable")
            await super().glide(virtual_id, effect_type, params, duration_ms)

    responder, executor = _install(
        monkeypatch, _scene(), _SpinFails(clock=time.monotonic))

    async def main():
        await engine.fire_response_event("flare", 0.8, via_trigger=True)
        await asyncio.sleep(0.3)

    with caplog.at_level(logging.ERROR):
        asyncio.run(main())
    (entry,) = responder.kind_batch_log
    assert entry["outcome"] == "error"
    assert "fixture unreachable" in entry["error"]
    assert any(r.levelno >= logging.ERROR and "Kind B" in r.getMessage()
               for r in caplog.records)
    assert _written(executor, "star") == [pytest.approx(STAR_TARGET)]


# ── 6. the drop-sequence preview drains the batch queue too ────────────────

def test_the_drop_sequence_preview_lands_a_charge_bands_staggered_kind(seam):
    from spectra.services import flare_preview_hold as fph
    from spectra.services.phase_preview import PhaseSequenceProgram
    program = PhaseSequenceProgram(_scene(event_class="charge"))

    async def main():
        result = await fph.open_program_hold(program, 0.8, step="charge",
                                             heartbeat_timeout_s=60.0)
        assert result["held"] is True
        assert seam.with_value("star", STAR_TARGET)
        assert seam.with_value("spin", SPIN_SPIKE) == []
        await asyncio.sleep(0.3)
        assert len(seam.with_value("spin", SPIN_SPIKE)) == 1

        # Closed inside the delay window: the batch is cancelled with the
        # hold and never writes after the revert.
        await fph.close_hold()
        await fph.open_program_hold(program, 0.8, step="charge",
                                    heartbeat_timeout_s=60.0)
        await fph.close_hold()
        seam.writes.clear()
        await asyncio.sleep(0.3)
        assert seam.writes == []

    asyncio.run(main())


# ── 7. the manual event injector is not relocated: its band is atomic ──────

@pytest.mark.parametrize("event_class", ["flare", "update"])
def test_the_engine_event_route_fires_the_band_atomically(monkeypatch, event_class):
    from spectra.api import engine as engine_api
    responder, executor = _install(monkeypatch, _scene())

    async def main():
        return await engine_api.post_event(
            engine_api.EventRequest(**{"class": event_class, "intensity": 0.4}))

    body = asyncio.run(main())
    assert body["kind_batches"] == []
    assert "deferred_kinds" not in body
    assert {k["name"] for k in body["kinds"]} == {"Kind A", "Kind B"}
    assert responder.take_kind_batch_schedule() == []
    assert _written(executor, "star") == [pytest.approx(STAR_TARGET)]
    assert _written(executor, "spin") == [pytest.approx(SPIN_SPIKE)]


# ── 8. an overlapping fire never starts a staggered batch's hold early ─────

def test_an_overlapping_fire_never_arms_a_staggered_batchs_release(monkeypatch):
    """A staggered batch runs as its own task, so the next fire routinely
    overlaps it. Here the batch's momentary spin spike takes 400ms to land
    (a slow fixture), and a second, unrelated fire starts and FINISHES
    inside that window — its own safety-net arming and its release
    scheduling both run while the batch's spike is still going out. The
    batch's hold must still be measured from ITS OWN spike landing: a
    blanket sweep by the second fire would arm the entry ~250ms before the
    spike lands and release it almost as soon as it did."""
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    from spectra.services import engine
    from spectra.services import room_controls as rc
    from spectra.services.fx_executor import RecordingExecutor

    hold_s = 0.3
    write_cost = {"spin": 0.4, "star": 0.02}

    class _SlowFixture(RecordingExecutor):
        def __init__(self) -> None:
            super().__init__(clock=time.monotonic,
                             room_controls_load=lambda: rc.RoomControlState())
            self.issued: list[tuple[float, dict]] = []

        async def _cost(self, params) -> None:
            self.issued.append((time.monotonic(), dict(params)))
            await asyncio.sleep(max(write_cost.get(p, 0.0) for p in params))

        async def glide(self, vid, effect_type, params, duration_ms):
            if params:
                await self._cost(params)
            await super().glide(vid, effect_type, params, duration_ms)

        async def jump(self, vid, effect_type, params):
            if params:
                await self._cost(params)
            await super().jump(vid, effect_type, params)

    scene = SceneV2(
        name="Overlap",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial",
                                   params={"spin": SPIN_BASE, "star": STAR_BASE})],
        flare_kinds=[
            FlareKind(name="Star Lead", type="permanent", trigger_offset_ms=-100,
                      params={"star": ParamTarget(mode="absolute", value=0.5)}),
            FlareKind(name="Spin Spike", type="momentary", trigger_offset_ms=0,
                      hold_ms=int(hold_s * 1000),
                      params={"spin": ParamTarget(mode="absolute",
                                                  value=SPIN_SPIKE)}),
            FlareKind(name="Star Late", type="permanent",
                      params={"star": ParamTarget(mode="absolute", value=0.7)}),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=0.5,
                      kinds={"Star Lead": 1.0, "Spin Spike": 1.0}),
            FlareBand(intensity_min=0.5, intensity_max=1.0,
                      kinds={"Star Late": 1.0})])})
    responder, executor = _install(monkeypatch, scene, _SlowFixture())

    async def main():
        await engine.fire_response_event("flare", 0.2, via_trigger=True)
        await asyncio.sleep(0.2)
        # The batch's spin spike was issued ~100ms after the first fire and
        # is still on its way out; this second fire starts and ends inside it.
        await engine.fire_response_event("flare", 0.9, via_trigger=True)
        assert _written(executor, "star") == [pytest.approx(0.5), pytest.approx(0.7)]
        assert _written(executor, "spin") == [], "the spike must still be in flight"
        await asyncio.sleep(1.4)

    asyncio.run(main())

    spike_landed = next(w["at"] for w in executor.writes
                        if w["params"].get("spin") == pytest.approx(SPIN_SPIKE))
    release_issued = next(t for t, params in executor.issued
                          if params.get("spin") == pytest.approx(SPIN_BASE))
    assert release_issued - spike_landed >= hold_s - 0.03, (
        f"the release went out {release_issued - spike_landed:.3f}s after the "
        f"spike landed, against a {hold_s}s hold — another fire armed it")
    assert _written(executor, "spin") == [pytest.approx(SPIN_SPIKE),
                                          pytest.approx(SPIN_BASE)]
    assert responder.pending_release_keys() == set()
    assert [e["outcome"] for e in responder.kind_batch_log] == ["landed"]


# ── 9. every entry point tick() did not relocate fires its band atomically ─

@pytest.mark.parametrize("path", ["bridge", "update"])
def test_an_unrelocated_engine_fire_lands_every_kind_before_it_returns(monkeypatch, path):
    """The bridge's classified flare (via_trigger=False) and the update
    choke point (dwell's deferral, the fire_scene_update action) run their
    band at their own moment with nothing moved, so the -100/0 band lands
    BOTH kinds inside the fire, queues nothing, and nothing lands later.
    The via_trigger=True run is the control: the same band staggers."""
    from spectra.services import engine
    scene = _scene()
    responder, executor = _install(monkeypatch, scene)

    async def main():
        if path == "bridge":
            await engine.fire_response_event("flare", 0.8)
        else:
            await engine.fire_scene_update_event(0.4)
        assert _written(executor, "star") == [pytest.approx(STAR_TARGET)]
        assert _written(executor, "spin") == [pytest.approx(SPIN_SPIKE)]
        writes_after_fire = len(executor.writes)
        await asyncio.sleep(0.3)
        assert len(executor.writes) == writes_after_fire
        assert list(responder.kind_batch_log) == []
        assert all("deferred_kinds" not in r for r in responder.surges)

        await engine.fire_response_event("flare", 0.8, via_trigger=True)
        assert len(_written(executor, "spin")) == 1, "control: B must wait"
        await asyncio.sleep(0.3)
        assert len(_written(executor, "spin")) == 2
        assert [e["outcome"] for e in responder.kind_batch_log] == ["landed"]

    asyncio.run(main())
