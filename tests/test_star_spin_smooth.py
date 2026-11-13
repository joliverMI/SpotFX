"""The spin smooth plan (2026-11-12, data/star-spin-smooth/plan.md) — the
Admiral, after the star improve plan went live: "it is too jerky in it's
spin especially on big bass hits. the burst speed is too fast and fades too
fast. I think sometimes it moves so fast it's hard to tell it moved. We
need to cap the burst speed ... it shouldn't be jerky, but it should be
dynamic"; after the analysis page: "the burst fade should be snappier at
higher energies and lazier at low energies. do 18 degrees per frame for
now".

  1. THE CAP is 18 degrees per RENDERED FRAME (under the 180/edges at which
     a 6-point star's turn reads backwards), whatever the frame's length;
     identity below it.
  2. THE RELEASE at 0 is today's motion to the frame — the governed advance
     equals the pre-plan ease+clamp arithmetic replayed on the same drive.
  3. THE RELEASE on: the shipped law equals the analysed law (the scout rig's
     one-pole on the advance, data/star-spin-smooth/scripts/motion.py
     GovState) to 1e-12; a bass hit's burst peaks lower and fades longer;
     the total turn and the mean speed are preserved (unity DC gain).
  4. ENERGY: the release time runs spin_release_low_s at energy 0 to
     spin_release_high_s at 1, linear; snappier when intense, lazier when
     calm; a change of energy never steps the motion.
  5. THE SCENE-DATA SCRIPT: dry run touches nothing, apply changes exactly
     the two Matrix params on a STAR-shaped fixture, idempotent, revert is
     byte-identical, a foreign value is refused; the registry carries both
     params with the effect's defaults.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx.effects import radial                                         # noqa: E402
from star_harness import star_room                                    # noqa: E402
from strip_phase_harness import DT, run                               # noqa: E402
from test_star_improve import _star_store, _turn                      # noqa: E402

CAP = radial.ROTATION_CAP_REV_FRAME
STAR_RELEASE = {"spin_release_low_s": radial.STAR_SPIN_RELEASE_LOW_S,
                "spin_release_high_s": radial.STAR_SPIN_RELEASE_HIGH_S}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hit(t: float, floor: float = 0.3, peak: float = 4.0, at: float = 1.0,
         half_life_s: float = 0.052) -> float:
    """A bass hit as the lows filter shapes it (rev/s): a floor, then an
    exponential burst decaying with the filter's ~52 ms half-life."""
    if t < at:
        return floor
    return floor + (peak - floor) * 0.5 ** ((t - at) / half_life_s)


def _replay(drive_rev_s, frames, *, ease_s: float, tau_fn, cap=CAP, dt=DT):
    """The plan's arithmetic (motion.py GovState: ease -> one-pole on the
    advance -> clamp), replayed in pure Python. tau_fn(i) is the release
    time on frame i; 0 bypasses. Frame 0 passes through ungoverned."""
    out, lp, active = [], None, 0.0
    for i in range(frames):
        a = float(drive_rev_s(i * dt)) * dt
        if i > 0:
            if ease_s > 0.0 and active < ease_s:
                x = active / ease_s
                a *= x * x * (3.0 - 2.0 * x)
            tau = tau_fn(i)
            if tau > 0.0:
                lp = a if lp is None else lp + (a - lp) * (1.0 - np.exp(-dt / tau))
                a = lp
            else:
                lp = None
            a = min(max(a, -cap), cap)
        active += dt
        out.append(a)
    return np.array(out)


def _room_turn(radial_cfg, drive, frames, on_frame=None):
    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 0.0, **radial_cfg}) as room:
                return _turn(room, drive, frames, on_frame)
    return run(go())


# ── 1. the cap ─────────────────────────────────────────────────────────────

