"""THE ORBITS AND FIREWORKS STRIPS ON THE STRIP PHASE LAYER, and the
particle strips' phase plumbing folded into it (fx/effects/strip_phase.py,
THE PARTICLE STRIPS' PLUMBING; strip phase plan phase 3, revision 3). The
Admiral, 2026-10-11: the strips should "increase in brightness and activity
during charge, dim and relax into black for most lulls, and big explosion
of brightness and activity on the [drop]" — binding: "i don't want to raise
the white in the charge, or on the drop". His calls: the Orbits strip's
charge swells and HOLDS; every lull is black at the room's dark point
except the Fireworks strip's rocket ember; a flare in the lull's dark
punches through.

What is proven here, on the real code it names:

- BEFORE/AFTER on his own Orbits V2 and Fireworks V2 strip entries
  (scripts/check_particle_strip_phase.py, run whole): swell to 16 and hold,
  re-add all 16 on the drop then shed back; more fireworks past his cap,
  no longer shortened, embers through the dark, a heavier drop; no charge
  or drop pixel whiter than the set; off-phase byte-identical to before;
  and the Black Hole strip byte-identical to before at strength 0 through
  a whole cycle and an orphaned lull (the fold moved plumbing, not looks).
- THE PRODUCTION PATH (tests/strip_phase_harness.py: the real
  ResponseEngine on the FacadeExecutor, a fake clock): both strips reach
  the room's dark point on the Pulse single's frame (the Orbits strip
  black, the Fireworks strip at its ember); a flare in the dark springs
  the Orbits strip's collapsed blob back out with a burst in its own
  colour and the dark returns, "Flare punch" 0 lets the dark win; an
  orphaned lull releases each strip back to its own show; the drop's
  phase key self-resets after each effect's own drop length while the
  layer's drop keeps running; and a house mode holds both back.
- THE FOLD, structurally: no particle strip keeps phase plumbing of its
  own (edge detection, the watchdog, the self-reset).
"""
from __future__ import annotations

import asyncio
import ast
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
from fx.effects import fireworks1d as fw1  # noqa: E402
from fx.effects import lull_dark, orbits1d as ob1  # noqa: E402
from fx.effects import particle_handoff  # noqa: E402
from fx.effects import strip_phase as sp  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response  # noqa: E402
from strip_phase_harness import (FPS, PALETTE, STRIP_PX, Room,  # noqa: E402
                                 lum, run, scene_for)

import scripts.check_particle_strip_phase as check  # noqa: E402

ORB = "orb"
FW = "fw"
HIS_ORB = dict(check.HIS_ORBITS, gradient=PALETTE)
HIS_FW = dict(check.HIS_FIREWORKS, gradient=PALETTE)
PARTICLE_STRIPS = ("blackhole1d", "orbits1d", "fireworks1d")


# ── before / after, his own entries ─────────────────────────────────────────

def test_the_measured_before_and_after_passes():
    """The whole measurement script — his rule now on both strips, every
    retired defect shown on the pinned before modules, off-phase frames
    byte-identical, the Black Hole strip's fold byte-identical."""
    check._failures.clear()
    assert check.main() == 0, check._failures


# ── the fold, structurally ──────────────────────────────────────────────────

def test_no_particle_strip_keeps_phase_plumbing_of_its_own():
    """Edge detection, the orphan watchdog and the drop's self-reset live in
    the layer ONCE. A particle strip that grew its own copy back would edge
    a phase twice and release a build on two clocks."""
    for name in PARTICLE_STRIPS:
        src = (ROOT / f"fx/effects/{name}.py").read_text()
        tree = ast.parse(src)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "phase_release_due" not in attrs, name
        assert "particle_handoff" not in names, name
        for own in ("_phase_pending", "_phase_done_t", "_phase_t"):
            assert own not in attrs, (name, own)
        cls = device_model._effect_class(name)
        assert issubclass(cls, sp.StripPhase), name
        assert cls.STRIP_PHASE_DROP_S is not None, name
        assert "_strip_phase_enter" in vars(cls), name
    assert ob1.Orbits1d.STRIP_PHASE_DROP_S == ob1.DROP_SETTLE_S
    assert fw1.Fireworks1d.STRIP_PHASE_DROP_S == fw1.DROP_SETTLE_S


