"""THE FISH'S WORD SHAPE PROCESSION (fx/effects/fish.py's WORD SHAPES
block; Word Shapes plan row W1.4, approved by the Admiral 2026-11-15 with
his Fish revision).

HIS WORDS: "Fish: similar to orbits ... they need to smoothly accelerate and
not have sudden velocity shifts", and on the first design: "the fish didn't
seem to be sufficiently making the outline. We may need to boost the trail
brightness and lower decay briefly to get it to show better. They also may
need to more tightly flow." P2 A, approved: with FEW fish the water keeps a
trace of the loop while the fish swim it.

The MEASURED proof is scripts/check_fish_word_shape.py — his crystal's real
976 cells through the real vendored pipeline, untold byte-identical to the
pinned pre-change module over both real-audio arcs, the plan's own clarity
bars per shape at both modes and both Energies over 20 seeds, no white, the
cost, and the restore. It runs as a subprocess, like every fish check script
here.

ROW W5.5 (2026-11-18) — his second room verdict: *"Oribits is really good
at showing shape, we need to get Fish to behave similarly ... you might
need to override some min turn radii to match the effect, especially on the
star."* Five levers moved (`word_shape_speed_x`, `WS_TURN_X`,
`WS_TURN_GAIN_X`, the pursuit aim and the wall's own floor), and the
measured proof gained a CORNER section and a lever SWEEP.

ROW W6.1 (2026-11-18) — his THIRD room verdict: *"Only thing left is the
fish needs a little more tuning. ... The shape outline needs to reach at
least a moment where it is either filled with fish or trail. Right now, the
fish seem to jitter out of the outline and so it isn't distinct enough.
Also, if we did a highlight of the shape in orbits, do it on fish."*

EVERYTHING HERE IS NOW PROVEN AT 30 fps, his crystal's own rate (`DT`
below), because three of the row's four findings do not exist at the 60 the
rig used to measure at — a PROPORTIONAL steer's stability, a turn clamp's
per-frame meaning and a pursuit aim's length are all functions of `dt`. The
row's own laws pinned below:
  * THE STEP IS THE EXACT FIRST-ORDER FORM under a shape — `1 - exp(-gain
    * dt)` of the heading error, never more than the error at ANY frame
    rate — and the ordinary proportional step to the bit at `m = 0`.
  * THE CLAMP STILL MEANS AN ARC: no more than `WS_TURN_MAX_RAD_FRAME` of
    heading in one RENDERED frame, STAR's own per-frame cap precedent.
  * THE AIM IS NEVER SHORTER THAN A FRAME'S TRAVEL (`WS_AIM_STEP_X`).
  * THE TRAIL AND THE TRACE OUTLIVE THE REVISIT GAP (`WS_TRAIL_GAP_X`) —
    Orbits' persistence ported, which is what his "if we did a highlight of
    the shape in orbits" actually names, there being no highlight in Orbits
    at all.
  * THE WANDER AND THE ORDINARY WAKE HAND OVER TO THE LOOP, by `m`, the way
    the swirl and the kicks already did.

Pinned in-process below:
  * THE CONTRACT — the opt-in (schema, ADVANCED_KEYS, WORD_SHAPE_EFFECTS,
    the registry), the SEQ edge and its creation baseline, and the told
    keys never written back.
  * THE FLOOR — `word_shape_form_min_s(["fish"]) == 2.0` and
    `(["orbits"]) == 0.0`, and, through the REAL engine on a real Fish
    virtual, a shape whose Energy-paced form would be 0.9 s still arriving
    as 2.0 s.
  * THE MOTION LAWS that are arithmetic rather than pixels: the envelope's
    restart and release inverses, the entry rule (no two crossing, the
    minimum gap, the ease to even spacing), and the loop's own authority.
  * ROW W5.5's OWN LAWS: the registered speed and its envelope ramp (x1 at
    both ends, no step), the lap and the dash cap both taking the
    multiplier, the turn clamp IN FORCE and his own again after, and the
    corner budget as arithmetic — the aim's own chord cut and the circle
    under half a cell pitch.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import device_model, headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from fx.effects import word_shape_keys as wsk  # noqa: E402
from fx.effects import word_shapes  # noqa: E402

# ROW W6.1: HIS CRYSTAL RENDERS AT 30 fps (the `crystal` WLED device's
# `refresh_rate`, and a virtual renders at its slowest device —
# `.claude/skills/radial-effect`'s own note), and every law in this file is
# now proven at that rate. The 60 fps cross-check lives in the check
# script (`--fps 60`), which is where the measured bars are.
DT = 1.0 / 30.0
ROWS, COLS = 37, 72
VID = "fish-word-shape-test"
FORM_S, HOLD_S, RELEASE_S = 2.0, 1.2, 3.0


# ── the measured proof ─────────────────────────────────────────────────────

def test_the_measured_fish_word_shape_proof_passes():
    """THE SLOWEST GATE HERE, and deliberately: it renders both of his
    real-audio arcs twice (today's fish and the pinned module's, frame for
    frame) and then 20 seeds x 3 shapes x few/many x two Energies on the
    real mask. Tens of minutes — the same shape as the other fish check
    scripts, an order of magnitude more runs."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_fish_word_shape.py")],
        cwd=REPO, capture_output=True, text=True, timeout=7200,
    )
    out = proc.stdout + proc.stderr
    if "cannot read" in out and "out of git" in out:
        pytest.skip(out.strip().splitlines()[-1])
    assert proc.returncode == 0, out[-6000:]
    assert "ALL FISH WORD SHAPE CHECKS PASS" in proc.stdout, out[-6000:]
    # both arcs really were compared against the pinned module
    assert proc.stdout.count("-> IDENTICAL") == 2, out[-6000:]


# ── the opt-in ─────────────────────────────────────────────────────────────

def test_fish_is_wired_and_declares_its_own_minimum_form():
    assert "fish" in device_model.WORD_SHAPE_EFFECTS
    assert device_model.WORD_SHAPE_FORM_MIN_S["fish"] == 2.0
    assert device_model.word_shape_form_min_s(["fish"]) == 2.0
    # ... and ONLY this effect's: a scene showing something else keeps the
    # approved Energy-paced 0.5-0.9 s form (the W0.3 review's own point)
    assert device_model.word_shape_form_min_s(["orbits"]) == 0.0
    assert device_model.word_shape_form_min_s(["orbits", "fish"]) == 2.0


