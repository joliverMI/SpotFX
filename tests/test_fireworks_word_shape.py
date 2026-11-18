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

ROW W5.6 (his SECOND room verdict, 2026-11-18) RETUNED ALL OF THAT,
verbatim: "I think we overtuned the fireworks last time. The background
doesn't need to be clear of other fireworks, just they need to be dimmer,
so fading out already. I think we can give it 80% less pre-fire darkness
time. It also holds too long and fades too abruptly. And it's too
well-defined. Let's turn back the increase in blob count, and at the end,
the blobs should lightly break apart and fade out. Also, the burst is too
fast. Slow the burst by 60% so we can see the blobs moving out to the
outline, and then decelerating to almost a stop, but not quite a stop. The
blobs should always be slightly drifting." What that row proves here:

  * THE QUIET IS 0.25 s (WORD_SHAPE_HUSH_S), immediately before the launch
    — 80% less than W4.3's 1.2 s — and it is the ONLY withholding left;
  * DIM, NOT DARK: from the edge to the hold's end every ORDINARY spark is
    drawn at WORD_SHAPE_BACKGROUND_DIM (0.40) of its brightness, ramped so
    nothing steps, with launches carrying on through it. The headline bar is
    a DIM one — the ordinary light on the word against the same seeds'
    untold light — bounded on BOTH sides, because "dimmer" is not "clear";
  * 60 SPARKS QUIET, 100 LOUD: W4.3's increase turned back;
  * THE HOLD IS THE ROOM'S OWN AGAIN: `fireworks` left
    `fx.device_model.WORD_SHAPE_HOLD_X` (STAR and the Black Hole keep 1.5);
  * THE BURST IS 60% SLOWER AS A SPEED: a 2.0 s flight whose deceleration
    spans the whole of it (WORD_SHAPE_FLIGHT_HL_S 0.65 s, the shaped
    sparks' own, not the effect's 0.255 s), still arriving ON the word;
  * ALMOST A STOP, NEVER QUITE: the hang keeps 4% of the arrival speed and
    then rides a mean-reverting walk, so no shaped spark's speed is EXACTLY
    zero on any frame of the hold;
  * LIGHTLY BREAK APART AND FADE OUT: the drift grows tenfold outward over
    the release while the fade is linear (WORD_SHAPE_FADE_POWER 1.0) over
    WORD_SHAPE_FADE_FRAC (0.6..1.0), so no spark is gone before 60% of it.

W1.2's own "the ordinary particles are untouched across the edge" is
RETIRED by W4.3's verdict and rewritten to the rule W5.6 leaves:
dimmed, never killed; launches withheld only in the 0.25 s quiet
(test_the_shaped_burst_is_additive_except_the_quiet_and_the_dim).

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


@pytest.mark.parametrize("form_s", [2.25, 2.8])
def test_the_shape_is_complete_on_the_word_through_the_real_engine(
        tmp_path, form_s):
    """The whole path: the real ResponseEngine fires the showing scene's
    Words band, its Word Shape kind writes the six keys to the live
    fireworks virtual, and the effect's own form fraction reaches 1.0 within
    ONE rendered frame of edge + form_s. The engine's own lead is what makes
    that the word (tests/test_word_shape_contract.py proves the lead).

    The two forms are the ones the engine can actually tell this effect —
    its own floor (2.25 s since W5.6: the 0.25 s quiet plus the 2.0 s
    flight) and a longer one from a long phrase. And the burst does not
    leave at the edge: nothing is launched until WORD_SHAPE_FLIGHT_S before
    the word, which is asserted here frame by frame."""
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
                # the EDGE arms the shape and starts the dim; the burst
                # is still in the barrel. Two frames in, the 0.25 s quiet
                # has not started yet on a form this long — it is anchored
                # to the LAUNCH (W5.6), not to the edge
                assert state["armed"] is True, "the told write never landed"
                # THE QUIET IS ANCHORED TO THE LAUNCH (W5.6), so where it
                # starts depends on the told form: at this effect's own
                # floor (quiet + flight) it runs from the edge, and a
                # LONGER form puts it later and leaves the ordinary show
                # launching (dimmed) in front of it
                at_floor = form_s <= (FX.WORD_SHAPE_HUSH_S
                                      + FX.WORD_SHAPE_FLIGHT_S + 1e-9)
                assert state["hushed"] is at_floor, (form_s, at_floor)
                assert 0.0 < state["dim"] <= 1.0, (
                    "the dim never started at the edge")
                assert state["sparks"] == 0, (
                    "the burst left at the edge — there is nothing in front "
                    "of it then")
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
    this effect's lead is floored (2.25 s since W5.6), so Energy no longer
    moves it (every row below reads 2.25 s) — what the sparks are solved
    against is the FLIGHT, the time left to the word at the launch. Both
    told forms the engine can produce are measured: the floor, and a longer
    one from a long phrase.

    W5.6 ALSO CHANGED WHAT DRAG THE SOLVE USES — the shaped sparks' own
    WORD_SHAPE_FLIGHT_HL_S rather than this effect's `0.6 - 0.5*drag` — and
    the arrival is the proof that the two halves agree: a solve done against
    one kernel and an integration done with another would land every spark
    far off its target, and this asserts it lands inside a cell."""
    for energy in ENERGIES + (wsk.LEVEL_FLOOR,):
        run = alone(shape_id, energy)
        assert run.form_s == pytest.approx(2.25, abs=0.01), (
            "the planner floors this effect's form at 2.25 s, so Energy "
            "cannot pace it")
        assert run.targets is not None and len(run.targets)
        assert run.arrival_pitch <= 1.0, (
            f"{shape_id} at Energy {energy} (form {run.form_s:.2f}s): a "
            f"spark is {run.arrival_pitch:.2f} cell pitches from its target")
        # ... and the burst left the centre a flight before the word, not
        # at the edge
        flight_frames = int(round(FX.WORD_SHAPE_FLIGHT_S / DT))
        assert abs((run.word_frame - run.launch_frame) - flight_frames) <= 1
    long_form = alone(shape_id, 0.8, form_override=2.8)
    assert long_form.form_s == pytest.approx(2.8)
    assert long_form.arrival_pitch <= 1.0, long_form.arrival_pitch
    assert abs((long_form.word_frame - long_form.launch_frame)
               - int(round(FX.WORD_SHAPE_FLIGHT_S / DT))) <= 1, (
        "a longer form only lengthens the dim's own run-up in front of the "
        "quiet, never the flight")


def test_the_outline_inside_split_is_the_told_share():
    run = alone("heart", 0.8)
    share = run.outline_sparks / run.total_sparks
    assert abs(share - 0.70) <= 0.05, share
    # and the share is a tunable, not a constant
    high = alone("heart", 0.8, config={"word_shape_outline_share": 0.9})
    assert abs(high.outline_sparks / high.total_sparks - 0.9) <= 0.05


def test_the_spark_count_runs_from_quiet_to_loud_with_the_words_energy():
    """60 sparks at the floor Energy, 100 at a full one — W1.2's own pair,
    which W5.6 puts back: "Let's turn back the increase in blob count"
    retires W4.3's 90/150. Linear between."""
    lo = alone("heart", wsk.LEVEL_FLOOR, tail_frames=2)
    hi = alone("heart", 1.0, tail_frames=2)
    # the floor Energy is 0.01, not 0 (word_shape_keys.LEVEL_FLOOR: 0 means
    # NOT TOLD), so the quietest word a scene can get is the quiet count
    # itself — 60 + 40 x 0.01, rounded
    assert lo.total_sparks == 60
    assert hi.total_sparks == 100
    mid = alone("heart", 0.5, tail_frames=2)
    assert mid.total_sparks == 80


