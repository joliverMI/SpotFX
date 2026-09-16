"""PER-FLARE TRIGGER MOMENT (his order, 2026-09-16: "build the offset
independence for flares and implement it") — the exact authorisation
scene_response.band_trigger_offset_ms's own docstring said was required
before per-kind timing inside one fire could exist. Ported from legacy
services/trigger_engine.py's MorphLane shape: `anchor = min(offsets)`,
the fire lands at the band's already-relocated moment, and each kind then
waits `its own offset - anchor` (always >= 0) before executing — see
spectra/services/scene_response.py's module docstring, "PER-FLARE TRIGGER
MOMENT", for the full mechanism.

Real vendored pipeline (fx.headless + FacadeExecutor, audio silenced), a
REAL asyncio clock wherever timing is the claim — same discipline as
tests/test_reverse_flare_release.py, whose own scheduling-shape replicas
this file reuses (importing spectra.services.engine would construct its
live bridge/executor singletons)."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless
from fx import device_model

REPO_ROOT = Path(__file__).resolve().parent.parent
VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["blackhole"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


class _Wall:
    """A `.now` shim so the engine's clock wiring runs on the REAL
    monotonic clock — timing is the claim in this file (test_reverse_
    flare_release.py's own precedent)."""
    @property
    def now(self) -> float:
        return time.monotonic()


def _engine(clock):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now, curve_profiles=lambda: {})
    return executor, conductor, responder


def _fire(conductor, scene, config, color_mode="set"):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id, "color_mode": color_mode}])


def _stagger_scene(*, offset_a: int = 0, offset_b: int = 0):
    """Two PERMANENT param-patch kinds on DIFFERENT blackhole params (never
    colliding, so any observed ordering effect is purely about WHEN each
    kind's write lands, not which one wins a same-param race) attached to
    one band."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [
        FlareKind(name="Kind A", type="permanent",
                 trigger_offset_ms=offset_a,
                 params={"swirl": {"mode": "absolute", "value": -2.0}}),
        FlareKind(name="Kind B", type="permanent",
                 trigger_offset_ms=offset_b,
                 params={"horizon_scale": {"mode": "absolute", "value": 0.4}}),
    ]
    return SceneV2(
        name="Stagger Test",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="blackhole",
            params={"swirl": 0.0, "horizon_scale": 0.2})],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                     kinds={"Kind A": 1.0, "Kind B": 1.0})])})


# ── the engine.py scheduling shape, replicated (test_reverse_flare_
# release.py's own precedent — importing spectra.services.engine would
# construct its live bridge/executor singletons) ────────────────────────────

async def _run_kind_batch(responder, batch) -> None:
    await asyncio.sleep(responder.seconds_until(batch.due_at))
    await responder.run_kind_batch(batch)


async def _fire_band(responder, event_class="flare", intensity=0.5) -> list:
    """engine.py's fire_response_event shape: on_event, then one task per
    take_kind_batch_schedule() batch, sleeping until its own absolute due
    time."""
    await responder.on_event(event_class, intensity)
    return [asyncio.create_task(_run_kind_batch(responder, b))
            for b in responder.take_kind_batch_schedule()]


CFG = {"horizon_scale": 0.2, "swirl": 0.0, "reverse": False,
      "base_speed": 2.0, "accel": 5.0, "spawn_rate": 0.0,
      "beat_burst": 0, "max_blobs": 20, "edge_speed": 0.2,
      "horizon_hold": 2.8}


def _params_written(executor, param: str) -> list:
    return [w for w in executor.writes if param in w["params"]]


# ── 1. byte-identical when every kind sits at the default 0 ─────────────────
#
# Proven against the PRE-CHANGE module itself, loaded out of git at a PINNED
# ref (tests/sweep_world_driver.py's BASELINE_REF precedent): master
# immediately before this feature. Never a moving ref — a proof whose
# reference moves out from under it retires itself silently.
BASELINE_REF = "829f55e3d16c6b0f14fa41021b85c4d3d97254a6"


def _baseline_scene_response():
    """scene_response.py as of BASELINE_REF, as its own module. Raises
    (never skips) when git cannot produce it."""
    path = "spectra/services/scene_response.py"
    src = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:{path}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert "PendingKindBatch" not in src, (
        f"the pinned baseline {BASELINE_REF} already carries the per-kind "
        "stagger — the pin is wrong, and this proof would compare the "
        "feature with itself")
    name = "scene_response_baseline_829f55e"
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(REPO_ROOT / path)
    sys.modules[name] = mod
    try:
        exec(compile(src, f"<{BASELINE_REF[:7]}:{path}>", "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


class _WriteCostClock:
    """Time passes only while a write goes out (~30ms, his live room's
    measured cost), so every stamped `at`/`due_at` is deterministic AND
    distinguishes a hold measured from a spike's landing from one measured
    anywhere else."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _every_kind_scene():
    """One band, every kind family that needs no colour-set storage — dice,
    a smooth (glide) and a non-smooth (jump) permanent move, a momentary
    spike with its own hold, a momentary gain and a colour rotate — all at
    the untouched default offset 0."""
    from spectra.models.binding import ValueBinding
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [
        FlareKind(name="Dice", type="drift_jump", jump="dice"),
        FlareKind(name="Star Patch", type="permanent",
                  params={"star": {"mode": "absolute", "value": 0.8}}),
        FlareKind(name="Edges Patch", type="permanent",
                  params={"edges": {"mode": "absolute", "value": 4}}),
        FlareKind(name="Spin Spike", type="momentary", hold_ms=300,
                  params={"spin": {"mode": "absolute", "value": 0.9}}),
        FlareKind(name="Gain Pulse", type="momentary", hold_ms=200, gain=0.5),
        FlareKind(name="Rotate", type="color_rotate"),
    ]
    return SceneV2(
        name="Byte Identity",
        devices=[SceneDeviceConfig(
            id="dev1", target_kind="virtual", target=VID, effect_type="radial",
            params={"spin": 0.2, "star": 0.3, "edges": 6,
                    "twist": ValueBinding(signal="random", mode="map",
                                          out_min=0.0, out_max=5.0)})],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Dice": 1.0, "Star Patch": 0.8,
                             "Edges Patch": 1.0, "Spin Spike": 1.0,
                             "Gain Pulse": 0.6, "Rotate": 1.0})])})