def test_the_six_told_keys_ride_only_the_dedicated_write():
    """word_shape_keys.py's rule 1: the keys are in the schema and in
    ADVANCED_KEYS, and deliberately NOT in the effect-parameter registry —
    nothing but the `word_shape` kind's own write may set them."""
    schema = FX.Fish2d.CONFIG_SCHEMA.schema
    names = {getattr(k, "schema", k) for k in schema}
    for key in wsk.KEYS:
        assert key in names, key
        assert key in FX.Fish2d.ADVANCED_KEYS, key
    registry = json.loads(
        (REPO / "config" / "effect_params.json").read_text())
    params = registry["effects"]["fish"]["params"]
    for key in wsk.KEYS:
        assert key not in params, f"{key} must never be registered"
    # the two SETTINGS are registered, which is what makes them
    # Sonic-tellable per scene entry for free
    for key, default in (("word_shape_size", 0.62), ("word_shape_few", 3)):
        assert params[key]["default"] == default
        assert registry["effects"]["fish"]["defaults"][key] == default
        assert params[key]["help_topic"] == "word-shapes"
    # ... and the minimum form is NOT one of them (device_model owns it)
    assert "word_shape_form_min_s" not in params


# ── the engine seam: the floor really is applied on the way in ────────────

def _words_scene(effect_type="fish"):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Fish Words",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual",
                                   target=VID, effect_type=effect_type)],
        flare_kinds=[FlareKind(name="Heart", type="word_shape")],
        responses={"word": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Heart": 1.0})])})


def _action(energy=0.0, form_s=FORM_S):
    """One planned shape word, exactly as `lyric_events.plan_words` builds
    it for the Fish's own 2.0 s floor."""
    from spectra.services import lyric_events as le
    hit = le.WordHit(
        key="100-100", first_word=100, last_word=100, phrase="love",
        label="love", line=0, ms=10_000.0, end_ms=11_200.0,
        emphasis=0.4, strength=0.9, his=False, set_ids=(), set_names=(),
        energy=energy, shape_id="heart", shape_name="Heart",
        pin=le.PIN_ALWAYS, match_id="m1")
    return le.WordAction(
        hit=hit, verdict=le.VERDICT_SHAPE, energy=energy, form_s=form_s,
        hold_s=HOLD_S, release_s=RELEASE_S,
        transition_ms=round(form_s * 1000))


def _told_write(effect_type, ramp_ms, monkeypatch):
    """Fire one shape through the REAL ResponseEngine on a scene showing
    `effect_type`, and return the six keys it wrote."""
    from spectra.services import engine as engine_mod
    from spectra.services import flare_preview
    from spectra.services.fx_executor import RecordingExecutor
    clock = flare_preview._FakeClock()
    executor = RecordingExecutor(clock=clock)
    conductor, responder, _w = flare_preview._scratch_engine(
        _words_scene(effect_type), 0.5, clock, executor)
    responder._rng = Random(7)
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", conductor)
    asyncio.run(engine_mod.fire_lyric_shape_event(_action(), ramp_ms))
    told = [w for w in executor.writes if wsk.SHAPE_KEY in (w["params"] or {})]
    return told[-1]["params"] if told else None


def test_the_engine_never_tells_the_fish_less_than_two_seconds(monkeypatch):
    """A quiet word's Energy-paced form is 0.9 s; the Fish is floored at
    2.0 s and the LEAD is that same number, so the band fires 2.0 s early
    and the effect is told 2.0 s (fx.device_model.word_shape_form_min_s'
    own docstring — the lead IS the form in practice)."""
    params = _told_write("fish", 900, monkeypatch)
    assert params is not None, "the Fish must take the write"
    assert params[wsk.FORM_KEY] == pytest.approx(2.0)
    assert params[wsk.SHAPE_KEY] == "heart"
    assert params[wsk.LEVEL_KEY] >= wsk.LEVEL_FLOOR
    # a LATER tick shortens nothing below the floor either
    assert _told_write("fish", 310, monkeypatch)[wsk.FORM_KEY] == \
        pytest.approx(2.0)
    # a longer ramp is its own number, never pulled down to the floor
    assert _told_write("fish", 2_600, monkeypatch)[wsk.FORM_KEY] == \
        pytest.approx(2.6)


def test_only_the_fish_scene_gets_the_fishs_floor(monkeypatch):
    """THE WHOLE REASON BOTH FLOORS ASK THE SHOWING SCENE (the W0.3 review).
    Fish is the only effect with a minimum form, so a scene showing another
    WIRED effect must still get the approved Energy-paced form — a quiet
    word's 0.9 s — and not be stretched to the Fish's 2.0 s. Wave 1 has
    given this test a real sibling to compare against; before it landed
    there was nothing to show the difference with."""
    other = next(e for e in sorted(device_model.WORD_SHAPE_EFFECTS)
                 if e != "fish")
    assert other not in device_model.WORD_SHAPE_FORM_MIN_S
    params = _told_write(other, 900, monkeypatch)
    assert params is not None, f"{other} is wired, so it takes the write"
    assert params[wsk.FORM_KEY] == pytest.approx(0.9), \
        "another scene keeps the Energy-paced form"
    assert _told_write("fish", 900, monkeypatch)[wsk.FORM_KEY] == \
        pytest.approx(2.0), "... while the Fish is floored"


def test_a_scene_showing_an_effect_no_row_has_wired_takes_no_write(monkeypatch):
    """The membership gate from the other side. `UNWIRED` is the contract
    test's own choice of an effect no wave-1 row has wired, so this stays
    true however many more land."""
    from tests.test_word_shape_contract import UNWIRED
    assert UNWIRED not in device_model.WORD_SHAPE_EFFECTS
    assert _told_write(UNWIRED, 900, monkeypatch) is None


# ── the envelope's own inverses ────────────────────────────────────────────

@pytest.mark.parametrize("frac", [0.0, 0.17, 0.5, 0.83, 1.0])
def test_a_restart_resumes_the_form_at_the_fraction_standing(frac):
    t = FX.word_shape_restart_t(frac, FORM_S)
    assert 0.0 <= t <= FORM_S
    assert wsk.envelope(t, FORM_S, HOLD_S, RELEASE_S) == pytest.approx(
        frac, abs=1e-9)


@pytest.mark.parametrize("frac", [0.05, 0.3, 0.5, 0.95, 1.0])
def test_a_clearing_write_releases_from_the_fraction_standing(frac):
    t = FX.word_shape_release_t(frac, FORM_S, HOLD_S, RELEASE_S)
    assert FORM_S + HOLD_S <= t <= FORM_S + HOLD_S + RELEASE_S
    assert wsk.envelope(t, FORM_S, HOLD_S, RELEASE_S) == pytest.approx(
        frac, abs=1e-9)


def test_the_loops_authority_is_full_from_the_first_frame_and_let_go_mid_release():
    """Plan 3.4: a fish heads for its entry from the FIRST frame of the form
    (the S-curve paces its speed, never where it is going) and lets go of
    the loop half-way down the release, returning to wandering with heading
    and speed intact."""
    assert FX.word_shape_grip(0.0, FORM_S, HOLD_S, RELEASE_S) == 1.0
    assert FX.word_shape_grip(FORM_S, FORM_S, HOLD_S, RELEASE_S) == 1.0
    standing = FORM_S + HOLD_S
    assert FX.word_shape_grip(standing, FORM_S, HOLD_S, RELEASE_S) == 1.0
    half = standing + RELEASE_S * FX.WS_RELEASE_GRIP
    assert FX.word_shape_grip(half, FORM_S, HOLD_S, RELEASE_S) == \
        pytest.approx(0.0)
    assert FX.word_shape_grip(half + 0.1, FORM_S, HOLD_S, RELEASE_S) == 0.0
    # ... and smoothly: zero slope at both ends of that ramp
    ts = np.linspace(standing, half, 400)
    vals = np.array([FX.word_shape_grip(t, FORM_S, HOLD_S, RELEASE_S)
                     for t in ts])
    assert np.all(np.diff(vals) <= 1e-12), "monotonic"
    d = np.abs(np.diff(vals))
    assert d[0] < d[len(d) // 2] and d[-1] < d[len(d) // 2], "eased"


# ── the entry rule ─────────────────────────────────────────────────────────

def _table(shape_id):
    shape = word_shapes.get(shape_id)
    s = np.linspace(0.0, 1.0, FX.WS_OUTLINE_SAMPLES, endpoint=False)
    ux, uy = shape.at(s)
    ang = np.unwrap(np.arctan2(uy, ux))
    if ang[-1] < ang[0]:
        ang, s = ang[::-1].copy(), s[::-1].copy()
    return ang, s


@pytest.mark.parametrize("shape_id", ["heart", "star", "diamond"])
def test_every_entry_is_the_point_on_that_fishs_own_bearing(shape_id):
    """So no two fish cross on the way in: a fish's entry is the outline
    point on ITS OWN bearing from the centre of view, and the order round
    the loop is the order of their bearings."""
    ang, s_tab = _table(shape_id)
    shape = word_shapes.get(shape_id)
    rng = np.random.default_rng(4)
    for _ in range(40):
        k = int(rng.integers(2, 9))
        bearings = rng.uniform(-np.pi, np.pi, k)
        entry, rank = FX.word_shape_entries(
            bearings, ang, s_tab, FX.WS_ENTRY_MIN_GAP / k)
        assert sorted(rank.tolist()) == list(range(k))
        # the entry really is on the outline, near its own bearing
        ux, uy = shape.at(entry)
        got = np.arctan2(uy, ux)
        off = np.abs((got - bearings + np.pi) % (2 * np.pi) - np.pi)
        # relaxation for the minimum gap can move an entry a little off its
        # own bearing; never far enough to pass a neighbour
        assert off.max() < np.pi / 2, off.max()
        order = np.argsort(entry)
        ring = entry[order]
        gaps = (np.roll(ring, -1) - ring) % 1.0
        assert gaps.min() >= FX.WS_ENTRY_MIN_GAP / k - 1e-6, gaps.min()


def test_no_two_entries_share_a_place_even_from_one_bearing():
    """Several fish on nearly the same bearing (a shoal that has just
    turned together) still get distinct, ordered places."""
    ang, s_tab = _table("heart")
    bearings = np.full(5, 0.3) + np.linspace(0.0, 1e-4, 5)
    entry, rank = FX.word_shape_entries(
        bearings, ang, s_tab, FX.WS_ENTRY_MIN_GAP / 5)
    ring = np.sort(entry)
    gaps = (np.roll(ring, -1) - ring) % 1.0
    assert gaps.min() >= FX.WS_ENTRY_MIN_GAP / 5 - 1e-6
    assert sorted(rank.tolist()) == [0, 1, 2, 3, 4]


# ── one real effect ────────────────────────────────────────────────────────

async def _effect(tmp_path, tag, **cfg):
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, "fish", dict(cfg))
    eff._rng = np.random.default_rng(3)
    return host, cm, clock, virtual, eff


def _render(clock, virtual, frames):
    for _ in range(frames):
        clock.advance(DT)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)