def test_a_saturated_show_plus_the_loud_burst_fits_in_the_capacity():
    """W4.3's headroom, still asserted at W5.6's 100 sparks. The shaped
    sparks are UNCAPPED (`p_nocap`), so they are bounded only by the
    module's own CAP: 100 of them on top of a show saturating his
    `max_blobs` of 100 is 200 of 1024, so the burst can never
    be clipped by the array and the ordinary show can never be starved by
    it. The clamp exists anyway (`_word_shape_burst`'s `CAP - self.n`), and
    this is the arithmetic that says it is unreachable in his room."""
    from fx.effects.fireworks import CAP, Fireworks2d
    schema = {str(k): k.default() for k in Fireworks2d.CONFIG_SCHEMA.schema
              if hasattr(k, "default")}
    loud = int(schema["word_shape_sparks_loud"])
    assert loud == 100
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


@pytest.mark.parametrize("burst_life,expected", [(1.9, 3.0), (1.2, 4.5)])
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

    W4.3 MOVED BOTH NUMBERS WITHOUT TOUCHING EITHER LEVER, AND W5.6 MOVED
    THEM AGAIN THE SAME WAY. A shaped spark lives THE FLIGHT (not the whole
    form) plus the hold plus its own share of the release — it is not born
    until WORD_SHAPE_FLIGHT_S before the word — but the release is 1.5x the
    FORM and the form is floored, so W5.6's 2.25 s floor makes the release
    3.375 s. The flight's own 0.8 -> 2.0 s and the fade window's floor
    0.45 -> 0.6 lengthen it further. Neither this effect nor either row
    chose that: the ratio is the ROOM's two settings, the planner's floor
    and his own "slow the burst by 60%". The lever for the WHOLE length is
    `word_shape_release_ratio`, which is his."""
    run = alone("heart", 0.8, config={"burst_life": burst_life})
    shaped = (FX.WORD_SHAPE_FLIGHT_S + run.hold_s
              + sum(FX.WORD_SHAPE_FADE_FRAC) / 2 * run.release_s)
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
    """W4.2 made the hold half again as long by telling a longer
    `word_shape_hold_s`, and W5.6 took that stretch back off this effect by
    removing its `WORD_SHAPE_HOLD_X` entry — NEITHER row changes anything
    in this module, which is the point. The hang is the TOLD number: tell
    two holds and the shape stands for each of them, measured on the
    effect's own `hanging` flag and on the sparks still alive. The rig tells
    the room's own unstretched hold, so these are the numbers his scene gets
    now."""
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
    within a cell of the shape that arrived on the word. W5.6 damps toward
    a DRIFT rather than to zero (see
    test_no_shaped_spark_is_ever_exactly_stopped_during_the_hold), and this
    is the other side of that coin — a drift small enough that the outline
    is still the outline a whole hold later."""
    run = alone("heart", 0.8)
    mid = (run.word_frame + run.hold_end_frame) // 2
    out, fill = C.cell_sets(word_shapes.get("heart"), panel(), 0.62)
    cov_word, _r, _o, _f = C.measure_frame(
        run.frames[run.word_frame], panel(), out, fill)
    cov_mid, _r2, _o2, _f2 = C.measure_frame(
        run.frames[mid], panel(), out, fill)
    assert cov_mid >= cov_word - 0.1, (cov_word, cov_mid)


# ── 4b. W5.6: the slower burst, the drift, the break-apart, the fade ─────