def test_the_fireworks_strip_carries_its_own_ember_default():
    assert device_model.schema_default("fireworks1d", "lull_ember") == \
        pytest.approx(fw1.LULL_EMBER) == pytest.approx(0.12)
    assert device_model.schema_default("orbits1d", "lull_ember") == 0.0
    assert fw1.CHARGE_SLOW == 0.0 and fw1.CHARGE_SHORT == 0.0
    assert fw1.DROP_TAIL_RATE == 12.0
    assert ob1.CHARGE_PEAK_N == 16
    with pytest.raises(KeyError):
        sp.tunable_fields(not_a_tunable=1.0)


# ── on the production path ──────────────────────────────────────────────────

def test_both_strips_reach_the_dark_point_on_the_singles_frame(tmp_path):
    """One room, one lull arm (6 s, the 3 s cap): the Orbits strip goes
    black on the Pulse single's frame and stays black; the Fireworks strip
    reaches its ember on that frame and holds it (lit, never above it)."""
    async def main():
        effects = {ORB: ("orbits1d", STRIP_PX, 1, dict(HIS_ORB)),
                   FW: ("fireworks1d", STRIP_PX, 1, dict(HIS_FW)),
                   "p": ("pulse", 1, 1, {"gradient": "#ff0000",
                                          "beat_ms": 500.0, "energy": 0.5})}
        async with Room(str(tmp_path), effects) as r:
            r.step(3 * FPS)
            await r.phase("charge", gap_ms=3000)
            r.step(3 * FPS)
            rec = await r.phase("lull", gap_ms=6000)
            assert set(rec["phase"]["targets"]) == {ORB, FW, "p"}
            n0 = len(r.frames[ORB])
            r.step(6 * FPS)
            return r.frames[ORB][n0:], r.frames[FW][n0:], r.frames["p"][n0:]
    orb, fw, pulse = run(main())
    first_orb = next(i for i, f in enumerate(orb) if f.max() == 0)
    first_pulse = next(i for i, f in enumerate(pulse) if f.max() == 0)
    assert first_orb == first_pulse == 3 * FPS - 1
    assert all(f.max() == 0 for f in orb[first_orb:])
    assert orb[first_orb - 15].max() > 0            # a fade, not a cut
    ember = fw1.LULL_EMBER * 255.0
    assert all(0.0 < f.max() <= ember + 1e-6 for f in fw[first_orb:])
    assert fw[first_orb - 30].max() > ember          # the ember is reached


def _orbit_punch(tmp_path, cfg_extra=None):
    from spectra.models.scene import FlareKind
    gain = FlareKind(name="Flare gain 0.7-1", type="permanent", gain=0.9)

    async def main():
        cfg = {**HIS_ORB, **(cfg_extra or {})}
        async with Room(str(tmp_path), {ORB: ("orbits1d", STRIP_PX, 1, cfg)},
                        scene=scene_for({ORB: "orbits1d"}, [gain])) as r:
            eff = r.effects[ORB]
            spawned = []
            orig = eff._spawn_fragments

            def logged(pos, rgb, colours=None, _o=orig):
                spawned.append((np.array(rgb, dtype=float), colours))
                _o(pos, rgb, colours)

            eff._spawn_fragments = logged
            r.step(60)
            await r.phase("lull", gap_ms=4000)
            r.step(3 * FPS)                 # dark (dark point 2 s in)
            dark_before = r.frames[ORB][-1].max()
            collapsed = eff._lull_f
            spawned.clear()
            n0 = len(r.frames[ORB])
            await r.flare()
            r.step(int(0.3 * FPS))
            sprung = eff._lull_f
            r.step(int(2.2 * FPS))
            return (dark_before, collapsed, sprung, r.frames[ORB][n0:],
                    spawned)
    return run(main())


def test_a_flare_in_the_dark_springs_the_orbits_blob_out_in_its_own_colour(tmp_path):
    dark_before, collapsed, sprung, after, spawned = _orbit_punch(tmp_path / "p")
    assert dark_before == 0.0 and collapsed == pytest.approx(1.0)
    # the collapsed blob springs back out along the punch's envelope …
    assert sprung < 0.1
    # … with an implosion burst in its OWN colour (no white guard in a lull)
    assert len(spawned) == 1
    rgb, colours = spawned[0]
    assert all(np.allclose(c, rgb) for c in colours)
    assert max(lum(f) for f in after[2:int(0.5 * FPS)]) > 0.005
    back = int(lull_dark.punch_length_s(0.25) * FPS) + 2
    assert all(f.max() == 0.0 for f in after[back:])


def test_flare_punch_zero_lets_the_orbits_dark_win(tmp_path):
    dark_before, collapsed, sprung, after, spawned = _orbit_punch(
        tmp_path / "d", {"flare_punch_strength": 0.0})
    assert dark_before == 0.0
    assert spawned == [] and sprung == pytest.approx(1.0)
    assert all(f.max() == 0.0 for f in after)