async def _one_fire_and_its_releases(engine_cls, scene):
    """The whole observable life of one fire: on_event, then every release
    and colour rotate it armed, drained at their own due times."""
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor

    clock = _WriteCostClock()

    class _CostlyWrites(RecordingExecutor):
        def _record(self, *a, **kw):
            super()._record(*a, **kw)
            clock.t = round(clock.t + 0.03, 6)

    executor = _CostlyWrites(clock=clock,
                             room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=clock, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(11))
    responder = engine_cls(
        conductor=conductor, executor=executor, rng=Random(7), clock=clock,
        curve_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState())
    config = {"spin": 0.2, "star": 0.3, "edges": 6, "twist": 1.0,
              "brightness": 0.9, "gradient": "#ff0000"}
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": "radial", "config": dict(config),
        "entry_id": "dev1", "color_mode": "set"}])

    record = await responder.on_event("flare", 0.5)
    groups = responder.take_release_schedule()
    for group in groups:
        clock.t = max(clock.t, group.due_at)
        await responder.flush_releases(group.hold_s, fire_seq=group.fire_seq,
                                       due_by=group.due_at)
    for dwell_s in responder.pending_color_rotate_holds():
        clock.t = round(clock.t + dwell_s, 6)
        await responder.flush_color_rotates(dwell_s)

    writes = [{k: w[k] for k in ("seq", "at", "kind", "virtual_id",
                                 "effect_type", "params", "duration_ms")}
              for w in executor.writes]
    return {"record": json.dumps(record),
            "writes": writes,
            "groups": [tuple(g) for g in groups],
            "pending_releases": responder.pending_release_keys(),
            "param_baseline": dict(conductor.virtuals[VID].param_baseline)}