def _flight_marks(run):
    """The flight's own frames at 25/50/75/100% of it. 100% is its LAST
    frame and not the word's own, which is already the hang — by then
    WORD_SHAPE_DRIFT_KEEP has taken 4% of the arrival speed."""
    launch = run.launch_frame if run.launch_frame >= 0 else run.word_frame
    span = run.word_frame - launch
    marks = [launch + int(round(f * span)) for f in (0.25, 0.5, 0.75)]
    marks.append(max(launch, run.word_frame - 1))
    return marks


@pytest.mark.parametrize("shape_id", SHAPES)
def test_the_burst_decelerates_across_the_whole_flight(shape_id, capsys):
    """"Slow the burst by 60% so we can see the blobs moving out to the
    outline, and then decelerating to almost a stop, but not quite a stop."

    TWO THINGS, and the second is the one that needed a second constant.
    The flight is 2.0 s — his 60% read as a SPEED (x0.4 of W4.3's 0.8 s),
    which is the only sense a viewer has of a burst's speed; the other
    reading, "60% LONGER" (1.3 s), is stated in the skill beside the
    constant. And the DECELERATION spans the whole flight, because this
    effect's own drag kernel (`0.6 - 0.5 * drag` = 0.255 s at his 0.69)
    saturates in about 0.4 s: over a 2 s flight it would land every spark
    in the first fifth and leave it sitting, which is the opposite of what
    he asked to see. WORD_SHAPE_FLIGHT_HL_S (0.65 s, about a third of the
    flight) is the shaped sparks' own.

    So: the mean speed falls at every quarter of the flight, it is still
    well above the drift at the last frame of it, and — the arithmetic that
    says the kernel really spans the flight — at the halfway mark the
    sparks are nowhere near their targets, which a 0.255 s kernel would
    have put them at."""
    run = alone(shape_id, 0.8)
    marks = _flight_marks(run)
    means = [run.ws_speed[m][1] for m in marks]
    radii = [run.ws_spread[m] for m in marks]
    with capsys.disabled():
        print(f"  {shape_id:8s}: speed "
              + " -> ".join(f"{v:.2f}" for v in means)
              + " cell pitches/s over the flight; radius "
              + " -> ".join(f"{v:.1f}" for v in radii))
    assert all(b < a for a, b in zip(means, means[1:])), means
    # still MOVING at the end of the flight, by a long way more than the
    # hold's own drift — the deceleration has not finished early
    assert means[-1] > 10 * FX.WORD_SHAPE_DRIFT, means[-1]
    # ... and the sparks are still crossing the panel at the halfway mark:
    # under this effect's own 0.255 s kernel they would be at 98% of their
    # targets by here (0.5 ** (1.0 / 0.255) is 6%) instead of about 75%
    half = radii[1] / max(radii[-1], 1e-9)
    assert 0.6 <= half <= 0.85, (
        f"{shape_id}: the sparks were {half:.0%} of the way out at the "
        f"flight's halfway mark — the deceleration is not spanning the "
        f"flight")


@pytest.mark.parametrize("shape_id", SHAPES)
def test_no_shaped_spark_is_ever_exactly_stopped_during_the_hold(
        shape_id, capsys):
    """"decelerating to almost a stop, but not quite a stop. The blobs
    should always be slightly drifting."

    W4.3's hang damped the arrived sparks to a dead stop in three frames (a
    0.05 s velocity half-life). Now a spark keeps WORD_SHAPE_DRIFT_KEEP
    (4%) of the speed it arrived with and then rides a mean-reverting
    random walk whose stationary spread is WORD_SHAPE_DRIFT, so its speed
    is never exactly zero — measured on the SLOWEST spark of every frame of
    the hold, which is the only honest place to read "always"."""
    run = alone(shape_id, 0.8)
    hold = run.ws_speed[run.word_frame:run.hold_end_frame + 1]
    assert len(hold) > 20, len(hold)
    slowest = [v[0] for v in hold]
    means = [v[1] for v in hold]
    with capsys.disabled():
        print(f"  {shape_id:8s}: over {len(hold)} frames of the hold the "
              f"slowest shaped spark runs {min(slowest):.4f}-"
              f"{max(slowest):.4f} cell pitches/s, the mean "
              f"{float(np.mean(means)):.3f}")
    assert min(slowest) > 0.0, (
        "a shaped spark was exactly stopped during the hold")
    # and the drift is a BREATH, not a wander: the mean speed sits around
    # the drift constant rather than carrying the shape off its outline
    assert float(np.mean(means)) <= 4 * FX.WORD_SHAPE_DRIFT, (
        float(np.mean(means)), FX.WORD_SHAPE_DRIFT)


