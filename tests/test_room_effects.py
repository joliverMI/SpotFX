"""The room-effects layer's own unit proofs — the composition seam, the
watchdog holder, and the ordering that keeps a revert unscaled.

The frame-level proof (the wave actually moving rendered pixels, its phase
lag matching its travel, and the room coming back) lives in
tests/test_room_effect_wave_landing.py against the real render pipeline;
this file holds the properties that are about the SEAMS rather than the
light.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,
                                     EmitterFootprint, Point, RoomMap)
from spectra.services import fx_seam, param_watchdog, room_effects
from spectra.services.light_field_fields import DimWave

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


def _fp(emitter_id: str, lo: float, hi: float, vids: list[str]) -> EmitterFootprint:
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int(round((1.0 - hi) * GRID_H))
    y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
    grid[y0:y1, :] = 1.0
    return EmitterFootprint(emitter_id=emitter_id, virtual_ids=vids,
                            grid=[float(v) for v in grid.reshape(-1)],
                            weight=float(grid.sum()))


def _room() -> RoomMap:
    room = RoomMap(name="R", device_ids=["low", "high"], axis=AXIS)
    room.put_footprint(_fp("low", 0.0, 0.2, ["v-low"]))
    room.put_footprint(_fp("high", 0.8, 1.0, ["v-high"]))
    return room


def _running(gains: dict[str, float]) -> None:
    """Put the layer into a running state without a hold — the shape a
    future 'ride on top without holding' change would take, and the shape
    the watchdog holder has to be right for."""
    room_effects._state.running = True
    room_effects._state.gains = dict(gains)
    room_effects._state.spec = room_effects.RoomEffectSpec(room_id="r")


@pytest.fixture()
def held(monkeypatch):
    """_live() requires the hold to be genuinely active; pin it True so the
    seam behaviour can be tested without standing a whole hold up."""
    from spectra.services import flare_preview_hold
    monkeypatch.setattr(flare_preview_hold, "active", lambda: True)


# ── 1. the composition seam ───────────────────────────────────────────────

def test_compose_is_the_identity_object_when_nothing_is_running():
    cfg = {"brightness": 0.5}
    assert room_effects.compose("v-low", "singleColor", cfg) is cfg, (
        "the seam's normal path must be byte-identical to before this "
        "feature existed — the SAME object back, not a copy")


def test_compose_multiplies_the_shows_own_brightness(held):
    _running({"v-low": 0.25})
    out = room_effects.compose("v-low", "singleColor", {"brightness": 0.8,
                                                        "color": "#ffffff"})
    assert out["brightness"] == pytest.approx(0.2)
    assert out["color"] == "#ffffff", "nothing else in the write is touched"
    assert room_effects._state.base["v-low"] == 0.8, (
        "the show's own authored brightness is LEARNED here — the base a "
        "gain multiplies is never invented")


def test_compose_leaves_an_undriven_virtual_and_a_write_with_no_brightness(held):
    _running({"v-low": 0.25})
    cfg = {"brightness": 0.8}
    assert room_effects.compose("v-other", "singleColor", cfg) is cfg
    cfg2 = {"color": "#ff0000"}
    assert room_effects.compose("v-low", "singleColor", cfg2) is cfg2


def test_the_layers_own_write_is_never_scaled_twice(held):
    """A tick's write already carries the gain; composing it again would
    square the wave."""
    _running({"v-low": 0.5})
    w = {"virtual_id": "v-low", "effect_type": "singleColor",
         "config": {"brightness": 0.4}, "room_effect": True}
    assert fx_seam._compose_room_effect(w) is w
    plain = {"virtual_id": "v-low", "effect_type": "singleColor",
             "config": {"brightness": 0.4}}
    assert fx_seam._compose_room_effect(plain)["config"]["brightness"] == \
        pytest.approx(0.2)


def test_the_seam_learns_the_live_effect_type_from_writes_passing_through(held):
    _running({"v-low": 1.0})
    room_effects.compose("v-low", "blackhole", {"brightness": 0.9})
    assert room_effects._state.effect_type["v-low"] == "blackhole", (
        "a tick must name the CURRENT effect type or its brightness write "
        "would switch the effect instead of merging into it")


# ── 2. the watchdog holder ────────────────────────────────────────────────

def test_holds_is_empty_when_nothing_runs():
    assert room_effects.holds() == set()


def test_holds_names_exactly_the_driven_brightness_keys(held):
    _running({"v-low": 0.4, "v-high": 0.9})
    assert room_effects.holds() == {("v-low", "brightness"),
                                    ("v-high", "brightness")}


def test_the_watchdog_does_not_repair_a_running_wave(held):
    """Proven against a deliberately-OPEN gate — the shape a narrowed gate
    would take. Today production's gate already stands the whole sweep down
    while a hold is active; this is the proof that the per-key holder is
    what actually protects the wave when it does not."""
    _running({"v-low": 0.3})

    class _Conductor:
        virtuals = {"v-low": type("S", (), {
            "effect_type": "singleColor",
            "param_baseline": {"brightness": 0.8, "spin": 0.5}})()}
        mechanisms: list = []

    class _Responses:
        def pending_release_keys(self):
            return set()

        def release_target(self, vid, pname):
            return {"brightness": 0.8, "spin": 0.5}[pname]

    live = param_watchdog.LiveEffect(
        effect_type="singleColor",
        # brightness moved by the wave; spin moved by nothing (a real orphan)
        config={"brightness": 0.24, "spin": 0.99}, tweening=frozenset())

    restored: list = []

    class _Executor:
        async def glide(self, *a, **k):
            restored.append(a)

        async def jump(self, *a, **k):
            restored.append(a)

    def _deps(holds):
        return param_watchdog.Deps(
            conductor=_Conductor(), responses=_Responses(),
            executor=lambda: _Executor(),
            live_effect=lambda vid: live,
            room_controls=lambda: type("C", (), {"brightness_multiplier": 1.0})(),
            gate=lambda: None, clock=lambda: 0.0,
            room_effect_holds=holds)

    rec = asyncio.run(param_watchdog.sweep_once(_deps(room_effects.holds)))
    assert rec["skipped"] is None
    assert rec["held"] >= 1, "the wave's brightness is HELD, not suspected"
    suspected_params = {k[1] for k in param_watchdog._tracking}
    assert "brightness" not in suspected_params, (
        "a travelling wave must never be suspected of being an orphan")
    assert "spin" in suspected_params, (
        "and every OTHER param stays watched — this is a per-key holder, "
        "not a global stand-down")

    # negative control: without the holder, the wave IS suspected
    param_watchdog.reset()
    rec2 = asyncio.run(param_watchdog.sweep_once(_deps(lambda: set())))
    assert "brightness" in {k[1] for k in param_watchdog._tracking}, (
        "without the holder the watchdog would start a case against the "
        "wave — which is what makes registering one load-bearing")


# ── 3. resolution and gains ───────────────────────────────────────────────

def test_only_mapped_emitters_are_driven_and_the_rest_are_named():
    room = _room()
    room.device_ids.append("never-mapped")
    driven = room_effects.resolve_driven(
        room, room_effects.RoomEffectSpec(room_id=room.id))
    assert sorted(d.emitter_id for d in driven) == ["high", "low"]


def test_a_device_selection_narrows_the_driven_set():
    room = _room()
    driven = room_effects.resolve_driven(
        room, room_effects.RoomEffectSpec(room_id=room.id, device_ids=["low"]))
    assert [d.emitter_id for d in driven] == ["low"]


def test_an_emitters_gain_reaches_every_virtual_its_light_came_out_of():
    """The footprint was captured with all of that device's virtuals lit
    together, so that is what the measurement means."""
    room = RoomMap(name="R", device_ids=["d"], axis=AXIS)
    room.put_footprint(_fp("d", 0.4, 0.6, ["v1", "v2"]))
    driven = room_effects.resolve_driven(
        room, room_effects.RoomEffectSpec(room_id=room.id))
    gains, masks = room_effects.compute_gains(driven, DimWave(depth=0.5), 0.0)
    assert set(gains) == {"v1", "v2"} and gains["v1"] == gains["v2"]
    assert masks == {}, "a whole-device emitter never installs a per-pixel mask"


def test_gains_are_clamped_into_zero_one():
    room = _room()
    driven = room_effects.resolve_driven(
        room, room_effects.RoomEffectSpec(room_id=room.id))
    gains, masks = room_effects.compute_gains(
        driven, lambda s, t: np.full(s.axis.shape, 4.2), 0.0)
    assert set(gains.values()) == {1.0} and masks == {}


# ── 4. start refuses honestly ─────────────────────────────────────────────

def test_start_refuses_by_name_when_nothing_is_mapped():
    room = RoomMap(name="R", device_ids=["d"], axis=AXIS)
    spec = room_effects.RoomEffectSpec(room_id=room.id)

    async def main():
        deps = room_effects.RunnerDeps(
            apply_writes=lambda *a, **k: None,
            get_virtuals=lambda: {}, open_hold=None, close_hold=None)
        return await room_effects.start(room, spec, deps)

    result = asyncio.run(main())
    assert result["running"] is False
    assert "map the room first" in result["reason"]
    assert result["unmapped"] == ["d"]


def test_start_refuses_when_no_mapped_virtual_is_rendering():
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id)

    async def main():
        async def virtuals():
            return {"someone-else": {"active": True,
                                     "effect": {"type": "blackhole", "config": {}}}}
        deps = room_effects.RunnerDeps(
            apply_writes=lambda *a, **k: None, get_virtuals=virtuals,
            open_hold=None, close_hold=None)
        return await room_effects.start(room, spec, deps)

    result = asyncio.run(main())
    assert result["running"] is False
    assert "is SPECTRA driving the room" in result["reason"]


def test_only_dim_wave_is_buildable_from_a_spec():
    spec = room_effects.RoomEffectSpec(room_id="r", kind="implode")
    with pytest.raises(ValueError, match="not built in this slice"):
        spec.field()


# ── 5. the ordering that keeps a revert unscaled ──────────────────────────

def test_stop_clears_the_gain_before_it_closes_the_hold():
    """ORDER IS LOAD-BEARING: the hold's revert write passes back through
    the same seam, so a gain still in place would hand the room back
    dimmed."""
    seen: list[str] = []
    room_effects._state.running = True
    room_effects._state.gains = {"v-low": 0.1}

    async def close():
        seen.append("close")
        seen.append(f"running={room_effects._state.running}")
        seen.append(f"gains={len(room_effects._state.gains)}")

    async def main():
        deps = room_effects.RunnerDeps(
            apply_writes=lambda *a, **k: None, get_virtuals=lambda: {},
            open_hold=None, close_hold=close)
        return await room_effects.stop(deps)

    asyncio.run(main())
    assert seen == ["close", "running=False", "gains=0"]
