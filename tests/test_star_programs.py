"""OUT OF STAR — the six approved transitions (the star plan, data/star-plan/
report.md; the Admiral, 2026-10-13: "The ones from star to the others are
great and approved"). fx/effects/transition_cloud.py's "OUT OF STAR"
section is the binding statement; radial.Radial2d._program_snapshot is the
release.

Measured on the real pipeline (tests/star_harness.py: a real Melt strip
under a real Radial, the switch through the REAL `Virtual.set_effect(
program=...)` hook):

  1. the registry: every pair out of Star has a program, into Star none
     yet; the anchors and the stages;
  2. the drop-led cut table: out of Star is a program on the mark;
  3. every program runs its whole clock (never dropped on an exception),
     draws no white cell, and starts from Star's released bands (the
     pieces wear the set's colours and carry the ring's turning);
  4. UNWIND and CLUSTER land every piece ON a live target of the incoming
     effect;
  5. the release is a program's alone: the ordinary hand-off snapshot (the
     crossfade's adoptions) is unchanged, and a dark star offers nothing;
  6. the room's three new tunables reach the program.
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
from spectra.services import room_controls as rc  # noqa: E402
from star_harness import (PALETTE, STAR, lit_cells, star_room,  # noqa: E402
                          white_cells)
from strip_phase_harness import palette_of, run, whiter_than_set  # noqa: E402

OUT = {"blackhole": tp.INFALL, "fireworks": tp.FOUNTAIN,
       "sauron": tp.IGNITION, "eye": tp.IGNITION, "squiggles": tp.UNRAVEL,
       "orbits": tp.UNWIND, "fish": tp.CLUSTER}


# ── 1. the registry ────────────────────────────────────────────────────────

def test_every_pair_out_of_star_has_its_program_and_none_into_it_yet():
    for inc, name in OUT.items():
        assert tp.program_name("radial", inc) == name, inc
        # into Star still crossfades (his "still need work")
        assert tp.program_name(inc, "radial") is None, inc
    s = tp.ProgramSettings()
    assert tp.anchor_frac(tp.UNWIND, s) == 0.0
    assert tp.anchor_frac(tp.CLUSTER, s) == 0.0
    assert tp.lead_ms(tp.UNWIND, s) == 0
    unwind = tp.stages("radial", "orbits", s)
    assert [x["label"] for x in unwind] == ["unwind", "condense"]
    assert unwind[0]["anchor"]
    cluster = tp.stages("radial", "fish", s)
    assert [x["label"] for x in cluster] == ["break", "gather", "shoal"]


def test_a_drop_led_cut_out_of_star_runs_the_program():
    for inc in OUT:
        if (("radial", inc) in ds.HANDOFF):
            assert ds.handoff_kind("radial", inc) == ds.HANDOFF_PROGRAM, inc


# ── 3 / 4. every program, on the real pipeline ─────────────────────────────

async def _switch(tmp, inc_type, request=None):
    async with star_room(tmp, layer=False) as room:
        room.step(room.secs(1.0))
        palette = palette_of(room.effects["radial-dummy"])
        v = room.virtuals[STAR]
        v._config["transition_mode"] = "Add"
        v._config["transition_time"] = 0.5
        star = room.star
        settings = tp.ProgramSettings.from_request(request or {})
        snap = star._program_snapshot(settings)
        new = room.host.effects.create(ledfx=room.host, type=inc_type,
                                       config={"gradient": PALETTE})
        prog = tp.build("radial", inc_type, {"seed": 3, **(request or {})})
        v.set_effect(new, activate=False, program=prog)
        room.effects[STAR] = new
        frames, whites, changes, prev = [], 0, [], None
        lands = []
        while not prog.done and len(frames) < 400:
            room.step(1)
            m = np.asarray(new.matrix, dtype=np.float64)
            whites = max(whites, white_cells(m))
            if prev is not None:
                changes.append(float(np.abs(m - prev).mean()))
            prev = m
            frames.append(m)
            f = getattr(prog, "former", None)
            if isinstance(f, tc.TargetFormer) and f.targets_seen:
                lands.append(f.last_s.copy())
        return {"prog": prog, "snap": snap, "frames": frames, "white": whites,
                "changes": changes, "palette": palette, "new": new,
                "virtual": v, "lands": lands, "omega": star._omega}


@pytest.mark.parametrize("inc_type", sorted(OUT))
def test_each_program_out_of_star_runs_whole_and_never_white(tmp_path, inc_type):
    out = run(_switch(str(tmp_path), inc_type))
    prog, snap = out["prog"], out["snap"]
    assert prog.name == OUT[inc_type]
    # the release: Star's bands as pieces, in the set's colours, turning
    assert snap["px"].size == tp.DEFAULT_BANDS_PIECES
    assert whiter_than_set(np.asarray(snap["rgb"]), out["palette"]) == 0
    assert out["omega"] > 0.0
    speed = np.hypot(snap["vx"], snap["vy"])
    r = np.hypot(snap["px"] - 36.0, snap["py"] - 18.5)
    assert np.corrcoef(speed, r)[0, 1] > 0.95, "v = omega x r"
    # the whole clock, then handed off — never dropped by an exception
    assert prog.done and prog.t_last >= prog.duration - 0.05
    assert out["virtual"]._program is None
    assert out["new"]._transition_program is None
    assert out["white"] == 0
    # one picture at a time: no frame-to-frame cut as large as a crossfade's
    # (the plan measured 22-30 per cell for today's 0.5 s blends)
    assert max(out["changes"]) < 20.0, max(out["changes"])
    assert lit_cells(out["frames"][0]) > 1000, "it starts from the star"


@pytest.mark.parametrize("inc_type", ["orbits", "fish"])
def test_unwind_and_cluster_land_every_piece_on_a_live_target(tmp_path, inc_type):
    out = run(_switch(str(tmp_path), inc_type))
    assert out["lands"], "the former saw the incoming effect's targets"
    last = out["lands"][-1]
    assert float(np.min(last)) > 0.97, float(np.min(last))


def test_cluster_gathers_onto_the_fish_count_of_seeds(tmp_path):
    out = run(_switch(str(tmp_path), "fish"))
    f = out["prog"].former
    assert isinstance(f, tc.ClusterFormer)
    seeds = np.unique(f.seed)
    fish_n = int(getattr(out["new"], "particle_count", 0))
    assert 1 <= seeds.size <= max(fish_n, 1)
    # each cluster flies to its OWN fish
    targets = {int(f.target[np.flatnonzero(f.seed == s)[0]]) for s in seeds}
    assert len(targets) == seeds.size


# ── 5. the release is a program's alone ────────────────────────────────────

def test_the_crossfade_snapshot_is_unchanged_and_a_dark_star_offers_nothing(tmp_path):
    async def body():
        async with star_room(str(tmp_path), layer=False) as room:
            room.step(room.secs(0.5))
            star = room.star
            ordinary = star._handoff_snapshot()
            # a dark frame: nothing lit to release
            from PIL import Image
            star.matrix = Image.new("RGB", (star.r_width, star.r_height))
            dark = star._program_snapshot(tp.ProgramSettings())
            prog = tp.build("radial", "orbits", {})
            return ordinary, dark, prog.capture(room.virtuals[STAR], star)
    ordinary, dark, captured = run(body())
    assert ordinary["px"].size == 0 and ordinary["src"] == "radial"
    assert dark["px"].size == 0
    assert captured is False, "no pieces -> no program (the crossfade runs)"


# ── 6. the room's tunables ─────────────────────────────────────────────────

def test_the_three_room_tunables_reach_the_program():
    room = rc.RoomControlState(transition_bands_pieces=90,
                               transition_bands_hold_ms=500,
                               transition_unwind=20.0)
    req = rc.transition_program_request(room)
    s = tp.ProgramSettings.from_request(req)
    assert (s.bands_pieces, s.bands_hold_s, s.unwind) == (90, 0.5, 20.0)
    d = tp.ProgramSettings.from_request({"bands_pieces": 999,
                                         "bands_hold_ms": -5, "unwind": 99})
    assert (d.bands_pieces, d.bands_hold_s, d.unwind) == (220, 0.0, 40.0)


def test_the_release_honours_the_piece_count(tmp_path):
    out = run(_switch(str(tmp_path), "orbits", {"bands_pieces": 90}))
    assert out["snap"]["px"].size == 90
    assert out["prog"].n == 90
