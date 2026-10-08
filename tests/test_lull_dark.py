"""THE LULL'S DARK POINT — dark for half the lull, never longer than the
room's lull_dark_max_s (the Admiral, 2026-10-07: "if we have a 20 second
lull ... Now it would be 17 seconds of expansion and 3 seconds of dark.
Pulse should match, so it's only pitch black for 3 seconds").

What is proven here, each on the real code it names:

- THE RULE (fx/effects/lull_dark.py, the one definition): 20 s -> 17 + 3,
  4 s -> 2 + 2 (short lulls keep half and half), the cap is the setting.
- THE LEGACY PATH: a write that does not carry SpotFX's lull timing reads
  exactly the progress fractions each effect used before the rule.
- THE ARM WRITE (spectra scene_response._drive_phase): only a lull, and
  only a LULL_DARK_EFFECTS virtual, is told; the cap comes from the room.
- THE THREE EFFECTS on the real render pipeline (fx.headless, the real
  ResponseEngine + FacadeExecutor, one clock), through a 20 s lull that
  follows a completed charge: Black Hole's real crystal cells, Squiggles'
  CRT line and Pulse's single light all go dark at 17 s and stay dark for
  the last 3 s — not at the old half-way point. A completed charge first is
  the ordinary sequence, and the case that once started a lull's
  phase_progress at 1.0 (fixed at its root for every phase effect —
  tests/test_lull_after_charge.py).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, facade, headless  # noqa: E402
from fx.effects import blackhole as bh  # noqa: E402
from fx.effects import lull_dark  # noqa: E402
from fx.effects import pulse as pulse_mod  # noqa: E402
from fx.effects import squiggles as sq  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response  # noqa: E402

FPS = 60
DT = 1.0 / FPS


# ── the rule ────────────────────────────────────────────────────────────────

def test_a_twenty_second_lull_is_seventeen_of_approach_and_three_dark():
    assert lull_dark.dark_hold_s(20.0, 3.0) == pytest.approx(3.0)
    assert lull_dark.dark_start_s(20.0, 3.0) == pytest.approx(17.0)


def test_a_short_lull_keeps_half_and_half():
    assert lull_dark.dark_hold_s(4.0, 3.0) == pytest.approx(2.0)
    assert lull_dark.dark_start_s(4.0, 3.0) == pytest.approx(2.0)
    # the cap only bites past twice itself
    assert lull_dark.dark_start_s(6.0, 3.0) == pytest.approx(3.0)
    assert lull_dark.dark_start_s(6.2, 3.0) == pytest.approx(3.2)


def test_the_cap_is_the_setting():
    assert lull_dark.dark_start_s(20.0, 5.0) == pytest.approx(15.0)
    assert lull_dark.dark_start_s(20.0, 0.0) == pytest.approx(20.0)
    assert lull_dark.dark_start_s(20.0, 30.0) == pytest.approx(10.0)
    assert rc.RoomControlState().lull_dark_max_s == 3.0
    assert lull_dark.DEFAULT_MAX_DARK_S == 3.0


def test_timing_runs_on_the_effects_own_clock_once_told():
    cfg = lull_dark.keys_for(20.0, 18.0, 3.0)
    assert cfg == {lull_dark.RAMP_KEY: 18.0, lull_dark.DARK_KEY: 17.0}
    # progress is deliberately ignored once told: the clock rules, because
    # progress sits at 1.0 through the hang (see the very-long-lull test)
    for p in (0.0, 0.5, 1.0):
        early = lull_dark.lull_timing(cfg, p, 16.9, 0.5)
        assert not early.dark and early.approach == pytest.approx(16.9 / 17)
        late = lull_dark.lull_timing(cfg, p, 17.0, 0.5)
        assert late.dark and late.approach == 1.0 and late.after == 0.0
    assert lull_dark.lull_timing(cfg, 1.0, 17.5, 0.5).after == pytest.approx(0.5)
    assert lull_dark.lull_timing(cfg, 1.0, 19.0, 0.5).after == 1.0


def test_a_very_long_lull_finds_its_dark_point_inside_the_hang():
    """A 40 s lull's ramp ends at 36 s but its dark point is 37 s: only the
    effect's clock can find a point where progress no longer moves."""
    cfg = lull_dark.keys_for(40.0, 36.0, 3.0)
    assert not lull_dark.lull_timing(cfg, 1.0, 36.5, 0.5).dark
    t = lull_dark.lull_timing(cfg, 1.0, 37.0, 0.5)
    assert t.dark and t.after == 1.0