def test_cap_is_eighteen_degrees_per_rendered_frame_whatever_the_frame_length():
    assert radial.ROTATION_CAP_DEG_FRAME == 18.0
    assert abs(CAP * 360.0 - 18.0) < 1e-12
    # under the aliasing limit of every edge count STAR rolls (3..6)
    for edges in (3, 4, 5, 6):
        assert radial.ROTATION_CAP_DEG_FRAME < 180.0 / edges

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 0.0}) as room:
                room.rev_s = 1.0
                room.step(2)
                eff = room.star
                out = []
                for dt in (1.0 / 60.0, 1.0 / 30.0, 0.1):     # the rig, the crystal, a stall
                    before = eff.spin_total
                    eff._frame_adv = 0.4                      # far past the cap
                    eff.spin_total = (before + 0.4) % 1.0
                    eff._govern_rotation(dt)
                    out.append((eff.spin_total - before + 0.5) % 1.0 - 0.5)
                return out
    for adv in run(go()):
        assert abs(adv - CAP) < 1e-12                          # the same angle, any dt


def test_cap_is_identity_below_it():
    adv = _room_turn({}, lambda t: 2.0, 30)                    # 2 rev/s = 12 deg/frame at 60 fps
    assert np.allclose(adv[1:] / DT, 2.0, atol=1e-9)


# ── 2. release 0 is today ──────────────────────────────────────────────────

def test_release_zero_is_the_ease_and_clamp_alone_to_the_frame():
    drive = lambda t: _hit(t, peak=4.8)                         # noqa: E731  — hits the cap
    got = _room_turn({"spin_ease_in_s": 1.0}, drive, 150)
    want = _replay(drive, 150, ease_s=1.0, tau_fn=lambda i: 0.0)
    assert np.allclose(got, want, atol=1e-12)
    assert got.max() <= CAP + 1e-12 and (got >= CAP - 1e-12).sum() >= 3


# ── 3. the release ─────────────────────────────────────────────────────────

def test_release_is_the_analysed_law_to_the_frame():
    drive = lambda t: _hit(t)                                   # noqa: E731
    got = _room_turn({"spin_ease_in_s": 1.0, "energy": 0.9, **STAR_RELEASE}, drive, 150)
    tau = 0.45 + (0.2 - 0.45) * 0.9
    want = _replay(drive, 150, ease_s=1.0, tau_fn=lambda i: tau)
    assert np.allclose(got, want, atol=1e-12)


def test_release_spreads_a_bass_hit_and_keeps_the_total_turn():
    # a hit that stays under the cap either way (2.5 rev/s = 15 deg per
    # 60 fps frame), so the clamp takes no turn from today's burst and the
    # two runs must turn exactly as far
    drive = lambda t: _hit(t, at=0.5, peak=2.5)                 # noqa: E731
    frames = 180                                                # 3 s: the floor, the hit, the settle
    today = _room_turn({}, drive, frames)
    eased = _room_turn({"energy": 1.0, **STAR_RELEASE}, drive, frames)   # tau 0.2 s
    hit = int(0.5 / DT)
    # lower peak, longer fade
    assert eased.max() < 0.6 * today.max()
    tenth = lambda a: (a[hit:] > a[:hit].mean() + 0.1 * (a.max() - a[:hit].mean())).sum()  # noqa: E731
    assert tenth(eased) > 3 * tenth(today)
    # the same total turn (unity DC gain), to well under a degree, and the
    # same steady speed before the hit
    assert abs(eased.sum() - today.sum()) * 360.0 < 0.5
    assert np.allclose(eased[5:hit], today[5:hit], atol=1e-9)


# ── 4. energy ──────────────────────────────────────────────────────────────

def test_release_time_follows_energy_linearly():
    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial=STAR_RELEASE) as room:
                eff = room.star
                out = {}
                for e in (0.0, 0.25, 0.5, 1.0):
                    eff.update_config({"energy": e})
                    out[e] = eff._spin_release_s()
                eff.update_config({"spin_release_low_s": 0.0, "spin_release_high_s": 0.0})
                out["off"] = eff._spin_release_s()
                return out
    got = run(go())
    assert abs(got[0.0] - 0.45) < 1e-12 and abs(got[1.0] - 0.2) < 1e-12
    assert abs(got[0.5] - 0.325) < 1e-12 and abs(got[0.25] - 0.3875) < 1e-12
    assert got["off"] == 0.0