def _told(seq=1, shape="heart", form_s=FORM_S):
    return wsk.keys_for(shape, seq, form_s, HOLD_S, RELEASE_S, 0.5)


def test_a_stale_persisted_seq_on_a_fresh_instance_never_fires(tmp_path):
    """The fireworks `burst_rockets` CREATION BASELINE rule: a fresh
    instance built from a persisted config carrying a stale SEQ must not
    draw a shape — the effect baselines the counter at construction."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-baseline", particle_count=3, **_told(seq=9))
        try:
            _render(clock, virtual, 60)
            assert eff._ws is None, "a stale SEQ fired a shape"
            assert eff._ws_pending is None
            # ... and the NEXT write, with a different SEQ, does fire
            eff.update_config(_told(seq=10))
            _render(clock, virtual, 2)
            assert eff._ws is not None
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_effect_never_writes_a_told_key_back(tmp_path):
    """word_shape_keys.py's contract: SpotFX writes once and the effect says
    nothing back — it just stops reading the keys when its own clock is
    past the whole shape."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-noback", particle_count=3)
        try:
            _render(clock, virtual, 60)
            eff.update_config(_told())
            _render(clock, virtual, int((FORM_S + HOLD_S + RELEASE_S) / DT)
                    + 30)
            assert eff._ws is None, "the effect resets itself past total_s"
            for key, value in _told().items():
                assert eff._config[key] == value, key
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_trail_and_the_wake_are_exactly_his_again_after_the_release(
        tmp_path):
    """His note asked for a brighter, longer-lived trail "briefly". The
    quantities `trail_decay` and `ripple_life` DRIVE are scaled by the
    envelope; the params themselves are never written, and both are back to
    the bit by the release's end.

    ROW W5.5 reads W1.4's two numbers as SMEAR LENGTHS rather than
    durations: the lap runs `word_shape_speed_x` times faster, so the same
    half-life would lay a smear that many times longer, and both targets
    are divided by the multiplier. W1.4's constants are untouched in the
    source — what moved is what they mean — so this test asserts the
    ARITHMETIC rather than the old loose "more than three times"."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-restore", particle_count=3)
        try:
            _render(clock, virtual, 60)
            base = (eff.trail_decay, eff.ripple_life,
                    eff._trail_half_life(), eff._trail_gain(),
                    eff._wake_half_life())
            eff.update_config(_told())
            _render(clock, virtual, int((FORM_S + HOLD_S / 2) / DT))
            # at a standing envelope the targets are the pair and the
            # trace's life, each divided by the lap's own speed-up
            few, _many = FX.WS_TRAIL_HALF_LIFE_S
            # ROW W6.1: each target is FLOORED at the revisit gap, which
            # with his three fish at x3 is the binding term — the whole
            # point of the row's port from Orbits.
            gap = eff._word_shape_revisit_gap(1.0)
            assert gap == pytest.approx(
                FX.WS_LOOP_S_FEW / (3 * FX.WS_SPEED_X))
            want_trail = max(few / FX.WS_SPEED_X, FX.WS_TRAIL_GAP_X * gap)
            want_wake = max(
                FX.WS_RIPPLE_LIFE_S / FX.WS_SPEED_X * FX.WAKE_HALF_LIFE_X,
                FX.WS_TRAIL_GAP_X * gap)
            assert eff._trail_half_life() == pytest.approx(want_trail)
            assert eff._wake_half_life() == pytest.approx(want_wake)
            # ... and the floor really is what binds, not the pair
            assert want_trail > few / FX.WS_SPEED_X
            # ... and both really are LONGER than his own, which is his
            # note ("lower decay briefly"), just not by the x3 the slow lap
            # needed
            assert eff._trail_half_life() > base[2]
            assert eff._wake_half_life() > base[4]
            assert eff._trail_gain() == pytest.approx(FX.WS_TRAIL_GAIN)
            assert (eff.trail_decay, eff.ripple_life) == base[:2]
            _render(clock, virtual, int((HOLD_S / 2 + RELEASE_S) / DT) + 30)
            assert eff._ws is None
            assert (eff.trail_decay, eff.ripple_life,
                    eff._trail_half_life(), eff._trail_gain(),
                    eff._wake_half_life()) == base
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_many_fish_take_the_shared_outline_and_the_mode_latches(tmp_path):
    """His Q10 A as revised for Fish: one shared outline either way, and
    which MODE it is — few (the water keeps a trace) or many — is latched
    at the edge, so a population change mid-shape cannot switch it."""
    async def go():
        for count, few in ((3, True), (6, False)):
            host, cm, clock, virtual, eff = await _effect(
                tmp_path, f"fish-ws-mode-{count}", particle_count=count)
            try:
                _render(clock, virtual, 180)
                eff.update_config(_told())
                _render(clock, virtual, 4)
                assert eff._ws["few"] is few, count
                # every fish has a place on the ONE loop, all distinct
                places = eff.p_ws_s[:eff.n]
                live = places[np.isfinite(places)]
                assert live.size == count
                assert np.unique(np.round(live, 6)).size == count
                # ... and the mode does not move when the count does
                eff.update_config({"particle_count": 9})
                _render(clock, virtual, 60)
                assert eff._ws["few"] is few, "the mode latched at the edge"
            finally:
                cm.__exit__(None, None, None)
                await host.shutdown()
    asyncio.run(go())


def test_the_water_trace_is_few_fish_only(tmp_path):
    """P2 A is scoped to FEW on purpose: with many, the bodies and their own
    trails already light the outline, and a longer-lived busy wake is where
    white comes from (the WAKE COLOUR block)."""
    async def go():
        for count, expect in ((3, True), (6, False)):
            host, cm, clock, virtual, eff = await _effect(
                tmp_path, f"fish-ws-trace-{count}", particle_count=count)
            try:
                _render(clock, virtual, 180)
                base = eff._wake_half_life()
                eff.update_config(_told())
                _render(clock, virtual, int(FORM_S / DT))
                # FEW eases the trace's life up to WS_RIPPLE_LIFE_S over
                # the lap's own speed-up (row W5.5 reads it as a LENGTH —
                # see `_wake_half_life`); MANY is left exactly as it is
                want = max(
                    FX.WS_RIPPLE_LIFE_S / FX.WS_SPEED_X
                    * FX.WAKE_HALF_LIFE_X,
                    FX.WS_TRAIL_GAP_X
                    * eff._word_shape_revisit_gap(1.0))
                longer = eff._wake_half_life() > base + 1e-9
                assert longer is expect, count
                assert eff._wake_half_life() == pytest.approx(
                    want if expect else base)
            finally:
                cm.__exit__(None, None, None)
                await host.shutdown()
    asyncio.run(go())


def test_a_fish_born_mid_shape_has_no_place_on_the_loop(tmp_path):
    """The places are handed out at the edge and nothing re-spaces the line
    for an arrival, so a fish that swims in mid-shape just swims."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-arrival", particle_count=3)
        try:
            _render(clock, virtual, 180)
            eff.update_config(_told())
            _render(clock, virtual, 30)
            before = int(np.isfinite(eff.p_ws_s[:eff.n]).sum())
            eff.update_config({"particle_count": 6})
            _render(clock, virtual, 30)
            placed = int(np.isfinite(eff.p_ws_s[:eff.n]).sum())
            assert eff.n > before and placed == before
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_wall_keeps_a_fish_it_is_late_turning_back(tmp_path):
    """The wall's authority is faded by the envelope (the PAUSES
    paragraph) — EXCEPT where it is late turning a fish back from a wall it
    is heading into. "The pond gives way, the wall does not" is what keeps
    a fish on the panel and a shape is not allowed to spend it.

    ROW W5.5 relaxed the wall's own FLOOR onto the shaped circle (the third
    member of `_ws_wall`): the wall is the one authority that still
    overrides the loop's steer, so a floor left at the fish's own circle
    would round a corner near the pond's edge wide of the line however
    tight the shape's circle is. STILL FLOORED, on the same tighter
    clamp — and `own_floor=True`, which the landing line's own corner
    rounding and the probe's reach use, keeps the fish's own radius."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-wall", particle_count=3, roam_scale=0.75)
        try:
            _render(clock, virtual, 120)
            eff.update_config(_told())
            _render(clock, virtual, int((FORM_S + HOLD_S) / DT))
            # the look-ahead is shortened, the arc tightened and the floor
            # relaxed onto the shaped circle, all three by m
            look_s, turn_x, floor_x = eff._ws_wall
            assert look_s == pytest.approx(
                eff.wall_lookahead * (1.0 - FX.WS_WALL_LOOK_CUT))
            assert turn_x == pytest.approx(FX.WS_WALL_TURN_X)
            assert floor_x == pytest.approx(FX.WS_TURN_X)
            theta = np.full(4, np.pi / 2, np.float32)
            speed = np.full(4, eff.cruise_px, np.float32)
            shaped = eff.turn_radius_px * FX.WS_TURN_X
            assert float(eff._glance_radius(theta, speed).min()) >= \
                shaped - 1e-6, "the clamp is still a clamp, a tighter one"
            assert float(eff._glance_radius(
                theta, speed, own_floor=True).min()) >= \
                eff.turn_radius_px - 1e-6, (
                    "the landing line's own rounding keeps HIS radius")
            _render(clock, virtual, int(RELEASE_S / DT) + 30)
            assert eff._ws_wall is None, "his own wall is back"
            assert float(eff._glance_radius(theta, speed).min()) >= \
                eff.turn_radius_px - 1e-6, "... and so is the floor"
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


# ── ROW W5.5: SPEED, THE TURN CIRCLE AND THE AIM ──────────────────────────

def test_the_speed_is_registered_and_ramped_by_the_envelope(tmp_path):
    """ROW W5.5's first lever. `word_shape_speed_x` is a REGISTERED param
    (so Sonic reaches it per scene entry for free, like `word_shape_size`),
    it is `1 + (x - 1) * m`, and it is x1 at BOTH ends of the shape — his
    standing rule, "they need to smoothly accelerate and not have sudden
    velocity shifts"."""
    schema = FX.Fish2d.CONFIG_SCHEMA.schema
    names = {getattr(k, "schema", k) for k in schema}
    assert "word_shape_speed_x" in names
    # registered, NOT one of the told keys (which ride only the one write)
    assert "word_shape_speed_x" not in FX.Fish2d.ADVANCED_KEYS
    registry = json.loads(
        (REPO / "config" / "effect_params.json").read_text())
    params = registry["effects"]["fish"]["params"]
    assert params["word_shape_speed_x"]["default"] == FX.WS_SPEED_X
    assert registry["effects"]["fish"]["defaults"]["word_shape_speed_x"] == \
        FX.WS_SPEED_X

    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-speed", particle_count=3)
        try:
            assert eff._word_shape_speed_x(0.0) == pytest.approx(1.0)
            assert eff._word_shape_speed_x(1.0) == pytest.approx(
                FX.WS_SPEED_X)
            assert eff._word_shape_speed_x(0.5) == pytest.approx(
                1.0 + (FX.WS_SPEED_X - 1.0) * 0.5)
            _render(clock, virtual, 120)
            eff.update_config(_told())
            seen = []
            for _ in range(int((FORM_S + HOLD_S + RELEASE_S) / DT) + 30):
                _render(clock, virtual, 1)
                ws = eff._ws
                if ws is None:
                    seen.append(1.0)
                    continue
                told = ws["told"]
                seen.append(eff._word_shape_speed_x(wsk.envelope(
                    ws["t"], told.form_s, told.hold_s, told.release_s)))
            assert max(seen) == pytest.approx(FX.WS_SPEED_X, abs=1e-3)
            assert seen[0] == pytest.approx(1.0, abs=0.05), "x1 at the edge"
            assert seen[-1] == pytest.approx(1.0), "and x1 again after"
            # ... and never a step: the envelope is a smoothstep, so the
            # multiplier's own largest one-frame move is bounded by the
            # steepest that smoothstep can be
            step = max(abs(b - a) for a, b in zip(seen, seen[1:]))
            bound = (FX.WS_SPEED_X - 1.0) * 1.5 * DT / min(FORM_S, RELEASE_S)
            assert step <= bound + 1e-9, (step, bound)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_lap_and_the_dash_cap_both_take_the_multiplier(tmp_path):
    """The four quantities of `_word_shape_speed_x`'s docstring, the two
    that are visible from outside: the LINE's own march really does run a
    lap in `loop_s / x` seconds, and the DASH CAP scales with it — left
    alone it binds at x3 (the heart's pace goes 21 -> 64 px/s against a
    44 px/s cap) and the fish would chase a line it can never catch."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-lap", particle_count=3,
            # HIS live Fish's own cruise — the cap arithmetic is about his
            # `base_speed`, not the harness's schema default
            base_speed=0.3, radius_scale=1.8)
        try:
            _render(clock, virtual, 120)
            eff.update_config(_told(form_s=FORM_S))
            march = []
            for _ in range(int((FORM_S + HOLD_S) / DT)):
                _render(clock, virtual, 1)
                if eff._ws is not None:
                    march.append(eff._ws["march"])
            assert march, "the shape ran"
            # the march over the HOLD's own frames: one lap per loop_s / x
            hold_from = int(FORM_S / DT) + 2
            laps = march[-1] - march[hold_from]
            secs = (len(march) - 1 - hold_from) * DT
            want = secs * FX.WS_SPEED_X / FX.WS_LOOP_S_FEW
            assert laps == pytest.approx(want, rel=0.02), (laps, want)
            # the cap: the procession's own pace already exceeds the
            # unscaled WS_DASH_X * cruise, which is why it had to scale
            pace = eff._word_shape_loop_px(
                word_shapes.get("heart"),
                eff._word_shape_size_n()) / FX.WS_LOOP_S_FEW * FX.WS_SPEED_X
            assert pace > FX.WS_DASH_X * eff.cruise_px, (
                pace, FX.WS_DASH_X * eff.cruise_px)
            assert pace < FX.WS_DASH_X * eff.cruise_px * FX.WS_SPEED_X
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_turn_circle_is_overridden_and_is_his_own_again_after(tmp_path):
    """ROW W5.5's second lever, and HIS OWN instruction for it: "you might
    need to override some min turn radii to match the effect, especially on
    the star." The clamp is still a clamp — every per-frame heading change
    is inside the circle IN FORCE — it is simply `WS_TURN_X` of the fish's
    own while a shape stands, and exactly his own again by the release's
    end (W1.4's law at 0.25, unchanged in shape at 0.10)."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-turn", particle_count=3)
        try:
            _render(clock, virtual, 120)
            eff.update_config(_told())
            worst_in_force = 0.0
            tight = 0.0
            hd0 = eff.p_hd[:eff.n].copy()
            spd0 = eff.p_spd[:eff.n].copy()
            for _ in range(int((FORM_S + HOLD_S + RELEASE_S) / DT) + 30):
                _render(clock, virtual, 1)
                n = eff.n
                ws = eff._ws
                m = 0.0
                if ws is not None:
                    told = ws["told"]
                    m = float(wsk.envelope(ws["t"], told.form_s,
                                           told.hold_s, told.release_s))
                turn_x = 1.0 - (1.0 - FX.WS_TURN_X) * m
                tight = max(tight, 1.0 / turn_x)
                step = np.abs(FX._wrap_pi(eff.p_hd[:n] - hd0[:n]))
                in_force = np.maximum(
                    eff.p_spd[:n] / eff.turn_radius_px, 1e-6
                ) / turn_x * float(eff.passed_dt)
                worst_in_force = max(
                    worst_in_force, float(np.max(step / in_force)))
                hd0 = eff.p_hd[:n].copy()
                spd0 = eff.p_spd[:n].copy()
            assert worst_in_force <= 1.0 + 1e-3, worst_in_force
            assert tight == pytest.approx(1.0 / FX.WS_TURN_X, rel=1e-3)
            assert eff._ws is None
            # back to his own: at m = 0 the divisor is exactly 1
            assert 1.0 - (1.0 - FX.WS_TURN_X) * 0.0 == 1.0
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


@pytest.mark.parametrize("shape_id", ["heart", "star", "diamond"])
def test_the_aim_and_the_circle_both_fit_inside_one_cell_pitch(shape_id):
    """ROW W5.5's CORNER BUDGET, as arithmetic rather than pixels — the two
    terms that chose `WS_TARGET_LEAD` and `WS_TURN_X`, so a later change
    that widens either fails here before it reaches the measured proof.

    THE AIM'S OWN CUT is a real bound: a pursuit steer aimed `L` of arc
    ahead has a chord that passes a corner of exterior angle theta at
    `(L / 2) sin(theta / 2)` at most, whatever it is capable of turning, so
    at the shipped lead the aim alone can never spend the row's whole
    1.0-cell-pitch budget. Read along the panel's TIGHTER axis (a row is
    sqrt(3)/2 of a pitch), the strict way round.

    THE CIRCLE is asserted as the spec's own sentence — "a turn circle
    under half a cell pitch" — and NOT as a corner depth, because the
    minimal-arc depth `R (1 / cos(theta / 2) - 1)` is a reference figure
    rather than a bound on the measured distance: a fish may also overshoot
    INTO a cusp and come back, which passes closer than any arc that merely
    turns the corner (measured, the heart's cleft: a 1.52-pitch arc depth
    against 0.04 pitches of real path). The bar itself is therefore section
    9 of scripts/check_fish_word_shape.py — the real paths, every vertex,
    both modes. This is the budget those paths have to fit in."""
    import math

    half_w, half_h = (COLS - 1) / 2.0, (ROWS - 1) / 2.0
    col_pitch, row_pitch = 0.5, math.sqrt(3.0) / 2.0
    size = 0.62                      # his `word_shape_size`
    shape = word_shapes.get(shape_id)
    s = np.linspace(0.0, 1.0, 2880, endpoint=False)
    ux, uy = shape.at(s)
    x, y = ux * size * half_w * col_pitch, uy * size * half_h * row_pitch
    dx, dy = np.roll(x, -1) - x, np.roll(y, -1) - y
    seg = np.hypot(dx, dy)
    phi = np.arctan2(dy, dx)
    step = FX._wrap_pi(np.roll(phi, -1) - phi)
    win = max(int(round(1.0 / max(seg.mean(), 1e-9))), 1)
    pad = np.concatenate([step[-win:], step, step[:win]])
    acc = np.convolve(pad, np.ones(win), mode="same")[win:win + s.size]
    sharpest = float(np.max(np.abs(acc)))          # radians at a vertex
    assert sharpest > 0.9, "every shipped shape has a real corner"

    # the AIM's own cut, in cell pitches. The loop's length in pitches is
    # the sum of its segments; `L` is the arc the chord may span, which is
    # WS_REACH + WS_TARGET_LEAD of it.
    loop_pitch = float(seg.sum())
    lead_arc = (FX.WS_REACH + FX.WS_TARGET_LEAD) * loop_pitch
    # ROW W6.1: the aim is also FLOORED at WS_AIM_STEP_X of a frame's own
    # travel, and at 30 fps that floor is the binding term — so the budget
    # this test is about is the floor's, not the lead's. A frame's travel
    # is the procession's own pace (`loop_px / lap`) times `dt`, in cell
    # pitches, which is what `loop_pitch` is measured in.
    lap_s = FX.WS_LOOP_S_FEW / FX.WS_SPEED_X
    step_pitch = loop_pitch / lap_s * DT
    aim_arc = max(lead_arc, FX.WS_AIM_STEP_X * step_pitch)
    assert aim_arc > lead_arc, "at 30 fps the frame-step floor binds"
    aim_cut = 0.5 * aim_arc * math.sin(min(sharpest, math.pi) / 2.0)
    deg = math.degrees(sharpest)
    # AND ROW W6.1 SPENT PART OF THIS BUDGET ON PURPOSE. The floor above is
    # what stopped the nose wagging (11.4 -> 6.1 reversals per fish-second
    # at his own rate), and it costs chord cut: 0.63 cell pitches on the
    # heart, 0.56 on the diamond, and 1.01 ON THE STAR, whose point turns
    # 139 degrees. That last one is OVER the row's 1.0-pitch corner bar AS
    # AN UPPER BOUND — `(L / 2) sin(theta / 2)` is the most a chord of that
    # arc could cut, reached only by a steer that aims straight across the
    # point and turns not at all, and the real paths do not: section 9 of
    # the check script measures 0.79 cell pitches on the worst corner of
    # the worst seed, every shape, both modes. So the bound is PINNED here
    # with its own number rather than asserted at the bar, exactly as
    # section 5 pins the white tail it exceeds, and the bar itself stays
    # the measured paths.
    assert aim_cut <= 1.05, (shape_id, deg, aim_cut)
    if shape_id != "star":
        assert aim_cut <= 1.0, (shape_id, deg, aim_cut)
    # ... and the circle, as HIS own instruction for the row reads it:
    # "you might need to override some min turn radii to match the effect,
    # especially on the star" — under half a cell pitch, measured along the
    # tighter axis
    r_px = 0.14 * 1.8 * half_h * FX.WS_TURN_X    # his orbit_radius, shaped
    assert r_px * row_pitch <= 0.5, (r_px, r_px * row_pitch)
    # and it really is an override: the fish's OWN circle is nowhere near
    assert 0.14 * 1.8 * half_h * row_pitch > 2.0


def test_a_phase_arriving_mid_shape_wins(tmp_path):
    """P3 A means a shape is never TOLD while a charge, lull or drop is
    armed, but one can still ARRIVE. Then the phase's own choreography
    wins — the school is not on the loop at all — and the trail and wake
    still restore themselves at the release's end."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-phase", particle_count=4)
        try:
            _render(clock, virtual, 120)
            base = (eff._trail_half_life(), eff._wake_half_life())
            eff.update_config(_told())
            _render(clock, virtual, int(FORM_S / DT))
            assert eff._ws is not None
            eff.update_config({"phase": "charge", "phase_progress": 0.0})
            for i in range(1, 61):
                eff.update_config({"phase_progress": i / 60.0})
                _render(clock, virtual, 1)
            # the school has it: no fish is being steered by the loop
            assert eff._school_on
            _render(clock, virtual, int((HOLD_S + RELEASE_S) / DT) + 60)
            assert eff._ws is None
            assert (eff._trail_half_life(), eff._wake_half_life()) == base
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_pond_rest_is_held_while_a_shape_runs(tmp_path):
    """`_rest_held`'s list gains the shape beside the charge, the lull, the
    drop, the school, a rush and a crossfade."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-rest", particle_count=3, quiet_rest=1.0)
        try:
            _render(clock, virtual, 10)
            assert eff._rest_held(eff.n) is False
            eff.update_config(_told())
            _render(clock, virtual, 30)
            assert eff._rest_held(eff.n) is True
            assert eff._rest_level == 0.0
            _render(clock, virtual,
                    int((FORM_S + HOLD_S + RELEASE_S) / DT) + 30)
            assert eff._rest_held(eff.n) is False
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_help_page_tells_him_about_the_run_and_the_corners():
    """AGENTS.md's help-content rule: row W5.5 added a user-facing setting
    and changed what the Fish's shape LOOKS like, so the Help page's own
    Fish paragraph has to say so in the same change. The topic the params
    name (`word-shapes`) must exist too, or the Initial Set tab's HelpLink
    goes nowhere."""
    content = (REPO / "spectra/web/src/help/helpContent.ts").read_text()
    assert "id: 'word-shapes'" in content
    assert "id: 'word-shapes-looks'" in content
    start = content.index("id: 'word-shapes-looks'")
    end = content.index("id: 'sung-labels-reading'", start)
    looks = content[start:end]
    fish = next(line for line in looks.splitlines()
                if line.strip().startswith("'Fish draws it as a procession"))
    for token in ("Word Shape Speed", "three times faster", "corners",
                  "a lap in under two seconds"):
        assert token in fish, token