@pytest.mark.parametrize("shape_id", SHAPES)
def test_the_release_breaks_the_shape_apart_rather_than_cutting_it(
        shape_id, capsys):
    """"at the end, the blobs should lightly break apart and fade out", and
    "fades too abruptly" answered.

    THE BREAK-APART is read on the COMPLETE POPULATION. WORD_SHAPE_FADE_FRAC
    is (0.6, 1.0) of the release, so NO spark is gone before 60% of it:
    the frame just inside that carries the same sparks the hold's end did,
    and their mean radius there is a TRAVEL rather than a survivorship
    effect (at the release's end a handful are left and which ones is
    random, which is why the radius there is printed and not asserted).

    THE FADE is gentler two ways: WORD_SHAPE_FADE_POWER is 1.0 (linear)
    where W4.3's 1.3 held the brightness up and then dropped it, and the
    window's floor is 0.6 where W4.3's was 0.45."""
    run = alone(shape_id, 0.8)
    rel_end = min(run.release_end_frame, len(run.ws_spread) - 1)
    full = min(run.hold_end_frame
               + int(FX.WORD_SHAPE_FADE_FRAC[0] * run.release_s / DT) - 1,
               rel_end)
    r0, r1 = run.ws_spread[run.hold_end_frame], run.ws_spread[full]
    rel_speed = [v[1] for v in run.ws_speed[run.hold_end_frame + 1:full + 1]]
    hold_speed = [v[1] for v in
                  run.ws_speed[run.word_frame:run.hold_end_frame + 1]]
    # the population really is complete up to there
    alive = run.state[full]["sparks"]
    with capsys.disabled():
        print(f"  {shape_id:8s}: the drift grows "
              f"{float(np.mean(hold_speed)):.3f} -> "
              f"{float(np.mean(rel_speed)):.3f} cell pitches/s and the "
              f"sparks' mean radius {r0:.3f} -> {r1:.3f} pitches over the "
              f"complete-population stretch ({alive} of "
              f"{run.total_sparks} still lit)")
    assert alive == run.total_sparks, (
        f"{alive} of {run.total_sparks} sparks left before "
        f"{FX.WORD_SHAPE_FADE_FRAC[0]:.0%} of the release — "
        f"WORD_SHAPE_FADE_FRAC says none may")
    assert r1 > r0, (
        f"{shape_id}: the shape did not break apart ({r0:.3f} -> "
        f"{r1:.3f} cell pitches)")
    assert float(np.mean(rel_speed)) > 2 * float(np.mean(hold_speed)), (
        "the release's drift is no bigger than the hold's own")


def test_the_fade_is_gentle_and_no_spark_goes_early(capsys):
    """"It also holds too long and fades too abruptly." The hold is the
    ROOM's again (the stretch is gone — see
    test_fireworks_declares_its_own_minimum_form_and_leaves_the_stretch);
    the fade is this effect's, and these are its two constants:

      * WORD_SHAPE_FADE_FRAC (0.6, 1.0) — every spark's own fade window is
        between 60% and 100% of the told release, so the FIRST one goes at
        60% of it and the LAST at its end. Measured on the live count;
      * WORD_SHAPE_FADE_POWER 1.0 — linear. W4.3's 1.3 is a curve that
        holds the brightness up and then drops it, which is what "abruptly"
        is, so this asserts the shape's own light falls at a roughly even
        rate over the release rather than in a late cliff."""
    run = alone("heart", 0.8)
    rel_end = min(run.release_end_frame, len(run.state) - 1)
    counts = [run.state[i]["sparks"]
              for i in range(run.hold_end_frame, rel_end + 1)]
    total = run.total_sparks
    first_loss = next((i for i, k in enumerate(counts) if k < total), None)
    assert first_loss is not None, "no spark ever went out"
    frac = first_loss * DT / run.release_s
    with capsys.disabled():
        print(f"  the first spark goes at {frac:.0%} of the release "
              f"(WORD_SHAPE_FADE_FRAC floor "
              f"{FX.WORD_SHAPE_FADE_FRAC[0]:.0%}), the last by its end; "
              f"{total} -> {counts[-1]} sparks")
    assert frac >= FX.WORD_SHAPE_FADE_FRAC[0] - 2 * DT / run.release_s, frac
    assert counts[-1] <= 0.1 * total, counts[-1]
    # THE LIGHT, not the count: the shape's own light over the release
    # falls without a cliff. The steepest one-frame drop is no more than a
    # few times the even rate it would fall at if it fell linearly.
    out, fill = C.cell_sets(word_shapes.get("heart"), panel(), 0.62)
    band = out & panel().grid
    light = [float(f.max(axis=2)[band].mean())
             for f in run.frames[run.hold_end_frame:rel_end + 1]]
    drops = [a - b for a, b in zip(light, light[1:])]
    even = max(light[0], 1e-9) / max(len(light) - 1, 1)
    with capsys.disabled():
        print(f"  the outline band's own light falls {light[0]:.3f} -> "
              f"{light[-1]:.3f} over the release; the steepest one-frame "
              f"drop is {max(drops):.4f} against an even "
              f"{even:.4f} ({max(drops) / even:.1f}x)")
    assert max(drops) <= 6.0 * even, (
        f"the shape's light fell {max(drops) / even:.1f}x the even rate in "
        f"one frame — that is a cliff, which is what 'fades too abruptly' "
        f"was about")


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