def test_byte_identical_when_every_kind_is_at_the_default_offset():
    """A band whose kinds all sit at trigger_offset_ms=0 must be
    byte-identical to before this feature existed: the same writes in the
    same order with the same params, durations, kinds and timestamps, the
    same on_event() record field for field and in the same key order, the
    same release schedule, and the same carried state — asserted against
    the pinned pre-change module, not a hand-written expectation."""
    from spectra.services import scene_response
    baseline = _baseline_scene_response()
    scene = _every_kind_scene()

    before = asyncio.run(_one_fire_and_its_releases(baseline.ResponseEngine, scene))
    after = asyncio.run(_one_fire_and_its_releases(scene_response.ResponseEngine, scene))

    kinds_fired = {k["name"] for k in json.loads(after["record"])["kinds"]}
    assert kinds_fired == {"Dice", "Star Patch", "Edges Patch", "Spin Spike",
                           "Gain Pulse", "Rotate"}
    assert {w["kind"] for w in after["writes"]} == {"jump", "glide"}
    assert after["groups"], "the momentary kinds must have armed releases"
    assert after["writes"] == before["writes"]
    assert after["record"] == before["record"]
    assert after["groups"] == before["groups"]
    assert after["pending_releases"] == before["pending_releases"] == set()
    assert after["param_baseline"] == before["param_baseline"]


# ── 2. the swim-burst shape: a negative offset fires NOW, the band-mate  ────
#      fires LATER, on the mark — never the other way around ───────────────

def test_negative_offset_kind_fires_now_zero_offset_kind_waits(tmp_path):
    """His exact ask: 'his swim burst at -100 ms on a band of otherwise-0
    kinds then fires 100 ms early by itself, and the rest of the band
    fires on the mark.' Kind A (offset -100) must already be written by
    the time on_event returns; Kind B (offset 0) must NOT be written yet,
    and lands ~100ms later once its scheduled batch runs."""
    _categories_fixture(tmp_path)
    scene = _stagger_scene(offset_a=-100, offset_b=0)

    async def main():
        host, virtual = await _host(tmp_path, "stagger")
        try:
            headless.attach_effect(host, virtual, "blackhole", CFG)
            executor, conductor, responder = _engine(_Wall())
            _fire(conductor, scene, CFG)

            t0 = time.monotonic()
            tasks = await _fire_band(responder)
            # Kind A landed inline, synchronously, before on_event returned.
            assert _params_written(executor, "swirl")
            assert not _params_written(executor, "horizon_scale")

            batches = responder.take_kind_batch_schedule()  # already drained by _fire_band
            assert batches == []  # _fire_band already took them

            for t in tasks:
                await t
            t1 = time.monotonic()

            b_writes = _params_written(executor, "horizon_scale")
            assert len(b_writes) == 1
            gap_s = t1 - t0
            # ~100ms, allowing scheduler slack the same way test_reverse_
            # flare_release.py's own hold measurements do.
            assert 0.08 <= gap_s <= 0.35, gap_s
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 3. three-kind anchor arithmetic: delays are relative to the SAME     ────
#      anchor band_trigger_offset_ms already computes ───────────────────────