@pytest.mark.parametrize("legacy", [bh.LULL_FILL_PROGRESS, sq.CRT_SPLIT,
                                    pulse_mod.LULL_LEGACY_DARK_AT])
def test_untold_writes_keep_each_effects_old_progress_fraction(legacy):
    for p in np.linspace(0.0, 1.0, 41):
        t = lull_dark.lull_timing({}, float(p), 99.0, legacy)
        assert t.approach == pytest.approx(min(p / legacy, 1.0))
        assert t.dark == (p >= legacy)
        if legacy < 1.0 and p >= legacy:
            assert t.after == pytest.approx((p - legacy) / (1.0 - legacy))


def test_the_three_effects_and_only_them_are_opted_in():
    assert device_model.LULL_DARK_EFFECTS == {"blackhole", "squiggles", "pulse"}
    assert device_model.LULL_DARK_EFFECTS <= device_model.PHASE_EFFECTS
    for mod, cls in ((bh, "Blackhole2d"), (sq, "Squiggles2d"),
                     (pulse_mod, None)):
        klass = (getattr(mod, cls) if cls else next(
            v for v in vars(mod).values()
            if getattr(v, "NAME", None) == "Pulse"))
        keys = {str(k) for k in klass.CONFIG_SCHEMA.schema}
        assert set(lull_dark.KEYS) <= keys, mod.__name__


# ── the arm write ─────────────────────────────────────────────────────────

def test_the_arm_keys_follow_the_real_gap():
    keys = scene_response._lull_dark_keys(
        scene_response._phase_ramp_ms("lull", 20_000), 20_000, 3.0)
    assert keys == {lull_dark.RAMP_KEY: 18.0, lull_dark.DARK_KEY: 17.0}
    short = scene_response._lull_dark_keys(
        scene_response._phase_ramp_ms("lull", 4_000), 4_000, 3.0)
    assert short[lull_dark.DARK_KEY] == pytest.approx(2.0)
    # gap unknowable: the flat ramp is the whole lull, dark at half of it
    flat = scene_response._lull_dark_keys(
        scene_response._phase_ramp_ms("lull", None), None, 3.0)
    assert flat == {lull_dark.RAMP_KEY: 2.5, lull_dark.DARK_KEY: 1.25}


class _Exec:
    def __init__(self):
        self.jumps, self.glides = [], []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        self.glides.append((vid, et, dict(params), ms))


def _responder(effects, max_dark=3.0):
    from types import SimpleNamespace
    ex = _Exec()
    conductor = SimpleNamespace(virtuals={
        vid: SimpleNamespace(effect_type=et) for vid, et in effects.items()})
    eng = scene_response.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(lull_dark_max_s=max_dark))
    return eng, ex


def test_only_a_lull_and_only_a_lull_dark_effect_is_told():
    eng, ex = _responder({"bh": "blackhole", "orb": "orbits", "p": "pulse",
                          "sq": "squiggles", "bh1": "blackhole1d"})
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=20_000))
    told = {vid: p for vid, _et, p in ex.jumps}
    for vid in ("bh", "p", "sq"):
        assert told[vid][lull_dark.DARK_KEY] == pytest.approx(17.0)
        assert told[vid][lull_dark.RAMP_KEY] == pytest.approx(18.0)
    for vid in ("orb", "bh1"):
        # no lull-dark keys (orbits is told the lull HAND-OFF keys since the
        # fireworks melds, a different hook — fx/effects/lull_handoff.py)
        assert not {lull_dark.DARK_KEY, lull_dark.RAMP_KEY} & set(told[vid])
        assert told[vid]["phase"] == "lull" and told[vid]["phase_progress"] == 0.0
    assert told["bh1"] == {"phase": "lull", "phase_progress": 0.0}
    assert rec["lull_dark_s"] == pytest.approx(17.0)

    eng, ex = _responder({"bh": "blackhole"})
    rec = asyncio.run(eng._drive_phase("charge", gap_ms=20_000))
    assert ex.jumps[0][2] == {"phase": "charge", "phase_progress": 0.0}
    assert "lull_dark_s" not in rec


def test_the_cap_comes_from_the_room():
    eng, ex = _responder({"bh": "blackhole"}, max_dark=5.0)
    asyncio.run(eng._drive_phase("lull", gap_ms=20_000))
    assert ex.jumps[0][2][lull_dark.DARK_KEY] == pytest.approx(15.0)


