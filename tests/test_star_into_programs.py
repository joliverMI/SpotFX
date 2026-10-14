"""INTO STAR — the six transitions into Star (the star plan, data/star-plan/
report.md revision 2; the Admiral, 2026-10-14: "Do rec on transitions",
after "the star just appears, make it smoother" and "all the transitions to
star have the same problem"). fx/effects/transition_cloud.py's "INTO STAR"
section is the binding statement; the RingFormer is Star's FORM.

Measured on the real pipeline (tests/star_harness.py: a real Melt strip
under the crystal, the crystal switched from a real particle effect to a
real Radial through the REAL `Virtual.set_effect(program=...)` hook):

  1. the registry: every partner into Star has its program, the anchors and
     the stages ("grow in" from STAR_FORM_AT), and a drop-led cut into Star
     runs the program;
  2. NO POP-IN, on every row: the star's own layer (Star's picture times the
     reveal gain the program composes) climbs from 10 % to 90 % of the
     star's lit cells over at least ~0.4 s, its light never jumps more than
     a few percent in one frame, and the last frame IS the plain star (gain
     1 everywhere — nothing pops at the hand-off); no cell is ever white;
  3. the pieces land: every piece glides onto a band, lands staggered (never
     all on one frame), and has melted into its band by the end;
  4. WIND is UNWIND with time inverted: every dot starts ON its orbit blob
     with the blob's velocity, the arcs wind INWARD where UNWIND's unwind
     outward, and no dot's speed jumps from one frame to the next;
  5. the old crossfade choreography is retired for program pairs: Star never
     arms its bloom while a program brings it in.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.effects import transition_cloud as tc  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402
from spectra.services import drop_switch as ds  # noqa: E402
from star_harness import (COLS, PALETTE, ROWS, STAR, STRIP, STRIP_N,  # noqa: E402
                          StarRoom, white_cells)
from strip_phase_harness import run  # noqa: E402

INTO = {"blackhole": tp.FOUNTAIN, "fish": tp.SHOAL_BREAK,
        "fireworks": tp.SPARK_RINGS, "sauron": tp.FLAME_LICK,
        "eye": tp.FLAME_LICK, "squiggles": tp.UNRAVEL, "orbits": tp.WIND}

MELT = {"gradient": PALETTE, "speed": 0.08, "reactivity": 0.3, "blur": 1.0,
        "brightness": 1.0, "background_brightness": 0.0}
RADIAL = {"source_virtual": STRIP, "edges": 6, "polygon": True, "star": 0.3,
          "twist": 0.0, "spin": 0.55, "background_brightness": 0.0,
          "gradient": PALETTE}


# ── 1. the registry ────────────────────────────────────────────────────────

def test_every_partner_into_star_has_its_program_anchor_and_stages():
    s = tp.ProgramSettings()
    for out, name in INTO.items():
        assert tp.program_name(out, "radial") == name, out
        st = tp.stages(out, "radial", s)
        assert [x["label"] for x in st][-1] == "grow in"
        assert st[-1]["from"] == pytest.approx(tp.STAR_FORM_AT)
        assert sum(1 for x in st if x.get("anchor")) == 1
    # the fountain sprays, and the sparks' payoff lands, where FORM begins
    assert tp.anchor_frac(tp.FOUNTAIN, s, "blackhole", "radial") == tp.STAR_FORM_AT
    assert tp.anchor_frac(tp.FOUNTAIN, s, "blackhole", "fireworks") == tp.FOUNTAIN_ANCHOR
    assert tp.anchor_frac(tp.SPARK_RINGS, s) == tp.STAR_FORM_AT
    # WIND comes apart ON the mark (UNWIND's mirror)
    assert tp.anchor_frac(tp.WIND, s) == 0.0
    assert tp.lead_ms(tp.FOUNTAIN, s, "blackhole", "radial") == round(
        tp.STAR_FORM_AT * s.duration_s * 1000)
    # on the mark every payoff opens the program
    on = tp.ProgramSettings(on_mark=True)
    assert tp.lead_ms(tp.FOUNTAIN, on, "blackhole", "radial") == 0


def test_a_drop_led_cut_into_star_runs_the_program():
    for out in ("blackhole", "orbits", "fish", "squiggles"):
        assert ds.handoff_kind(out, "radial") == ds.HANDOFF_PROGRAM, out


# ── 2 / 3. every row on the real pipeline ─────────────────────────────────

async def _into(tmp, out_type, request=None, warm_s=1.5, record=None):
    async with StarRoom(tmp, {STRIP: ("melt", STRIP_N, 1, dict(MELT)),
                             STAR: (out_type, COLS * ROWS, ROWS,
                                    {"gradient": PALETTE})},
                        layer=False) as room:
        room.step(room.secs(warm_s))
        v = room.virtuals[STAR]
        star = room.host.effects.create(ledfx=room.host, type="radial",
                                        config=dict(RADIAL))
        prog = tp.build(out_type, "radial", {"seed": 3, **(request or {})})
        v.set_effect(star, activate=False, program=prog)
        room.effects[STAR] = star
        rec = {"energy": [], "lit": [], "raw_lit": [], "white": 0,
               "gain_end": None, "reveal": [], "snaps": []}
        real = prog.compose

        def compose(effect):
            raw = np.asarray(effect.matrix, dtype=np.float64)
            real(effect)
            out = np.asarray(effect.matrix, dtype=np.float64)
            g = getattr(getattr(prog, "former", None), "_gain", None)
            g = g if isinstance(g, np.ndarray) else np.zeros(raw.shape[:2])
            star_layer = raw.max(-1) * g
            lit = raw.max(-1) > 20.0
            rec["energy"].append(float(star_layer.sum())
                                 / max(float(raw.max(-1).sum()), 1.0))
            rec["lit"].append(int((star_layer[lit] > 20.0).sum()))
            rec["raw_lit"].append(int(lit.sum()))
            rec["white"] = max(rec["white"], white_cells(out))
            rec["gain_end"] = g
            rec["reveal"].append(star._reveal)
            if record is not None:
                rec["snaps"].append(record(prog))
        prog.compose = compose
        n = 0
        while not prog.done and n < 240:
            room.step(1)
            n += 1
        rec["prog"] = prog
        rec["star"] = star
        return rec


def _climb_s(lit, raw_lit, lo=0.1, hi=0.9):
    frac = np.asarray(lit, float) / np.maximum(np.asarray(raw_lit, float), 1.0)
    a = int(np.argmax(frac >= lo))
    b = int(np.argmax(frac >= hi))
    return (b - a) / 60.0, frac


@pytest.mark.parametrize("out_type", sorted(INTO))
def test_each_row_into_star_grows_in_with_no_pop(tmp_path, out_type):
    rec = run(_into(str(tmp_path), out_type))
    prog = rec["prog"]
    assert prog.name == INTO[out_type]
    assert isinstance(prog.former, tc.RingFormer)
    # the whole clock, then let go — never dropped by an exception
    assert prog.done and prog.t_last >= prog.duration - 0.05
    # nothing of the star before FORM
    form_frame = int(tp.STAR_FORM_AT * prog.duration * 60) - 1
    assert max(rec["energy"][:form_frame]) == 0.0
    # NO POP-IN: the star's own lit cells climb over >= ~0.4 s ...
    climb, frac = _climb_s(rec["lit"], rec["raw_lit"])
    assert climb >= 0.4, climb
    # ... its light never jumps in one frame ...
    steps = np.diff(rec["energy"])
    assert steps.max() < 0.06, steps.max()
    # ... and the last frame is the plain star: nothing pops at the hand-off
    assert float(rec["gain_end"].min()) == pytest.approx(1.0, abs=1e-3)
    assert frac[-1] == pytest.approx(1.0, abs=0.01)
    assert rec["white"] == 0


@pytest.mark.parametrize("out_type", ["blackhole", "orbits", "fish"])
def test_the_pieces_land_staggered_and_melt_into_their_bands(tmp_path, out_type):
    rec = run(_into(str(tmp_path), out_type))
    f = rec["prog"].former
    assert f.formed and f.n > 0
    assert (f.j >= 0).all(), "every piece glided onto a band"
    landed = f.t_land[np.isfinite(f.t_land)]
    assert landed.size == f.n, "every piece landed"
    # staggered: the landings run from FORM + the glide to RING_LAND_END_S
    # before the end (0.94 -> 1.15 s on the room's 1.4 s), never one frame
    span = (rec["prog"].duration - tc.RING_LAND_END_S
            - (tp.STAR_FORM_AT * rec["prog"].duration + tc.RING_LOCK_S))
    assert float(landed.max() - landed.min()) > 0.8 * span
    counts = np.unique(np.round(landed * 60).astype(int), return_counts=True)[1]
    assert counts.max() < 0.2 * f.n
    # every one has landed before the end and melted into its band by it
    assert float(landed.max()) <= rec["prog"].duration - 0.2
    assert float(rec["prog"].form_fade.max()) < 0.05


# ── 4. WIND ────────────────────────────────────────────────────────────────

def _wind_state(prog):
    if not getattr(prog, "_ready", False) or not hasattr(prog, "w_p0x"):
        return None
    return (prog._t, prog.x.copy(), prog.y.copy(), prog.vx.copy(),
            prog.vy.copy())


def test_wind_is_unwind_with_time_inverted(tmp_path):
    rec = run(_into(str(tmp_path), "orbits", record=_wind_state))
    prog = rec["prog"]
    assert isinstance(prog, tc.WindProgram)
    snaps = [s for s in rec["snaps"] if s is not None]
    t0, x0, y0, vx0, vy0 = snaps[0]
    # every dot starts ON its orbit blob, moving with the blob (one frame
    # in, it is where the blob's own orbit has carried it)
    bx, by = prog._orbit_at(np.full(prog.w_tau.size, t0, np.float32))
    assert np.abs(x0 - bx).max() < 0.5
    assert np.abs(y0 - by).max() < 0.5
    sp = np.hypot(prog.w_v0x, prog.w_v0y)
    first = np.hypot(vx0, vy0)
    assert np.allclose(first, sp, rtol=0.25, atol=2.0)
    # the arcs come apart along the blob's own orbit over WIND_ARC_S ...
    by_t = {round(s[0], 3): s for s in snaps}
    arc = min(by_t, key=lambda t: abs(t - tc.WIND_ARC_S))
    _t, xa, ya, _vx, _vy = by_t[arc]
    spread = np.hypot(xa - prog.w_p0x, ya - prog.w_p0y)
    assert spread.max() > 2.0
    # ... then wind INWARD about Star's centre until FORM (UNWIND unwinds
    # outward on the same law): the radial speed turns inward
    form = tp.STAR_FORM_AT * prog.duration
    wind = [x for x in snaps if tc.WIND_ARC_S + 0.05 < x[0] < form]
    vr = [float(((x[1] - prog.ccx) * x[3] + (x[2] - prog.ccy) * x[4]).mean())
          for x in wind]
    assert vr[-1] < vr[0]
    # continuity: no dot's velocity jumps between consecutive frames
    jumps = []
    for a, b in zip(snaps, snaps[1:]):
        if a[1].size != b[1].size:
            continue
        dv = np.hypot(b[3] - a[3], b[4] - a[4])
        jumps.append(float(np.percentile(dv, 95)))
    peak = max(float(np.hypot(s[3], s[4]).max()) for s in snaps)
    assert max(jumps) < 0.35 * max(peak, 1.0), (max(jumps), peak)


def _ring_flight(cls, t0):
    """A ring of pieces turning about a centre with no radial motion, flown
    by the program's own FLIGHT for half a second: mean radius before and
    after."""
    prog = cls(tp.ProgramSettings(unwind=20.0), "x", "y")
    ang = np.linspace(0.0, 2 * np.pi, 48, endpoint=False).astype(np.float32)
    prog.ccx, prog.ccy = 36.0, 18.0
    prog.x = (36.0 + 12.0 * np.cos(ang)).astype(np.float32)
    prog.y = (18.0 + 12.0 * np.sin(ang)).astype(np.float32)
    w = 1.5
    prog.vx = (-w * 12.0 * np.sin(ang)).astype(np.float32)
    prog.vy = (w * 12.0 * np.cos(ang)).astype(np.float32)
    r0 = float(np.hypot(prog.x - 36.0, prog.y - 18.0).mean())
    t = t0
    for _ in range(30):
        t += 1 / 60
        prog._fly(None, t, 1 / 60)
    return r0, float(np.hypot(prog.x - 36.0, prog.y - 18.0).mean())


def test_wind_winds_in_on_unwinds_own_law_with_the_push_reversed():
    # past their first stretch (UNWIND's hold, WIND's arcs) the two flights
    # are one law (transition_cloud.turn_about, the same drag) with the push
    # reversed: a turning ring unwinds OUT under UNWIND and winds IN under
    # WIND, by the same room setting (`transition_unwind`)
    assert tc.WindProgram.DRAG == tc.UnwindProgram.DRAG
    r0, r_out = _ring_flight(tc.UnwindProgram, 0.5)
    _r0, r_in = _ring_flight(tc.WindProgram, 0.5)
    assert r_out > r0 + 0.5
    assert r_in < r0 - 0.5


# ── 5. the old choreography is retired for program pairs ──────────────────

def test_star_never_arms_its_crossfade_bloom_while_a_program_brings_it_in(tmp_path):
    rec = run(_into(str(tmp_path), "fish"))
    assert all(r is None for r in rec["reveal"])
    assert rec["prog"].virtual._transition_effect is None