def test_the_shaped_burst_is_additive_except_the_quiet_and_the_dim(
        tmp_path):
    """tests/test_firework_burst.py's own additive proof, REWRITTEN TO W4.3's
    RULE AND THEN TO W5.6's. His 2026-11-17 verdict retired W1.2's "the
    ordinary particles are untouched across the edge"; his 2026-11-18 one
    softened what replaced it from a blackout to a dim. What holds now:

      * ordinary sparks are SHORTENED, never killed: each one's remaining
        life is capped at its own share of WORD_SHAPE_HUSH_FADE_S, so it
        fades out rather than blinking out ("so fading out already"), and
        nothing else about it moves — it keeps its age, its colour and its
        motion;
      * ordinary sparks are DIMMED — a brightness on `p_shown` and nothing
        else, so no position, life, age, colour or velocity of theirs reads
        it;
      * ordinary LAUNCHES are withheld in the 0.25 s quiet before the
        launch, and NOWHERE ELSE;
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
                pre_vx = eff.p_vx[:pre_n].copy()
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
                assert shaped.sum() == 92            # 60 + 40 x 0.8
                assert not shaped[:pre_n].any(), "an old particle was flagged"
                # uncapped: the shape never occupies max_blobs, so the
                # ordinary show has exactly the room it had
                assert (eff.p_nocap[:eff.n][shaped] == 1.0).all()
                assert eff._capacity() == room_before
                # W5.6: ON THE EDGE FRAME ITSELF THE DIM IS ZERO, which is
                # the whole point of ramping it (WORD_SHAPE_DIM_RAMP_S) —
                # the ordinary show is rendered exactly as it was on the
                # frame the shape is told, and darkens over the next
                # quarter-second. That the dim is a brightness and ONLY a
                # brightness is
                # test_the_dim_is_a_brightness_and_only_a_brightness.
                assert eff.word_shape_state()["dim"] == 0.0
                # ... and the ordinary sparks' own velocities took the
                # effect's own drag and nothing else
                assert eff.p_vx[:pre_n] == pytest.approx(pre_vx * (
                    0.5 ** (DT / max(0.6 - 0.5 * eff.drag, 0.05))), rel=1e-4)
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


# W5.6: the engine's floor for this effect is the 0.25 s quiet plus the
# 2.0 s flight, and the hold is the room's own again (no stretch)
HUSH_FORM, HUSH_HOLD = 2.25, 1.2
HUSH_KEYS = dict(form_s=HUSH_FORM, hold_s=HUSH_HOLD,
                 release_s=1.5 * HUSH_FORM, level=1.0)


def _told(seq=1, shape="heart", **kw):
    k = dict(HUSH_KEYS)
    k.update(kw)
    return wsk.keys_for(shape, seq, k["form_s"], k["hold_s"],
                        k["release_s"], k["level"])


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_not_one_ordinary_launch_happens_inside_the_quiet(tmp_path, seed):
    """HIS TWO ASKS, MEASURED AT THE CALL. W4.3's was "make sure no
    fireworks fire right before, or concurrently", which withheld every
    ordinary launch from the SEQ edge to the END OF THE HOLD. W5.6's is "the
    background doesn't need to be clear of other fireworks ... I think we
    can give it 80% less pre-fire darkness time", so what is asserted now
    is BOTH halves of that:

      * inside the WORD_SHAPE_HUSH_S (0.25 s) before the launch there is no
        `_spawn_burst` call of any kind — the spawn rate, the beat bursts
        and the drop tail's shower all withheld;
      * and OUTSIDE it, over the flight and the hold, the ordinary
        fireworks keep launching — the dim is the only thing happening to
        them. A test that only counted zeroes would pass just as well on
        W4.3's blackout, which is the thing he overturned.

    Driven with real 120 bpm beats at his scene's busiest binding, across
    seeds."""
    async def main():
        host, virtual, cm, clock, eff, calls = await _hush_effect(
            tmp_path, f"hush{seed}")()
        eff._rng = np.random.default_rng(seed)
        try:
            _beat_step(virtual, clock, eff, 60)
            assert len(calls) > 0, "nothing was launching to begin with"
            eff.update_config(_told())
            # the stretch in front of the quiet: the dim is coming in and
            # the ordinary show is still launching through it
            launch_at = HUSH_FORM - FX.WORD_SHAPE_FLIGHT_S
            lead_frames = int(round(
                (launch_at - FX.WORD_SHAPE_HUSH_S) / DT))
            assert lead_frames == 0, (
                "this effect's floored form is exactly the quiet plus the "
                "flight, so there is no stretch in front of the quiet")
            calls.clear()
            quiet_frames = int(round(FX.WORD_SHAPE_HUSH_S / DT))
            _beat_step(virtual, clock, eff, quiet_frames, 60)
            assert len(calls) == 0, (
                f"{len(calls)} ordinary launches happened inside the quiet")
            assert eff.word_shape_state()["sparks"] == 0, (
                "the burst left before the quiet was over")
            # the LAUNCH frame, and from there the ordinary show carries on
            calls.clear()
            _beat_step(virtual, clock, eff, 2, 60 + quiet_frames)
            assert eff.word_shape_state()["sparks"] > 0, (
                "the shaped burst itself never fired")
            # ... through the whole flight and hold, dimmed but launching
            _beat_step(virtual, clock, eff,
                       int(round((FX.WORD_SHAPE_FLIGHT_S + HUSH_HOLD) / DT)),
                       62 + quiet_frames)
            assert len(calls) > 0, (
                "the ordinary fireworks were still being withheld over the "
                "flight and the hold — W5.6 dims them, it does not withhold "
                "them")
            assert eff.word_shape_state()["dim"] > 0.0
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_a_flare_poke_inside_the_quiet_is_dropped_not_deferred(tmp_path):
    """A `burst_rockets` poke landing in the 0.25 s quiet spawns NOTHING,
    and it is not held over either — the pre-drop breath's own swallow
    (`_pre_drop_step`). The key is still self-reset, so an identical later
    write edges again. W5.6 narrows WHERE that applies to the quiet alone:
    a poke after it lands, dimmed, like any other launch."""
    async def main():
        host, virtual, cm, clock, eff, _calls = await _hush_effect(
            tmp_path, "hushpoke")()
        try:
            _beat_step(virtual, clock, eff, 10, audio=C.QuietAudio)
            eff.update_config(_told())
            # 3 frames in: inside the 0.25 s quiet (7 frames at 30 fps)
            _beat_step(virtual, clock, eff, 3, 10, audio=C.QuietAudio)
            assert eff.word_shape_state()["hushed"] is True
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
            # it is DROPPED, not deferred: nothing of it appears later. The
            # feed is QuietAudio and his Matrix entry runs spawn_rate 0, so
            # nothing ordinary launches of its own accord to confuse this
            rest = int(round((HUSH_FORM + HUSH_HOLD) / DT))
            _beat_step(virtual, clock, eff, rest, 15, audio=C.QuietAudio)
            shaped = int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0))
            assert eff.n == shaped, (
                f"{eff.n - shaped} unshaped particles appeared — a withheld "
                f"poke was deferred rather than dropped")
            # ... and a poke AFTER the quiet lands as it always did
            eff.update_config({"burst_rockets": 6})
            _beat_step(virtual, clock, eff, 2, 15 + rest, audio=C.QuietAudio)
            assert eff.n > shaped, "the flare never came back"
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_the_ordinary_show_is_dimmed_not_dark_when_the_shape_arrives(
        capsys):
    """W5.6'S HEADLINE BAR, and it is bounded on BOTH SIDES because his
    second verdict overturns W4.3's: "The background doesn't need to be
    clear of other fireworks, just they need to be dimmer, so fading out
    already." W4.3 measured 0.00% of his real cells carrying ordinary light
    on the word; that is exactly what he does not want.

    So the measure is a RATIO — the ORDINARY light on the panel at the word
    against the SAME SEED's untold frame — and the bars are: at most
    DIM_BAR (45%) of it, and MORE THAN ZERO on every seed. Measured on his
    real mask at his scene's busiest binding (`beat_burst` 6 x `burst_size`
    14 a beat at Energy 1.0, each spark living 1.9 s into a `max_blobs` of
    100) over 20 seeds at 120 bpm, with the shaped burst stubbed out so the
    light being read is only ever the ordinary show's.

    THE BAR IS THE POOLED RATIO and the per-seed worst is PRINTED, not
    asserted: one frame of one seed compares two shows whose last beat
    landed differently (the quiet withheld it on one of them), so a single
    seed's ratio is a noisy estimate of a 0.40 dim rather than a measurement
    of it. The worst seed reads above the row's letter and
    `scripts/check_fireworks_word_shape.py` reports it under "ABOVE THE
    PLAN'S LETTER" rather than moving the bar."""
    real_cells = int(panel().grid.sum())
    lights, twins, shares, launches = [], [], [], []
    for seed in range(1, C.CANVAS_SEEDS + 1):
        kw = dict(energy=1.0, config=C.WORST_CFG,
                  audio_cls=C.Beat120Audio, settle_frames=60,
                  stop_at_hold_end=True, seed=seed)
        run = run_for("heart", no_burst=True, **kw)
        twin = run_for("heart", told=False, **kw)
        lights.append(C.panel_light(run.frames[run.word_frame], panel()))
        twins.append(C.panel_light(twin.frames[twin.word_frame], panel()))
        shares.append(run.canvas[run.word_frame] / real_cells)
        # `no_burst` stubs the burst out, so the run has no launch FRAME to
        # read — the launch is where the clock says it is
        launch_f = run.word_frame - int(round(FX.WORD_SHAPE_FLIGHT_S / DT))
        quiet_from = max(run.edge_frame,
                         launch_f - int(round(FX.WORD_SHAPE_HUSH_S / DT)))
        launches.append(sum(run.launches[quiet_from:launch_f]))
    ratios = [a / b for a, b in zip(lights, twins)]
    pooled = sum(lights) / sum(twins)
    with capsys.disabled():
        print(f"  the ordinary light on the word over {C.CANVAS_SEEDS} "
              f"seeds: POOLED {pooled:.1%} of the untold light "
              f"(WORD_SHAPE_BACKGROUND_DIM is "
              f"{FX.WORD_SHAPE_BACKGROUND_DIM:.2f}); per seed worst "
              f"{max(ratios):.1%}, median {float(np.median(ratios)):.1%}, "
              f"least {min(ratios):.1%}")
        print(f"  ... and still a show: {float(np.median(shares)):.1%} of "
              f"{real_cells} real cells lit at 20/255, median over the "
              f"seeds")
        print(f"  ordinary launches inside the "
              f"{FX.WORD_SHAPE_HUSH_S:.2f} s quiet: {max(launches)} at "
              f"worst")
    assert pooled <= C.DIM_BAR, (
        f"the ordinary light on the word is {pooled:.1%} of the untold "
        f"light pooled over {C.CANVAS_SEEDS} seeds (bar {C.DIM_BAR:.0%})")
    # DIM, NOT DARK — the half of the bar W4.3 would have failed
    assert min(ratios) > 0.0, (
        "the panel went dark rather than dim on at least one seed")
    assert min(shares) > 0.0, (
        "not one of his real cells carried ordinary light on the word — "
        "that is W4.3's dark canvas, which his second verdict retires")
    assert max(launches) == 0, max(launches)
    # and the untold show really was the cluttered one, or this measures
    # nothing at all
    assert min(twins) > 0.05, (
        f"the untold show was not busy ({min(twins):.4f} mean luminance), "
        f"so this measures nothing")