def test_an_unreadable_room_reads_as_the_default_cap():
    eng, ex = _responder({"bh": "blackhole"})

    def boom():
        raise RuntimeError("room file unreadable")

    eng._room_controls = boom
    asyncio.run(eng._drive_phase("lull", gap_ms=20_000))
    assert ex.jumps[0][2][lull_dark.DARK_KEY] == pytest.approx(17.0)


# ── the three effects, on the real render pipeline ─────────────────────────

BH_V, SQ_V, PULSE_V = "bh-v", "sq-v", "pulse-v"
COLS, ROWS = 72, 37
BH_CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "horizon_audio": 0.3, "base_speed": 2.0, "accel": 5.0, "spawn_rate": 30.0,
    "beat_burst": 0, "spawn_audio": 1.5, "speed_audio": 2.0,
    "max_blobs": 50, "edge_speed": 0.2, "horizon_hold": 2.8,
}
SQ_CFG = {"spawn_rate": 6.0, "max_blobs": 24, "gradient": "#ffffff"}


def _real_mask():
    prof = json.loads((Path(__file__).resolve().parent.parent
                       / "storage/device_profiles/crystal-mapper.json")
                      .read_text(encoding="utf-8"))
    mask, v = [], False
    for run in prof["mask_rle"]:
        mask.extend([v] * run)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


def _config(config_dir):
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    shapes = ((BH_V, COLS * ROWS, ROWS), (SQ_V, COLS * ROWS, ROWS),
              (PULSE_V, 1, 1))
    devices = [{"id": f"{vid}-dev", "type": "dummy",
                "config": {"name": f"{vid}-dev", "pixel_count": n}}
               for vid, n, _rows in shapes]
    virtuals = [{"id": vid, "is_device": False, "auto_generated": False,
                 "config": {"name": vid, "mapping": "span", "rows": rows},
                 "segments": [[f"{vid}-dev", 0, n - 1, False]]}
                for vid, n, rows in shapes]
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


def _run_the_room(tmp_path, lull_gap_ms):
    """A completed charge, then a lull of `lull_gap_ms`, driven by the
    production ResponseEngine on the FacadeExecutor. Returns per-frame
    (seconds into the lull, black hole real cells dark, squiggles lit rows,
    pulse level)."""
    from spectra.models.scene import SceneV2
    from spectra.services import color_journey as cj
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    async def main():
        config_dir = str(tmp_path / "fx-room")
        _config(config_dir)
        headless.silence_audio()
        from fx.host import FxHost
        host = FxHost(config_dir)
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        facade.set_host(host)
        rows = []
        try:
            with headless.fake_clock() as clock:
                vs = {vid: host.virtuals.get(vid)
                      for vid in (BH_V, SQ_V, PULSE_V)}
                effects = {
                    BH_V: headless.attach_effect(host, vs[BH_V], "blackhole",
                                                 dict(BH_CFG)),
                    SQ_V: headless.attach_effect(host, vs[SQ_V], "squiggles",
                                                 dict(SQ_CFG)),
                    PULSE_V: headless.attach_effect(
                        host, vs[PULSE_V], "pulse",
                        {"gradient": "#ff0000", "beat_ms": 500.0,
                         "energy": 0.5}),
                }
                room = [cj.RoomColorState()]
                ex = FacadeExecutor(
                    clock=lambda: clock.now,
                    room_controls_load=lambda: rc.RoomControlState())
                conductor = DriftConductor(
                    executor=ex, clock=lambda: clock.now,
                    drift_profiles=lambda: {}, curve_profiles=lambda: {},
                    room_load=lambda: room[0],
                    room_save=lambda st: room.__setitem__(0, st),
                    set_cards=lambda: [], gradient_profiles=lambda: {},
                    room_controls=lambda: rc.RoomControlState(),
                    rng=Random(3))
                responder = ResponseEngine(
                    conductor=conductor, executor=ex, rng=Random(5),
                    clock=lambda: clock.now, curve_profiles=lambda: {},
                    room_load=lambda: room[0],
                    room_save=lambda st: room.__setitem__(0, st),
                    room_controls=lambda: rc.RoomControlState())
                conductor.on_scene_fire(SceneV2(name="room"), [
                    {"virtual_id": vid, "effect_type": et, "config": {},
                     "entry_id": "", "color_mode": "set"}
                    for vid, et in ((BH_V, "blackhole"), (SQ_V, "squiggles"),
                                    (PULSE_V, "pulse"))])
                mask = _real_mask()
                frames = {}

                def step(n=1):
                    for _ in range(n):
                        clock.advance(DT)
                        for vid, v in vs.items():
                            f = v.assemble_frame()
                            if f is not None:
                                v.flush(f)
                                frames[vid] = np.asarray(f, dtype=np.float32)

                step(4 * FPS)                       # a population first
                await responder.on_event("charge", 0.7, gap_ms=3_000)
                step(3 * FPS)                       # the charge COMPLETES
                assert effects[BH_V]._config["phase_progress"] == 1.0
                rec = await responder.on_event("lull", 0.5,
                                               gap_ms=lull_gap_ms)
                assert set(rec["phase"]["targets"]) == {BH_V, SQ_V, PULSE_V}
                for i in range(1, int(lull_gap_ms / 1000 * FPS) + 1):
                    step()
                    bh_cells = frames[BH_V].reshape(ROWS, COLS, -1)[mask]
                    sq_frame = frames[SQ_V].reshape(ROWS, COLS, -1)
                    rows.append({
                        "t": i * DT,
                        "bh_dark": float(bh_cells.max()) == 0.0,
                        "sq_rows": int(np.count_nonzero(
                            sq_frame.max(axis=(1, 2)) > 0.0)),
                        "pulse": float(effects[PULSE_V].level),
                        "pulse_px": float(frames[PULSE_V].max()),
                    })
        finally:
            facade.set_host(None)
            await host.shutdown()
        return rows

    return asyncio.run(main())


