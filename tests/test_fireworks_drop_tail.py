"""The FIREWORKS DROP TAIL (owner ask, 2026-08-21: "On the fireworks drop
there need to be fireworks spawning continuously after the first big
burst."), on BOTH vendored fireworks effects — fx/effects/fireworks.py
(his crystal) and fx/effects/fireworks1d.py (his strips) — which he sees
together and which must agree.

Deterministic, fast pytest coverage of what scripts/check_fireworks_drop_
tail.py measures and prints in full (real headless render pipeline,
fx.headless dummy device, silenced audio, fake clock):

  - the drop phase's own clock is UNTOUCHED: `phase` still self-resets to
    "none" at DROP_SETTLE_S (0.9 s) — the tail runs on its own clock
    (_drop_tail_step) and outlives it to DROP_TAIL_S;
  - the tail is a launch RATE (DROP_TAIL_RATE launches/s, easing linearly
    to 0 over DROP_TAIL_S — the charge's own linear shape mirrored on the
    way out), NOT a spawn_rate multiplier: his real Fireworks V2 entries
    run spawn_rate=0 (beat bursts only), where a multiplier is inert, so
    the tail must land on a spawn_rate=0 scene, with no beats at all;
  - tail launches are ordinary-sized fireworks (never the payoff's giant
    PAYOFF_SPEED/PAYOFF_LIFE shape);
  - a bare drop (no lull, no rockets) grows the same tail;
  - a flare burst (burst_rockets) alone never starts a tail;
  - particles spawned past the density cap (payoff, flare burst, tail,
    lull rockets — flagged p_nocap/f_nocap, compacted with the SoA) never
    OCCUPY max_blobs: the ordinary show keeps launching underneath the
    payoff's afterglow instead of going silent for PAYOFF_LIFE x
    burst_life (the measured pre-fix cliff on his crystal);
  - the tail ends exactly: after DROP_TAIL_S the launch rate is the
    ordinary show's own, and the tail clock is idle.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0
SHAPES = {"fireworks": (72 * 37, 37), "fireworks1d": (17, 1)}


def _run(coro):
    return asyncio.run(coro)


def _mod(effect_type):
    if effect_type == "fireworks":
        from fx.effects import fireworks as m
    else:
        from fx.effects import fireworks1d as m
    return m


def _spawn_name(effect_type):
    return "_spawn_burst" if effect_type == "fireworks" else "_spawn_firework"


def _life_arr(effect, effect_type):
    return effect.p_life if effect_type == "fireworks" else effect.f_life


class _Rig:
    """One effect on a headless virtual with an ordinary-launch log."""

    def __init__(self, host, virtual, effect, effect_type, clock):
        self.host, self.virtual, self.effect = host, virtual, effect
        self.effect_type, self.clock = effect_type, clock
        self.t = 0.0
        self.launches: list[float] = []   # t of every ordinary-sized launch
        self.payoff_launches: list[float] = []
        in_payoff = [False]
        orig_payoff = effect._payoff_burst_at

        def payoff(*a, _o=orig_payoff, **kw):
            in_payoff[0] = True
            try:
                _o(*a, **kw)
            finally:
                in_payoff[0] = False
        effect._payoff_burst_at = payoff
        name = _spawn_name(effect_type)
        orig = getattr(effect, name)

        def logged(*a, _o=orig, **kw):
            before = effect.n
            _o(*a, **kw)
            if effect.n > before:
                (self.payoff_launches if in_payoff[0]
                 else self.launches).append(self.t)
        setattr(effect, name, logged)

    def step(self, n_frames, beat_every_s=None):
        for i in range(n_frames):
            if beat_every_s and (round(self.t / DT) % int(round(beat_every_s / DT)) == 0):
                self.effect._beat_pending = True
            self.clock.advance(DT)
            self.t += DT
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)

    def launches_between(self, t0, t1):
        return sum(1 for s in self.launches if t0 < s <= t1)

    def drop(self, ramp_s=0.4):
        """Write the drop edge the way scene_response does and ramp it."""
        self.effect.update_config({"phase": "drop", "phase_progress": 0.0})
        n = int(ramp_s / DT)
        for i in range(1, n + 1):
            self.effect.update_config({"phase_progress": i / n})
            self.step(1)

    def lull(self, hold_s=1.0):
        self.effect.update_config({"phase": "lull", "phase_progress": 0.0})
        n = int(hold_s / DT)
        for i in range(1, n + 1):
            self.effect.update_config({"phase_progress": i / n})
            self.step(1)


_RIG_SEQ = [0]


async def _rig(tmp_path, effect_type, config):
    pixels, rows = SHAPES[effect_type]
    # a unique virtual id per rig: an effect's deactivate() stores a
    # particle-handoff snapshot under its virtual id, and a later test's
    # fresh effect on the SAME id would adopt the previous test's particles
    _RIG_SEQ[0] += 1
    vid = f"{effect_type}-rig{_RIG_SEQ[0]}"
    host = await headless.start_headless_host(
        str(tmp_path / effect_type), pixel_count=pixels, rows=rows,
        device_id=vid)
    virtual = host.virtuals.get(vid)
    clock_cm = headless.fake_clock()
    clock = clock_cm.__enter__()
    effect = headless.attach_effect(host, virtual, effect_type, config)
    rig = _Rig(host, virtual, effect, effect_type, clock)
    rig._clock_cm = clock_cm
    return rig


async def _teardown(rig):
    rig._clock_cm.__exit__(None, None, None)
    await rig.host.shutdown()


EFFECTS = ["fireworks", "fireworks1d"]


@pytest.mark.parametrize("effect_type", EFFECTS)
def test_tail_outlives_the_drop_phase_on_its_own_clock(tmp_path, effect_type):
    """The phase flag still resets at DROP_SETTLE_S; the tail keeps
    launching past that, easing out, and is idle again by DROP_TAIL_S."""
    mod = _mod(effect_type)
    assert mod.DROP_TAIL_S > mod.DROP_SETTLE_S

    async def main():
        rig = await _rig(tmp_path, effect_type,
                         {"spawn_rate": 0.0, "beat_burst": 0,
                          "spawn_audio": 0.0})
        try:
            rig.step(30)
            assert rig.launches == []           # spawn_rate 0: silent show
            rig.lull()
            t_mark = rig.t
            reset_at = None
            after = 0.0
            while after < mod.DROP_TAIL_S + 0.5:
                if after == 0.0:
                    rig.drop()
                else:
                    rig.step(1)
                after = rig.t - t_mark
                if reset_at is None and rig.effect._phase == "none":
                    reset_at = after
            # 1. phase clock untouched (one frame of granularity)
            assert reset_at == pytest.approx(mod.DROP_SETTLE_S, abs=2 * DT)
            # 2. launches continue AFTER the phase reset (the tail is not
            #    gated on the phase flag)
            assert rig.launches_between(
                t_mark + mod.DROP_SETTLE_S, t_mark + mod.DROP_TAIL_S) >= 2
            # 3. the tail lands its integral, DROP_TAIL_RATE*DROP_TAIL_S/2
            #    fireworks, to within accumulator granularity
            total = rig.launches_between(t_mark, t_mark + mod.DROP_TAIL_S)
            expect = mod.DROP_TAIL_RATE * mod.DROP_TAIL_S / 2.0
            assert abs(total - expect) <= 1.5
            # 4. front-loaded, easing: more in the first half than the second
            half = t_mark + mod.DROP_TAIL_S / 2
            assert rig.launches_between(t_mark, half) > rig.launches_between(
                half, t_mark + mod.DROP_TAIL_S)
            # 5. over: nothing after DROP_TAIL_S on a spawn_rate 0 scene,
            #    and the tail clock is idle
            assert rig.launches_between(
                t_mark + mod.DROP_TAIL_S, rig.t) == 0
            assert rig.effect._tail_t is None
            assert rig.effect._tail_rate == 0.0
            # the payoff itself still fired (rockets exploded)
            assert len(rig.payoff_launches) >= 1
        finally:
            await _teardown(rig)

    _run(main())


@pytest.mark.parametrize("effect_type", EFFECTS)
def test_tail_is_ordinary_fireworks_not_payoff_shape(tmp_path, effect_type):
    mod = _mod(effect_type)

    async def main():
        rig = await _rig(tmp_path, effect_type,
                         {"spawn_rate": 0.0, "beat_burst": 0,
                          "spawn_audio": 0.0, "burst_life": 1.0})
        try:
            rig.step(5)
            rig.drop()          # bare drop: no lull, no rockets — still a tail
            n_payoff_end = rig.effect.n
            rig.step(int(0.5 / DT))
            lives = _life_arr(rig.effect, effect_type)
            # the payoff's particles carry PAYOFF_LIFE-stretched lives; the
            # tail's are ordinary (burst_life x jitter <= 1.15)
            fresh = lives[n_payoff_end:rig.effect.n]
            assert fresh.size > 0
            assert (fresh <= 1.0 * 1.15 + 1e-6).all()
            assert rig.launches_between(0.0, rig.t) >= 2
            assert (lives[:n_payoff_end].max()
                    >= 1.0 * mod.PAYOFF_LIFE * 0.7 - 1e-6)
        finally:
            await _teardown(rig)

    _run(main())


@pytest.mark.parametrize("effect_type", EFFECTS)
def test_flare_burst_alone_never_starts_a_tail(tmp_path, effect_type):
    async def main():
        rig = await _rig(tmp_path, effect_type,
                         {"spawn_rate": 0.0, "beat_burst": 0,
                          "spawn_audio": 0.0})
        try:
            rig.step(5)
            rig.effect.update_config({"burst_rockets": 6})
            rig.step(int(3.0 / DT))
            assert len(rig.payoff_launches) >= 6   # the flare landed
            assert rig.launches == []              # no ordinary launches
            assert rig.effect._tail_t is None
        finally:
            await _teardown(rig)

    _run(main())


@pytest.mark.parametrize("effect_type", EFFECTS)
def test_uncapped_particles_never_occupy_the_density_cap(tmp_path, effect_type):
    """The ordinary show keeps launching underneath a payoff that is far
    over max_blobs — the measured pre-fix cliff (zero ordinary launches
    for PAYOFF_LIFE x burst_life) is gone. Same for a flare burst."""
    mod = _mod(effect_type)
    small_cap = 24 if effect_type == "fireworks" else 4  # schema floors: 20 / 4

    async def main():
        rig = await _rig(tmp_path, effect_type,
                         {"spawn_rate": 6.0, "beat_burst": 0,
                          "spawn_audio": 0.0, "max_blobs": small_cap,
                          "burst_life": 2.0})
        try:
            rig.step(int(1.0 / DT))
            rig.lull()
            t_mark = rig.t
            rig.drop()
            n_over = rig.effect.n
            assert n_over > small_cap            # payoff sits way over the cap
            nocap = (rig.effect.p_nocap if effect_type == "fireworks"
                     else rig.effect.f_nocap)
            assert nocap[:n_over].sum() >= n_over - small_cap
            # ordinary launches keep landing in the very first 0.5 s while
            # the payoff is all still alive (life 2.0 x PAYOFF_LIFE)
            rig.step(int(0.5 / DT))
            assert rig.launches_between(t_mark, rig.t) >= 2
            # past the tail window the ordinary show is its own self again:
            # still launching, still cap-bound (one firework per ~burst_life
            # at this cap, so look across a whole 2.5 s window)
            rig.step(int((mod.DROP_TAIL_S + 2.5) / DT))
            assert rig.launches_between(rig.t - 2.5, rig.t) >= 1
            # compaction keeps the flag aligned: every live nocap particle is
            # still one of the payoff's (PAYOFF_LIFE-stretched life) or the
            # tail's / rockets', never an ordinary launch's
            lives = _life_arr(rig.effect, effect_type)
            n = rig.effect.n
            assert n > 0
            assert (nocap[:n] == 0.0).sum() <= small_cap
            # an ordinary flare burst over the cap behaves the same way:
            # pre-fix its PAYOFF_LIFE x burst_life (~2.7 s here) particles
            # held the cap full and blocked every ordinary launch for that
            # long; now one lands within the ordinary show's own ~2.3 s
            # per-firework cadence at this cap
            t0 = rig.t
            rig.effect.update_config({"burst_rockets": 6})
            rig.step(int(2.5 / DT))
            assert rig.launches_between(t0, rig.t) >= 1
        finally:
            await _teardown(rig)

    _run(main())


def test_both_effects_agree_on_the_tail_constants():
    """He sees the crystal and the strips together — the tail must read
    the same on both: same rate, same ease-out duration, both outliving
    the (also shared) drop settle window."""
    from fx.effects import fireworks as a
    from fx.effects import fireworks1d as b
    assert a.DROP_TAIL_RATE == b.DROP_TAIL_RATE
    assert a.DROP_TAIL_S == b.DROP_TAIL_S
    assert a.DROP_SETTLE_S == b.DROP_SETTLE_S
    assert a.DROP_TAIL_S > a.DROP_SETTLE_S
