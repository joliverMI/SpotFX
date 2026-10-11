"""Eye and Sauron's lull, UPSIDE DOWN (fx/effects/eye.py, fx/effects/
sauron.py — `lull_lids_upside_down`).

HIS WORDS (2026-10-11), on the transitions/drop plan's "flip it
vertically" reading (which had turned the lids a quarter turn, closing from
the sides): "no, i meant upside down. it's a simple 180 degree rotation."
So today's lull is drawn turned 180 degrees about the eye: the lids meet
just ABOVE the eye's centre and curve the other way; nothing else about the
lull (its timing, its pause on the iris, the lid colour) changes, and the
drop opens the lids from there, the same way round.

On the real vendored pipeline (scripts/check_fish_wall.py's rig, a plain
72x37 rectangle so the eye — gazing home during the lull — sits at the
panel's own centre and a 180-degree turn about it maps the panel onto
itself).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.check_fish_wall as W  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GRADIENT = "linear-gradient(90deg, #ff4000 0%, #ffd000 100%)"
BASELINE_REF = "37178b3690a5412cdbc42ab73804418d2fd312ac"
LULL_FRAMES = 180


def _run(coro):
    return asyncio.run(coro)


async def _lull_and_drop(effect_type, upside_down, prepare=None,
                         shock=False):
    # The drop Shockwave (fx/effects/phase_grammar.py) paints its own set
    # colour over the drop frames, so the lid-geometry tests hold it off
    # (`drop_shock: 0`) and measure the lids alone; the coexistence test
    # below turns it on.
    cfg = {"gradient": GRADIENT, "drop_shock": 1.0 if shock else 0.0}
    if upside_down is not None:
        cfg["lull_lids_upside_down"] = upside_down
    r = await W.rig("lids", cfg, seed=3, effect_type=effect_type,
                    crystal=False)
    eff = r.effect
    if prepare is not None:
        prepare(eff)
    out = {"frames": {}, "drop": [],
           "before": getattr(eff, "_lids_rotated", False)}
    try:
        r.step(60)
        eff.update_config({"phase": "lull", "phase_progress": 0.0})
        for k in range(1, LULL_FRAMES + 1):
            eff.update_config(
                {"phase_progress": min(1.0, k / (0.9 * LULL_FRAMES))})
            r.step(1)
            out["frames"][k] = np.asarray(eff.matrix, np.float32).copy()
        eff.update_config({"phase": "drop", "phase_progress": 0.0})
        for _ in range(40):
            r.step(1)
            # (the predecessor has no switch: never turned)
            rotated = getattr(eff, "_lids_rotated", False)
            out["drop"].append((eff._lid, rotated,
                                np.asarray(eff.matrix, np.float32).copy()))
    finally:
        await W.close(r)
    return out


def _lit(frame):
    return frame.max(axis=2) > 20


@pytest.mark.parametrize("effect_type", ["eye", "sauron"])
def test_the_closed_lull_is_todays_turned_180_degrees(effect_type):
    today = _run(_lull_and_drop(effect_type, False))
    turned = _run(_lull_and_drop(effect_type, True))
    closed = LULL_FRAMES - 10                 # the lids have met
    a = _lit(today["frames"][closed])
    b = _lit(turned["frames"][closed])
    assert a.any() and b.any()
    assert (np.rot90(a, 2) == b).mean() >= 0.99
    # today the lids meet just below the eye's centre, turned just above
    rows_a = np.flatnonzero(a.any(axis=1))
    rows_b = np.flatnonzero(b.any(axis=1))
    centre = (a.shape[0] - 1) / 2.0
    assert rows_a.mean() > centre > rows_b.mean()


@pytest.mark.parametrize("effect_type", ["eye", "sauron"])
def test_the_closing_lids_travel_the_turned_way(effect_type):
    today = _run(_lull_and_drop(effect_type, False))
    turned = _run(_lull_and_drop(effect_type, True))
    h = today["frames"][1].shape[0]
    for k in (60, 100, 140):
        ra = np.flatnonzero(_lit(today["frames"][k]).any(axis=1))
        rb = np.flatnonzero(_lit(turned["frames"][k]).any(axis=1))
        # the lit band between the lids, turned: its top is today's bottom
        assert abs((h - 1 - ra[-1]) - rb[0]) <= 1, (k, ra, rb)
        assert abs((h - 1 - ra[0]) - rb[-1]) <= 1, (k, ra, rb)


@pytest.mark.parametrize("effect_type", ["eye", "sauron"])
def test_the_drop_opens_the_lids_the_same_way_round(effect_type):
    out = _run(_lull_and_drop(effect_type, True))
    assert out["before"] is False
    lids = [lid for lid, _rot, _f in out["drop"]]
    rotated = [rot for _lid, rot, _f in out["drop"]]
    # they open fast and completely
    assert lids[0] > 0.8 and lids[-1] == 0.0
    assert all(b <= a for a, b in zip(lids, lids[1:]))
    # turned while they are opening; back to the ordinary way once open
    assert all(rot for lid, rot, _f in out["drop"] if lid > 0.001)
    assert not out["drop"][-1][1]
    # the first opening frame keeps the turned geometry: dark below the
    # meet line's mirror, lit band above centre
    first = _lit(out["drop"][0][2])
    rows = np.flatnonzero(first.any(axis=1))
    assert rows.mean() < (first.shape[0] - 1) / 2.0


@pytest.mark.parametrize("effect_type", ["eye", "sauron"])
def test_the_upside_down_lull_and_the_shockwave_coexist(effect_type,
                                                      monkeypatch):
    """The drop Shockwave and the upside-down lull on one Eye/Sauron: the
    Shockwave paints the drop, and the lids still open the same way round,
    their own state machine untouched by it. (Eye and Sauron draw their
    construction-time state from an unseeded generator, so both runs are
    constructed from the same seed.)"""
    real_rng = np.random.default_rng
    monkeypatch.setattr(
        np.random, "default_rng",
        lambda seed=None, *a, **k: real_rng(11 if seed is None else seed,
                                            *a, **k))
    held = _run(_lull_and_drop(effect_type, True))
    shocked = _run(_lull_and_drop(effect_type, True, shock=True))
    # nothing is told to breathe here, so the lull itself is the same
    for k in held["frames"]:
        assert np.array_equal(held["frames"][k], shocked["frames"][k]), k
    # the Shockwave genuinely ran: it changed the drop's light
    assert any(not np.array_equal(a, b) for (_l, _r, a), (_l2, _r2, b)
               in zip(held["drop"], shocked["drop"]))
    # and the lids opened exactly as they do without it
    lids = [lid for lid, _rot, _f in shocked["drop"]]
    assert lids == [lid for lid, _rot, _f in held["drop"]]
    assert ([rot for _lid, rot, _f in shocked["drop"]]
            == [rot for _lid, rot, _f in held["drop"]])
    assert lids[0] > 0.8 and lids[-1] == 0.0
    assert all(rot for lid, rot, _f in shocked["drop"] if lid > 0.001)
    assert not shocked["drop"][-1][1]


@pytest.mark.parametrize("effect_type", ["eye", "sauron"])
def test_lids_rotated_carries_through_a_same_type_handoff_mid_lull(
        effect_type):
    """A flare fallback POST recreates the effect instance mid-lull (eye.py's
    own comment on the `native` hand-off block). The outgoing instance's
    `deactivate()` stores its live state — including whether the lull's
    lids are drawn turned 180 degrees — for the successor to adopt on its
    first draw. Before `lids_rotated` joined that block, a successor would
    silently reset to the UN-rotated orientation mid-lull even though the
    predecessor (and the room's own `lull_lids_upside_down` default) had
    it turned: the geometry would visibly jump at the exact moment of the
    recreation."""
    async def main():
        r = await W.rig("lidshand", {"gradient": GRADIENT}, seed=3,
                        effect_type=effect_type, crystal=False)
        eff_a = r.effect
        try:
            r.step(60)
            eff_a.update_config({"phase": "lull", "phase_progress": 0.0})
            for k in range(1, 61):
                eff_a.update_config(
                    {"phase_progress": min(1.0, k / (0.9 * LULL_FRAMES))})
                r.step(1)
            # mid-close, genuinely rotated — not merely the default state
            assert eff_a._lids_rotated is True
            assert 0.05 < eff_a._lid < 0.95

            # the predecessor hands off; a successor is created on the SAME
            # virtual (a same-type recreation, not a fresh song/scene)
            eff_a.deactivate()
            eff_b = W.headless.attach_effect(
                r.host, r.virtual, effect_type, {"gradient": GRADIENT})
            eff_b._rng = np.random.default_rng(3)
            r.step(1)  # first draw -> _adopt_handoff()

            assert eff_b._phase == "lull"
            assert eff_b._lids_rotated is True, (
                "successor did not inherit the predecessor's rotated lull"
            )
            frame = np.asarray(eff_b.matrix, np.float32)
            lit = _lit(frame)
            rows = np.flatnonzero(lit.any(axis=1))
            assert rows.size > 0
            # rotated: the lit band between the closing lids sits above the
            # panel's own centre (the un-rotated default would sit below)
            assert rows.mean() < (frame.shape[0] - 1) / 2.0
        finally:
            await W.close(r)

    _run(main())


def test_upside_down_is_the_default():
    for effect_type in ("eye", "sauron"):
        out = _run(_lull_and_drop(effect_type, None))
        closed = _lit(out["frames"][LULL_FRAMES - 10])
        rows = np.flatnonzero(closed.any(axis=1))
        assert rows.mean() < (closed.shape[0] - 1) / 2.0, effect_type


def _load_baseline_eye(name="eye_lids_baseline"):
    src = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:fx/effects/eye.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


def test_switched_off_eye_is_the_old_lull_bit_for_bit():
    """`lull_lids_upside_down` off is the pre-change Eye through a whole
    lull and drop, bit for bit (the pinned predecessor loaded out of git as
    a second registered effect; Eye's construction-time flame seeds are
    unseeded, so both instances are given the same ones)."""
    name = _load_baseline_eye()
    def prepare(eff):
        seeds = np.random.default_rng(17)
        for k in ("fl_speed", "fl_phase", "fl_speed2", "fl_phase2"):
            n = getattr(eff, k).size
            setattr(eff, k, seeds.uniform(0.3, 1.8, n).astype(np.float32))
        eff._wander_seed = 1.25

    new = _run(_lull_and_drop("eye", False, prepare=prepare))
    old = _run(_lull_and_drop(name, None, prepare=prepare))
    for k in new["frames"]:
        assert np.array_equal(new["frames"][k], old["frames"][k]), k
    for (_l, _r, a), (_l2, _r2, b) in zip(new["drop"], old["drop"]):
        assert np.array_equal(a, b)


def test_sonic_reaches_the_switch():
    reg = json.loads((REPO / "config/effect_params.json").read_text())
    for effect_type in ("eye", "sauron"):
        p = reg["effects"][effect_type]["params"]["lull_lids_upside_down"]
        assert p["type"] == "toggle" and p["default"] is True
        assert reg["effects"][effect_type]["defaults"][
            "lull_lids_upside_down"] is True
