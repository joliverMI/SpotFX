"""THE SEARCHING LULL and THE DROP THAT FOLLOWS THE MUSIC (fx/effects/
fish.py, the 2026-10-08 LULL block; fish-lull plan phases 2-3).

The Admiral, verbatim: "have all the fish leave over time except for one,
so one is left at the half way mark. then have that last fish move slowly
and look like it's searching. have it move to one side, pause, then move to
the other. then on the drop, all the missing fish come back in the rush we
currently have. also, make the length of the drop and how fast the fish
swirl depend on the inensity of the music so that lower intensity songs
don't have such a prolonged rush." This REVERSES his own 2026-08-28 "no
lone fish" ruling (approved 2026-10-08); the old clock is still the lull
when the hand-off hook tells it `lull_keep = 0`, and that is proven here
bit for bit against the pinned pre-change module.

Everything runs on the real vendored render pipeline (fx.headless dummy
Matrix host at his crystal-mapper's 72x37 shape, audio silenced). The RED
CONTROL is the pre-change fish.py loaded out of git at PRE_CHANGE_REF and
registered beside the current one — its lull leaves NOTHING at the half, so
the instrument that sees one keeper here can see the difference.
"""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from fx.effects import lull_handoff as lh  # noqa: E402

# the commit this change was built on: the pre-change fish, pinned (never a
# moving ref — scripts/check_fish_camera.py records what a moving reference
# silently does to an instrument)
PRE_CHANGE_REF = "17f263223b8334024aef5b99c4090b35c3e448cf"

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

HIS = {
    "particle_count": 6, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.15, "tether_scatter": 0.0,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "reverse": False, "camera_follow": 0.8,
}


def _run(coro):
    return asyncio.run(coro)


class _Room:
    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm
        self.frame = None

    def step(self, frames=1, watch=None):
        for _ in range(frames):
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)
                self.frame = np.array(f, copy=True)
            if watch is not None:
                watch()

    def charge(self, seconds=4.0):
        eff = self.effect
        eff.update_config({"phase": "charge", "phase_progress": 0.0})
        frames = int(seconds / DT)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if i % 12 == 0:
                eff._beat_pending = True
            self.step(1)

    def lull(self, gap_s, told=None, watch=None):
        """A lull as SpotFX drives it: the arm write (with `told` hook keys
        when given), progress ramped over 90% of the gap, then the hang."""
        eff = self.effect
        arm = {"phase": "lull", "phase_progress": 0.0}
        if told is not None:
            arm.update(told)
        eff.update_config(arm)
        ramp = max(int(0.9 * gap_s / DT), 1)
        total = int(gap_s / DT)
        for i in range(1, total + 1):
            if i <= ramp:
                eff.update_config({"phase_progress": i / ramp})
            self.step(1, watch)

    def drop(self, seconds, told=None, watch=None):
        eff = self.effect
        arm = {"phase": "drop", "phase_progress": 0.0}
        if told is not None:
            arm.update(told)
        eff.update_config(arm)
        ramp = int(0.4 / DT)
        for i in range(1, int(seconds / DT) + 1):
            if i <= ramp:
                eff.update_config({"phase_progress": i / ramp})
            self.step(1, watch)


async def _room(tmp_path, tag, config=None, seed=5, effect_type="fish"):
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, effect_type,
                                 dict(config or HIS))
    eff._rng = np.random.default_rng(seed)
    return _Room(host, virtual, clock, eff, cm)


async def _close(room):
    room._cm.__exit__(None, None, None)
    await room.host.shutdown()


def _load_pre_change(name="fish_prelull"):
    """Register the PINNED pre-change fish.py beside the current one (an
    Effect registers under its module's last name segment)."""
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{PRE_CHANGE_REF}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except Exception as exc:                            # noqa: BLE001
        pytest.skip(f"cannot read {PRE_CHANGE_REF} out of git: {exc}")
    # it must genuinely predate the change — a loud failure, never a skip
    assert "lull_handoff" not in src and "LULL_GONE_AT" in src, (
        f"the pinned {PRE_CHANGE_REF} is not the pre-change fish")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