def test_an_ordinary_sparks_remaining_life_is_capped_at_the_edge(tmp_path):
    """What is already in the air is NOT killed — blinking a panel full of
    sparks out in one frame is exactly the jump the plan bars. Each one's
    remaining life is capped at its own share of WORD_SHAPE_HUSH_FADE_S, so
    they fade out a few at a time.

    W5.6 KEEPS THE CAP AND DROPS WHAT IT WAS FOR. W4.3 asserted that by the
    time the burst left there was not one ordinary spark alive; his second
    verdict asks for the opposite ("the background doesn't need to be clear
    of other fireworks, just they need to be dimmer, so fading out
    already"), and the cap IS the "fading out already" half of that
    sentence. So what is asserted now is the cap itself, and that the panel
    the burst leaves into still carries an ordinary show."""
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
            # ... and by the launch there IS still an ordinary show, dimmed
            launch = int(round((HUSH_FORM - FX.WORD_SHAPE_FLIGHT_S) / DT))
            _beat_step(virtual, clock, eff, launch, 61)
            n = eff.n
            assert int(np.count_nonzero(eff.p_wfade[:n] <= 0.0)) > 0, (
                "the panel was empty of ordinary sparks when the burst "
                "left — that is W4.3's dark canvas, which W5.6 retires")
            # the ones from BEFORE the edge are gone (the cap did its work)
            # and what is there launched during the dim, at 0.40 brightness
            st = eff.word_shape_state()
            assert st["dim"] == pytest.approx(1.0, abs=1e-6)
            assert st["background"] == pytest.approx(
                FX.WORD_SHAPE_BACKGROUND_DIM, abs=1e-6)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    asyncio.run(main())


