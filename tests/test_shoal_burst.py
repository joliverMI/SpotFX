"""THE SHOALING BURST — the host frame, measured (the shoal-burst plan,
/home/javi/fleet-spotfx/data/shoal-burst-plan/report.md; fx/effects/
transition_cloud.py's HostFormer is the binding statement).

The Admiral, verbatim: "The burst particles continue generally moving as if
the original object were still moving, like nothing happened, except it
burst into particles. So it keeps moving like a fish or like an orbit. Then,
the new effect object matches initial conditions, and starts doing it's own
motion, so it smoothly flows, and the particles recombine into the new
object ... It should also match the particle count where applicable, so that
3 fish turn into 3 orbits, etc."

Every number here is measured on the real vendored pipeline through
tests/shoal_burst_harness.py (fx.headless, a 72x37 dummy matrix, silent
audio, a fake clock), against a CONTROL run with the identical seed in which
the switch never happens — the control is the ground truth for what the
parent was doing, so nothing is checked against what the release published
about itself. The plan's own five acceptance criteria, in order:

  1. the new objects are BORN ON the released ones (within 2 px, against the
     random baseline this panel gives);
  2. a piece's speed against the object it joins is small and does not scale
     with how far apart the two forms were;
  3. the cloud's INITIAL velocity points the way its parent was heading, and
     the cloud TURNS with its parent instead of flying dead straight;
  4. the count is matched on the way in (3 fish -> 3 orbits) and the scene's
     own authored count wins a moment later;
  5. `transition_burst_px = 0` reproduces today's orbits -> fish FRAME FOR
     FRAME — proven against a `git archive` of the branch's merge-base, not
     against a fingerprint committed after the fact (which is also where
     criterion 1's own BEFORE comes from: the same pair, same seed, same
     rig, in both trees);

plus TIER B IS UNCHANGED (the Admiral scoped the build: "for scope, dont do
B"), proven the same way — every pair, including the four out of Squiggles,
whose own release still reads exactly the velocity it read before: the walk
direction he asked to correct rides its own snapshot keys, which only the
host frame reads.

Offline throughout: tmp_path dummy hosts, no live storage, no network.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import shoal_burst_harness as H  # noqa: E402
from fx.effects import transition_cloud as tc  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DRIVER = Path(__file__).resolve().parent / "shoal_tier_b_driver.py"

# The host-frame pairs whose OUTGOING form publishes discrete objects, so
# every element of his ask applies (the plan §3a's tier A, minus the Black
# Hole's eruption, which has its own section below because its ring
# collapses to a point and has no 1:1 with the spray) plus the pair he
# NAMED, which gains the burst by his D1 (§3b).
OBJECT_PAIRS = (
    ("fish", "orbits"),
    ("fish", "squiggles"),
    ("orbits", "squiggles"),
    ("squiggles", "orbits"),
    ("squiggles", "fish"),
    ("orbits", "fish"),
)
ERUPTION_PAIRS = (
    ("blackhole", "orbits"),
    ("blackhole", "fish"),
    ("blackhole", "squiggles"),
)
# Where the parent's own heading is a continuous curve, so "the cloud turns
# with its parent" is a number worth holding to. A chain head WALKS A
# LATTICE whose six directions sit 45/45/90 apart: its own measured heading
# swings +-45 degrees every couple of frames, so its "turn" over a window is
# that quantisation, not a curve — reported, never asserted against.
CONTINUOUS_PARENT = ("fish", "orbits")

# tier B, proven byte-identical against the merge-base — EVERY pair out of
# Squiggles included: the walk direction the Admiral asked for rides its own
# `walk_*` snapshot keys, which only the host frame reads, so what these
# release from is the same `vx`/`vy` they read before (his scope word was
# "for scope, dont do B").
TIER_B_IDENTICAL = (
    ("fish", "radial"),          # SHOAL BREAK into Star: its release CHANGED
    ("squiggles", "radial"),     # UNRAVEL into Star: its release CHANGED
    ("squiggles", "blackhole"),  # INFALL, out of the effect that was fixed
    ("squiggles", "eye"),        # IGNITION, likewise
    ("squiggles", "sauron"),
    ("orbits", "radial"),        # WIND
    ("orbits", "blackhole"),     # INFALL
    ("fish", "blackhole"),       # INFALL, and Fish now publishes `om`
    ("sauron", "orbits"),        # FLAME LICK: still the TargetFormer
    ("eye", "orbits"),
    ("fireworks", "blackhole"),
    ("blackhole", "fireworks"),
)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """One rig run per pair (they take real frames), shared by the tests
    that read different numbers off the same measurement."""
    tmp = tmp_path_factory.mktemp("shoal")
    out = {}
    for pair in OBJECT_PAIRS + ERUPTION_PAIRS:
        rec = H.run(H.program_run(tmp, *pair, seed=3))
        ctl = H.run(H.control_run(tmp, pair[0], seed=3, frames=rec["frames"]))
        out[pair] = (rec, ctl)
    return out


# ── 1. the new objects are BORN ON the released ones ──────────────────────

@pytest.mark.parametrize("pair", OBJECT_PAIRS)
def test_the_new_objects_are_born_on_the_released_ones(runs, pair):
    rec, _ = runs[pair]
    assert isinstance(rec["prog"].former, tc.HostFormer), rec["former"]
    d = H.birth_distance(rec)
    rand = H.random_baseline(rec)
    assert d is not None and rand is not None
    # the plan's criterion 1: within 2 px (it measured 11.3 px before, on a
    # panel where two unrelated point sets sit 10.7 px apart)
    assert d < 2.0, (pair, d)
    assert d < 0.25 * rand, (pair, d, rand)


@pytest.mark.parametrize("pair", OBJECT_PAIRS)
def test_every_piece_follows_the_object_its_own_parent_became(runs, pair):
    """Assignment is INHERITED, never searched — which is also what stops
    two pieces of one fish being sent to opposite sides of the panel."""
    rec, _ = runs[pair]
    prog = rec["prog"]
    assert prog.obj_of is not None and prog.host_pids is not None
    assert prog.obj_of.size == prog.n
    assert (prog.host_pids >= 0).all(), "every object got a host"
    # the hosts are real, live and found every frame
    seen = sum(1 for h in rec["hosts"]
               if h is not None and np.isfinite(h[0]).any())
    assert seen >= 0.9 * len(rec["hosts"]), (pair, seen, len(rec["hosts"]))


# ── 2. no zoom: the speed against the object it joins ─────────────────────

@pytest.mark.parametrize("pair", OBJECT_PAIRS)
def test_a_piece_barely_moves_against_the_object_it_joins(runs, pair):
    rec, _ = runs[pair]
    rel = H.relative_speed(rec)
    assert rel is not None
    # the plan's criterion 2 and its measured target (~8 px/s; it measured
    # 39.3 px/s before, 1.36x the parent's own speed)
    assert rel < 8.0, (pair, rel)


@pytest.mark.parametrize("pair", OBJECT_PAIRS)
def test_nothing_snaps_anywhere_in_the_program(runs, pair):
    """No snap and no zoom, measured over the WHOLE program rather than a
    window: a piece's speed against its own host never spikes (the only
    moment it moves quickly against it is the burst opening, which is
    bounded by `transition_burst_px` and its envelope), and the gather
    arrives at REST — the land envelope is a smoothstep, so its derivative
    goes to zero and the piece dissolves into the object instead of
    catching up to it."""
    rec, _ = runs[pair]
    prof = H.host_relative_profile(rec)
    assert prof is not None, pair
    med, mx = prof
    # BOUNDED BY THE BURST, not by how far apart the two forms were: the
    # ceiling is R over its own opening, which is the fastest the only term
    # that moves a piece against its host can ever open (measured peaks:
    # 18-27 px/s median, 34-44 worst piece, against a 93 px/s ceiling)
    burst = rec["prog"].settings
    ceiling = 4.0 * burst.burst_px / burst.burst_open_s()
    assert float(mx.max()) < ceiling, (pair, float(mx.max()), ceiling)
    # IT ARRIVES AT REST — the land envelope is a smoothstep, so its
    # derivative goes to zero and the piece dissolves into the object
    # instead of catching up to it (measured: exactly 0.00 on every pair)
    assert float(med[-1]) < 0.25, (pair, med[-5:])
    # ... and gets there by decaying, never by snapping: no frame-to-frame
    # step in that relative motion, and the last quarter never rises
    assert float(np.abs(np.diff(med)).max()) < 8.0, (pair, med)
    tail = med[int(len(med) * 0.75):]
    assert float(np.diff(tail).max()) <= 0.05, (pair, tail)


# ── 3. the cloud continues its parent's motion ────────────────────────────

@pytest.mark.parametrize("pair", OBJECT_PAIRS)
def test_the_cloud_leaves_the_way_its_parent_was_heading(runs, pair):
    rec, ctl = runs[pair]
    cos = H.initial_cosines(rec, ctl)
    assert cos is not None and cos.size >= 6, pair
    assert float(cos.min()) > 0.0, (pair, float(cos.min()))
    assert float(np.median(cos)) >= 0.7, (pair, float(np.median(cos)))


@pytest.mark.parametrize("pair", OBJECT_PAIRS)
def test_the_cloud_turns_with_its_parent(runs, pair):
    rec, ctl = runs[pair]
    land = int(rec["prog"].settings.land_s() * 60)
    cloud = H.cloud_turn_deg(rec, land)
    assert cloud is not None
    cloud = float(np.median(cloud))
    # it turns AT ALL — the defect was a dead-straight ballistic drift,
    # measured at exactly 0 degrees on every pair
    assert cloud > 30.0, (pair, cloud)
    parent = H.parent_turn_deg(ctl, land)
    assert parent is not None
    parent = float(np.median(parent))
    if pair[0] in CONTINUOUS_PARENT:
        # the plan's criterion 3: at least 60% of its parent's own turn
        assert cloud >= 0.6 * parent, (pair, cloud, parent)


# ── 4. the count rule (his D3) ────────────────────────────────────────────

def test_three_fish_become_three_orbits_then_the_scenes_own_count(tmp_path):
    rec = H.run(H.program_run(tmp_path, "fish", "orbits", seed=3,
                              out_cfg={"particle_count": 3},
                              in_cfg={"particle_count": 6},
                              after=120, sub="count-3-6"))
    assert rec["authored"] == 6
    # matched on the way in...
    assert rec["count"][0] == 3, rec["count"][:5]
    assert rec["count"][-1] == 3, rec["count"][-5:]
    # ... and the scene's own count a moment after the program ends
    assert rec["count_after"] == 6
    # the matched count really is the released one, not a coincidence
    assert rec["released"][0].size == 3


def test_six_fish_into_an_orbits_scene_of_three_still_matches(tmp_path):
    rec = H.run(H.program_run(tmp_path, "fish", "orbits", seed=4,
                              out_cfg={"particle_count": 6},
                              in_cfg={"particle_count": 3},
                              after=120, sub="count-6-3"))
    assert rec["count"][0] == 6
    assert rec["count_after"] == 3


def test_match_count_off_keeps_the_scenes_own_count_from_the_start(tmp_path):
    rec = H.run(H.program_run(tmp_path, "fish", "orbits", seed=3,
                              out_cfg={"particle_count": 3},
                              in_cfg={"particle_count": 6},
                              request={"match_count": False},
                              sub="count-off"))
    assert rec["count"][0] == 6
    # and it still rides its hosts: the match is a count, not the mechanism
    assert isinstance(rec["prog"].former, tc.HostFormer)


def test_more_released_objects_than_the_incoming_can_hold_merge(tmp_path):
    """The clamp bite (the plan §5.4): the surplus objects' pieces merge
    into the nearest born host — two fish visibly becoming one orbit —
    rather than a count nobody asked for."""
    objs = {
        "px": np.array([10.0, 11.0, 50.0], np.float32),
        "py": np.array([10.0, 11.0, 20.0], np.float32),
        "bright": np.ones(3, np.float32),
        "om": np.zeros(3, np.float32),
    }
    hosts = (np.array([10.0, 11.0, np.nan], np.float32),
             np.array([10.0, 11.0, np.nan], np.float32))
    prog = tp.build("fish", "orbits", {"seed": 1})
    prog.objs = objs
    prog.incoming = object()
    prog.birth_offered = True
    prog._birth_order = np.arange(3)
    prog.x = np.zeros(6, np.float32)
    prog.y = np.zeros(6, np.float32)

    class _Inc:
        _prog_birth_token = id(prog)
        # the incoming form took only the first two objects
        _prog_birth_pids = np.array([7, 8, -1], dtype=np.int64)

        def _program_hosts(self, pids):
            return hosts

    prog.incoming = _Inc()
    ok = prog._host_frame(objs, np.array([0, 0, 1, 1, 2, 2]))
    assert ok
    # object 2 had no host of its own and was merged into the NEAREST one
    assert prog.host_pids.tolist() == [7, 8, 8]


# ── 5. burst 0, and tier B, against the branch's merge-base ───────────────

def _merge_base():
    try:
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/master"],
                              cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:                                   # noqa: BLE001
        return None
    return base or None


@pytest.fixture(scope="module")
def base_tree():
    """A `git archive` of the branch's merge-base, unpacked — so "before"
    is genuinely before. A STATED skip when git cannot produce it, never a
    silent pass."""
    base = _merge_base()
    if base is None:
        pytest.skip("no merge-base with origin/master in this checkout")
    d = Path(tempfile.mkdtemp(prefix="shoal-base-"))
    try:
        ar = subprocess.run(["git", "archive", base], cwd=REPO,
                            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(d)], input=ar.stdout,
                       check=True)
    except Exception as exc:                            # noqa: BLE001
        pytest.skip(f"cannot unpack {base}: {exc}")
    (d / "tests").mkdir(exist_ok=True)
    (d / "tests" / DRIVER.name).write_text(DRIVER.read_text())
    return d


def _digest(tree: Path, out_type, in_type, req=None, seed=3):
    cmd = [sys.executable, str(tree / "tests" / DRIVER.name), str(tree),
           out_type, in_type, str(seed)]
    if req is not None:
        cmd.append(json.dumps(req))
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, (out_type, in_type, r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_burst_zero_reproduces_todays_shoaling_frame_for_frame(base_tree):
    """The plan's criterion 5, and the Admiral's own escape hatch: at
    `transition_burst_px` 0 orbits -> fish is the pair he has today, frame
    for frame — the fish simply appear on the blobs, no burst."""
    now = _digest(REPO, "orbits", "fish", {"burst_px": 0.0})
    was = _digest(base_tree, "orbits", "fish", {"burst_px": 0.0})
    assert now["cls"] == "ShoalingProgram"
    assert now["digest"] == was["digest"]
    # ... and with the burst it is a different program entirely
    with_burst = _digest(REPO, "orbits", "fish")
    assert with_burst["cls"] == "ShoalBurstProgram"
    assert with_burst["digest"] != was["digest"]


@pytest.mark.parametrize("pair", ERUPTION_PAIRS)
def test_burst_zero_reproduces_todays_eruption_frame_for_frame(base_tree, pair):
    now = _digest(REPO, *pair, {"burst_px": 0.0})
    was = _digest(base_tree, *pair, {"burst_px": 0.0})
    assert now["digest"] == was["digest"], pair


@pytest.mark.parametrize("pair", (
    ("fish", "orbits"), ("squiggles", "orbits"), ("squiggles", "fish")))
def test_the_birth_distance_against_the_merge_base_itself(base_tree, pair):
    """Criterion 1 as a real BEFORE/AFTER, not just a small number now: the
    same pair, same seed, same rig, in this checkout and in the branch's
    merge-base. (The three pairs INTO Squiggles have no "before" to measure
    — an empty Squiggles has no chain head on the program's first frame at
    all — and orbits -> fish was already born matched by the Fish's own
    adopt; what IT gains is the burst, proven above.)"""
    now = _digest(REPO, *pair)
    was = _digest(base_tree, *pair)
    assert was["birth_px"] is not None and was["birth_px"] > 8.0, (pair, was)
    assert now["birth_px"] is not None and now["birth_px"] < 2.0, (pair, now)
    assert now["birth_px"] < 0.2 * was["birth_px"], (pair, now, was)


def test_orbits_into_fish_was_already_born_matched_and_still_is(base_tree):
    """The pair he NAMED is the one case that never had the birth defect —
    `fish._adopt_handoff` already started every fish on its blob. What D1
    adds there is the burst it never had, and the birth stays where it was."""
    now = _digest(REPO, "orbits", "fish")
    was = _digest(base_tree, "orbits", "fish")
    assert was["birth_px"] is not None and was["birth_px"] < 2.0, was
    assert now["birth_px"] == pytest.approx(was["birth_px"], abs=0.05)
    assert now["cls"] == "ShoalBurstProgram" and was["cls"] == "ShoalingProgram"


@pytest.mark.parametrize("pair", TIER_B_IDENTICAL)
def test_tier_b_is_byte_for_byte_unchanged(base_tree, pair):
    now = _digest(REPO, *pair)
    was = _digest(base_tree, *pair)
    assert now["digest"] == was["digest"], pair
    assert now["former"] == was["former"], pair


def test_the_squiggles_fix_is_confined_to_the_keys_only_tier_a_reads():
    """The two velocity families sit SIDE BY SIDE on the snapshot, and the
    reason is scope: `vx`/`vy` is a contract four programs release from and
    three effects adopt on an ordinary crossfade, none of them in tier A. So
    the ordinary pair still carries the last lattice move, byte for byte,
    and the way the chain is actually GOING rides `walk_vx`/`walk_vy`/
    `walk_om`, which only `_program_objects` (the host frame's own object
    set) reads."""
    from fx.effects import squiggles as sq

    src = Path(sq.__file__).read_text()
    # the ordinary pair comes from the single-move formula...
    assert '"vx": np.array([v[0] for v in vel]' in src
    assert '"walk_vx": np.array([w[0] for w in walk]' in src
    # ... and nothing but the host frame's object set reads the walk keys
    hits = subprocess.run(["git", "grep", "-l", "walk_vx"], cwd=REPO,
                          capture_output=True, text=True).stdout.split()
    readers = {h for h in hits if h.endswith(".py")}
    assert readers <= {"fx/effects/squiggles.py",
                       "fx/effects/transition_program.py",
                       "tests/test_shoal_burst.py"}, readers


# ── the Admiral's squiggles comment, measured ─────────────────────────────

def test_a_squiggle_publishes_the_way_it_is_actually_going(tmp_path):
    """His comment on the plan: "The bursts don't seem to carry the
    directional velocity of the squiggles. Some look like they go the
    opposite direction."

    A chain head walks a lattice whose six directions sit 45/45/90 degrees
    apart with NO horizontal move, and every move inside one segment is the
    SAME slot — so the last move points up to 45 degrees off the way the
    chain is going, and the first move of a fresh segment can be 90. The
    heading is now averaged over a whole segment pair instead.
    """
    rec = H.run(H.program_run(tmp_path, "squiggles", "orbits", seed=3,
                              sub="sq-vel"))
    eff = None
    # the outgoing snapshot was taken off the real effect; re-read its own
    # chains through both formulas
    snap = rec["out_snap"]
    paths = [np.asarray(list(p), np.float32)
             for p in [c[0] for c in rec["prog"].paths]]
    assert paths, "the unspool read the chains' own paths"
    now, old, ideal = [], [], []
    for pts in paths:
        if pts.shape[0] < 6:
            continue
        # the chain's own travel over its whole visible body — the ground
        # truth neither formula is derived from
        tru = pts[-1] - pts[0]
        n = math.hypot(*tru)
        if n < 1e-3:
            continue
        tru = tru / n
        single = pts[-1] - pts[-2]               # today's one lattice move
        k = min(6, pts.shape[0] - 1)
        span = pts[-1] - pts[-1 - k]             # a whole segment pair
        for vec, bag in ((single, old), (span, now)):
            m = math.hypot(*vec)
            if m > 1e-3:
                bag.append(float((vec[0] * tru[0] + vec[1] * tru[1]) / m))
        ideal.append(1.0)
    assert len(now) >= 3 and len(old) >= 3
    # the averaged heading agrees with the chain's own travel...
    assert float(np.median(now)) > 0.9, now
    # ... and is strictly better than the single move it replaces, which is
    # the defect he reported (its worst reading is far off, and can be
    # 90 degrees out)
    assert float(np.median(now)) > float(np.median(old)), (now, old)
    assert float(np.min(old)) < 0.8, old
    # BOTH are published, side by side: the walk direction and its turn rate
    # under their own keys, the last lattice move still under `vx`/`vy` for
    # everything that was already reading them
    assert snap.get("walk_vx") is not None and snap.get("walk_om") is not None
    assert snap.get("vx") is not None
    walk = np.hypot(snap["walk_vx"], snap["walk_vy"])
    plain = np.hypot(snap["vx"], snap["vy"])
    assert walk.size == plain.size and walk.size >= 3
    # the two really are different readings of the same chains — the walk
    # keys would be pointless if they agreed with the move they replace
    cos = ((snap["walk_vx"] * snap["vx"] + snap["walk_vy"] * snap["vy"])
           / np.maximum(walk * plain, 1e-6))
    assert float(np.min(cos)) < 0.999, cos
    # and the host frame reads the WALK pair, not the plain one
    objs = rec["prog"]._program_objects()
    k = int(objs["src"][0])
    assert objs["vx"][0] == pytest.approx(float(snap["walk_vx"][k]))


# ── the Black Hole's eruption: only the last stage changed ────────────────
# "its contraction and bloom untouched, only the last stage's homing becomes
# a host-frame gather, with the hosts born AT THE BLOOM, at the centre, on
# the spray velocity, so the new blobs are carried outward by their own
# clouds" (the plan §7 phase 3). The count match is NOT APPLICABLE here —
# there is no meaningful 1:1 between the pre-collapse ring and the spray —
# so the incoming form keeps its own authored count, which is why these
# pairs have their own section rather than the numbers above.

@pytest.mark.parametrize("pair", ERUPTION_PAIRS)
def test_the_eruptions_hosts_are_born_at_its_bloom(runs, pair):
    rec, _ = runs[pair]
    prog = rec["prog"]
    assert prog.host_pids is not None, "no hosts were born"
    assert prog.e_obj is not None and prog.e_obj.size == prog.e_n
    # every ejecta rides a host that was actually born
    assert (prog.host_pids[prog.e_obj] >= 0).all()
    assert prog.gather is not None, "the host-frame gather never engaged"
    # the incoming form keeps its OWN count (no 1:1 with the spray)
    if rec["authored"]:
        assert rec["count"][-1] == rec["authored"]


@pytest.mark.parametrize("pair", ERUPTION_PAIRS)
def test_the_eruptions_contraction_and_bloom_are_untouched(tmp_path, pair):
    """Only the homing moved: every frame up to the FORM stage is identical
    with the host frame on and off."""
    sub = f"er-{pair[1]}"
    new = H.run(H.program_run(tmp_path, *pair, seed=3, keep_frames=True,
                              sub=sub + "-on"))
    old = H.run(H.program_run(tmp_path, *pair, seed=3, keep_frames=True,
                              request={"burst_px": 0.0}, sub=sub + "-off"))
    form = int(new["prog"].t_form * 60)
    assert form > 10 and len(new["px"]) > form
    for i in range(form):
        assert np.array_equal(new["px"][i], old["px"][i]), (pair, i)
    # ... and from there they genuinely diverge (otherwise this proves
    # nothing about the new mechanism)
    assert not np.array_equal(new["px"][-1], old["px"][-1]), pair


@pytest.mark.parametrize("pair", ERUPTION_PAIRS)
def test_the_eruptions_gather_has_less_distance_to_cross(tmp_path, pair):
    sub = f"erd-{pair[1]}"
    new = H.run(H.program_run(tmp_path, *pair, seed=3, sub=sub + "-on"))
    old = H.run(H.program_run(tmp_path, *pair, seed=3,
                              request={"burst_px": 0.0}, sub=sub + "-off"))
    f = int(new["prog"].t_form * 60)
    d_new = H.nearest_form_distance(new, f)
    assert d_new is not None and d_new < 8.0, (pair, d_new)
    d_old = H.nearest_form_distance(old, f)
    if d_old is None:
        # blackhole -> squiggles: an empty Squiggles has no chain head to
        # form onto at all today, so its ejecta simply FADE OUT. The matched
        # birth gives them real chains to gather onto — a pair that did not
        # work before, not merely one that works better.
        assert pair[1] == "squiggles", pair
        return
    assert d_new < d_old, (pair, d_new, d_old)


# ── the plan's own edge cases ─────────────────────────────────────────────

def test_a_switch_arriving_before_the_birth_is_drawn_takes_it_back(tmp_path):
    """The plan §8: a switch arriving mid-program is unchanged — the running
    program finishes first. What the host frame adds is a birth it may have
    offered and the incoming effect never drew: the program takes that back
    on the way out (`TransitionProgram.finish`), so no LATER frame can
    consume it as if it were current."""
    import asyncio

    from fx import headless
    from fx.effects import particle_handoff as ph
    from fx.host import FxHost

    async def go():
        ph._store.clear()
        d = str(tmp_path / "interrupt")
        headless.write_headless_config(d, pixel_count=H.PIXELS, rows=H.ROWS)
        headless.silence_audio()
        host = FxHost(d)
        host.audio = headless.SyntheticAudioSource()
        await host.start()
        v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        v._config["transition_mode"] = "Add"
        v._config["transition_time"] = 0.5
        try:
            with H.pinned_rng(3), headless.fake_clock() as clk:
                headless.attach_effect(host, v, "fish", {"gradient": H.WARM})
                headless.render_frames(v, H.WARM_FRAMES, clock=clk)
                a = host.effects.create(ledfx=host, type="orbits",
                                        config={"gradient": H.WARM})
                prog = tp.build("fish", "orbits", {"seed": 3})
                v.set_effect(a, activate=False, program=prog)
                # the birth is pending on `a`, which has not drawn yet
                assert getattr(a, "_prog_birth_snap", None) is not None
                b = host.effects.create(ledfx=host, type="squiggles",
                                        config={"gradient": H.WARM})
                v.set_effect(b, activate=False)       # an ordinary switch
                headless.render_frames(v, 60, clock=clk)
                return prog, a
        finally:
            await host.shutdown()

    prog, a = asyncio.run(go())
    assert prog.done, "the running program was not finished"
    assert getattr(a, "_prog_birth_snap", None) is None, \
        "a birth nobody drew was left pending on the effect"
    assert getattr(a, "_prog_birth_pids", None) is None, \
        "... and nothing was born from it"