def _screen(eff, idx):
    px = eff.cx + eff.p_x[idx] * eff.sx - eff.cam_px
    py = eff.cy + eff.p_y[idx] * eff.sy - eff.cam_py
    return px, py


def _on_panel(eff):
    n = eff.n
    px, py = _screen(eff, np.arange(n))
    m = eff._body_len_px()
    return np.flatnonzero((px >= -m) & (px <= eff.r_width - 1 + m)
                          & (py >= -m) & (py <= eff.r_height - 1 + m))


def _lull_trace(room, gap_s, told):
    """Drive a lull and record, every frame: seconds in, fish on the panel,
    keepers, non-keepers on the panel, the brightest pixel, the wake, the
    window origin, and the keepers' search stage."""
    eff = room.effect
    rec = []

    def watch():
        n = eff.n
        keepers = np.flatnonzero(eff.p_mode[:n] == 5)
        vis = _on_panel(eff)
        others = np.setdiff1d(vis, keepers)
        st = eff._lull_state or {}
        search = st.get("search") or {}
        kx = (_screen(eff, keepers)[0].copy() if keepers.size
              else np.zeros(0))
        rec.append({
            "t": eff._phase_t, "vis": vis.size, "keep": keepers.size,
            "others": others.size,
            "lit": float(np.asarray(eff.matrix, dtype=np.float32).max()),
            "wake": float(eff.wake.max()),
            "cam": float(np.hypot(eff.cam_px, eff.cam_py)),
            "stage": search.get("stage"), "kx": kx,
            "kspd": eff.p_spd[keepers].copy(),
            "bright": eff.p_bright[keepers].copy(),
        })
    room.lull(gap_s, told=told, watch=watch)
    return rec


# ── the searching lull ──────────────────────────────────────────────────

@pytest.mark.parametrize("gap_s", [2.0, 6.0, 12.0])
@pytest.mark.parametrize("seed", [3, 11])
def test_one_fish_is_left_at_the_half_and_stays_until_the_drop(
        tmp_path, gap_s, seed):
    """His words: "all the fish leave over time except for one, so one is
    left at the half way mark". Told the lull's length (as SpotFX always
    tells it), the half is a moment in seconds."""
    async def main():
        room = await _room(tmp_path, f"half{seed}", seed=seed)
        room.step(240)
        room.charge()
        rec = _lull_trace(room, gap_s, lh.keys_for(1, "", gap_s))
        await _close(room)
        return rec
    rec = _run(main())
    half = gap_s / 2.0
    start = rec[0]
    assert start["vis"] > 1, "the lull must start with a school in it"
    after = [r for r in rec if r["t"] >= half]
    assert after, "the lull never reached its half"
    # exactly one fish, and only it, from the half to the drop
    assert all(r["keep"] == 1 for r in rec), "one keeper throughout"
    assert all(r["others"] == 0 for r in after), (
        "every other fish is gone by the half",
        max(r["others"] for r in after))
    assert all(r["vis"] == 1 for r in after), "the keeper stays on screen"
    # "over time": the others leave across the first half, not all at once
    counts = [r["vis"] for r in rec if r["t"] < half]
    assert len(set(counts)) >= 3, ("the shoal must thin out over time",
                                   sorted(set(counts)))
    # and the lull is never dark — the keeper and its wake keep it lit
    assert min(r["lit"] for r in rec) > 0.0, "the lull went dark"
    assert all(r["wake"] > 0.0 for r in after), "the keeper's wake died"


