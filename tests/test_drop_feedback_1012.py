"""THE ADMIRAL'S DROP FEEDBACK, 2026-10-12 — three changes, one proof each.

1. "The flash flare on pulse should only happen on high energy, .8 or
   higher." — a pulse_flash flare writes nothing unless the top bar's
   Energy (bridge.intensity()) is at least RoomControlState.
   pulse_flash_min_energy (0.8); in a lull a gated flash therefore cannot
   punch the dark open either (scene_response.pulse_flash_allowed).
2. "stip shockwave, yes" — the strips' own drop shockwave
   (fx/effects/strip_phase.py) obeys the crystal Shockwave's three switches
   (the room, the scene, the 0.7 energy floor): told off, ONLY the wave and
   its flood go; the strip's colour brightness and activity burst still run.
3. "I want orbits and fish to specifically not go dark completely on the
   crystal or the strips. I do want it on pulse effect, though." / "orbits
   should keep at least one dim blob" — the breath-hold
   (fx/effects/phase_grammar.py) skips the Fish, dims Orbits to one dim
   blob, and takes the Pulse singles to true black (a flare's punch and
   flash included); the Orbits strip keeps one dim blob through its lull's
   dark (its own lull_ember). The crystal halves are measured on the real
   pipeline by tests/test_phase_grammar.py::test_on_the_real_pipeline
   (scripts/check_drop_shockwave.breath_ok); the Orbits strip's by
   tests/test_particle_strip_phase.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import device_model  # noqa: E402
from fx.effects import phase_grammar as pg  # noqa: E402
from fx.effects import strip_phase as sp  # noqa: E402
from spectra.models.scene import FlareKind, SceneV2  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response as sr  # noqa: E402
from strip_phase_harness import (FPS, PALETTE, STRIP_PX, Room,  # noqa: E402
                                 run, scene_for)


# ── who is told what ───────────────────────────────────────────────────────

def test_the_breath_hold_set_matches_the_effect_classes():
    """BREATH_HOLD_EFFECTS = every Shockwave member whose class takes the
    breath (not the Fish) plus Pulse and Star (both take it in their own
    draw); Orbits takes it only down to a floor."""
    taking = {e for e in device_model.DROP_SHOCK_EFFECTS
              if getattr(device_model._effect_class(e), "BREATH_HOLD", True)}
    assert device_model.BREATH_HOLD_EFFECTS == taking | {"pulse", "radial"}
    assert "fish" not in device_model.BREATH_HOLD_EFFECTS
    assert "pulse" in device_model.BREATH_HOLD_EFFECTS
    assert device_model._effect_class("fish").BREATH_HOLD is False
    assert device_model._effect_class("orbits").BREATH_FLOOR > 0.0
    for e in ("blackhole", "eye", "sauron"):
        assert device_model._effect_class(e).BREATH_FLOOR == 0.0
    # every breathing effect's schema carries the two keys
    for e in device_model.BREATH_HOLD_EFFECTS:
        assert device_model.schema_default(e, pg.BREATH_KEY) == 0.0


def test_every_strip_member_is_told_the_shockwave_verdict():
    assert device_model.STRIP_PHASE_EFFECTS <= device_model.DROP_SHOCK_TOLD_EFFECTS
    assert device_model.DROP_SHOCK_EFFECTS <= device_model.DROP_SHOCK_TOLD_EFFECTS
    for e in device_model.STRIP_PHASE_EFFECTS:
        assert device_model.schema_default(e, pg.SHOCK_ON_KEY) is True
    assert pg.SHOCK_ON_KEY in sp.StripPhase.PASSIVE_CONFIG_KEYS


class _Exec:
    def __init__(self):
        self.jumps = []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        pass


def _responder(effects: dict, energy=0.8, scene=None, **room):
    ex = _Exec()
    conductor = SimpleNamespace(scene=scene, virtuals={
        vid: SimpleNamespace(effect_type=et) for vid, et in effects.items()})
    eng = sr.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(**room),
        song_position=lambda: (None, None),
        room_energy=(energy if callable(energy) else (lambda: energy)))
    return eng, ex


ROOM = {"orbits": "orbits", "fish": "fish", "blackhole": "blackhole",
        "p": "pulse", "strip": "orbits1d", "melt": "melt",
        "fw": "fireworks1d", "fireworks": "fireworks"}


def test_a_lull_arm_tells_the_breath_to_pulse_and_orbits_but_not_the_fish():
    eng, ex = _responder(ROOM)
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=4_000, intensity=0.6))
    told = {vid: p for vid, _et, p in ex.jumps}
    for vid in ("orbits", "blackhole", "p"):
        assert told[vid][pg.BREATH_KEY] == pytest.approx(0.4), vid
    for vid in ("fish", "strip", "melt", "fw", "fireworks"):
        assert pg.BREATH_KEY not in told[vid], vid
    assert rec["lull_breath_s"] == pytest.approx(0.4)


def test_a_pulse_only_room_still_gets_its_breath():
    eng, ex = _responder({"p": "pulse"})
    asyncio.run(eng._drive_phase("lull", gap_ms=4_000, intensity=0.6))
    assert ex.jumps[0][2][pg.BREATH_KEY] == pytest.approx(0.4)


@pytest.mark.parametrize("energy, room, scene_on, want", [
    (0.9, {}, True, True),
    (0.5, {}, True, False),                              # below 0.7
    (0.9, {"drop_shock_enabled": False}, True, False),   # the room off
    (0.9, {}, False, False),                             # the scene off
    (None, {}, True, True),                              # unknown: not gated
])
def test_a_drop_arm_tells_the_strips_the_same_verdict(energy, room, scene_on,
                                                      want):
    eng, ex = _responder(ROOM, energy=energy,
                         scene=SceneV2(name="x", drop_shock_enabled=scene_on),
                         **room)
    rec = asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.6))
    told = {vid: p for vid, _et, p in ex.jumps}
    for vid in ("strip", "melt", "fw", "orbits", "fish", "blackhole"):
        assert told[vid][pg.SHOCK_ON_KEY] is want, vid
    # never told to an effect with no shockwave of either kind
    assert pg.SHOCK_ON_KEY not in told["fireworks"]
    assert pg.SHOCK_ON_KEY not in told["p"]
    assert rec["drop_shock"]["on"] is want


def test_a_strip_only_room_is_told_the_verdict():
    eng, ex = _responder({"melt": "melt"}, energy=0.2)
    rec = asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.6))
    assert ex.jumps[0][2][pg.SHOCK_ON_KEY] is False
    assert rec["drop_shock"]["reason"] == pg.SHOCK_BELOW_ENERGY


# ── the strips' shockwave obeys the switches, on the real pipeline ────────

MELT = {"gradient": PALETTE}


def _strip_drop(tmp_path, energy, *, scene_on=True, wave=None):
    """One melt strip on the real pipeline through the production
    ResponseEngine: a drop arm at the top bar's `energy`, then 1.2 s.
    Returns (frames from the drop on, the layer's frame values at the
    drop's first frame)."""
    cfg = dict(MELT)
    if wave is not None:
        cfg["drop_shockwave"] = wave

    async def main():
        scene = scene_for({"s": "melt"})
        scene.drop_shock_enabled = scene_on
        async with Room(str(tmp_path), {"s": ("melt", STRIP_PX, 1, cfg)},
                        scene=scene) as r:
            r.responder._room_energy = lambda: energy
            r.step(2 * FPS)
            n0 = len(r.frames["s"])
            rec = await r.phase("drop", intensity=0.85)
            r.step(1)
            first = r.effects["s"]._sp_frame
            r.step(int(1.2 * FPS))
            return rec, r.frames["s"][n0:], first
    return run(main())


def test_a_skipped_strip_drop_loses_only_its_shockwave(tmp_path):
    rec_on, on, f_on = _strip_drop(tmp_path / "on", 0.9)
    rec_off, off, f_off = _strip_drop(tmp_path / "off", 0.5)
    _r, zero, f_zero = _strip_drop(tmp_path / "zero", 0.9, wave=0.0)
    assert rec_on["phase"]["drop_shock"]["on"] is True
    assert rec_off["phase"]["drop_shock"]["reason"] == pg.SHOCK_BELOW_ENERGY
    # told on: the wave paints; told off: no wave at all ...
    assert f_on.wave > 0.0 and f_off.wave == 0.0
    # ... but the rest of the drop still runs: brighter colours, busier
    assert f_off.gain > 1.0 and f_off.activity > 1.0
    assert (f_off.gain, f_off.activity) == (f_on.gain, f_on.activity)
    # skipped is EXACTLY the strip's drop with its shockwave at zero
    assert len(off) == len(zero)
    assert all(np.array_equal(a, b) for a, b in zip(off, zero))
    # and the control: told on, the shockwave changes the drop's frames
    assert any(not np.array_equal(a, b) for a, b in zip(on, zero))


def test_a_scene_switched_off_skips_its_strips_shockwave(tmp_path):
    rec, _frames, first = _strip_drop(tmp_path, 1.0, scene_on=False)
    assert rec["phase"]["drop_shock"]["reason"] == pg.SHOCK_SCENE_OFF
    assert first.wave == 0.0 and first.gain > 1.0


# ── the Pulse flash's energy floor ─────────────────────────────────────────

def test_the_flash_rule():
    assert sr.pulse_flash_allowed(0.8, 0.8) == (True, sr.PULSE_FLASH_ALLOWED)
    assert sr.pulse_flash_allowed(0.95, 0.8)[0] is True
    assert sr.pulse_flash_allowed(0.79, 0.8) == (
        False, sr.PULSE_FLASH_BELOW_ENERGY)
    assert sr.pulse_flash_allowed(None, 0.8) == (
        True, sr.PULSE_FLASH_ENERGY_UNKNOWN)
    assert sr.pulse_flash_allowed(0.0, 0.0)[0] is True


def test_the_flash_floor_setting_defaults_to_08_and_is_sonic_editable():
    from spectra.services import settings_console as sc
    assert rc.RoomControlState().pulse_flash_min_energy == pytest.approx(0.8)
    assert rc.field_bounds("pulse_flash_min_energy") == (0.0, 1.0)
    spec = sc.SETTINGS_REGISTRY["pulse_flash_min_energy"]
    assert (spec.min, spec.max) == (0.0, 1.0)
    assert "top-bar" in spec.label.lower()


def test_sonic_moves_the_flash_floor(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import settings_console as sc
    for name in ("SETTINGS_LOG_FILE", "ROOM_CONTROLS_FILE"):
        monkeypatch.setattr(scfg, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    asyncio.run(sc.apply_change("pulse_flash_min_energy", 0.9))
    assert rc.load_room_controls().pulse_flash_min_energy == pytest.approx(0.9)
    with pytest.raises(sc.SettingChangeError):
        asyncio.run(sc.apply_change("pulse_flash_min_energy", 1.2))


@pytest.mark.parametrize("energy, floor, fires", [
    (0.85, 0.8, True), (0.8, 0.8, True), (0.79, 0.8, False),
    (0.3, 0.8, False), (0.3, 0.0, True), (None, 0.8, True)])
def test_the_flash_writes_only_at_or_above_the_floor(energy, floor, fires):
    eng, ex = _responder({"p": "pulse", "strip": "melt"}, energy=energy,
                         pulse_flash_min_energy=floor)
    out = asyncio.run(eng._pulse_flash(0.9))
    flashes = [p for _v, _et, p in ex.jumps if "flash" in p]
    assert bool(flashes) is fires
    assert out["virtuals"] == (1 if fires else 0)
    assert out["min_energy"] == pytest.approx(floor)
    if not fires:
        assert out["skipped"] == sr.PULSE_FLASH_BELOW_ENERGY


def test_an_unreadable_energy_does_not_hold_the_flash_back():
    def boom():
        raise RuntimeError("bridge down")
    eng, ex = _responder({"p": "pulse"}, energy=boom)
    out = asyncio.run(eng._pulse_flash(0.9))
    assert out["virtuals"] == 1 and out["reason"] == sr.PULSE_FLASH_ENERGY_UNKNOWN


FLASH = FlareKind(name="Pulse Flash", type="pulse_flash")
PULSE_CFG = {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5}


def _lull_flash(tmp_path, energy, breath_s=0.0, flare_at_s=2.6):
    """A Pulse single on the real pipeline: a 4 s lull (dark from 2 s), a
    pulse_flash flare at `flare_at_s` at the top bar's `energy`. Returns
    (the flare's record, frames from the flare on, frames per second)."""
    async def main():
        async with Room(str(tmp_path), {"p": ("pulse", 1, 1, dict(PULSE_CFG))},
                        scene=scene_for({"p": "pulse"}, [FLASH])) as r:
            r.responder._room_energy = lambda: energy
            base = r.responder._room_controls

            def controls():
                return base().model_copy(update={"lull_breath_hold_s": breath_s})
            r.responder._room_controls = controls
            r.step(2 * FPS)
            await r.phase("lull", gap_ms=4000)
            r.step(int(flare_at_s * FPS))
            n0 = len(r.frames["p"])
            rec = await r.flare(0.9)
            r.step(int(1.0 * FPS))
            return rec, r.frames["p"][n0:]
    return run(main())


def test_a_low_energy_flash_does_not_light_the_lull(tmp_path):
    """In the lull's dark: a flash below the floor writes nothing — no flash
    and no punch through the dark — while one above it lights the single."""
    rec_lo, lo = _lull_flash(tmp_path / "lo", 0.6)
    rec_hi, hi = _lull_flash(tmp_path / "hi", 0.9)
    assert "flare_punch" not in repr(rec_lo)
    assert "below_energy" in repr(rec_lo)
    assert all(f.max() == 0.0 for f in lo)               # the dark holds
    assert "flare_punch" in repr(rec_hi)
    assert max(f.max() for f in hi) > 0.0                 # the flare shows


def test_the_breath_hold_takes_the_pulse_single_to_true_black(tmp_path):
    """A loud flash that punches the lull open just before the drop: with
    the breath-hold (0.4 s before the 4 s mark) the single is TRUE BLACK
    for the breath; without it (the control) the punch shows there."""
    _rec, held = _lull_flash(tmp_path / "b", 0.95, breath_s=0.4,
                             flare_at_s=3.45)
    _rec, open_ = _lull_flash(tmp_path / "n", 0.95, breath_s=0.0,
                              flare_at_s=3.45)
    # frames from 3.45 s: the breath runs 3.6 .. 4.0 s of the lull
    start = int(round(0.17 * FPS))
    end = int(round(0.53 * FPS))
    assert all(f.max() == 0.0 for f in held[start:end])
    assert max(f.max() for f in open_[start:end]) > 0.0
    # before the breath the punch still shows (only the breath is black)
    assert max(f.max() for f in held[:int(0.1 * FPS)]) > 0.0
