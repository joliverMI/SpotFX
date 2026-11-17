"""FIREWORKS' SHAPED PAYOFF BURST (Word Shapes plan row W1.2, section 3.6,
approved by the Admiral 2026-11-15). His words for the row: "Fireworks: have
a flare style firework (so the ones that are bigger) explode into the given
shape and hang longer than the others. It should form a slightly more solid
outline than the filling, but it also needs to still appear random." Q9 A:
one big centred shaped burst per word, ~70% of the sparks on the outline,
hanging about twice as long, bigger at higher Energy.

ROW W4.3 (his room verdict, 2026-11-17) ADDED THE DARK CANVAS AND HALF AGAIN
AS MANY SPARKS, verbatim: "Fireworks is too cluttered to visually identiy
the shape. Let's have it plan to make sure no fireworks fire right before,
or concurrently, so that it is on a mostly dark canvass. Also, increase the
amount of blobs by 50% so it is more clearly visible, and have it hold 50%
longer." What that row proves here, beside everything below:

  * THE PLANNER GIVES FIREWORKS A 2.0 s FORM (`WORD_SHAPE_FORM_MIN_S`, the
    Fish's own precedent) — the form IS the lead, so the write arrives 2.0 s
    early and the effect has that long to empty the panel;
  * THE HUSH: from the SEQ edge to the END OF THE HOLD not one ordinary
    launch of any kind, across seeds and across a beat — no `spawn_rate`
    burst, no beat burst, no drop-tail shower, and a `burst_rockets` flare
    poke DROPPED rather than deferred; what was already in the air has its
    remaining life capped and fades out instead of blinking out;
  * THE FLIGHT: the burst leaves the centre WORD_SHAPE_FLIGHT_S before the
    word, not at the edge, and still arrives ON it;
  * 90 SPARKS QUIET, 150 LOUD, with the headroom for them asserted;
  * THE HOLD IS THE ROOM'S (W4.2): the hang follows `word_shape_hold_s` and
    nothing here stretches it;
  * A PHASE ARRIVING ENDS THE HUSH — the drop payoff still bursts.

W1.2's own "the ordinary particles are untouched across the edge" is
RETIRED by that verdict and rewritten to the new rule
(test_the_shaped_burst_is_additive_except_the_hush).

What is proven here, in the plan's own order (section 6 is the row's gate):

  1. UNTOLD IS TODAY'S, frame for frame: 300+ frames of busy and of quiet
     music against the module as it was before this row (pinned out of git),
     byte-identical.
  2. COMPLETE ON THE WORD, through the REAL ResponseEngine and the real
     effect: the told write lands and the effect's own form fraction reads
     1.0 within one rendered frame of edge + form_s, at both ends of the
     Energy-paced form; and EVERY spark is inside one cell of the target it
     was launched at — the claim the velocity solve exists for.
  3. NOTHING JUMPS: the frame-to-frame change in lit cells over the form and
     over the release stays under 8% of the lit count.
  4. IT IS THE SHAPE: the row's clarity bar, measured by
     scripts/check_fireworks_word_shape.py on HIS crystal's real mask at
     SIZE 0.62 — the sparks light at least 70% of the shape's outline cells
     on the word, and the inside's mean brightness is at most 0.70 of the
     outline's — for all three shapes at Energy 0.2 and 0.8, at the word and
     at mid-hold.
  5. NO WHITE: the shape ALONE lights no white-ish cell at all, at any
     Energy, for any of the three shapes. Over a LIVE show it is 0.25-0.5
     points above the plan's letter and that number is RECORDED rather than
     claimed — see
     test_the_live_show_white_is_recorded_above_the_plans_letter.
  6. COST: the p50 per-frame render cost with a shape holding.
  7. THE EDGES: two words back to back both fire (the SEQ, never the id), a
     second word mid-release never snaps the first away, a clearing write
     takes nothing away, a form shorter than any minimum is clamped rather
     than dividing by zero, and a stale persisted SEQ on a fresh instance
     never fires (the creation-baseline rule).
  8. THE WIRING: `fireworks` is in WORD_SHAPE_EFFECTS and `fireworks1d` is
     not, the four tunables are registered (so Sonic reaches them) and name
     a real help topic, and the skill map lists this file.

Offline by construction: fx.headless dummy devices on the real mask, a fake
clock, canned audio, no network, nothing written. The rig is
scripts/check_fireworks_word_shape.py's own, so the evidence script and
these proofs measure one thing.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from random import Random

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import device_model, headless  # noqa: E402
from fx.effects import fireworks as FX  # noqa: E402
from fx.effects import word_shape_keys as wsk  # noqa: E402
from fx.effects import word_shapes  # noqa: E402
from scripts import check_fireworks_word_shape as C  # noqa: E402

# origin/master just before this row: fireworks.py without the shaped burst
BASELINE_REF = "5db75fe6"
ROWS, COLS = C.ROWS, C.COLS
DT = C.DT


# ── the shared rig (one run per case, measured many ways) ──────────────────

_PANEL = None
_RUNS: dict = {}


def panel():
    global _PANEL
    if _PANEL is None:
        _PANEL = C.load_panel()
    return _PANEL


def run_for(shape_id: str, energy: float, **kw):
    """One rendered run per (shape, Energy, options), kept for the whole
    module: each of these is ~250 real rendered frames on the real mask."""
    key = (shape_id, energy, repr(sorted(kw.items(), key=repr)))
    if key not in _RUNS:
        _RUNS[key] = C.run_shape(panel(), shape_id, energy, **kw)
    return _RUNS[key]


def alone(shape_id: str, energy: float, **kw):
    """THE SHAPE ALONE — no ordinary show underneath. This is what the
    row's clarity bar is measured on, and it is a real state of his scene
    rather than a convenience: his Fireworks V2 Matrix entry runs
    `spawn_rate: 0`, so a quiet passage launches nothing at all. What the
    room's own beat bursts add on top is measured separately (a burst that
    happens to land inside the outline is not the shape failing to be
    one)."""
    return run_for(shape_id, energy, busy=False, settle_frames=10, **kw)


SHAPES = ("heart", "star", "diamond")
ENERGIES = (0.2, 0.8)


# ── 1. untold is today's ──────────────────────────────────────────────────

_PINNED: dict = {}


def _pinned_type() -> str:
    """fx/effects/fireworks.py as it was before this row, registered as a
    SECOND effect beside today's (the registry keys an effect by its
    module's last name segment) — tests/test_flare_punch_crystal.py's own
    pattern."""
    if "name" in _PINNED:
        return _PINNED["name"]
    name = "fireworks_pre_word_shape"
    try:
        src = subprocess.run(
            ["git", "show", f"{BASELINE_REF}:fx/effects/fireworks.py"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                              # noqa: BLE001
        pytest.skip(f"cannot read {BASELINE_REF}:fx/effects/fireworks.py "
                    f"({exc}) — the byte-identity claim is NOT checked")
    assert "word_shape" not in src, (
        "the pinned fireworks.py already knows word shapes — BASELINE_REF "
        "is not before this row")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _PINNED["name"] = name
    return name


def _plain_frames(tmp: Path, effect_type: str, tag: str, n_frames: int,
                  busy: bool) -> np.ndarray:
    """`n_frames` of the ordinary show, NO told keys at all, on the real
    mask — the untold case, rendered."""
    audio = C.BusyAudio if busy else C.QuietAudio

    async def main():
        host, virtual = await C._host(tmp, tag, C.crystal_mask(panel()))
        try:
            with headless.fake_clock() as clock:
                eff = headless.attach_effect(
                    host, virtual, effect_type, dict(C.HIS_CFG))
                eff._rng = np.random.default_rng(7)
                out = []
                for i in range(n_frames):
                    eff.audio_data_updated(audio(i))
                    clock.advance(DT)
                    frame = virtual.assemble_frame()
                    if frame is not None:
                        virtual.flush(frame)
                        out.append(np.array(frame, copy=True))
                return np.asarray(out, dtype=np.float32)
        finally:
            await host.shutdown()

    return asyncio.run(main())


@pytest.mark.parametrize("busy", [True, False])
def test_without_a_told_shape_the_effect_renders_exactly_as_before(
        tmp_path, busy):
    pinned = _pinned_type()
    today = _plain_frames(tmp_path / "today", "fireworks", "wsid1", 320, busy)
    before = _plain_frames(tmp_path / "before", pinned, "wsid2", 320, busy)
    assert today.shape == before.shape and today.size
    if busy:
        assert today.max() > 0.0, "a show that never lit would prove nothing"
    assert np.array_equal(today, before)


# ── 2. complete on the word, through the real engine ──────────────────────

def _words_scene(vid: str):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Fireworks Words",
        devices=[SceneDeviceConfig(target_kind="virtual", target=vid,
                                   effect_type="fireworks")],
        flare_kinds=[FlareKind(name="Heart", type="word_shape")],
        responses={"word": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Heart": 1.0})])})


def _engine(clock):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now, curve_profiles=lambda: {})
    return executor, conductor, responder


@pytest.mark.parametrize("form_s", [2.0, 2.6])
def test_the_shape_is_complete_on_the_word_through_the_real_engine(
        tmp_path, form_s):
    """The whole path: the real ResponseEngine fires the showing scene's
    Words band, its Word Shape kind writes the six keys to the live
    fireworks virtual, and the effect's own form fraction reaches 1.0 within
    ONE rendered frame of edge + form_s. The engine's own lead is what makes
    that the word (tests/test_word_shape_contract.py proves the lead).

    W4.3: the two forms are the ones the engine can actually tell this
    effect — its own 2.0 s floor, and a longer one from a long phrase. And
    the burst no longer leaves at the edge: nothing is launched until
    WORD_SHAPE_FLIGHT_S before the word, with THE HUSH emptying the panel
    in front of it, which is asserted here frame by frame."""
    from fx import facade
    from spectra.services.scene_response import PreviewWordShape

    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    # a virtual id of its own per run: a deactivated particle effect leaves
    # a hand-off snapshot keyed by virtual id (fx/effects/particle_handoff),
    # which the next parametrization's effect would otherwise ADOPT —
    # shaped sparks and all (tests/test_flare_punch_crystal.py's own note)
    vid = f"ws-engine-{str(form_s).replace('.', '_')}"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [vid], "effects": ["fireworks"], "role": None}}))
    scene = _words_scene(vid)
    hold_s, release_s = 1.2, 1.5 * form_s

    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "engine"), pixel_count=ROWS * COLS, rows=ROWS,
            device_id=vid, real_mask=C.crystal_mask(panel()))
        facade.set_host(host)
        virtual = host.virtuals.get(vid)
        try:
            with headless.fake_clock() as clock:
                cfg = dict(C.HIS_CFG)
                eff = headless.attach_effect(host, virtual, "fireworks", cfg)
                eff._rng = np.random.default_rng(7)
                _ex, conductor, responder = _engine(clock)
                conductor.on_scene_fire(scene, [{
                    "virtual_id": vid, "effect_type": "fireworks",
                    "config": dict(cfg), "entry_id": scene.devices[0].id,
                    "color_mode": "set"}])
                headless.render_frames(virtual, 30, clock=clock, dt=DT)
                assert eff.word_shape_state()["sparks"] == 0

                record = await responder.on_word_shape(PreviewWordShape(
                    shape_id="heart", energy=0.8, form_s=form_s,
                    hold_s=hold_s, release_s=release_s))
                assert record["result"] == "applied"
                assert record["word_shape"]["virtuals"] == 1

                # frame 1 lands the jump's own 1 ms tween, frame 2 is the
                # effect's first frame with the keys (the burst_rockets
                # proof's own arithmetic)
                headless.render_frames(virtual, 2, clock=clock, dt=DT)
                state = eff.word_shape_state()
                # W4.3: the EDGE arms the shape and opens the hush; the
                # burst is still in the barrel
                assert state["armed"] is True, "the told write never landed"
                assert state["hushed"] is True
                assert state["sparks"] == 0, (
                    "the burst left at the edge — the hush has nothing to "
                    "empty the panel in front of")
                # the form, frame by frame from here
                frames = max(2, int(round(max(form_s, 0.1) / DT)))
                fracs, sparks = [], []
                for _ in range(frames + 1):
                    headless.render_frames(virtual, 1, clock=clock, dt=DT)
                    st = eff.word_shape_state()
                    fracs.append(st["form_fraction"])
                    sparks.append(st["sparks"])
                # 1.0 by the frame the form ends, allowing the acceptance
                # bar's one rendered frame either side of where the jump's
                # own 1 ms tween landed the keys
                full = next((i for i, f in enumerate(fracs)
                             if f >= 1.0 - 1e-9), None)
                assert full is not None, (
                    f"form {form_s}: never complete; fractions {fracs}")
                assert frames - 2 <= full <= frames, (
                    f"form {form_s}: complete on frame {full} of {frames}; "
                    f"fractions {fracs}")
                # monotonic, and it never overshoots
                assert all(0.0 <= f <= 1.0 for f in fracs)
                assert fracs == sorted(fracs)
                # THE FLIGHT: the burst left WORD_SHAPE_FLIGHT_S before the
                # word, not at the edge, and the sparks it launched all
                # survive to it
                launched = next(i for i, k in enumerate(sparks) if k)
                due = frames - int(round(FX.WORD_SHAPE_FLIGHT_S / DT))
                assert abs(launched - due) <= 2, (
                    f"form {form_s}: the burst left on frame {launched} of "
                    f"{frames}, expected about {due}")
                assert sparks[-1] == sparks[launched], (
                    "a spark died during the flight")
                assert sparks[launched] > 0
        finally:
            facade.set_host(None)
            await host.shutdown()

    asyncio.run(main())


# ── 3. the sparks arrive, and the split is the told one ───────────────────

@pytest.mark.parametrize("shape_id", SHAPES)
def test_every_spark_is_inside_one_cell_of_its_target_on_the_word(shape_id):
    """The velocity solve: each spark's launch speed comes from the
    effect's OWN drag over THE FLIGHT, so on the word it is standing where
    it was aimed. Measured in real-cell pitches on his crystal.

    W4.3 CHANGED WHAT THE SOLVE IS OVER. The told form is the LEAD, and
    this effect's lead is floored at 2.0 s, so Energy no longer moves it
    (every row below reads 2.00 s) — what the sparks are solved against is
    the FLIGHT, the time left to the word at the launch. Both told forms the
    engine can produce are measured: the floor, and a longer one from a long
    phrase."""
    for energy in ENERGIES + (wsk.LEVEL_FLOOR,):
        run = alone(shape_id, energy)
        assert run.form_s == pytest.approx(2.0, abs=0.01), (
            "the planner floors this effect's form at 2.0 s, so Energy "
            "cannot pace it")
        assert run.targets is not None and len(run.targets)
        assert run.arrival_pitch <= 1.0, (
            f"{shape_id} at Energy {energy} (form {run.form_s:.2f}s): a "
            f"spark is {run.arrival_pitch:.2f} cell pitches from its target")
        # ... and the burst left the centre a flight before the word, not
        # at the edge
        flight_frames = int(round(FX.WORD_SHAPE_FLIGHT_S / DT))
        assert abs((run.word_frame - run.launch_frame) - flight_frames) <= 1
    long_form = alone(shape_id, 0.8, form_override=2.6)
    assert long_form.form_s == pytest.approx(2.6)
    assert long_form.arrival_pitch <= 1.0, long_form.arrival_pitch
    assert abs((long_form.word_frame - long_form.launch_frame)
               - int(round(FX.WORD_SHAPE_FLIGHT_S / DT))) <= 1, (
        "a longer form only lengthens the hush, never the flight")


def test_the_outline_inside_split_is_the_told_share():
    run = alone("heart", 0.8)
    share = run.outline_sparks / run.total_sparks
    assert abs(share - 0.70) <= 0.05, share
    # and the share is a tunable, not a constant
    high = alone("heart", 0.8, config={"word_shape_outline_share": 0.9})
    assert abs(high.outline_sparks / high.total_sparks - 0.9) <= 0.05


def test_the_spark_count_runs_from_quiet_to_loud_with_the_words_energy():
    """90 sparks at the floor Energy, 150 at a full one — W1.2's 60/100 with
    his W4.3 "increase the amount of blobs by 50%" applied, linear
    between."""
    lo = alone("heart", wsk.LEVEL_FLOOR, tail_frames=2)
    hi = alone("heart", 1.0, tail_frames=2)
    # the floor Energy is 0.01, not 0 (word_shape_keys.LEVEL_FLOOR: 0 means
    # NOT TOLD), so the quietest word a scene can get is one spark over the
    # quiet count — 90 + 60 x 0.01, rounded
    assert lo.total_sparks == 91
    assert hi.total_sparks == 150
    mid = alone("heart", 0.5, tail_frames=2)
    assert mid.total_sparks == 120


def test_a_saturated_show_plus_the_loud_burst_fits_in_the_capacity():
    """W4.3's headroom. The shaped sparks are UNCAPPED (`p_nocap`), so they
    are bounded only by the module's own CAP: 150 of them on top of a show
    saturating his `max_blobs` of 100 is 250 of 1024, so the burst can never
    be clipped by the array and the ordinary show can never be starved by
    it. The clamp exists anyway (`_word_shape_burst`'s `CAP - self.n`), and
    this is the arithmetic that says it is unreachable in his room."""
    from fx.effects.fireworks import CAP, Fireworks2d
    schema = {str(k): k.default() for k in Fireworks2d.CONFIG_SCHEMA.schema
              if hasattr(k, "default")}
    loud = int(schema["word_shape_sparks_loud"])
    assert loud == 150
    his_cap = int(C.HIS_CFG["max_blobs"])
    assert his_cap + loud <= CAP, (his_cap, loud, CAP)
    # and even the registry's own maximum for the param still fits
    registry = json.loads(
        (REPO / "config" / "effect_params.json").read_text())
    ceiling = registry["effects"]["fireworks"]["params"][
        "word_shape_sparks_loud"]["max"]
    assert his_cap + ceiling <= CAP, (his_cap, ceiling, CAP)


# ── 4. the hang, and the fade ─────────────────────────────────────────────

@pytest.mark.parametrize("shape_id", SHAPES)
def test_the_shape_hangs_through_the_hold_and_is_gone_by_the_release(shape_id):
    run = alone(shape_id, 0.8)
    mid = (run.word_frame + run.hold_end_frame) // 2
    launched = run.state[run.word_frame]["sparks"]
    assert launched == run.total_sparks
    assert run.state[mid]["sparks"] == launched, "a spark died in the hold"
    assert run.state[mid]["hanging"] is True
    end = min(run.release_end_frame, len(run.state) - 1)
    left = run.state[end]["sparks"]
    assert left <= 0.1 * launched, (
        f"{left} of {launched} sparks were still lit at the release's end")
    # and they went one at a time, not in a step: somewhere in the release
    # the count is between
    middling = [s["sparks"] for s in run.state[run.hold_end_frame:end]]
    assert any(0 < v < launched for v in middling)


@pytest.mark.parametrize("burst_life,expected", [(1.9, 2.0), (1.2, 3.0)])
def test_the_shaped_sparks_hang_longer_than_the_others(
        burst_life, expected, capsys):
    """"hang longer than the others", measured rather than asserted from the
    told times. A shaped spark's whole life is the told form + hold + its
    own share of the release; an ordinary burst's is `burst_life` times
    `uniform(0.7, 1.15)`, so its MEAN is 0.925 x burst_life.

    THE PLAN'S "about twice as long" IS AGAINST THE EFFECT'S DEFAULT
    `burst_life` (1.2 s), where this comes out at about 2x. HIS OWN Matrix
    entry carries 1.9 s — he tuned ordinary bursts to be long-lived — so
    against the show he actually runs it is about 1.3x. Both are measured
    here and stated in the skill rather than rounded to the plan's phrase:
    the shape's duration is the told envelope's, which is the room's
    setting, not this effect's to stretch.

    W4.3 MOVED BOTH NUMBERS WITHOUT TOUCHING EITHER LEVER. A shaped spark
    now lives THE FLIGHT (not the whole form) plus the hold plus its own
    share of the release — it is not born until WORD_SHAPE_FLIGHT_S before
    the word — but the release is 1.5x the FORM, and the form is floored at
    2.0 s, so the release is 3.0 s and the spark outlives W1.2's by a long
    way. Neither this effect nor this row chose that: the ratio is the
    ROOM's two settings and the planner's floor."""
    run = alone("heart", 0.8, config={"burst_life": burst_life})
    shaped = (FX.WORD_SHAPE_FLIGHT_S + run.hold_s
              + (0.45 + 1.0) / 2 * run.release_s)
    ordinary = 0.925 * burst_life
    with capsys.disabled():
        print(f"  burst_life {burst_life}: a shaped spark lives "
              f"{shaped:.2f} s on average against an ordinary burst's "
              f"{ordinary:.2f} s ({shaped / ordinary:.2f}x)")
    assert run.state[run.word_frame]["sparks"] > 0
    assert shaped / ordinary >= expected
    # and that is what the effect really gave them, not arithmetic about it
    assert run.sparks_life_mean == pytest.approx(shaped, abs=0.2), (
        run.sparks_life_mean, shaped)


def test_the_hang_follows_the_told_hold_and_nothing_here_stretches_it():
    """W4.2 is what made the hold half again as long, by telling a longer
    `word_shape_hold_s`; W4.3 changes NOTHING about it. So the proof is that
    the hang is the TOLD number: tell two holds and the shape stands for
    each of them, measured on the effect's own `hanging` flag and on the
    sparks still alive."""
    short = alone("heart", 0.8, phrase_s=0.9, tail_frames=2)
    long_ = alone("heart", 0.8, phrase_s=1.8, tail_frames=2)
    assert short.hold_s == pytest.approx(0.9)
    assert long_.hold_s == pytest.approx(1.8)
    for run in (short, long_):
        hanging = [i for i, st in enumerate(run.state) if st["hanging"]]
        assert hanging, "the shape never arrived"
        # it hangs from the word to the end of the told hold, within a frame
        assert abs(hanging[0] - run.word_frame) <= 1, (
            hanging[0], run.word_frame)
        assert run.state[run.hold_end_frame - 1]["sparks"] == \
            run.total_sparks, "a spark died before the hold was over"
    # ... and a hold 1.5x as long really does stand 1.5x as long
    ratio = (long_.hold_end_frame - long_.word_frame) / \
        max(short.hold_end_frame - short.word_frame, 1)
    assert ratio == pytest.approx(1.8 / 0.9, abs=0.05)


def test_the_sparks_hang_where_they_arrived_rather_than_drifting_on():
    """The hang damps their velocity: the shape standing at mid-hold is
    within a cell of the shape that arrived on the word."""
    run = alone("heart", 0.8)
    mid = (run.word_frame + run.hold_end_frame) // 2
    out, fill = C.cell_sets(word_shapes.get("heart"), panel(), 0.62)
    cov_word, _r, _o, _f = C.measure_frame(
        run.frames[run.word_frame], panel(), out, fill)
    cov_mid, _r2, _o2, _f2 = C.measure_frame(
        run.frames[mid], panel(), out, fill)
    assert cov_mid >= cov_word - 0.1, (cov_word, cov_mid)


# ── 5. the clarity bar, on the real mask ──────────────────────────────────

@pytest.mark.parametrize("shape_id", SHAPES)
@pytest.mark.parametrize("energy", ENERGIES)
def test_it_reads_as_the_shape_on_his_real_crystal(shape_id, energy, capsys):
    """THE ROW'S CLARITY BAR (plan section 3.6): on the word, the sparks
    light at least 70% of the shape's outline cells, and the inside's mean
    brightness is at most 0.70 of the outline's — an outline, not a blob.
    The denominators are scripts/check_word_shapes.py's own (heart 168
    outline cells, star 176, diamond 119 at SIZE 0.62), so a changed
    outline is a deliberate change to a pinned test and not a drifting
    bar."""
    run = alone(shape_id, energy)
    for m in C.measure_run(run, panel(), 0.62):
        with capsys.disabled():
            print(f"  {shape_id:8s} energy {energy:.1f} {m.at:9s}: "
                  f"{m.coverage:6.1%} of {m.outline_cells} outline cells, "
                  f"fill ratio {m.fill_ratio:.2f} "
                  f"({m.inside_mean:.3f} / {m.outline_mean:.3f})")
        if m.at == "word":
            assert m.coverage >= C.COVERAGE_BAR, (
                f"{shape_id} at Energy {energy}: {m.coverage:.1%} of the "
                f"outline cells lit (bar {C.COVERAGE_BAR:.0%})")
            assert m.fill_ratio <= C.FILL_BAR, (
                f"{shape_id} at Energy {energy}: the inside is "
                f"{m.fill_ratio:.2f} of the outline's brightness "
                f"(bar {C.FILL_BAR:.2f})")


@pytest.mark.parametrize("shape_id", SHAPES)
@pytest.mark.parametrize("energy", ENERGIES + (1.0,))
def test_the_band_stands_out_from_the_rest_of_the_panel(
        shape_id, energy, capsys):
    """W4.3's CONTRAST BAR, because legibility on the dark canvas is the
    whole point of the row. A ">= LIT" coverage share is vacuous the moment
    anything else is trailing (the W1.4 Fish review's discipline, carried to
    every wave-4 row), so the shape's own outline band is graded by
    LUMINANCE and read against the rest of his real panel: the band's mean
    luminance at least CONTRAST_BAR times the rest's, at the word AND at
    mid-hold."""
    run = alone(shape_id, energy)
    outline, _fill = C.cell_sets(word_shapes.get(shape_id), panel(), 0.62)
    mid = (run.word_frame + run.hold_end_frame) // 2
    for label, idx in (("word", run.word_frame), ("mid-hold", mid)):
        lo, hi, ratio = C.band_contrast(run.frames[idx], panel(), outline)
        with capsys.disabled():
            print(f"  {shape_id:8s} energy {energy:.1f} {label:9s}: "
                  f"{lo:5.1%} of the band >= 64/255, {hi:5.1%} >= 128/255, "
                  f"band/rest luminance {ratio:5.2f}x")
        assert ratio >= C.CONTRAST_BAR, (
            f"{shape_id} at Energy {energy} ({label}): the band is "
            f"{ratio:.2f}x the rest of the panel (bar {C.CONTRAST_BAR:.1f})")


def test_nothing_jumps_over_the_form_or_the_release(capsys):
    """Plan section 6's third bar — READ ON LIGHT SINCE W4.3, and the
    reason is arithmetic rather than convenience.

    W1.2's form of the bar is the largest frame-to-frame change in LIT
    CELLS as a share of the lit count, over the form and over the release.
    THE HUSH DRIVES THAT DENOMINATOR TO ZERO ON PURPOSE: the panel is
    deliberately dark when the burst leaves, so the first spark is an
    unbounded relative change and the measured number (2300-3300%) is about
    the lit threshold, not about anything a viewer would call a jump. The
    old number is still printed here — a bar is not quietly dropped — and
    the bar itself is asserted on the panel's own MEAN LIGHT over each of
    the shape's four stretches, against THE EFFECT'S OWN ORDINARY MAXIMUM
    (row W1.3's own wording): the same seed's untold worst over the same
    span.

    The comparator is the span's worst and not each stretch's own,
    deliberately: the hush MOVES when this effect's busiest frames happen
    (the release's return lands on an emptied panel instead of a full one),
    so a per-stretch comparison would put a shifted show beside an
    unshifted one. Both numbers are printed."""
    for shape_id in SHAPES:
        run = run_for(shape_id, 0.8)
        twin = run_for(shape_id, 0.8, told=False)
        wins = C.shape_windows(run, len(run.frames))
        told_j = C.light_jumps(run, panel(), wins)
        twin_j = C.light_jumps(twin, panel(), wins)
        own_worst = max(twin_j.values())
        with capsys.disabled():
            print(f"  {shape_id:8s}: lit-count ratio "
                  f"{C._worst_jump(run):.0%} with the shape, "
                  f"{C._worst_jump(twin):.0%} without it (W1.2's form, "
                  f"printed not asserted)")
            for name, value in told_j.items():
                print(f"    {name:18s}: light moves {value:.4f} told, "
                      f"{twin_j[name]:.4f} untold here, own worst "
                      f"{own_worst:.4f}")
        for name, value in told_j.items():
            assert value <= own_worst + 1e-6, (
                f"{shape_id} over {name}: the panel's mean light moves "
                f"{value:.4f} in one frame against this effect's own untold "
                f"worst of {own_worst:.4f} over the same span")


# ── 6. no white ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("shape_id", SHAPES)
def test_the_shape_alone_lights_no_white_cell(shape_id):
    """The row's own bar, at its strictest: in a quiet room the shape is the
    only thing on the panel, and not one of its cells comes out white — the
    colours are the set's gradient by position, and the shape never adds a
    white core the way a saturated pile of sparks does."""
    run = alone(shape_id, 0.8)
    worst = max(C.white_share(run.frames[i], panel())
                for i in range(run.edge_frame,
                               min(run.release_end_frame + 1,
                                   len(run.frames))))
    assert worst == 0.0, f"{shape_id}: {worst:.2%} of its lit cells are white"


def test_the_live_show_white_is_recorded_above_the_plans_letter(capsys):
    """THE ONE NUMBER THIS ROW DOES NOT CLEAR, pinned so it cannot drift
    unnoticed. Plan section 6's fifth bar asks for "no higher than the
    effect's own busy frames today". The shape ALONE lights no white cell
    at all (the test above) — but over a LIVE show the room's own beat
    bursts cross the standing sparks, and where they do the two colours ADD:
    the worst frame carries about ten more washed-out cells than the same
    show without a shape (1.7-2.0% of the lit cells against the room
    alone's ~0.6% and the effect's own Firework Burst flare's ~0.5% over the
    same frames).

    It is the same mechanism the effect already shows wherever two of its
    own fireworks share a cell inside the trail's memory, and nothing an
    effect-level knob reaches changes it — all measured (2026-11-17), so
    nobody re-chases it: not brightness (1.63-2.01% at shaped-spark
    brightness 1.0, 0.8 and 0.65 alike); NOT the per-frame composite, which
    is the one that looks like the answer (summing, a per-channel
    `np.maximum` and a per-cell winner-takes-all over two frames all give
    the heart the SAME 1.74%, at most 0.23 points on the diamond — that
    two-pass version was built, measured and not kept, it cost +0.2-0.4 ms
    p50 for that); and not the trail length in the other direction
    (`trail_decay` 0.27 -> 0.0 RAISES the share to 2.95-3.63%, the room's
    own lit cells leaving the denominator faster than the washed-out ones
    leave the numerator). The cause is `self.trail` being a channel-wise MAX
    over TIME, so a cell holding the shape's hue and a passing burst's hue
    from a NEIGHBOURING frame has every channel high whatever this frame
    did. The levers left are the Admiral's: accept it, or change how this
    effect trails, which is its look.

    So this test does not claim the bar: it RECORDS the measured number and
    fails only if it gets worse, which is what "report the number rather
    than move the bar" means in a test.

    W4.3 RE-MEASURES IT at Energy 1.0 as well as 0.8, for all three shapes,
    because 150 sparks overlap deeper on the outline than W1.2's 100 did.
    What actually moved was not the sparks but the WINDOW and the hush: the
    2.0 s form makes the measured span two and a half times longer (so the
    untold comparator itself rose, 0.62% -> 1.46%), and the hush takes the
    room's own bursts away for the whole form and hold, so most rows now sit
    AT OR BELOW the room's own number over the same frames. If it ever does
    rise with the spark count, the levers are WORD_SHAPE_GRAD_SPAN and
    WORD_SHAPE_LAUNCH_PITCH — and the trade is his, since a narrower
    gradient slice is less of his colour set on the shape. His 2026-11-17
    ruling stands: option A, ship as built, his to judge by eye."""
    for shape_id in SHAPES:
        for energy in (0.8, 1.0):
            run = run_for(shape_id, energy)
            twin = run_for(shape_id, energy, told=False)
            flare = run_for(shape_id, energy, told=False, flare=True)
            lo = run.edge_frame
            hi = min(run.release_end_frame + 1, len(run.frames))
            during = max(C.white_share(run.frames[i], panel())
                         for i in range(lo, hi))
            room = max(C.white_share(twin.frames[i], panel())
                       for i in range(lo, hi))
            own = max(C.white_share(flare.frames[i], panel())
                      for i in range(lo, hi))
            with capsys.disabled():
                print(f"  {shape_id:8s} energy {energy:.1f}: {during:.2%} "
                      f"of lit cells white-ish with the shape, {room:.2%} "
                      f"with the room alone, {own:.2%} with the effect's "
                      f"own Firework Burst flare instead "
                      f"{'(ABOVE, reported)' if during > max(room, own) else '(within the bar)'}")
            # the measured envelope, not the bar: a regression guard
            assert during <= 0.025, (shape_id, energy, during, room, own)


# ── 7. additive: the ordinary show is untouched ───────────────────────────

def test_the_shaped_burst_is_additive_except_the_hush(tmp_path):
    """tests/test_firework_burst.py's own additive proof, REWRITTEN TO W4.3's
    RULE. His 2026-11-17 verdict retires W1.2's "the ordinary particles are
    untouched across the edge" — "no fireworks fire right before, or
    concurrently" is exactly a statement that they are touched. What holds
    now:

      * ordinary sparks are SHORTENED, never killed: each one's remaining
        life is capped at its own share of WORD_SHAPE_HUSH_FADE_S, so it
        fades out rather than blinking out, and nothing else about it moves
        — it keeps its age, its colour and its motion;
      * ordinary LAUNCHES are withheld from the edge to the hold's end;
      * everything else is as additive as it was: the shaped sparks are
        appended after the live ones, flagged, uncapped, and the density cap
        the ordinary show reads is exactly the one it had."""
    async def main():
        host, virtual = await C._host(tmp_path, "additive",
                                      C.crystal_mask(panel()))
        try:
            with headless.fake_clock() as clock:
                cfg = dict(C.HIS_CFG)
                cfg["max_blobs"] = 20       # the 2-D effect's own minimum
                eff = headless.attach_effect(host, virtual, "fireworks", cfg)
                eff._rng = np.random.default_rng(7)
                for i in range(60):
                    eff.audio_data_updated(C.BusyAudio(i))
                    clock.advance(DT)
                    out = virtual.assemble_frame()
                    if out is not None:
                        virtual.flush(out)
                pre_n = eff.n
                assert pre_n > 0, "no ordinary show to be additive to"
                pre_age = eff.p_age[:pre_n].copy()
                pre_life = eff.p_life[:pre_n].copy()
                pre_grad = eff.p_grad[:pre_n].copy()
                pre_x = eff.p_x[:pre_n].copy()
                room_before = eff._capacity()

                # a told form that makes the burst launch on the same frame
                # (flight = form), so this is the W1.2 comparison frame
                eff.update_config(wsk.keys_for("heart", 1, 0.5, 1.0, 0.75, 0.8))
                eff.audio_data_updated(C.BusyAudio(60))
                clock.advance(DT)
                out = virtual.assemble_frame()
                if out is not None:
                    virtual.flush(out)
                alive = eff.p_age[:pre_n] < eff.p_life[:pre_n]
                assert alive.all(), "an ordinary particle was killed"
                assert eff.p_age[:pre_n] == pytest.approx(pre_age + DT,
                                                          abs=1e-5)
                # THE ONE THING W4.3 CHANGED: their lives were capped, each
                # one to its own share of the hush's fade, and never
                # lengthened
                left = eff.p_life[:pre_n] - eff.p_age[:pre_n]
                assert (eff.p_life[:pre_n] <= pre_life + 1e-5).all()
                assert (left <= FX.WORD_SHAPE_HUSH_FADE_S + 1e-5).all(), (
                    float(left.max()))
                lo, hi = FX.WORD_SHAPE_HUSH_FADE_FRAC
                shortened = eff.p_life[:pre_n] < pre_life - 1e-5
                assert shortened.any(), "nothing was shortened at all"
                assert left[shortened].min() >= (
                    lo * FX.WORD_SHAPE_HUSH_FADE_S - DT - 1e-5)
                assert left[shortened].max() <= (
                    hi * FX.WORD_SHAPE_HUSH_FADE_S + 1e-5)
                assert float(np.unique(np.round(left[shortened], 4)).size) > 1, (
                    "every spark was given the SAME remaining life — they "
                    "would all reach zero on one frame, which is the cliff "
                    "the staggered window exists to avoid")
                # ... and nothing else about them moved
                assert eff.p_grad[:pre_n] == pytest.approx(pre_grad)
                assert not np.array_equal(eff.p_x[:pre_n], pre_x), (
                    "the ordinary particles stopped moving")
                shaped = eff.p_wfade[:eff.n] > 0.0
                assert shaped.sum() == 138           # 90 + 60 x 0.8
                assert not shaped[:pre_n].any(), "an old particle was flagged"
                # uncapped: the shape never occupies max_blobs, so the
                # ordinary show has exactly the room it had
                assert (eff.p_nocap[:eff.n][shaped] == 1.0).all()
                assert eff._capacity() == room_before
        finally:
            await host.shutdown()

    asyncio.run(main())


# ── 7b. THE HUSH: the dark canvas (W4.3) ──────────────────────────────────

def _hush_effect(tmp_path, tag, cfg=None):
    """One attached effect on the real mask AT HIS SCENE'S BUSIEST BINDING
    (`C.WORST_CFG`), with a counter on its own `_spawn_burst` — so "not one
    ordinary launch" is counted at the call rather than inferred from the
    picture. `_beat_step` is the stepper; it chooses the audio."""
    async def start():
        host, virtual = await C._host(tmp_path, tag, C.crystal_mask(panel()))
        cm = headless.fake_clock()
        clock = cm.__enter__()
        eff = headless.attach_effect(host, virtual, "fireworks",
                                     {**C.HIS_CFG, **C.WORST_CFG,
                                      **(cfg or {})})
        eff._rng = np.random.default_rng(7)
        calls = []
        real = eff._spawn_burst

        def counting(*a, **kw):
            calls.append(1)
            return real(*a, **kw)

        eff._spawn_burst = counting
        return host, virtual, cm, clock, eff, calls

    return start


def _beat_step(virtual, clock, eff, n, i0=0, audio=None):
    audio = audio or C.Beat120Audio
    for i in range(n):
        eff.audio_data_updated(audio(i0 + i))
        clock.advance(DT)
        out = virtual.assemble_frame()
        if out is not None:
            virtual.flush(out)


HUSH_FORM, HUSH_HOLD = 2.0, 1.2
HUSH_KEYS = dict(form_s=HUSH_FORM, hold_s=HUSH_HOLD,
                 release_s=1.5 * HUSH_FORM, level=1.0)


def _told(seq=1, shape="heart", **kw):
    k = dict(HUSH_KEYS)
    k.update(kw)
    return wsk.keys_for(shape, seq, k["form_s"], k["hold_s"],
                        k["release_s"], k["level"])


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_not_one_ordinary_launch_happens_inside_the_hush(tmp_path, seed):
    """HIS ASK, MEASURED AT THE CALL: "make sure no fireworks fire right
    before, or concurrently". From the SEQ edge to the END OF THE HOLD the
    effect makes NO `_spawn_burst` call of any kind — the spawn rate, the
    beat bursts and the drop tail's shower all withheld — and launching
    resumes with the RELEASE, because W1.2's vision ends "the ordinary
    fireworks carry on around them". Driven with real 120 bpm beats at his
    scene's busiest binding, across seeds."""
    async def main():
        host, virtual, cm, clock, eff, calls = await _hush_effect(
            tmp_path, f"hush{seed}")()
        eff._rng = np.random.default_rng(seed)
        try:
            _beat_step(virtual, clock, eff, 60)
            assert len(calls) > 0, "nothing was launching to begin with"
            eff.update_config(_told())
            calls.clear()
            hush_frames = int(round((HUSH_FORM + HUSH_HOLD) / DT))
            _beat_step(virtual, clock, eff, hush_frames, 60)
            assert len(calls) == 0, (
                f"{len(calls)} ordinary launches happened inside the hush")
            assert eff.word_shape_state()["sparks"] > 0, (
                "the shaped burst itself never fired")
            # ... and the release opens launching again
            _beat_step(virtual, clock, eff, int(round(1.0 / DT)),
                       60 + hush_frames)
            assert len(calls) > 0, (
                "the ordinary fireworks never came back on the release")
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_a_flare_poke_inside_the_hush_is_dropped_not_deferred(tmp_path):
    """A `burst_rockets` poke landing in the hush spawns NOTHING, and it is
    not held over to the release either — the pre-drop breath's own swallow
    (`_pre_drop_step`). The key is still self-reset, so an identical later
    write edges again."""
    async def main():
        host, virtual, cm, clock, eff, _calls = await _hush_effect(
            tmp_path, "hushpoke")()
        try:
            _beat_step(virtual, clock, eff, 10, audio=C.QuietAudio)
            eff.update_config(_told())
            _beat_step(virtual, clock, eff, 6, 10, audio=C.QuietAudio)
            before = eff.n
            eff.update_config({"burst_rockets": 6})
            _beat_step(virtual, clock, eff, 2, 16, audio=C.QuietAudio)
            assert eff.n == before, (
                f"{eff.n - before} particles came from a flare poke the hush "
                f"should have dropped")
            assert eff._burst_pending == 0
            assert int(eff._config["burst_rockets"]) == 0, (
                "the key was not self-reset, so an identical later write "
                "could not edge")
            # it is DROPPED, not deferred: nothing of it appears later
            rest = int(round((HUSH_FORM + HUSH_HOLD) / DT))
            _beat_step(virtual, clock, eff, rest, 18, audio=C.QuietAudio)
            shaped = int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0))
            assert eff.n == shaped, (
                f"{eff.n - shaped} unshaped particles appeared — a withheld "
                f"poke was deferred rather than dropped")
            # ... and a poke AFTER the hold's end lands as it always did
            eff.update_config({"burst_rockets": 6})
            _beat_step(virtual, clock, eff, 2, 18 + rest, audio=C.QuietAudio)
            assert eff.n > shaped, "the flare never came back"
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_the_canvas_is_mostly_dark_when_the_shape_arrives(capsys):
    """W4.3'S HEADLINE BAR, on his real mask at his scene's busiest binding
    (`beat_burst` 6 x `burst_size` 14 a beat at Energy 1.0, each spark
    living 1.9 s into a `max_blobs` of 100 — the clutter his verdict is
    about), over 20 seeds at 120 bpm: ON THE WORD, ordinary (non-shaped)
    light covers at most 5% of his real cells at 20/255. The SAME SEED
    untold is printed beside it — that difference IS the clutter the hush
    takes away."""
    real_cells = int(panel().grid.sum())
    shares, twins, launches = [], [], []
    for seed in range(1, C.CANVAS_SEEDS + 1):
        kw = dict(energy=1.0, config=C.WORST_CFG,
                  audio_cls=C.Beat120Audio, settle_frames=60,
                  stop_at_hold_end=True, seed=seed)
        run = run_for("heart", no_burst=True, **kw)
        twin = run_for("heart", told=False, **kw)
        shares.append(run.canvas[run.word_frame] / real_cells)
        twins.append(twin.canvas[twin.word_frame] / real_cells)
        launches.append(sum(
            run.launches[run.edge_frame:run.hold_end_frame + 1]))
    with capsys.disabled():
        print(f"  the canvas on the word over {C.CANVAS_SEEDS} seeds: worst "
              f"{max(shares):.2%} of {real_cells} real cells, median "
              f"{float(np.median(shares)):.2%} — against the same seeds "
              f"untold, worst {max(twins):.2%}, median "
              f"{float(np.median(twins)):.2%}")
        print(f"  ordinary launches inside the hush: {max(launches)} at "
              f"worst")
    assert max(shares) <= C.CANVAS_BAR, (
        f"the canvas carries {max(shares):.2%} of his real cells of ordinary "
        f"light on the word (bar {C.CANVAS_BAR:.0%})")
    assert max(launches) == 0, max(launches)
    # and the untold show really was the cluttered one, or the bar is empty
    assert min(twins) > 4 * C.CANVAS_BAR, (
        "the untold show was not busy, so this measures nothing")