# ── ROW W6.1's OWN LAWS ────────────────────────────────────────────────────

@pytest.mark.parametrize("fps", [30.0, 60.0, 15.0])
def test_the_shaped_heading_step_never_passes_the_error_at_any_rate(fps):
    """ROW W6.1's FIRST LAW, as arithmetic: the shaped step is the EXACT
    first-order form, `k = 1 - exp(-gain * dt)` of the heading error
    commanded as `d_hd * k / dt`, so `k < 1` at every frame rate and the
    error can never change sign because the step passed it.

    WHAT IT REPLACED, and why the row exists: `omega = d_hd * gain` with
    `gain = TURN_GAIN * (1 + WS_TURN_GAIN_X)` corrects `gain * dt` of the
    error per frame — fine at the 60 fps the rig used to measure at, and
    PAST THE TARGET at his crystal's 30, where it alternates sign every
    frame. This test holds at 15 fps too, which is the point of a closed
    form: there is no frame rate at which it misbehaves."""
    dt = 1.0 / fps
    gain_ws = FX.TURN_GAIN * (1.0 + FX.WS_TURN_GAIN_X)
    k = -np.expm1(-gain_ws * dt)
    # the step as a FRACTION of the error, which is the quantity that must
    # stay under 1
    assert 0.0 < k < 1.0, (fps, k)
    # ... and the old law really did pass it at his own rate
    proportional = gain_ws * dt
    if fps <= 30.0:
        assert proportional > 1.0, (fps, proportional)
    # the rate commanded is the error times k / dt
    omega_per_rad = k / dt
    assert omega_per_rad < gain_ws
    assert omega_per_rad * dt == pytest.approx(k)