def test_the_keeper_searches_go_pause_go_slowly(tmp_path):
    """"move slowly and look like it's searching. have it move to one side,
    pause, then move to the other" — on a 6 s lull: at least one leg, one
    pause, and a leg the OTHER way; slow (about search_speed x cruise) on a
    leg and a hover in a pause; its head looks about in the pause."""
    async def main():
        room = await _room(tmp_path, "search", seed=3)
        room.step(240)
        room.charge()
        looks = []
        eff = room.effect
        orig = eff._keep_targets

        def spy(*a, _o=orig):
            _o(*a)
            if eff._keep is not None:
                looks.append(float(np.max(np.abs(eff._keep["look"]))))
        eff._keep_targets = spy
        rec = _lull_trace(room, 6.0, lh.keys_for(1, "", 6.0))
        cruise = eff.cruise_px
        await _close(room)
        return rec, looks, cruise
    rec, looks, cruise = _run(main())
    stages = [r["stage"] for r in rec if r["stage"] is not None]
    runs = [s for i, s in enumerate(stages) if i == 0 or stages[i - 1] != s]
    assert runs[:3] == ["go", "pause", "go"], runs
    # the two legs go opposite ways
    legs = []
    cur, start_x = None, None
    for r in rec:
        if r["stage"] != cur:
            if cur == "go" and start_x is not None:
                legs.append(prev_x - start_x)
            cur = r["stage"]
            start_x = r["kx"][0] if r["kx"].size else None
        prev_x = r["kx"][0] if r["kx"].size else prev_x
    if cur == "go" and start_x is not None:
        legs.append(prev_x - start_x)
    assert len(legs) >= 2 and legs[0] * legs[1] < 0, (
        "the second leg must head to the OTHER side", legs)
    # slow: never faster than cruise once searching, a hover in a pause
    searching = [r for r in rec if r["stage"] == "go"]
    assert max(float(r["kspd"].max()) for r in searching) <= cruise * 0.6
    pausing = [r for r in rec if r["stage"] == "pause"]
    assert min(float(r["kspd"].min()) for r in pausing) <= (
        cruise * FX.SEARCH_PAUSE_X * 2.5)
    # it looks about while it pauses
    assert max(looks) > FX.SEARCH_LOOK_SWING * 0.5
    # never fades: full brightness the whole time (audio silenced)
    b = np.concatenate([r["bright"] for r in rec])
    assert b.min() >= b.max() * 0.99