def test_an_ordinary_sparks_remaining_life_is_capped_at_the_edge(tmp_path):
    """What is already in the air is NOT killed — blinking a panel full of
    sparks out in one frame is exactly the jump the plan bars. Each one's
    remaining life is capped at its own share of WORD_SHAPE_HUSH_FADE_S, so
    they fade out a few at a time, and the panel really is empty by the
    time the burst leaves."""
    async def main():
        host, virtual, cm, clock, eff, _calls = await _hush_effect(
            tmp_path, "hushcap")()
        try:
            _beat_step(virtual, clock, eff, 60)
            n = eff.n
            assert n > 20, n
            long_lived = int(np.count_nonzero(
                (eff.p_life[:n] - eff.p_age[:n])
                > FX.WORD_SHAPE_HUSH_FADE_S))
            assert long_lived > 0, "nothing had a long enough life to cap"
            eff.update_config(_told())
            _beat_step(virtual, clock, eff, 1, 60)
            n = eff.n
            ordinary = eff.p_wfade[:n] <= 0.0
            left = (eff.p_life[:n] - eff.p_age[:n])[ordinary]
            assert left.size
            assert float(left.max()) <= FX.WORD_SHAPE_HUSH_FADE_S + 1e-5
            # ... and by the launch the panel is empty of them
            launch = int(round((HUSH_FORM - FX.WORD_SHAPE_FLIGHT_S) / DT))
            _beat_step(virtual, clock, eff, launch, 61)
            n = eff.n
            assert int(np.count_nonzero(eff.p_wfade[:n] <= 0.0)) == 0, (
                "an ordinary spark was still alive when the burst left")
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_a_phase_arriving_during_the_hush_ends_it(tmp_path):
    """P3 A means a shape is never TOLD while a charge, lull or drop is
    armed — but one that ARRIVES on a standing shape owns the panel. The
    drop payoff and its tail fire exactly as they do today, and the shaped
    sparks, additive, keep flying or hanging over them."""
    async def main():
        host, virtual, cm, clock, eff, calls = await _hush_effect(
            tmp_path, "hushdrop")()
        try:
            _beat_step(virtual, clock, eff, 10, audio=C.QuietAudio)
            eff.update_config(_told())
            # past the launch, so the shape is in the air when the drop lands
            _beat_step(virtual, clock, eff,
                       int(round((HUSH_FORM - 0.3) / DT)), 10,
                       audio=C.QuietAudio)
            shaped_before = int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0))
            assert shaped_before > 0
            assert eff.word_shape_state()["hushed"] is True
            n_before = eff.n
            calls.clear()
            eff.update_config({"phase": "drop", "phase_progress": 1.0})
            _beat_step(virtual, clock, eff, 2, 200, audio=C.QuietAudio)
            assert eff.word_shape_state()["hushed"] is False, (
                "a phase arriving must end the hush — the panel is the "
                "drop's")
            assert eff.n > n_before, "the drop payoff never burst"
            # the shape is still there, on its own clock
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == \
                shaped_before
            # ... and the drop TAIL showers too, which the payoff's own
            # bursts above would otherwise have stood in for (they go
            # through `_spawn_burst` as well, so the counter is cleared
            # before the tail's own second is measured)
            calls.clear()
            _beat_step(virtual, clock, eff, int(round(1.0 / DT)), 202,
                       audio=C.QuietAudio)
            assert len(calls) > 0, "the drop tail was still being withheld"
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