def test_the_dim_is_a_brightness_and_only_a_brightness(tmp_path):
    """"just they need to be dimmer" — so the ordinary show is DRAWN
    darker and nothing else about it changes. Rendered twice from the same
    seed over the same frames, told and untold, with the shaped burst
    stubbed out: every ordinary particle's position, age, life, colour and
    velocity matches frame for frame outside the 0.25 s quiet's own
    withheld launches, and only the rendered light differs."""
    async def main():
        out = {}
        for tag, told in (("told", True), ("untold", False)):
            host, virtual, cm, clock, eff, _c = await _hush_effect(
                tmp_path, f"dimonly{tag}")()
            try:
                eff._word_shape_burst = lambda *a, **kw: None
                # BEATS FIRST to put an ordinary show on the panel, then
                # QUIET so nothing new launches while the dim is measured:
                # his Matrix entry runs spawn_rate 0, so a quiet feed
                # launches nothing at all and the two runs are the SAME
                # particles. 8 frames is past the dim's own ramp (0.25 s)
                # and inside the earliest the life cap can kill anything
                # (0.5 x WORD_SHAPE_HUSH_FADE_S = 0.35 s), so the two
                # populations are identical and the comparison is exact.
                _beat_step(virtual, clock, eff, 30)
                if told:
                    eff.update_config(_told())
                _beat_step(virtual, clock, eff, 8, 30, audio=C.QuietAudio)
                n = eff.n
                out[tag] = dict(
                    n=n, x=eff.p_x[:n].copy(), y=eff.p_y[:n].copy(),
                    vx=eff.p_vx[:n].copy(), age=eff.p_age[:n].copy(),
                    grad=eff.p_grad[:n].copy(), rev=eff.p_rev[:n].copy(),
                    bright=eff.p_bright[:n].copy(),
                    life=eff.p_life[:n].copy(),
                    shown=eff.p_shown[:n].copy(),
                    dim=eff.word_shape_state()["dim"])
            finally:
                cm.__exit__(None, None, None)
                await host.shutdown()
        a, b = out["told"], out["untold"]
        assert a["n"] == b["n"] and a["n"] > 0, (a["n"], b["n"])
        # the QUIET withholds nothing here: QuietAudio launches nothing of
        # its own (his Matrix entry runs spawn_rate 0), so the two
        # populations are the same particles and the comparison is exact
        assert a["x"] == pytest.approx(b["x"])
        assert a["y"] == pytest.approx(b["y"])
        assert a["vx"] == pytest.approx(b["vx"])
        assert a["grad"] == pytest.approx(b["grad"])
        assert a["age"] == pytest.approx(b["age"])
        # ... AND THE LIGHT IS THIS EFFECT'S OWN ORDINARY ENVELOPE TIMES
        # THE DIM, exactly. It is NOT the untold frame's light times the
        # dim, and the reason is worth stating: the W4.3 LIFE CAP (which
        # W5.6 keeps — it is the "so fading out already" half of his
        # sentence) shortens `p_life` at the edge, and `frac_t = age/life`
        # is what the fade envelope reads, so a capped spark is at a
        # different point of its OWN curve than the untold one beside it.
        # So the expected brightness is computed from the told effect's own
        # age/life/bright, with nothing but the dim factor applied on top —
        # which is the whole claim.
        assert a["dim"] > 0.9, a["dim"]
        factor = 1.0 - (1.0 - FX.WORD_SHAPE_BACKGROUND_DIM) * a["dim"]
        assert (a["rev"] == 0.0).all(), "no reverse envelope here"
        frac_t = np.clip(a["age"] / a["life"], 0.0, 1.0)
        fwd = ((1.0 - frac_t) ** 1.4) * np.minimum(
            a["age"] / FX.FADE_IN_S + 0.3, 1.0)
        lit = b["shown"] > 0.0
        assert lit.any(), "nothing was lit, so nothing was dimmed"
        assert a["shown"][lit] == pytest.approx(
            (a["bright"] * fwd * factor)[lit], rel=1e-4, abs=1e-6)
        # and it really is DIMMER than the same spark untold — the dim did
        # something, and in the right direction
        assert float(a["shown"][lit].sum()) < float(b["shown"][lit].sum())

    asyncio.run(main())