def test_phase_implosions_are_drawn_from_the_set_not_the_hue_wheel(tmp_path):
    """On a charge (and the drop) the Orbits strip's implosion pair comes
    from the set itself — off-phase it is the effect's own ±120° pair."""
    async def main():
        async with Room(str(tmp_path), {ORB: ("orbits1d", STRIP_PX, 1,
                                              dict(HIS_ORB))}) as r:
            eff = r.effects[ORB]
            off = eff._phase_fragment_colours(0.2)
            await r.phase("charge", gap_ms=3000)
            r.step(2)
            on = eff._phase_fragment_colours(0.2)
            want = eff.get_gradient_color_vectorized1d(
                np.array([0.2 + 1 / 3, 0.2 - 1 / 3 + 1.0]))
            return off, on, want
    off, on, want = run(main())
    assert off is None
    assert np.allclose(on[0], want[0]) and np.allclose(on[1], want[1])


@pytest.mark.parametrize("effect_type", ["orbits1d", "fireworks1d"])
def test_an_orphaned_lull_releases_the_strip_to_its_own_show(tmp_path, effect_type):
    """A lull whose drop never comes must never hold a strip dark: past the
    layer's watchdog the key reads "none", the strip lights again, the
    Orbits strip is back at his count and the Fireworks rockets burn out."""
    cfg = dict(HIS_ORB if effect_type == "orbits1d" else HIS_FW)

    async def main():
        async with Room(str(tmp_path), {"s": (effect_type, STRIP_PX, 1,
                                              cfg)}) as r:
            eff = r.effects["s"]
            r.step(60)
            await r.phase("lull", gap_ms=4000)
            r.step(int((4.0 + particle_handoff.PHASE_GRACE_S + 3.0) * FPS))
            return (eff._sp_phase, eff._config["phase"], r.frames["s"][-FPS:],
                    eff)
    phase, key, tail, eff = run(main())
    assert phase == "none" and key == "none"
    assert max(f.max() for f in tail) > 0.0
    if effect_type == "orbits1d":
        assert eff.particle_count == cfg["particle_count"]
        assert eff._fly is None and eff._pos_scale == 1.0
    else:
        assert not np.any(eff.f_rocket[:eff.n] > 0.0)


@pytest.mark.parametrize("effect_type", PARTICLE_STRIPS)
def test_the_drop_key_self_resets_while_the_layers_drop_runs_on(tmp_path,
                                                                effect_type):
    cfg = {"orbits1d": HIS_ORB, "fireworks1d": HIS_FW}.get(
        effect_type, {"gradient": PALETTE})

    async def main():
        async with Room(str(tmp_path), {"s": (effect_type, STRIP_PX, 1,
                                              dict(cfg))}) as r:
            eff = r.effects["s"]
            r.step(30)
            await r.phase("charge", gap_ms=2000)
            r.step(2 * FPS)
            await r.phase("drop", intensity=0.85)
            seen = []
            for _ in range(int(1.4 * FPS)):
                r.step()
                seen.append((eff._sp_t, eff._sp_phase, eff._config["phase"],
                             eff._sp_drop_t is not None))
            return type(eff).STRIP_PHASE_DROP_S, seen
    drop_s, seen = run(main())
    in_drop = [s for s in seen if s[1] == "drop"]
    after = [s for s in seen if s[1] == "none"]
    assert in_drop and after
    assert max(s[0] for s in in_drop) < drop_s + 1.5 / FPS
    assert all(key == "none" for _t, _p, key, _d in after)
    # the layer's drop look has its own clock: still live past the reset
    assert after[0][3]


class _Exec:
    def __init__(self):
        self.jumps, self.glides = [], []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        self.glides.append((vid, et, dict(params), ms))


def test_a_house_mode_holds_both_strips_back(monkeypatch):
    """His call 4 covers the Orbits and Fireworks strips too."""
    ex = _Exec()
    conductor = SimpleNamespace(virtuals={
        ORB: SimpleNamespace(effect_type="orbits1d"),
        FW: SimpleNamespace(effect_type="fireworks1d")})
    eng = scene_response.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState())
    monkeypatch.setattr(scene_response, "_house_owns_the_look",
                        lambda: "a house mode rests")
    rec = asyncio.run(eng._drive_phase("charge", gap_ms=4000))
    assert not ex.jumps and not ex.glides
    assert sorted(rec["withheld"]["virtuals"]) == sorted([ORB, FW])