# ── 8. the edges ──────────────────────────────────────────────────────────

def _effect(tmp_path, tag, cfg=None):
    """One attached effect on the real mask, and a frame-stepper for it."""
    async def start():
        host, virtual = await C._host(tmp_path, tag, C.crystal_mask(panel()))
        cm = headless.fake_clock()
        clock = cm.__enter__()
        eff = headless.attach_effect(host, virtual, "fireworks",
                                     {**C.HIS_CFG, **(cfg or {})})
        eff._rng = np.random.default_rng(7)
        return host, virtual, cm, clock, eff

    return start


def _step(virtual, clock, eff, n, i0=0):
    for i in range(n):
        eff.audio_data_updated(C.QuietAudio(i0 + i))
        clock.advance(DT)
        out = virtual.assemble_frame()
        if out is not None:
            virtual.flush(out)


def test_two_words_of_the_same_shape_both_fire_and_neither_snaps(tmp_path):
    """The SEQ is the edge, never the id (word_shape_keys): two hearts back
    to back both burst. A second word arriving mid-release never snaps the
    first away — its sparks keep fading on their own clock, which is this
    effect's "nothing to blend" (section 3.6's release)."""
    async def main():
        host, virtual, cm, clock, eff = await _effect(tmp_path, "twice")()
        try:
            _step(virtual, clock, eff, 10)
            eff.update_config(wsk.keys_for("heart", 1, 0.5, 0.8, 0.75, 0.5))
            _step(virtual, clock, eff, 2, 10)
            first = eff.n
            assert first == 120           # 90 + 60 x 0.5
            # mid-RELEASE of the first (form + hold + half the release)
            _step(virtual, clock, eff, int(round((0.5 + 0.8 + 0.37) / DT)), 12)
            held = eff.p_wfade[:eff.n] > 0.0
            fading = int(held.sum())
            assert 0 < fading < 120, fading
            lit_before = float(eff.p_shown[:eff.n][held].mean())
            # every first-burst spark's time left, sorted: an identity that
            # survives compaction (which moves a dead particle's slot)
            left_before = np.sort(
                (eff.p_life[:eff.n] - eff.p_age[:eff.n])[held])
            eff.update_config(wsk.keys_for("heart", 2, 0.5, 0.8, 0.75, 0.5))
            _step(virtual, clock, eff, 2, 100)
            # the second burst landed ON TOP. The two are told apart by AGE,
            # never by slot: the first's survivors are over a second old,
            # the second's sparks two frames.
            held = eff.p_wfade[:eff.n] > 0.0
            age = eff.p_age[:eff.n]
            old = held & (age > 0.5)
            new = held & (age <= 0.5)
            assert int(new.sum()) == 120, "the second word never fired"
            assert int(old.sum()) > 0, (
                "the second word took the first's sparks with it")
            # THE FIRST BURST WAS NEVER RE-TIMED AND NEVER CUT SHORT: its
            # survivors are exactly the longest-lived of the sparks that
            # were fading, each two frames further through its OWN clock —
            # the ones missing are the ones whose own p_life ran out.
            left_after = np.sort(
                (eff.p_life[:eff.n] - eff.p_age[:eff.n])[old])
            assert left_after == pytest.approx(
                left_before[-len(left_after):] - 2 * DT, abs=1e-4)
            # and dimmer than they were, never re-lit
            assert float(eff.p_shown[:eff.n][old].mean()) < lit_before
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_a_clearing_write_mid_shape_takes_nothing_away(tmp_path):
    """`told() is None` mid-shape: there is nothing to blend down, because
    every spark is already on its own clock. Nothing is killed, nothing is
    re-lit, and the shape finishes its own fade.

    W4.3 adds one thing it DOES take away: THE HUSH. A clearing write says
    no shape is standing, and holding the panel dark for a shape that will
    never arrive is worse than doing nothing, so launching resumes at once —
    while the sparks already in the air go on fading untouched."""
    async def main():
        host, virtual, cm, clock, eff = await _effect(tmp_path, "clear")()
        try:
            _step(virtual, clock, eff, 10)
            eff.update_config(wsk.keys_for("heart", 1, 0.5, 1.2, 0.75, 0.8))
            _step(virtual, clock, eff, int(round((0.5 + 0.4) / DT)), 10)
            held = int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0))
            assert held == 138           # 90 + 60 x 0.8
            lit_before = int(np.count_nonzero(eff.p_shown[:eff.n] > 0.01))
            assert eff.word_shape_state()["hushed"] is True
            eff.update_config(dict(wsk.NOT_TOLD))
            assert eff.word_shape_state()["hushed"] is False, (
                "a clearing write must let the ordinary fireworks back")
            _step(virtual, clock, eff, 1, 60)
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == held
            lit_after = int(np.count_nonzero(eff.p_shown[:eff.n] > 0.01))
            assert lit_after >= lit_before - 2
            # and it does die on its own clock
            _step(virtual, clock, eff, int(round(2.0 / DT)), 61)
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == 0
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_a_form_shorter_than_any_minimum_is_clamped_not_a_divisor(tmp_path):
    """A form shorter than the effect's own minimum is impossible by
    contract (the engine floors it), so this is only about handling it
    gracefully: a told form of 0 clamps to the module's own floor, the
    sparks still fly out and arrive, and nothing divides by zero."""
    async def main():
        host, virtual, cm, clock, eff = await _effect(tmp_path, "zeroform")()
        try:
            _step(virtual, clock, eff, 5)
            eff.update_config(wsk.keys_for("heart", 1, 0.0, 0.8, 0.0, 0.8))
            _step(virtual, clock, eff, 2, 5)
            held = eff.p_wfade[:eff.n] > 0.0
            assert held.sum() == 138
            assert np.isfinite(eff.p_vx[:eff.n]).all()
            assert np.isfinite(eff.p_vy[:eff.n]).all()
            # it still flies rather than teleporting: after the clamped
            # form the sparks are out at the shape's own radius
            _step(virtual, clock, eff, int(round(0.2 / DT)), 7)
            held = eff.p_wfade[:eff.n] > 0.0
            r = np.hypot(eff.p_x[:eff.n][held], eff.p_y[:eff.n][held])
            assert r.max() > 0.2
            assert np.isfinite(r).all()
            # and a told release of 0 still fades rather than stepping out
            assert (eff.p_wfade[:eff.n][held] > 0.0).all()
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_a_stale_persisted_seq_never_fires_on_a_fresh_instance(tmp_path):
    """The phase-key creation-baseline rule (the burst_rockets one): an
    instance built from a config that already carries a shape and a SEQ — a
    restart between the word and the next frame — must NOT burst, and a
    LATER write of the SAME seq must not either (it is not an edge), while
    the next seq fires normally."""
    stale = wsk.keys_for("heart", 7, 0.5, 0.8, 0.75, 0.8)

    async def main():
        host, virtual, cm, clock, eff = await _effect(
            tmp_path, "stale", cfg=stale)()
        try:
            _step(virtual, clock, eff, 5)
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == 0
            eff.update_config(dict(stale))        # the same seq: no edge
            _step(virtual, clock, eff, 2, 5)
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == 0
            eff.update_config(wsk.keys_for("heart", 8, 0.5, 0.8, 0.75, 0.8))
            _step(virtual, clock, eff, 2, 7)
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == 138
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_an_unknown_shape_id_is_not_told_at_all(tmp_path):
    """word_shape_keys' own rule: an id this build does not know reads as
    NOT TOLD (a newer SpotFX must not make the effect draw nothing-shaped),
    so nothing fires."""
    async def main():
        host, virtual, cm, clock, eff = await _effect(tmp_path, "unknown")()
        try:
            _step(virtual, clock, eff, 5)
            eff.update_config({**wsk.keys_for("heart", 1, 0.5, 0.8, 0.75, 0.8),
                               wsk.SHAPE_KEY: "trapezium"})
            _step(virtual, clock, eff, 3, 5)
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == 0
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