def test_three_kind_delays_match_the_anchor_arithmetic(tmp_path):
    """offsets [-100, 0, +50]: anchor = min(nonzero) = -100 (the -100 and
    +50 kinds are the only authored asks; 0 never competes). Delays:
    kind(-100) -> 0 (runs now), kind(0) -> 100, kind(+50) -> 150 — two
    distinct PendingKindBatch entries, never one merged, never negative."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [
        FlareKind(name="A", type="permanent", trigger_offset_ms=-100,
                 params={"swirl": {"mode": "absolute", "value": -2.0}}),
        FlareKind(name="B", type="permanent", trigger_offset_ms=0,
                 params={"horizon_scale": {"mode": "absolute", "value": 0.4}}),
        FlareKind(name="C", type="permanent", trigger_offset_ms=50,
                 params={"base_speed": {"mode": "absolute", "value": 3.0}}),
    ]
    scene = SceneV2(
        name="Three Kind", devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="blackhole",
            params={"swirl": 0.0, "horizon_scale": 0.2, "base_speed": 2.0})],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                     kinds={"A": 1.0, "B": 1.0, "C": 1.0})])})

    _run(_check_three_kind(scene))


async def _check_three_kind(scene):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _categories_fixture(Path(tmp))
        host, virtual = await _host(Path(tmp), "three")
        try:
            headless.attach_effect(host, virtual, "blackhole", CFG)
            executor, conductor, responder = _engine(_Wall())
            _fire(conductor, scene, CFG)
            t0 = time.monotonic()
            await responder.on_event("flare", 0.5)
            assert _params_written(executor, "swirl")       # A ran now
            assert not _params_written(executor, "horizon_scale")  # B waits
            assert not _params_written(executor, "base_speed")    # C waits

            batches = responder.take_kind_batch_schedule()
            assert len(batches) == 2, batches
            due = sorted(b.due_at - t0 for b in batches)
            assert 0.08 <= due[0] <= 0.15, due   # ~100ms
            assert 0.13 <= due[1] <= 0.20, due   # ~150ms
        finally:
            facade.set_host(None)
            await host.shutdown()


# ── 4. all-positive offsets clamp to zero delay, never negative ─────────────

def test_all_positive_offsets_never_produce_a_negative_delay(tmp_path):
    """offsets [0, +50]: anchor = min(nonzero) = 50 (0 never competes).
    Naively kind(0)'s delay would be 0-50=-50 — clamped to 0 instead, so
    it simply rides along at the band's own already-relocated moment
    (its pre-existing behaviour) rather than crashing or scheduling
    something impossible."""
    _categories_fixture(tmp_path)
    scene = _stagger_scene(offset_a=0, offset_b=50)

    async def main():
        host, virtual = await _host(tmp_path, "clamped")
        try:
            headless.attach_effect(host, virtual, "blackhole", CFG)
            executor, conductor, responder = _engine(_Wall())
            _fire(conductor, scene, CFG)
            record = await responder.on_event("flare", 0.5)
            assert responder.take_kind_batch_schedule() == []
            names = {k["name"] for k in record["kinds"]}
            assert names == {"Kind A", "Kind B"}
            assert _params_written(executor, "swirl")
            assert _params_written(executor, "horizon_scale")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 5. two kinds sharing one delay still honour the fixed execution      ────
#      order (regression guard on the _run_kinds extraction) ────────────────

def test_same_param_collision_within_one_batch_keeps_fixed_order(tmp_path):
    """Two kinds at the SAME stagger delay, targeting the SAME param:
    the fixed permanent-before-momentary order (scene_response.py's own
    module docstring) must survive the _execute_band_locked/_run_kinds
    refactor — the momentary patch (processed after permanent in the
    sorted moves loop) still wins the same-key dict.update()."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [
        FlareKind(name="Perm", type="permanent", trigger_offset_ms=-100,
                 params={"swirl": {"mode": "absolute", "value": -1.0}}),
        FlareKind(name="Mom", type="momentary", hold_ms=300,
                 trigger_offset_ms=-100,
                 params={"swirl": {"mode": "absolute", "value": -3.0}}),
    ]
    scene = SceneV2(
        name="Collision", devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="blackhole",
            params={"swirl": 0.0})],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                     kinds={"Perm": 1.0, "Mom": 1.0})])})

    async def main():
        host, virtual = await _host(tmp_path, "collision")
        try:
            headless.attach_effect(host, virtual, "blackhole", CFG)
            executor, conductor, responder = _engine(_Wall())
            _fire(conductor, scene, CFG)
            record = await responder.on_event("flare", 0.5)
            assert responder.take_kind_batch_schedule() == []
            writes = _params_written(executor, "swirl")
            assert writes, "same-delay batch should still run inline"
            assert writes[-1]["params"]["swirl"] == -3.0, (
                "Mom must win the same-key write, matching the "
                "permanent-before-momentary fixed order")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 6. fire_kind (the isolated preview path) never stagg­ers itself ─────────

def test_fire_kind_preview_never_schedules_a_kind_batch(tmp_path):
    """fire_kind (the flare scrubbing-preview's execution entry point)
    fires ONE kind in isolation, bypassing band selection entirely — a
    single kind's own anchor is itself, so its delay is always 0 no
    matter what trigger_offset_ms it carries. Confirms the new mechanism
    is scoped to _execute_band_locked and never reaches fire_kind."""
    from spectra.models.scene import FlareKind
    _categories_fixture(tmp_path)
    kind = FlareKind(name="Solo", type="permanent", trigger_offset_ms=-9000,
                     params={"swirl": {"mode": "absolute", "value": -2.0}})

    async def main():
        host, virtual = await _host(tmp_path, "solo")
        try:
            headless.attach_effect(host, virtual, "blackhole", CFG)
            executor, conductor, responder = _engine(_Wall())
            scene = _stagger_scene()
            _fire(conductor, scene, CFG)
            await responder.fire_kind(kind, 0.5)
            assert responder.take_kind_batch_schedule() == []
            assert _params_written(executor, "swirl")
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