def test_a_phase_arriving_during_the_shape_ends_the_quiet_and_the_dim(
        tmp_path):
    """P3 A means a shape is never TOLD while a charge, lull or drop is
    armed — but one that ARRIVES on a standing shape owns the panel. The
    drop payoff and its tail fire exactly as they do today, AT FULL
    BRIGHTNESS (W5.6: the dim ends with the quiet, so a drop is never
    dimmed and neither are a lull's rockets), and the shaped sparks,
    additive, keep flying or hanging over them."""
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
            # the 0.25 s quiet is long over by here; the DIM is what the
            # phase has to end
            assert eff.word_shape_state()["hushed"] is False
            assert eff.word_shape_state()["dim"] > 0.0
            n_before = eff.n
            calls.clear()
            eff.update_config({"phase": "drop", "phase_progress": 1.0})
            _beat_step(virtual, clock, eff, 2, 200, audio=C.QuietAudio)
            st = eff.word_shape_state()
            assert st["hushed"] is False and st["dim"] == 0.0, (
                "a phase arriving must end the quiet AND the dim — the "
                "panel is the drop's, at the drop's own brightness")
            assert st["background"] == pytest.approx(1.0), (
                "the drop's own payoff was dimmed")
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
            assert first == 80            # 60 + 40 x 0.5
            # INTO THE RELEASE of the first, past the point where its
            # own sparks start going out. W5.6's WORD_SHAPE_FADE_FRAC floor
            # is 0.6, so none of them is gone before 60% of the release —
            # at W4.3's 0.45 floor half the release was enough
            _step(virtual, clock, eff, int(round((0.5 + 0.8 + 0.50) / DT)), 12)
            held = eff.p_wfade[:eff.n] > 0.0
            fading = int(held.sum())
            assert 0 < fading < 80, fading
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
            assert int(new.sum()) == 80, "the second word never fired"
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

    W4.3 added one thing it DOES take away: the hold on the ordinary
    show. A clearing write says no shape is standing, and holding the
    ordinary fireworks down for a shape that will never arrive is worse
    than doing nothing — so launching resumes at once and the DIM ends in
    the same frame (W5.6: the quiet is only the 0.25 s before the launch,
    so 0.9 s in it is the dim that is still running), while the sparks
    already in the air go on fading untouched."""
    async def main():
        host, virtual, cm, clock, eff = await _effect(tmp_path, "clear")()
        try:
            _step(virtual, clock, eff, 10)
            eff.update_config(wsk.keys_for("heart", 1, 0.5, 1.2, 0.75, 0.8))
            _step(virtual, clock, eff, int(round((0.5 + 0.4) / DT)), 10)
            held = int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0))
            assert held == 92            # 60 + 40 x 0.8
            lit_before = int(np.count_nonzero(eff.p_shown[:eff.n] > 0.01))
            st = eff.word_shape_state()
            assert st["hushed"] is False, "the 0.25 s quiet is long over"
            assert st["dim"] > 0.0, "the dim should still be running"
            eff.update_config(dict(wsk.NOT_TOLD))
            st = eff.word_shape_state()
            assert st["hushed"] is False and st["dim"] == 0.0, (
                "a clearing write must let the ordinary fireworks back, at "
                "their own brightness")
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
            assert held.sum() == 92
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
            assert int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0)) == 92
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

def test_fireworks_declares_its_own_minimum_form_and_leaves_the_stretch():
    """The planner half, W4.3's floor as W5.6 revises it. The floor is HOW
    EARLY THE WRITE ARRIVES, and it is exactly what this effect needs in
    front of the word: `WORD_SHAPE_HUSH_S` (the 0.25 s quiet) plus
    `WORD_SHAPE_FLIGHT_S` (the 2.0 s flight) = 2.25 s. Asserted as that SUM
    and not as a literal, so neither half can move without the floor
    following it. It lives in `fx.device_model`, never as a registered
    param, because the planner needs it before it has asked any effect
    anything, and it applies ONLY to a scene showing this effect (the W0.3
    review's own point: the lead IS the form, so a global floor would
    stretch every scene's shape).

    AND THE HOLD STRETCH IS GONE (his "It also holds too long"):
    `fireworks` has left `WORD_SHAPE_HOLD_X`, so the room's own 0.8-2.0 s
    hold reaches this effect unmultiplied while STAR and the Black Hole
    keep their 1.5 — he liked those two."""
    floor = FX.WORD_SHAPE_HUSH_S + FX.WORD_SHAPE_FLIGHT_S
    assert floor == pytest.approx(2.25)
    assert device_model.WORD_SHAPE_FORM_MIN_S["fireworks"] == floor
    assert device_model.word_shape_form_min_s(["fireworks"]) == 2.25
    assert device_model.word_shape_form_min_s(["radial"]) == 0.0
    assert device_model.word_shape_form_min_s(["radial", "fireworks"]) == 2.25
    # ... and it is NOT a registered param
    registry = json.loads(
        (REPO / "config" / "effect_params.json").read_text())
    params = registry["effects"]["fireworks"]["params"]
    assert "word_shape_form_min_s" not in params
    # the room's own resolver really applies it, at both halves' tier
    from spectra.services.room_controls import (RoomControlState,
                                                word_shape_timing)
    st = RoomControlState()
    assert word_shape_timing(1.0, 1000, st, ["fireworks"])[0] == 2.25
    assert word_shape_timing(0.0, 1000, st, ["fireworks"])[0] == 2.25
    assert word_shape_timing(1.0, 1000, st, ["radial"])[0] == 0.5
    # A CONSEQUENCE WORTH STATING: the band fires 2.25 s early, so a COLOUR
    # kind pooled in a Fireworks scene's Words band lands 2.25 s early too —
    # exactly as it already does on Fish, the other declared floor.
    assert device_model.word_shape_form_min_s(["fish"]) == 2.0
    # THE HOLD: back to the room's own, and the other two keep the stretch
    assert "fireworks" not in device_model.WORD_SHAPE_HOLD_X
    assert device_model.word_shape_hold_x(["fireworks"]) == 1.0
    assert device_model.word_shape_hold_x(["radial"]) == 1.5
    assert device_model.word_shape_hold_x(["blackhole"]) == 1.5
    assert word_shape_timing(0.5, 0, st, ["fireworks"])[1] == 0.8
    assert word_shape_timing(0.5, 5000, st, ["fireworks"])[1] == 2.0


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
                "word_shape_sparks_quiet": 60, "word_shape_sparks_loud": 100}
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