# ── 9. the cost ───────────────────────────────────────────────────────────

def test_the_shape_costs_under_a_millisecond_a_frame(capsys):
    """Plan section 6's sixth bar, measured by the rig: the p50 per-frame
    render cost with the shape holding, against the same show's own frames
    before the word. Reported either way — a bar whose number is not
    printed is not a bar."""
    run = run_for("heart", 0.8)
    twin = run_for("heart", 0.8, told=False)
    lo, hi = run.word_frame, run.hold_end_frame + 1
    during = float(np.median(run.frame_ms[lo:hi]))
    baseline = float(np.median(twin.frame_ms[lo:hi]))
    with capsys.disabled():
        print(f"  p50 render: {baseline:.2f} ms without the shape -> "
              f"{during:.2f} ms with it holding (+{during - baseline:.2f})")
    assert during - baseline < 1.0


# ── 10. the wiring ────────────────────────────────────────────────────────

def test_fireworks_declares_its_own_two_second_minimum_form():
    """W4.3's planner half. The floor is HOW EARLY THE WRITE ARRIVES, which
    is all the hush needs — the effect stops launching at the SEQ edge and
    has 1.2 s to empty the panel before the burst leaves. It lives in
    `fx.device_model`, never as a registered param, because the planner
    needs it before it has asked any effect anything, and it applies ONLY to
    a scene showing this effect (the W0.3 review's own point: the lead IS
    the form, so a global floor would stretch every scene's shape)."""
    assert device_model.WORD_SHAPE_FORM_MIN_S["fireworks"] == 2.0
    assert device_model.word_shape_form_min_s(["fireworks"]) == 2.0
    assert device_model.word_shape_form_min_s(["radial"]) == 0.0
    assert device_model.word_shape_form_min_s(["radial", "fireworks"]) == 2.0
    # ... and it is NOT a registered param
    registry = json.loads(
        (REPO / "config" / "effect_params.json").read_text())
    params = registry["effects"]["fireworks"]["params"]
    assert "word_shape_form_min_s" not in params
    # the room's own resolver really applies it, at both halves' tier
    from spectra.services.room_controls import (RoomControlState,
                                                word_shape_timing)
    st = RoomControlState()
    assert word_shape_timing(1.0, 1000, st, ["fireworks"])[0] == 2.0
    assert word_shape_timing(0.0, 1000, st, ["fireworks"])[0] == 2.0
    assert word_shape_timing(1.0, 1000, st, ["radial"])[0] == 0.5
    # A CONSEQUENCE WORTH STATING: the band fires 2.0 s early, so a COLOUR
    # kind pooled in a Fireworks scene's Words band lands 2.0 s early too —
    # exactly as it already does on Fish, the other declared floor.
    assert device_model.word_shape_form_min_s(["fish"]) == 2.0