def test_snappier_when_intense_lazier_when_calm():
    drive = lambda t: _hit(t, at=0.5)                           # noqa: E731
    peaks, fades = {}, {}
    for e in (0.0, 0.5, 1.0):
        adv = _room_turn({"energy": e, **STAR_RELEASE}, drive, 180)
        peaks[e] = adv.max()
        hit = int(0.5 / DT)
        floor = adv[:hit].mean()
        fades[e] = (adv[hit:] > floor + 0.1 * (adv.max() - floor)).sum()
    assert peaks[1.0] > peaks[0.5] > peaks[0.0]                 # intense: a sharper surge
    assert fades[0.0] > fades[0.5] > fades[1.0]                 # calm: a longer fade


def test_a_change_of_energy_never_steps_the_motion():
    """Energy only moves the filter coefficient; the state integrates, so
    flipping energy 0 -> 1 mid-fade changes the pace, never the value."""
    drive = lambda t: _hit(t, at=0.5)                           # noqa: E731
    flip = int(0.6 / DT)                                        # mid-fade, 100 ms after the hit

    def flip_energy(room):
        def on_frame(i):
            if i == flip:
                room.star.update_config({"energy": 1.0})
        return on_frame

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 0.0, "energy": 0.0,
                                               **STAR_RELEASE}) as room:
                return _turn(room, drive, 120, flip_energy(room))
    adv = run(go())
    steps = np.abs(np.diff(adv))
    # the frame of the flip moves no more than its neighbours do
    assert steps[flip - 1] <= 1.5 * max(steps[flip - 3], steps[flip + 1]) + 1e-6
    # and the pure replay with the same flip matches to the frame
    tau = lambda i: 0.45 if i < flip else 0.2                   # noqa: E731  (on_frame runs before step i)
    want = _replay(drive, 120, ease_s=0.0, tau_fn=tau)
    assert np.allclose(adv, want, atol=1e-12)


# ── 5. the scene-data script and the registry ──────────────────────────────

def test_scene_data_script_dry_run_apply_revert(tmp_path):
    sd = _load("star_spin_smooth_scene_data")
    f = tmp_path / "scenes.json"
    store = _star_store()
    f.write_text(json.dumps(store, indent=2))
    before = f.read_bytes()
    changed = sd.run(f, apply=False, revert=False)
    assert len(changed) == 2 and f.read_bytes() == before       # a dry run writes nothing
    sd.run(f, apply=True, revert=False)
    after = json.loads(f.read_text())
    assert after["other"] == store["other"]
    m = after[sd.STAR_ID]["devices"][0]["params"]
    assert m["spin_release_low_s"] == 0.45 and m["spin_release_high_s"] == 0.2
    assert sd.diff_paths(store, after) == [
        f".{sd.STAR_ID}.devices[0].params.spin_release_high_s",
        f".{sd.STAR_ID}.devices[0].params.spin_release_low_s"]
    assert sd.run(f, apply=True, revert=False) == []           # idempotent
    sd.run(f, apply=True, revert=True)
    assert json.loads(f.read_text()) == store                   # revert is byte-identical


def test_scene_data_script_refuses_a_foreign_value(tmp_path):
    sd = _load("star_spin_smooth_scene_data")
    store = _star_store()
    store[sd.STAR_ID]["devices"][0]["params"]["spin_release_low_s"] = 0.9
    f = tmp_path / "scenes.json"
    f.write_text(json.dumps(store))
    with pytest.raises(SystemExit):
        sd.run(f, apply=True, revert=False)
    assert json.loads(f.read_text()) == store


def test_registry_carries_both_release_params_at_the_effect_default():
    reg = json.loads((ROOT / "config" / "effect_params.json").read_text())["effects"]["radial"]["params"]
    for key in STAR_RELEASE:
        assert reg[key]["default"] == 0.0 == radial.DEFAULT_SPIN_RELEASE_S
        assert reg[key]["help_topic"] == "star-spin-smooth"
        assert (reg[key]["min"], reg[key]["max"]) == (0, 3)
    assert "ROTATION_CAP_DEG_FRAME" in reg["spin_ease_in_s"]["note"]