@pytest.fixture(scope="module")
def twenty_second_lull(tmp_path_factory):
    return _run_the_room(tmp_path_factory.mktemp("lull20"), 20_000)


def _at(rows, t):
    return min(rows, key=lambda r: abs(r["t"] - t))


def _after(rows, t):
    return [r for r in rows if r["t"] >= t + 2 * DT]


def test_black_hole_expands_for_seventeen_seconds_then_holds_dark_for_three(
        twenty_second_lull):
    rows = twenty_second_lull
    late = _after(rows, 17.0)
    assert late and all(r["bh_dark"] for r in late)
    # still expanding — real cells lit — up to just before the dark point,
    # and certainly at the old half-way point
    for t in (5.0, 10.0, 16.0):
        assert not _at(rows, t)["bh_dark"], t
    first_dark = next(r["t"] for r in rows if r["bh_dark"]
                      and all(x["bh_dark"] for x in rows if x["t"] >= r["t"]))
    assert 16.0 < first_dark <= 17.0 + 2 * DT


def test_squiggles_squashes_for_seventeen_seconds_then_holds_its_line(
        twenty_second_lull):
    rows = twenty_second_lull
    # the picture is still there, squashing, until the dark point — chains
    # keep forming through a told lull until it is dark (Black Hole's model)
    for t in (5.0, 10.0, 12.0, 15.0):
        assert _at(rows, t)["sq_rows"] > 1, t
    late = _after(rows, 17.0)
    assert late and all(r["sq_rows"] <= 1 for r in late)


def test_pulse_is_pitch_black_for_exactly_the_last_three_seconds(
        twenty_second_lull):
    rows = twenty_second_lull
    assert _at(rows, 10.0)["pulse"] > 0.02          # not black at half way
    assert _at(rows, 16.9)["pulse"] > 0.0
    black = [r for r in rows if r["pulse"] <= 1e-9 and r["pulse_px"] == 0.0]
    first = black[0]["t"]
    assert abs(first - 17.0) <= 2 * DT
    assert all(r["pulse"] <= 1e-9 and r["pulse_px"] == 0.0
               for r in rows if r["t"] >= first)
    span = rows[-1]["t"] - first + DT
    assert abs(span - 3.0) <= 2 * DT


def test_a_short_lull_is_still_half_and_half(tmp_path):
    rows = _run_the_room(tmp_path, 4_000)
    assert not _at(rows, 1.5)["bh_dark"]
    assert all(r["bh_dark"] for r in _after(rows, 2.0))
    assert _at(rows, 1.5)["pulse"] > 0.0
    assert all(r["pulse"] <= 1e-9 for r in _after(rows, 2.0))
    assert all(r["sq_rows"] <= 1 for r in _after(rows, 2.0))