def test_only_the_matrix_fireworks_is_wired_for_shapes():
    assert "fireworks" in device_model.WORD_SHAPE_EFFECTS
    assert "fireworks1d" not in device_model.WORD_SHAPE_EFFECTS, (
        "a shape has nowhere to be drawn on one line")
    # and the strip's schema does not carry the told keys
    from fx.effects import fireworks1d
    assert not any(k in str(fireworks1d.Fireworks1d.CONFIG_SCHEMA.schema)
                   for k in (wsk.SHAPE_KEY, wsk.SEQ_KEY))


def test_the_four_tunables_are_registered_and_sonic_tellable():
    registry = json.loads(
        (REPO / "config" / "effect_params.json").read_text())
    params = registry["effects"]["fireworks"]["params"]
    expected = {"word_shape_size": 0.62, "word_shape_outline_share": 0.7,
                "word_shape_sparks_quiet": 90, "word_shape_sparks_loud": 150}
    for name, default in expected.items():
        meta = params.get(name)
        assert meta is not None, f"{name} is not registered"
        assert meta["default"] == default
        assert meta["min"] <= default <= meta["max"]
        assert meta["note"] and meta["label"]
        assert meta["help_topic"] == "fireworks-word-shape"
    # the SIX TOLD KEYS are deliberately NOT registered: they ride only
    # SpotFX's own write (word_shape_keys' rule 1)
    for key in wsk.KEYS:
        assert key not in params, key
    # the effect's own schema defaults agree with the registry's
    from fx.effects.fireworks import Fireworks2d
    schema = {str(k): k.default() for k in Fireworks2d.CONFIG_SCHEMA.schema
              if hasattr(k, "default")}
    for name, default in expected.items():
        assert schema[name] == pytest.approx(default)


