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

DT = 1.0 / 60.0
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
    the bit by the release's end."""
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
            assert eff._trail_half_life() > base[2] * 3
            assert eff._trail_gain() == pytest.approx(FX.WS_TRAIL_GAIN)
            assert eff._wake_half_life() > base[4] * 3
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
                longer = eff._wake_half_life() > base * 2
                assert longer is expect, count
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
    a fish on the panel and a shape is not allowed to spend it."""
    async def go():
        host, cm, clock, virtual, eff = await _effect(
            tmp_path, "fish-ws-wall", particle_count=3, roam_scale=0.75)
        try:
            _render(clock, virtual, 120)
            eff.update_config(_told())
            _render(clock, virtual, int((FORM_S + HOLD_S) / DT))
            # the look-ahead is shortened and the arc tightened, both by m,
            # and both still floored at the fish's own turn radius
            look_s, turn_x = eff._ws_wall
            assert look_s == pytest.approx(
                eff.wall_lookahead * (1.0 - FX.WS_WALL_LOOK_CUT))
            assert turn_x == pytest.approx(FX.WS_WALL_TURN_X)
            theta = np.full(4, np.pi / 2, np.float32)
            speed = np.full(4, eff.cruise_px, np.float32)
            assert float(eff._glance_radius(theta, speed).min()) >= \
                eff.turn_radius_px - 1e-6
            _render(clock, virtual, int(RELEASE_S / DT) + 30)
            assert eff._ws_wall is None, "his own wall is back"
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(go())


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
