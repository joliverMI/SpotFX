"""Star's own lull and drop, and the shape morph (fx/effects/radial.py — the
"STAR'S OWN LULL AND DROP" block is the binding statement; the star plan,
data/star-plan/report.md; the Admiral, 2026-10-13: "Use lull b, drop d 3").

Measured on the real render pipeline through tests/star_harness.py: Star
samples a real `radial-dummy` Melt strip, and every phase arrives the way
it reaches his room (the PRODUCTION ResponseEngine on the FacadeExecutor):

  1. who is told what: Star joins the lull's dark point, the breath-hold,
     the drop intensity and the Shockwave VERDICT — never the overlay;
  2. LULL B: the bands fall in as pieces and the panel is BLACK ON the dark
     point — with the strip's own fade switched off, so it is Star's doing
     (and with it on, the room's real shape);
  3. "implode" stays selectable and is today's lull (no pieces);
  4. DROP D3: the swallowed pieces are thrown back out, the bands wear a
     colour gain, and no cell is whiter than the set's own colour at its
     hue; the switches withhold it (and a quiet watchdog release never
     throws anything);
  5. the breath-hold is black;
  6. the shape morph spreads an edges re-roll over its seconds;
  7. pieces composed brighter-wins never pale toward white.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model  # noqa: E402
from fx.effects import lull_dark, lull_handoff, phase_grammar as pg  # noqa: E402
from fx.effects import radial  # noqa: E402
from star_harness import (PALETTE, STAR, lit_cells, star_room,  # noqa: E402
                          white_cells)
from strip_phase_harness import palette_of, run, whiter_than_set  # noqa: E402

GAP_MS = 5000          # a 5 s lull: dark point at 2.5 s (half, inside 3 s)
DARK_S = 2.5


# ── 1. who is told what ────────────────────────────────────────────────────

def test_star_joins_the_shared_rules_but_never_the_overlay():
    assert "radial" in device_model.LULL_DARK_EFFECTS
    assert "radial" in device_model.BREATH_HOLD_EFFECTS
    assert "radial" in device_model.DROP_INTENSITY_EFFECTS
    assert "radial" in device_model.DROP_SHOCK_TOLD_EFFECTS
    assert "radial" not in device_model.DROP_SHOCK_EFFECTS
    assert radial.Radial2d.DROP_SHOCK is False
    keys = {str(k) for k in radial.Radial2d.CONFIG_SCHEMA.schema}
    for k in (*lull_dark.KEYS, *pg.BREATH_KEYS, lull_handoff.DROP_KEY,
              pg.SHOCK_ON_KEY):
        assert k in keys, k
    assert device_model.schema_default("radial", "lull_mode") == "bands"
    assert device_model.schema_default("radial", "shape_morph_s") == 0.6


def test_the_new_params_are_registered_for_sonic():
    params = device_model.effect_params("radial")
    for key in ("lull_mode", "lull_core_u", "lull_piece_tau",
                "drop_snap_gain", "drop_snap_decay_s", "shape_morph_s"):
        assert key in params, key
        assert params[key]["default"] == device_model.schema_default(
            "radial", key), key
    assert params["lull_mode"]["options"] == list(radial.LULL_MODES)


# ── 2. LULL B ──────────────────────────────────────────────────────────────

async def _lull(tmp, *, layer, radial_cfg=None, until_s=3.2):
    """A 5 s lull from a lit star; Star's lit cells, falling and held
    pieces every 0.1 s."""
    out = []
    async with star_room(tmp, layer=layer, radial=radial_cfg) as room:
        room.step(room.secs(1.0))
        await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
        n = int(round(until_s / 0.1))
        for i in range(n):
            room.step(room.secs(0.1))
            st = room.star._bands
            held = room.star._held
            out.append({
                "t": round(0.1 * (i + 1), 2),
                "lit": lit_cells(room.matrix()),
                "falling": 0 if st is None else int(st["u"].size),
                "held": 0 if held is None else int(held["u0"].size),
                "white": white_cells(room.matrix()),
            })
        return out, room.star


def test_lull_b_bands_fall_in_and_the_panel_is_black_on_the_dark_point(tmp_path):
    # the strip's own phase layer OFF: the strip stays lit throughout, so
    # every bit of darkening here is Star's own
    series, star = run(_lull(str(tmp_path), layer=False))
    at = {r["t"]: r for r in series}
    assert at[0.1]["lit"] > 1000
    # pieces fall while the bands empty
    assert max(r["falling"] for r in series) > 40
    # still lit well into the approach (no early blackout) ...
    assert at[1.8]["lit"] > 100
    # ... and black from the dark point on
    for r in series:
        if r["t"] >= DARK_S:
            assert r["lit"] == 0, r
    # the core swallowed the pieces, and they are kept for the drop
    assert at[DARK_S]["held"] > 40
    assert all(r["white"] == 0 for r in series)
    assert star._config.get("lull_dark_s") == pytest.approx(DARK_S)


def test_lull_b_in_the_real_room_shape_with_the_strip_fading_too(tmp_path):
    series, _star = run(_lull(str(tmp_path), layer=True))
    for r in series:
        if r["t"] >= DARK_S:
            assert r["lit"] == 0, r
    assert max(r["falling"] for r in series) > 20


def test_implode_mode_is_todays_lull_with_no_pieces(tmp_path):
    series, star = run(_lull(str(tmp_path), layer=False,
                             radial_cfg={"lull_mode": "implode"}, until_s=2.0))
    assert all(r["falling"] == 0 and r["held"] == 0 for r in series)
    assert star._bands is None
    # today's implode never goes dark on its own before the breath
    assert series[-1]["lit"] > 0


# ── 4. DROP D3 ─────────────────────────────────────────────────────────────

async def _lull_then_drop(tmp, *, shock_on=True, drop_s=1.6, layer=False,
                          radial_cfg=None):
    frames = []
    layers = []
    async with star_room(tmp, layer=layer, radial=radial_cfg) as room:
        star = room.star
        for name in ("_lull_bands", "_drop_snap"):
            real = getattr(star, name)

            def spy(*a, _real=real, **k):
                out = _real(*a, **k)
                if out is not None:
                    layers.append(out.copy())
                return out
            setattr(star, name, spy)
        room.step(room.secs(1.0))
        palette = palette_of(room.effects["radial-dummy"])
        await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
        room.step(room.secs(DARK_S + 0.3))
        held = room.star._held
        n_held = 0 if held is None else int(held["u0"].size)
        if not shock_on:
            # SpotFX's verdict (the room's switch, the scene's, the energy
            # floor) arrives on the drop arm as drop_shock_on
            room.responder._drop_shock_keys = lambda: (
                {pg.SHOCK_ON_KEY: False}, {"allowed": False})
        await room.phase("drop", intensity=0.8)
        snaps = []
        for _ in range(room.secs(drop_s)):
            room.step(1)
            frames.append(room.matrix())
            snaps.append(room.star._snap is not None)
        return {"frames": frames, "held": n_held, "snaps": snaps,
                "palette": palette, "star": room.star, "layers": layers}


def test_d3_throws_the_swallowed_pieces_back_out_with_no_white(tmp_path):
    out = run(_lull_then_drop(str(tmp_path)))
    assert out["held"] > 40
    assert out["snaps"][0], "the drop's edge starts the snap"
    assert not out["snaps"][-1], "and it ends"
    assert out["star"]._held is None
    pal = out["palette"]
    for f in out["frames"]:
        assert white_cells(f) == 0
    # every piece Star draws — falling in the lull and thrown out on the
    # drop — wears a set colour: never whiter than the set at its hue (the
    # strip's own blur already mixes a few in-between pixels, so this is
    # measured on Star's own layers, not on the whole frame)
    assert out["layers"]
    for layer in out["layers"]:
        lit = layer.reshape(-1, 3)
        lit = lit[lit.max(axis=1) > 20.0]
        assert whiter_than_set(lit, pal) == 0
    # the bloom brings the picture back
    assert lit_cells(out["frames"][-1]) > 1000


def test_d3_colour_gain_is_more_colour_not_white(tmp_path):
    """The bands' gain is hue-kept: during the snap the panel is brighter
    than the same drop told it may not paint, and no pixel changes hue."""
    on = run(_lull_then_drop(str(tmp_path / "on"), drop_s=0.6))
    off = run(_lull_then_drop(str(tmp_path / "off"), shock_on=False,
                              drop_s=0.6))
    m_on = np.mean([f.max(axis=-1).mean() for f in on["frames"][20:36]])
    m_off = np.mean([f.max(axis=-1).mean() for f in off["frames"][20:36]])
    assert m_on > m_off * 1.05
    assert not any(off["snaps"]), "told it may not paint: the plain bloom"


def test_a_quiet_watchdog_release_throws_nothing():
    eff = radial.Radial2d.__new__(radial.Radial2d)
    eff._held = {"u0": np.ones(5, np.float32), "phi": np.zeros(5, np.float32),
                 "rgb": np.full((5, 3), 200, np.float32)}
    eff._bands = None
    eff._snap = None
    eff._silent_drop = True
    eff._config = {}
    eff._begin_snap()
    assert eff._snap is None and eff._held is None


def test_a_charge_straight_into_a_drop_is_the_plain_bloom():
    eff = radial.Radial2d.__new__(radial.Radial2d)
    eff._held = None
    eff._bands = None
    eff._snap = None
    eff._silent_drop = False
    eff._config = {}
    eff._begin_snap()
    assert eff._snap is None


# ── 5. the breath-hold ─────────────────────────────────────────────────────

def test_the_breath_hold_is_black_in_implode_mode(tmp_path):
    async def body():
        async with star_room(str(tmp_path), layer=False,
                             radial={"lull_mode": "implode"}) as room:
            room.step(room.secs(1.0))
            rec = await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
            assert rec["phase"]["lull_breath_s"] == pytest.approx(0.4)
            at = room.star._config
            room.step(room.secs(4.0))
            before = lit_cells(room.matrix())
            room.step(room.secs(0.75))        # inside the breath (4.6..5.0 s)
            return before, lit_cells(room.matrix()), at
    before, during, _cfg = run(body())
    assert before > 0
    assert during == 0


# ── 6. the shape morph ─────────────────────────────────────────────────────

async def _reroll(tmp, morph_s):
    changes = []
    async with star_room(tmp, layer=False,
                         radial={"shape_morph_s": morph_s, "twist": 0.0},
                         ) as room:
        room.rev_s = 0.0
        room.step(room.secs(1.0))
        prev = room.matrix()
        room.star.update_config({"edges": 3})
        for _ in range(room.secs(0.9)):
            room.step(1)
            m = room.matrix()
            changes.append(float(np.abs(m - prev).mean()))
            prev = m
        return changes, room.star


def test_an_edges_reroll_glides_instead_of_cutting(tmp_path):
    cut, _ = run(_reroll(str(tmp_path / "cut"), 0.0))
    glide, star = run(_reroll(str(tmp_path / "glide"), 0.6))
    assert max(glide) < 0.6 * max(cut), (max(glide), max(cut))
    assert star._morph is None, "the morph ends"
    assert star.edges == 3


def test_the_morph_starts_only_on_a_change_of_edges(tmp_path):
    async def body():
        async with star_room(str(tmp_path), layer=False) as room:
            room.step(room.secs(0.5))
            room.star.update_config({"twist": 0.5})   # not the shape
            started_by_twist = room.star._morph is not None
            room.star.update_config({"edges": 4})
            return started_by_twist, room.star._morph
    by_twist, morph = run(body())
    assert not by_twist
    assert morph == {"from": 6, "t": 0.0}


# ── 7. brighter-wins ───────────────────────────────────────────────────────

def test_brighter_wins_never_pales_two_set_colours_toward_white():
    layer = np.zeros((10, 10, 3), np.float32)
    red = np.array([[255.0, 0.0, 40.0]], np.float32)
    green = np.array([[0.0, 255.0, 40.0]], np.float32)
    radial.splat_brighter(layer, np.array([5.0]), np.array([5.0]), red)
    radial.splat_brighter(layer, np.array([5.2]), np.array([5.0]), green)
    lit = layer.max(axis=-1) > 1.0
    # every lit cell wears ONE of the two colours (scaled), never their max
    for c in layer[lit]:
        n = c / c.max()
        assert (np.allclose(n, red[0] / 255.0, atol=0.02)
                or np.allclose(n, green[0] / 255.0, atol=0.02)), c


def test_hue_gain_keeps_the_hue_and_stops_at_full():
    f = np.array([[[200.0, 100.0, 0.0], [40.0, 20.0, 10.0]]], np.float32)
    g = radial.hue_gain(f, 1.6)
    assert g.max() <= 255.0 + 1e-3
    for a, b in zip(f[0], g[0]):
        assert np.allclose(a / a.max(), b / b.max(), atol=1e-4)