def test_the_help_topic_the_params_name_is_a_real_entry():
    """AGENTS.md's help-content rule, and the registry-help convention
    (docs/agents/fx-effects.md): the topic a param names has to exist, or
    the Initial Set tab's HelpLink goes nowhere."""
    content = (REPO / "spectra" / "web" / "src" / "help"
               / "helpContent.ts").read_text()
    assert "id: 'fireworks-word-shape'" in content


def test_the_skill_map_lists_this_rows_files():
    """scripts/check_effect_scene_skills_current.py's own manifest."""
    mapping = json.loads(
        (REPO / ".claude" / "skills" / "EFFECT_SCENE_MAP.json").read_text())
    files = mapping["effects"]["fireworks-effect"]["files"]
    assert "scripts/check_fireworks_word_shape.py" in files
    assert "tests/test_fireworks_word_shape.py" in files


def test_the_shape_library_is_not_primed_on_a_render_frame():
    """`prime()` builds the sdf_fast grid — ~200 ms, which a render frame
    must never pay. This row uses only `at(s)` (the arc-length walk, built
    by `build()`), so no shape it draws ever grows a fast grid."""
    import fx.effects.fireworks as fw
    source = Path(fw.__file__).read_text()
    assert ".prime()" not in source
    assert "sdf_fast" not in source