def test_the_shaped_step_is_his_own_expression_at_m_zero(tmp_path):
    """... and the blend is byte-exact at `m = 0`: `TURN_GAIN * (1 - 0) +
    k / dt * 0` IS `TURN_GAIN`, in IEEE arithmetic and not just in
    algebra — which is half of why section 1 of the check script still
    reads IDENTICAL at both frame rates (the other half being that the
    whole block is gated on `ws is not None`)."""
    for fps in (30.0, 60.0):
        dt = 1.0 / fps
        gain_ws = FX.TURN_GAIN * (1.0 + FX.WS_TURN_GAIN_X)
        k_ws = -np.expm1(-gain_ws * dt) / max(dt, 1e-6)
        blended = FX.TURN_GAIN * (1.0 - 0.0) + k_ws * 0.0
        assert blended == FX.TURN_GAIN
        # and at m = 1 it IS the closed form
        assert (FX.TURN_GAIN * (1.0 - 1.0) + k_ws * 1.0) == k_ws


def test_the_clamp_still_means_an_arc_at_his_own_frame_rate(tmp_path):
    """ROW W6.1's SECOND LAW: the shaped clamp carries a per-RENDERED-FRAME
    ceiling, so `omega_max * dt` can never pass `WS_TURN_MAX_RAD_FRAME` and
    the turn-circle guarantee's own sentence — "an about-face is always an
    arc and never a flip" — stays TRUE at 30 fps.

    Measured before the ceiling existed: a fish on the loop with the wall's
    glance saturating the clamp turned 6.6 radians in one frame (more than
    a full circle) and travelled 20.5 px OFF THE LIT PANEL. STAR's
    `ROTATION_CAP_DEG_FRAME` is the precedent for a cap per rendered frame.
    """
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-arc", particle_count=3)
        try:
            _render(clock, virtual, 120)
            eff.update_config(_told())
            hd0 = eff.p_hd[:eff.n].copy()
            worst = 0.0
            seen_shape = False
            for _ in range(int((FORM_S + HOLD_S) / DT)):
                _render(clock, virtual, 1)
                n = eff.n
                if eff._ws is not None:
                    seen_shape = True
                step = np.abs(FX._wrap_pi(eff.p_hd[:n] - hd0[:n]))
                worst = max(worst, float(np.max(step)))
                hd0 = eff.p_hd[:n].copy()
            assert seen_shape
            # EVERY per-frame heading change, at his own rate, inside the
            # ceiling — and the ceiling is well under a half turn, so it
            # really is an arc
            assert worst <= FX.WS_TURN_MAX_RAD_FRAME + 1e-6, worst
            assert FX.WS_TURN_MAX_RAD_FRAME <= np.pi
            # AND THE CEILING CANNOT BIND AT m = 0, which is why it needs
            # no gate of its own beyond the shape block it sits in: the
            # ordinary clamp would have to belong to a fish swimming
            # `ceiling / dt * turn_radius_px` = 214 px/s at 30 fps, and
            # this effect's own fastest ordinary fish is the swim burst's
            # dash plus the lunge, 4.2x cruise. (The SHAPED dash cap is
            # 7.5x cruise and does pass it — but a fish moving that fast is
            # a fish ON the loop at a standing envelope, which is exactly
            # the case the ceiling is FOR.)
            need = (FX.WS_TURN_MAX_RAD_FRAME / DT) * eff.turn_radius_px
            own_max = ((1.0 + FX.SWIM_BURST_SPEED_X + FX.LUNGE_GAIN)
                       * eff.cruise_px)
            assert need > own_max, (need, own_max)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_aim_is_never_shorter_than_a_frames_travel(tmp_path):
    """ROW W6.1's THIRD LAW, and the one that owns the WAG: the aim is an
    ARC and a frame's travel is a LENGTH, and at 30 fps the second is the
    bigger one. Measured frame by frame on the diamond before the floor
    existed — the target 0.2-1.1 px of arc ahead against 1.5 px of travel,
    so at a corner the aim point jumped across it within ONE frame and the
    steer spent 90 degrees in a single step.

    Proven here as the arithmetic the effect applies: the aim arc every
    shaped fish gets is at least `WS_AIM_STEP_X` of its own frame step,
    converted into loop fractions by the loop's own measured length."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-aim", particle_count=3)
        try:
            _render(clock, virtual, 120)
            eff.update_config(_told())
            _render(clock, virtual, int((FORM_S + HOLD_S / 2) / DT))
            st = eff._ws
            assert st is not None and st["loop_px"] > 0.0
            n = eff.n
            placed = np.flatnonzero(np.isfinite(eff.p_ws_s[:n]))
            assert placed.size >= 1
            # the floor the effect computes, in loop fractions
            floor = (FX.WS_AIM_STEP_X * eff.p_spd[placed]
                     * float(eff.passed_dt) / st["loop_px"])
            # ... and it really is bigger than the lead the aim would
            # otherwise be, at HIS frame rate
            assert float(np.min(floor)) > FX.WS_TARGET_LEAD, (
                float(np.min(floor)), FX.WS_TARGET_LEAD)
            # in PX the floor is exactly WS_AIM_STEP_X frame steps
            step_px = eff.p_spd[placed] * float(eff.passed_dt)
            assert np.allclose(floor * st["loop_px"],
                               FX.WS_AIM_STEP_X * step_px)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_revisit_gap_is_the_latched_lap_over_the_latched_count(tmp_path):
    """ROW W6.1's FOURTH LAW — the quantity the two half-lives are floored
    at, and the one Orbits' W4.4 finding is about. It reads the LATCHED lap
    and the LATCHED count, so a fish leaving mid-shape cannot step the
    floor, and it is ZERO before the entries exist (which is what makes the
    floor inert on those frames)."""
    async def go():
        for count, loop_s in ((3, FX.WS_LOOP_S_FEW),
                              (6, FX.WS_LOOP_S_MANY)):
            host, cm, clock, virtual, eff = await _effect(
                tmp_path, f"fish-ws-gap-{count}", particle_count=count)
            try:
                # before a shape there is no gap at all
                assert eff._word_shape_revisit_gap(1.0) == 0.0
                _render(clock, virtual, 180)
                eff.update_config(_told())
                _render(clock, virtual, int(FORM_S / DT))
                st = eff._ws
                assert st is not None and st["assigned"]
                k = int(st["count"])
                want = loop_s / (k * FX.WS_SPEED_X)
                assert eff._word_shape_revisit_gap(1.0) == pytest.approx(
                    want)
                # the numbers the row quotes: 0.61 s with three fish on the
                # heart, 0.39 s with six
                assert want == pytest.approx(
                    0.611 if count == 3 else 0.389, abs=5e-3)
                # at m = 0 the gap is the UNSPED lap's, so the floor it
                # feeds is zero there anyway (it is multiplied by m)
                assert eff._word_shape_revisit_gap(0.0) == pytest.approx(
                    loop_s / k)
            finally:
                cm.__exit__(None, None, None)
                await host.shutdown()
    asyncio.run(go())


def test_the_wander_and_the_ordinary_wake_hand_over_to_the_loop(tmp_path):
    """ROW W6.1: the two terms W1.4 and W5.5 left ungated. THE WANDER was
    the one steering term still pushing the DESIRED heading about while a
    shape ran (`WANDER_W` 1.0 against the loop's `WS_SEEK_W` 14, about 0.7
    degrees of noise a frame, which the shaped gain then chased); THE
    ORDINARY WAKE was half the off-band light at the moment bar 4 is read
    at. Both now ease out by `m` exactly as the swirl and the beat's kicks
    already did, and both are his own again by the release's end.

    Asserted as the CONSTANTS and the gate rather than as pixels, because
    the pixels are section 11's job: the wake's fade is a real number under
    1 and the blend is per fish, so an unplaced fish keeps its whole wake.
    """
    assert FX.WS_WAKE_FADE < 1.0, "the ordinary wake really does ease out"
    assert 0.0 <= FX.WS_WAKE_FADE
    src = (REPO / "fx" / "effects" / "fish.py").read_text()
    # the wander's blend is gated on a shape running and uses m_fish, so an
    # untold frame is the same expression it always was
    assert 'w_wander = w_wander * (1.0 - ws["m_fish"])' in src
    assert 'if ws is not None and WS_WAKE_FADE < 1.0:' in src

    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-hand-over", particle_count=3)
        try:
            _render(clock, virtual, 120)
            base = float(eff.ripple_amount)
            eff.update_config(_told())
            _render(clock, virtual, int((FORM_S + HOLD_S) / DT))
            # `ripple_amount` itself is NEVER written — the scaling is the
            # quantity it drives, which is what makes the restore exact
            assert float(eff.ripple_amount) == base
            _render(clock, virtual, int(RELEASE_S / DT) + 30)
            assert eff._ws is None
            assert float(eff.ripple_amount) == base
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


def test_the_port_from_orbits_is_persistence_and_not_a_highlight():
    """HIS WORDS: "if we did a highlight of the shape in orbits, do it on
    fish." THERE IS NO HIGHLIGHT IN ORBITS TO PORT, and this test is what
    keeps that straight for the next row: `fx/effects/orbits.py` carries
    four WORD_SHAPE_* constants and no shape-time brightness, glow or line
    lift — W4.4's option B was framed and never built, he settled option A.
    What makes Orbits' outline read whole is its TRAIL outliving the
    revisit gap at x4, and that is what row W6.1 gave Fish."""
    orbits = (REPO / "fx" / "effects" / "orbits.py").read_text()
    names = {n for n in ("WORD_SHAPE_FEW", "WORD_SHAPE_MANY",
                         "WORD_SHAPE_TRAIL_S", "WORD_SHAPE_SPEED_X")
             if f"\n{n} " in orbits or f"\n{n}=" in orbits}
    assert names == {"WORD_SHAPE_FEW", "WORD_SHAPE_MANY",
                     "WORD_SHAPE_TRAIL_S", "WORD_SHAPE_SPEED_X"}, names
    # no FIFTH word-shape constant has appeared that could be a highlight
    import re
    found = set(re.findall(r"^WORD_SHAPE_[A-Z_]+", orbits, re.M))
    assert found == names, found
    # ... and Fish's own answer is a DURATION floor, not a brightness
    assert FX.WS_TRAIL_GAP_X > 0.0
    fish_src = (REPO / "fx" / "effects" / "fish.py").read_text()
    assert "THERE IS NO HIGHLIGHT IN ORBITS TO PORT" in fish_src
    # the trail's own BOOST is W1.4's and is untouched by this row
    assert FX.WS_TRAIL_GAIN == pytest.approx(1.6)


def test_the_skill_and_the_map_name_this_rows_proofs():
    """The skill gate (scripts/check_effect_scene_skills_current.py): row
    W5.5 changed a mapped effect file, so the effect's own skill carries
    its levers and its proofs."""
    skill = (REPO / ".claude/skills/fish-effect/SKILL.md").read_text()
    assert "ROW W5.5" in skill
    assert "ROW W6.1" in skill
    for token in ("word_shape_speed_x", "WS_TURN_X", "WS_TURN_GAIN_X",
                  "WS_TARGET_LEAD", "WS_WALL_TURN_X",
                  "WS_AIM_STEP_X", "WS_TURN_MAX_RAD_FRAME",
                  "WS_TRAIL_GAP_X", "WS_WAKE_FADE", "30 fps",
                  "check_fish_word_shape.py"):
        assert token in skill, token
    shapes = (REPO / ".claude/skills/word-shapes/SKILL.md").read_text()
    assert "ROW W5.5" in shapes
    assert "ROW W6.1" in shapes
    mapping = json.loads(
        (REPO / ".claude/skills/EFFECT_SCENE_MAP.json").read_text())
    files = mapping["effects"]["fish-effect"]["files"]
    assert "scripts/check_fish_word_shape.py" in files
    assert "tests/test_fish_word_shape.py" in files