def test_the_window_does_not_follow_the_keeper(tmp_path):
    """camera_follow 0.8: if the window followed the searching fish it
    would stay centred and the water would slide instead. The window eases
    home once the school breaks and sits at rest while the keeper
    searches."""
    async def main():
        room = await _room(tmp_path, "cam", seed=11)
        room.step(240)
        room.charge()
        away = float(np.hypot(room.effect.cam_px, room.effect.cam_py))
        rec = _lull_trace(room, 12.0, lh.keys_for(1, "", 12.0))
        await _close(room)
        return away, rec
    away, rec = _run(main())
    assert away > 2.0, ("the charge must have moved the window", away)
    searching = [r for r in rec if r["stage"] is not None]
    assert searching
    assert max(r["cam"] for r in searching[len(searching) // 2:]) == 0.0, (
        "the window must be back at rest exactly while the keeper searches")
    span = np.ptp(np.concatenate([r["kx"] for r in searching]))
    assert span > 10.0, ("the keeper must visibly travel on screen", span)


@pytest.mark.parametrize("nxt", ["", "fireworks"])
def test_three_keepers_hold_a_spaced_group_for_a_fireworks_drop(
        tmp_path, nxt):
    """`lull_keep = 3` — what a drop landing on Fireworks will ask for (the
    drop-scene-variety melds). Three fish are left at the half, spaced
    apart, and search together; told the drop lands on another effect they
    space further apart, so the adopting effect gets three distinct
    origins (TRANSITION_ADOPTERS read the live snapshot)."""
    async def main():
        room = await _room(tmp_path, f"three{nxt or 'x'}", seed=3)
        room.step(240)
        room.charge()
        eff = room.effect
        gaps = []
        rec = _lull_trace(room, 6.0, lh.keys_for(3, nxt, 6.0))
        # keep searching past the trace's end (a drop that comes late) and
        # watch the group's tightest pair the whole way
        def watch():
            n = eff.n
            keepers = np.flatnonzero(eff.p_mode[:n] == 5)
            px, py = _screen(eff, keepers)
            d = np.hypot(px[:, None] - px[None, :],
                         py[:, None] - py[None, :])
            np.fill_diagonal(d, np.inf)
            gaps.append(float(d.min()))
        room.step(int(6.0 / DT), watch)
        spacing = eff._lull_state["spacing_px"]
        snap = eff._handoff_snapshot()
        await _close(room)
        return rec, np.array(gaps), spacing, snap
    rec, gaps, spacing, snap = _run(main())
    after = [r for r in rec if r["t"] >= 3.0]
    assert all(r["keep"] == 3 and r["others"] == 0 for r in after)
    assert all(r["vis"] == 3 for r in after), "all three stay on screen"
    assert np.median(gaps) >= 0.6 * spacing, (
        "the keepers must hold apart, not clump", np.median(gaps), spacing)
    assert gaps.min() >= 0.35 * spacing, (gaps.min(), spacing)
    # the snapshot an adopting effect reads holds exactly the three keepers
    assert len(snap["px"]) == 3


def test_a_fireworks_drop_spaces_the_keepers_further_apart(tmp_path):
    """Told the drop lands on another effect, the group's spacing widens
    (KEEP_SPACING_NEXT_BODIES, within the pond) — distinct launch origins."""
    async def spacing(nxt):
        room = await _room(tmp_path, f"sp{nxt or 'x'}", seed=3)
        room.step(240)
        room.charge()
        room.lull(4.0, told=lh.keys_for(3, nxt, 4.0))
        out = room.effect._lull_state["spacing_px"]
        await _close(room)
        return out
    assert _run(spacing("fireworks")) > _run(spacing("")) * 1.3


def test_a_lull_with_fewer_fish_than_it_keeps_calls_the_rest_in(tmp_path):
    """No charge first and one ordinary fish: told to keep three, the lull
    calls two more in from off-panel — they swim in and fade up like any
    arrival, never appear from nothing — and three search at the half."""
    async def main():
        room = await _room(tmp_path, "short",
                           dict(HIS, particle_count=1), seed=5)
        room.step(240)
        assert room.effect.n == 1
        rec = _lull_trace(room, 6.0, lh.keys_for(3, "", 6.0))
        await _close(room)
        return rec
    rec = _run(main())
    assert rec[0]["keep"] == 3
    b = np.sort(rec[0]["bright"])
    assert b[:2].max() < 0.1 * b[-1], (
        "the shortfall arrives fading up, never already lit", b)
    assert all(r["vis"] == 3 for r in rec if r["t"] >= 3.0)


def test_an_untold_lull_keeps_one_at_half_progress(tmp_path):
    """Not told the lull's length (an older SpotFX, a hand scrub), the keep
    mark is phase_progress 0.5 — the effect's own default, keep 1."""
    async def main():
        room = await _room(tmp_path, "untold", seed=11)
        room.step(240)
        room.charge()
        eff = room.effect
        out = []

        def watch():
            n = eff.n
            out.append((eff.phase_progress, int(np.count_nonzero(
                eff.p_mode[:n] == 5)), _on_panel(eff).size))
        room.lull(4.0, told=None, watch=watch)
        await _close(room)
        return out
    out = _run(main())
    past = [o for o in out if o[0] >= 0.5]
    assert past and all(o[1] == 1 and o[2] == 1 for o in past)


def test_the_drop_brings_the_keeper_back_into_the_rush(tmp_path):
    """"then on the drop, all the missing fish come back in the rush we
    currently have" — the keeper rejoins the population at the drop instant
    (mode 0, ordinary), the rush pours in, and the drop settles to the
    blob count as before."""
    async def main():
        room = await _room(tmp_path, "dropback", seed=3)
        room.step(240)
        room.charge()
        room.lull(4.0, told=lh.keys_for(1, "", 4.0))
        eff = room.effect
        keeper = int(np.flatnonzero(eff.p_mode[:eff.n] == 5)[0])
        kx = float(eff.p_x[keeper])
        peak = [0]

        def watch():
            peak[0] = max(peak[0], eff.n)
        eff.update_config({"phase": "drop", "phase_progress": 0.0})
        room.step(1, watch)
        modes = eff.p_mode[:eff.n].copy()
        rejoined = np.flatnonzero(np.isclose(eff.p_x[:eff.n], kx, atol=0.2)
                                  & (modes < 2))
        room.step(int((FX.DROP_SETTLE_S + 0.6) / DT), watch)
        out = (int(np.count_nonzero(modes == 5)), rejoined.size, peak[0],
               eff._phase, int(np.count_nonzero(
                   (eff.p_mode[:eff.n] < 2) & (eff.p_nocap[:eff.n] == 0))),
               int(eff._config["particle_count"]))
        await _close(room)
        return out
    keepers_left, rejoined, peak, phase, swimming, want = _run(main())
    assert keepers_left == 0, "no keeper survives the drop's first frame"
    assert rejoined >= 1, "the keeper itself rejoins the shoal"
    assert peak > 20, ("the rush must pour in", peak)
    assert phase == "none" and swimming == want


# ── keep = 0 is the old lull, bit for bit; the pre-change module is the red
#    control ─────────────────────────────────────────────────────────────

def test_the_pre_change_lull_leaves_nothing_at_the_half(tmp_path):
    """RED CONTROL: the pinned pre-change fish empties the panel by the
    third, so the instrument above (one keeper at the half) can see the
    change — it is not measuring something both versions do."""
    name = _load_pre_change()

    async def main():
        room = await _room(tmp_path, "red", seed=3, effect_type=name)
        room.step(240)
        room.charge()
        rec = []
        eff = room.effect

        def watch():
            rec.append((eff._phase_t, _on_panel(eff).size))
        room.lull(6.0, told=None, watch=watch)
        await _close(room)
        return rec
    rec = _run(main())
    assert all(v == 0 for t, v in rec if t >= 3.0), (
        "the pre-change lull is supposed to leave nothing at the half")


def test_keep_zero_and_an_untold_drop_are_the_pre_change_fish_bit_for_bit(
        tmp_path):
    """Told `lull_keep = 0`, the lull is his 2026-08-28 clock; an untold
    drop is the fixed drop. Together they must render EXACTLY what the
    pinned pre-change module renders, frame for frame — the hook adds a
    behaviour, it never moves the old one."""
    name = _load_pre_change()

    async def run(effect_type, told):
        room = await _room(tmp_path, f"bit{effect_type[-4:]}", seed=7,
                           effect_type=effect_type)
        frames = []

        def watch():
            frames.append(room.frame.copy())
        room.step(240, watch)
        room.charge()
        room.lull(5.0, told=told, watch=watch)
        room.drop(5.0, watch=watch)
        room.step(120, watch)
        await _close(room)
        return frames
    old = _run(run(name, None))
    new = _run(run("fish", {lh.KEEP_KEY: 0}))
    assert len(old) == len(new)
    diff = [i for i, (a, b) in enumerate(zip(old, new))
            if not np.array_equal(a, b)]
    assert not diff, f"frames differ from the pre-change fish at {diff[:5]}"


# ── the drop follows the music ───────────────────────────────────────────

def _drop_trace(tmp_path, tag, told, seed=4):
    async def main():
        room = await _room(tmp_path, tag, seed=seed)
        room.step(240)
        room.charge()
        room.lull(3.0, told=lh.keys_for(1, "", 3.0))
        eff = room.effect
        spawned = {}
        orig = eff._spawn_rush

        def spy(count, speed_x=None, _o=orig):
            base = eff.n
            _o(count, speed_x=speed_x)
            spawned["spd"] = eff.p_spd[base:eff.n].copy()
        eff._spawn_rush = spy
        rec = []

        def watch():
            rec.append((eff._phase, eff._speed_scale, eff._rush_swirl))
        room.drop(7.0, told=told, watch=watch)
        await _close(room)
        settle = next(i for i, r in enumerate(rec) if r[0] == "none") * DT
        return settle, max(r[1] for r in rec), spawned["spd"]
    return _run(main())


def test_a_quiet_song_gets_a_shorter_gentler_rush(tmp_path):
    base = _drop_trace(tmp_path, "d0", None)
    out = {i: _drop_trace(tmp_path, f"d{int(i * 100)}", lh.drop_keys_for(i))
           for i in (0.3, 0.75, 1.0)}
    # the settle horizon scales with drop_scale
    for i, (settle, boost, _spd) in out.items():
        scale = lh.drop_scale(i)
        assert settle == pytest.approx(FX.DROP_SETTLE_S * scale, abs=2 * DT)
        assert boost == pytest.approx(1.0 + FX.DROP_BOOST * scale, rel=0.02)
    # 0.75 is exactly the old drop; quieter is shorter, a marked track longer
    assert out[0.75][0] == pytest.approx(base[0], abs=DT)
    assert out[0.3][0] < out[0.75][0] < out[1.0][0]
    assert out[0.3][0] == pytest.approx(2.69, abs=0.05)
    # the rush comes in slower on a quiet song
    assert np.median(out[0.3][2]) < np.median(base[2])


def test_an_untold_drop_is_the_fixed_drop(tmp_path):
    settle, boost, _spd = _drop_trace(tmp_path, "dn", None)
    assert settle == pytest.approx(FX.DROP_SETTLE_S, abs=2 * DT)
    assert boost == pytest.approx(1.0 + FX.DROP_BOOST, rel=0.02)


def test_the_drop_scale_floor_is_his_knob(tmp_path):
    async def main():
        room = await _room(tmp_path, "floor",
                           dict(HIS, drop_scale_min=0.8), seed=4)
        room.step(60)
        room.drop(0.1, told=lh.drop_keys_for(0.01))
        scale = room.effect._drop_state["scale"]
        await _close(room)
        return scale
    assert _run(main()) == pytest.approx(lh.drop_scale(0.01, 0.8))


def test_a_told_intensity_is_forgotten_with_the_drop(tmp_path):
    """The self-reset clears drop_intensity, so a later drop nobody told
    runs the fixed drop rather than inheriting this one's scale."""
    async def main():
        room = await _room(tmp_path, "forget", seed=4)
        room.step(60)
        room.drop(5.0, told=lh.drop_keys_for(0.3))
        val = room.effect._config.get(lh.DROP_KEY)
        await _close(room)
        return val
    assert _run(main()) == 0.0


def test_the_search_params_are_registered_for_sonic():
    from fx import device_model
    params = device_model.effect_params("fish")
    schema = {str(k): k for k in FX.Fish2d.CONFIG_SCHEMA.schema}
    for name in ("search_speed", "search_pause_s", "search_reach",
                 "drop_scale_min"):
        assert name in params, name
        assert name in schema, name
        assert params[name]["default"] == schema[name].default(), name


def test_three_keepers_become_three_firework_bursts(tmp_path):
    """THE FISH -> FIREWORKS MELD, end to end on the real effects: a lull
    told `lull_keep = 3, lull_next = "fireworks"` leaves three spaced
    keepers, and Fireworks' own adopt path (fireworks._adopt_handoff, the
    one a scene change at the drop runs on its first frame) launches one
    burst from EACH keeper's position — three distinct origins, where the
    keepers are. Nothing here is new machinery on the Fireworks side: the
    hook's whole job is to leave the right pieces in the right places."""
    async def main():
        room = await _room(tmp_path, "meld", seed=3)
        room.step(240)
        room.charge()
        room.lull(4.0, told=lh.keys_for(3, "fireworks", 4.0))
        fish = room.effect
        keepers = np.flatnonzero(fish.p_mode[:fish.n] == 5)
        kx, ky = _screen(fish, keepers)
        snap = fish._handoff_snapshot()
        await _close(room)

        fw_room = await _room(tmp_path, "meldfw", seed=3,
                              effect_type="fireworks",
                              config={"reverse": False})
        fw = fw_room.effect
        fw_room.step(1)
        fw.n = 0
        fw._adopt_handoff(snap=snap, allow_hold=False)
        ox = fw.cx + fw.p_x[:fw.n] * fw.sx
        oy = fw.cy + fw.p_y[:fw.n] * fw.sy
        origins = {(round(float(x), 3), round(float(y), 3))
                   for x, y in zip(ox, oy)}
        await _close(fw_room)
        return np.stack([kx, ky], 1), origins
    keepers, origins = _run(main())
    assert len(keepers) == 3
    assert len(origins) == 3, ("one burst per keeper", origins)
    for o in origins:
        d = np.hypot(keepers[:, 0] - o[0], keepers[:, 1] - o[1]).min()
        assert d < 1.0, ("each burst launches from a keeper", o, keepers)
