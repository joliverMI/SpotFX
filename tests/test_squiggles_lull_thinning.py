"""Squiggles' lull THINNING OUT, and the drop after it landing on real light
(fx/effects/squiggles.py "the lull: thinning out"; fx/effects/lattice.py's
gap-segment fallback).

HIS WORDS (2026-10-11), on the transitions/drop plan's Squiggles lull
options: "I like A. Use that one" — A is "Thinning out": no new chains are
born, the ones flying fizzle one by one into small booms, head-on meetings
arc less often, the colour slides to the set's darkest stop, and the panel
is dark by the lull's dark point; the entry is eased (the normal flow
carries on while the rule ramps in) because the first sketch's lull start
was "jarringly abrupt". It replaces the old-TV switch-off.

THE DEFECT the plan found while rendering ("after a lull, Squiggles' drop
fan lands entirely on the crystal's dead cells"): every ring move keeps a
cell's (col + row) parity, so a chain walks ONE sublattice for its whole
life. With no shape map the lattice view fell back to an all-live
rectangle, the drop's fan was born at the panel centre (35.5, 18) snapped
to (36, 18) — the dead parity on his crystal — and every burst chain walked
the dead cells. Without a lull, edge-spawned chains of either parity hid
it. His live crystal-mapper carries a shape map, so the room itself takes
the real-shape path; the fallback now reads the real cells off the
virtual's own gap segments (the render path's own gap rule), which is what
the offline rigs — and any virtual whose shape map is missing — get.

Everything runs on the real vendored pipeline with his crystal's real
cells (scripts/check_fish_wall.py's rig: real cells on one dummy device,
gaps on a `gap-` device, no shape map) and his Squiggles V2 Matrix params.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.check_fish_wall as W  # noqa: E402
from fx import shapemap  # noqa: E402
from fx.effects import lattice  # noqa: E402
from fx.effects import lull_dark  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DT = W.DT
REAL = W.crystal_real_mask()
BEAT_EVERY = 26  # ~138 bpm, pulsed by hand (audio is silenced)

# his Squiggles V2 Matrix entry (storage/spectra/scenes.json, read
# 2026-10-11), beat_burst's binding at its fallback
SQUIGGLES_V2 = {
    "blob_size": 2, "reverse": False, "x_offset": 0.5, "y_offset": 0.5,
    "step_size": 3, "step_count": 4, "horizontal_gap": 10, "spawn_rate": 0,
    "spawn_audio": 0.5, "base_speed": 38, "speed_audio": 2.7,
    "length_audio": 1, "brightness_audio": 1, "jiggle": 0.24,
    "impulse_decay": 0.06, "beat_burst": 2, "max_blobs": 8,
    "gradient": "linear-gradient(90deg, #00ffff 0%, #0040ff 100%)",
}


def _run(coro):
    return asyncio.run(coro)


def _frame(eff):
    return np.asarray(eff.matrix, dtype=np.float32).reshape(-1, 3)


def _lit(eff):
    return _frame(eff).max(axis=1) > 20


class _Show:
    def __init__(self, r):
        self.r, self.i = r, 0

    def step(self, n=1, beats=True):
        for _ in range(n):
            self.i += 1
            if beats and self.i % BEAT_EVERY == 0:
                self.r.effect._beat_pending = True
            self.r.step(1)

    def charge(self, seconds):
        eff = self.r.effect
        eff.update_config({"phase": "charge", "phase_progress": 0.0})
        n = int(seconds / DT)
        for k in range(1, n + 1):
            eff.update_config({"phase_progress": k / n})
            self.step()

    def lull(self, seconds, told=True, watch=None):
        eff = self.r.effect
        arm = {"phase": "lull", "phase_progress": 0.0}
        if told:
            arm.update(lull_dark.keys_for(seconds, 0.9 * seconds, 3.0))
        eff.update_config(arm)
        n = int(seconds / DT)
        for k in range(1, n + 1):
            eff.update_config({"phase_progress": min(1.0, k / (0.9 * n))})
            self.step()
            if watch is not None:
                watch(k * DT, eff)

    def drop(self, seconds, watch=None):
        eff = self.r.effect
        eff.update_config({"phase": "drop", "phase_progress": 0.0})
        for k in range(1, int(seconds / DT) + 1):
            self.step()
            if watch is not None:
                watch(k * DT, eff)


# the pinned predecessor: master just before the thinning lull (a fixed
# commit, never a moving ref — scripts/check_fish_camera.py's BASELINE_REF
# says what a moving ref once did to a proof)
BASELINE_REF = "37178b3690a5412cdbc42ab73804418d2fd312ac"


def _load_baseline_squiggles(name="squiggles_lull_baseline"):
    """The predecessor's squiggles.py registered as a SECOND effect (an
    Effect registers under its module's last name segment). A git that
    cannot produce the pinned ref is a FAILURE, not a skip — a proof that
    silently stops running reads as green."""
    import importlib.util
    import subprocess
    import tempfile

    src = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:fx/effects/squiggles.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


# ── the lattice: real cells off the gap segments ─────────────────────────
def test_without_a_shape_map_the_lattice_reads_the_real_cells_off_the_gaps():
    async def main():
        r = await W.rig("sqlat", SQUIGGLES_V2, effect_type="squiggles")
        try:
            r.step(1)
            v = r.virtual
            assert getattr(v, "_shape", None) is None
            lat = r.effect.lat
            assert lat.has_real_shape
            assert (lat.mask.ravel() == REAL).all()
            # the same mask a shape map decoded from those segments gives
            shape = shapemap.decode_segments(
                [list(s) for s in v.segments], W.COLS, W.ROWS)
            assert (shape.mask == lat.mask).all()
            # the drop's birth point snaps onto a real cell
            c, rr = lat.snap(r.effect.cx, r.effect.cy)
            assert REAL.reshape(W.ROWS, W.COLS)[rr, c]
        finally:
            await W.close(r)

    _run(main())


def test_a_virtual_without_gap_segments_keeps_the_rectangle():
    async def main():
        r = await W.rig("sqrect", SQUIGGLES_V2, effect_type="squiggles",
                        crystal=False)
        try:
            r.step(1)
            assert not r.effect.lat.has_real_shape
            assert r.effect.lat.mask.all()
        finally:
            await W.close(r)

    _run(main())


# ── the drop after a lull lands on real light ────────────────────────────
async def _drop_after_lull(seed):
    r = await W.rig("sqdrop", SQUIGGLES_V2, seed=seed,
                    effect_type="squiggles")
    show = _Show(r)
    rows = []
    try:
        show.step(240)
        show.charge(2.0)
        show.lull(4.0)
        show.drop(1.5, watch=lambda t, e: rows.append(
            (t, int((_lit(e) & REAL).sum()), int((_lit(e) & ~REAL).sum()))))
    finally:
        await W.close(r)
    return rows


def test_the_drop_after_a_lull_lights_real_cells():
    for seed in (3, 5):
        rows = _run(_drop_after_lull(seed))
        late = [r for r in rows if r[0] >= 0.5]
        # the plan's reproduction measured 0 real / 170 gap from +0.6 s on
        assert min(real for _t, real, _g in late) > 60, (seed, late[:5])
        for _t, real, gap in late:
            assert real > gap, (seed, _t, real, gap)


def test_red_control_the_rectangle_fallback_reproduces_the_dead_cell_drop(
        monkeypatch):
    lattice._VIEW_CACHE.clear()
    monkeypatch.setattr(lattice, "_segment_key", lambda effect, virtual: None)
    try:
        rows = _run(_drop_after_lull(5))
    finally:
        lattice._VIEW_CACHE.clear()
    late = [r for r in rows if r[0] >= 0.9]
    # the defect as found: nearly all of the fan's light on dead cells
    assert max(real for _t, real, _g in late) < 20
    assert min(gap for _t, _r, gap in late) > 150


# ── the lull: thinning out ───────────────────────────────────────────────
async def _lull_run(seconds, seed=3, told=True, config=None):
    r = await W.rig("sqlull", dict(config or SQUIGGLES_V2), seed=seed,
                    effect_type="squiggles")
    show = _Show(r)
    out = {"flow": [], "lull": []}
    try:
        show.step(240)
        show.charge(2.0)
        prev = [_frame(r.effect)]

        def flow_watch():
            cur = _frame(r.effect)
            out["flow"].append(float(np.abs(cur - prev[0])[REAL].mean()))
            prev[0] = cur

        for _ in range(30):
            show.step()
            flow_watch()
        dark_stop = r.effect._dark_stop()

        def watch(t, e):
            cur = _frame(e)
            cols = [e.get_gradient_color_vectorized1d(
                np.array([c["grad"]], dtype=np.float32))[0]
                for c in e.chains]
            out["lull"].append({
                "t": t,
                "diff": float(np.abs(cur - prev[0])[REAL].mean()),
                "real_lit": int((_lit(e) & REAL).sum()),
                "chains": len(e.chains),
                "sparks": int(e.s_n),
                "max": float(cur.max()),
            })
            prev[0] = cur

        show.lull(seconds, told=told, watch=watch)
        out["dark_stop"] = dark_stop
    finally:
        await W.close(r)
    return out


def test_the_lull_starts_inside_the_normal_flow():
    out = _run(_lull_run(4.0))
    first = [row["diff"] for row in out["lull"][:3]]
    # the plan's measure: the lull's first-frame change within the normal
    # flow's own (it was 27 per cell for the abrupt first sketch)
    assert max(first) <= max(out["flow"]) + 0.5, (first, out["flow"])


def test_a_long_lull_thins_out_one_by_one_and_is_dark_from_its_dark_point():
    out = _run(_lull_run(20.0, seed=5))
    rows = out["lull"]
    dark_at = lull_dark.dark_start_s(20.0, 3.0)        # 17 s
    entry_end = [r for r in rows if r["t"] >= 1.0][0]
    # no chain is born once the entry has eased in: the population only
    # ever falls from there
    after = [r["chains"] for r in rows if r["t"] >= 1.0]
    assert all(b <= a for a, b in zip(after, after[1:]))
    assert entry_end["chains"] >= 4
    # one by one, on a schedule spread across the lull — chains are still
    # crossing late in it, not collided out within seconds
    by_t = {round(r["t"], 2): r for r in rows}
    assert by_t[12.0]["chains"] >= 1 and by_t[15.0]["real_lit"] > 0
    drops = [a - b for a, b in zip(after, after[1:]) if a != b]
    assert max(drops) <= 2
    # every chain is gone before the dark point, the panel dark from it
    pre = [r for r in rows if dark_at - 0.2 <= r["t"] < dark_at - 2 * DT]
    assert all(r["chains"] == 0 for r in pre)
    late = [r for r in rows if r["t"] >= dark_at + 2 * DT]
    assert late and all(r["max"] == 0.0 for r in late)


def test_a_short_lull_is_dark_from_half_way():
    rows = _run(_lull_run(4.0))["lull"]
    late = [r for r in rows if r["t"] >= 2.0 + 2 * DT]
    assert late and all(r["max"] == 0.0 for r in late)
    assert any(r["real_lit"] > 50 for r in rows if r["t"] < 1.0)


def test_an_untold_lull_still_thins_out_and_ends_dark():
    rows = _run(_lull_run(4.0, told=False))["lull"]
    # the legacy dark point: LULL_LEGACY_DARK_AT of the progress ramp
    from fx.effects import squiggles as sq
    dark_t = sq.LULL_LEGACY_DARK_AT * 0.9 * 4.0
    late = [r for r in rows if r["t"] >= dark_t + 2 * DT]
    assert late and all(r["max"] == 0.0 for r in late)


def test_the_colour_slides_to_the_sets_darkest_stop():
    gradient = "linear-gradient(90deg, #ffff00 0%, #00ffff 50%, #0000ff 100%)"
    cfg = dict(SQUIGGLES_V2, gradient=gradient, max_blobs=16, beat_burst=4)

    async def main(slide):
        r = await W.rig("sqslide", dict(cfg, lull_color_slide=slide), seed=7,
                        effect_type="squiggles")
        show = _Show(r)
        means = []
        try:
            show.step(240)

            def watch(t, e):
                px = _frame(e)[REAL]
                lit = px.max(axis=1) > 20
                if 2.0 <= t <= 3.2 and lit.sum() > 10:
                    means.append(px[lit].mean(axis=0))

            show.lull(8.0, watch=watch)
            dark = r.effect._dark_stop()
        finally:
            await W.close(r)
        return np.mean(means, axis=0), dark

    slid, dark = _run(main(1.0))
    held, _ = _run(main(0.0))
    assert dark[2] > 200 and dark[0] < 10 and dark[1] < 10   # blue
    # late in the approach the slid chains lean to the darkest stop (blue):
    # less red and green than the same lull with no slide
    assert slid[0] < held[0] and slid[1] < held[1]


def test_outside_the_lull_squiggles_is_unchanged_bit_for_bit():
    """The normal flow and the charge are the pre-change effect's own
    frames, bit for bit (the pinned predecessor loaded out of git as a
    second registered effect, on the same rig, seed and beats)."""
    name = _load_baseline_squiggles()

    async def frames(effect_type):
        r = await W.rig("sqsame", SQUIGGLES_V2, seed=11,
                        effect_type=effect_type)
        show = _Show(r)
        out = []
        try:
            for _ in range(180):
                show.step()
                out.append(_frame(r.effect).copy())
            eff = r.effect
            eff.update_config({"phase": "charge", "phase_progress": 0.0})
            for k in range(1, 121):
                eff.update_config({"phase_progress": k / 120})
                show.step()
                out.append(_frame(eff).copy())
        finally:
            await W.close(r)
        return out

    new = _run(frames("squiggles"))
    old = _run(frames(name))
    assert len(new) == len(old)
    for a, b in zip(new, old):
        assert np.array_equal(a, b)


def test_sonic_reaches_the_lull_settings_with_the_effects_own_bounds():
    import voluptuous as vol
    from fx.effects.squiggles import Squiggles2d

    reg = json.loads((REPO / "config/effect_params.json").read_text())
    params = reg["effects"]["squiggles"]["params"]
    keys = {str(k): k for k in Squiggles2d.CONFIG_SCHEMA.schema}
    for key in ("lull_entry_s", "lull_fizzle_rate", "lull_arc_rate",
                "lull_color_slide"):
        p = params[key]
        validator = Squiggles2d.CONFIG_SCHEMA.schema[keys[key]]
        assert validator(p["min"]) == p["min"]
        assert validator(p["max"]) == p["max"]
        for outside in (p["min"] - 0.01, p["max"] + 0.01):
            try:
                validator(outside)
            except vol.Invalid:
                pass
            else:
                raise AssertionError((key, outside))
        assert keys[key].default() == p["default"]
        assert reg["effects"]["squiggles"]["defaults"][key] == p["default"]
