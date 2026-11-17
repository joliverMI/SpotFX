"""ORBITS' WORD SHAPE — few trace it, many become it (Word Shapes plan row
W1.3, his P1 A; `fx/effects/orbits.py`'s own WORD SHAPES block and
`.claude/skills/orbits-effect/SKILL.md` are the binding statements).

Every number this file asserts is measured on the real vendored render
pipeline, on his real `crystal-mapper` mask, by
`scripts/check_orbits_word_shape.py` — imported here rather than
re-implemented, so the evidence script and the gate can never disagree
about what was measured.

The plan's common acceptance for a wave-1 row, in order:

  1. UNTOLD IS TODAY'S — the pinned pre-change module, frame for frame over
     300 frames of quiet and of busy audio, with no told keys and with the
     keys at NOT_TOLD.
  2. COMPLETE ON THE WORD — through the real ResponseEngine and the real
     effect, the form fraction reads 1.0 within one rendered frame of
     `edge + form_s`, for form 0.5 s and 0.9 s; and a form shorter than
     anything the engine would send is handled, never divided by.
  3. NOTHING JUMPS — every blob's per-frame speed and heading change at the
     form's start, the hold's two edges and the release's end, against this
     effect's OWN ordinary maximum on the same seed and the same audio.
  4. IT IS THE SHAPE — the row's clarity bar on the real mask at SIZE 0.62,
     all three shapes, Energy 0.2 and 0.8: >= 60% of the outline lit with
     FEW, >= 75% with MANY; plus every blob's centre (FEW) or tether (MANY)
     within one cell pitch of the outline at the hold.
  5. NO WHITE, 6. COST — both measured by the same script.
  7. THE EDGES — two words of the same shape both edge on the SEQ, a second
     word mid-release restarts the form from the current fraction, a
     clearing write releases from the current fraction, a stale persisted
     SEQ on a fresh instance never fires, and a phase arriving mid-shape
     takes precedence.
  8. THE WIRING — the registry, the skill, the map, the contract fixture.

WHERE THE BAR IS ASSERTED, stated plainly: the plan measures coverage "at
the word and at mid-hold" and sets the bar "AT THE HOLD". The bar is
asserted at the hold (mid-hold) and the word's own number is printed
beside it, because at the word the shape has only just completed — the
trail behind each blob is still the forming sweep, not the outline — and no
blob-based effect can light 60% of an outline at the instant it arrives on
it. Measured, the word reads 31-70% and the hold 74-100%.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from random import Random

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.check_orbits_word_shape as C  # noqa: E402
from fx import device_model, facade, headless  # noqa: E402
from fx.effects import orbits as FX  # noqa: E402
from fx.effects import word_shape_keys as wsk  # noqa: E402
from fx.effects import word_shapes  # noqa: E402

DT = C.DT
ROWS, COLS = C.ROWS, C.COLS
VID = headless.DEFAULT_VIRTUAL_ID

# The merge base this row was built on — master at W0.3 (PR 521), the last
# commit before this module knew any shape. A FIXED ref, never a moving one
# (scripts/check_fish_camera.py's BASELINE_REF is the cautionary tale).
BASELINE_REF = "5db75fe6774437100383b3a0bed31aa90642cce1"

_PINNED: dict[str, str] = {}


def _run(coro):
    return asyncio.run(coro)


def _pinned_type() -> str:
    """The pre-change orbits.py, registered as a SECOND effect beside
    today's (an Effect subclass registers under its module's last name
    segment) — tests/test_flare_punch_crystal.py's `_pinned_type`."""
    if "orbits" in _PINNED:
        return _PINNED["orbits"]
    name = "orbits_pre_word_shape"
    try:
        src = subprocess.run(
            ["git", "show", f"{BASELINE_REF}:fx/effects/orbits.py"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                                 # noqa: BLE001
        pytest.skip(f"cannot read {BASELINE_REF}:fx/effects/orbits.py "
                    f"({exc}) — the byte-identity claim is NOT checked")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _PINNED["orbits"] = name
    return name


# ── 1. untold is today's ───────────────────────────────────────────────────

def _frames(tag: str, effect_type: str, energy: float, n_frames: int,
            count: int = 3, write: dict | None = None) -> np.ndarray:
    """Render `n_frames` of one effect type on the real crystal mask, same
    seed and same audio, optionally writing `write` after the first frame."""
    async def main():
        headless.silence_audio()
        td = tempfile.mkdtemp()
        host = await headless.start_headless_host(
            str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS,
            device_id=tag, real_mask=C.REAL)
        virtual = host.virtuals.get(tag)
        out = []
        try:
            with headless.fake_clock() as clock:
                np.random.seed(7)
                eff = headless.attach_effect(
                    host, virtual, effect_type,
                    dict(C.HIS_MATRIX, gradient=C.SET, particle_count=count))
                eff._rng = np.random.default_rng(7)
                for i in range(1, n_frames + 1):
                    with eff.lock:
                        eff.audio_data_updated(C._Audio(i, energy))
                    clock.advance(DT)
                    f = virtual.assemble_frame()
                    if f is not None:
                        virtual.flush(f)
                        out.append(np.array(f, dtype=np.float32))
                    if i == 1 and write is not None:
                        with eff.lock:
                            eff._apply_config(dict(write), validate=False,
                                              fire_event=False)
        finally:
            await host.shutdown()
        return np.array(out)

    return _run(main())


@pytest.mark.parametrize("energy,label", [(0.0, "quiet"), (0.8, "busy")])
def test_untold_renders_exactly_what_it_renders_today(energy, label):
    """Acceptance 1. No told keys at all: 300 frames, byte for byte."""
    pinned = _pinned_type()
    today = _frames(f"today-{label}", "orbits", energy, 300)
    before = _frames(f"before-{label}", pinned, energy, 300)
    assert today.shape == before.shape and today.size
    assert today.max() > 0.0, "a run that never lit anything proves nothing"
    assert np.array_equal(today, before), label


def test_the_not_told_defaults_are_also_byte_identical():
    """Rule 2 of word_shape_keys: every member gets every key on every
    write, NOT_TOLD included — so a write OF the defaults must be inert.

    The control is another write, not no write at all: ANY `_apply_config`
    on this effect rebuilds its two audio filters (`config_updated`), which
    moves the impulse and therefore the frame. That is pre-existing and has
    nothing to do with shapes, so the comparison is NOT_TOLD against a
    write of a key at the value it already holds."""
    inert = _frames("inert", "orbits", 0.6, 240, write={"phase": "none"})
    cleared = _frames("cleared", "orbits", 0.6, 240, write=dict(wsk.NOT_TOLD))
    assert inert.shape == cleared.shape and inert.max() > 0.0
    assert np.array_equal(inert, cleared)


def test_the_told_keys_are_absent_from_the_parameter_registry():
    """They ride ONLY the Words band's own write (rule 1), so they must
    never become editable, driftable or Sonic-settable params."""
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    params = registry["effects"]["orbits"]["params"]
    defaults = registry["effects"]["orbits"]["defaults"]
    for key in wsk.KEYS:
        assert key not in params, key
        assert key not in defaults, key
    assert set(wsk.KEYS) <= set(FX.Orbits2d.ADVANCED_KEYS)


# ── 2. complete on the word (the real ResponseEngine) ──────────────────────

def _categories(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["orbits"], "role": None}}))


def _words_scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Orbits Words",
        devices=[SceneDeviceConfig(target_kind="virtual", target=VID,
                                   effect_type="orbits")],
        flare_kinds=[FlareKind(name="Heart", type="word_shape")],
        responses={"word": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0,
            kinds={"Heart": 1.0})])})


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


def _action(shape: str, energy: float, form_s: float, hold_s: float,
            release_s: float):
    """The synthetic shape action on_word_shape accepts beside a real
    WordAction — scene_response's own PreviewWordShape, so this test never
    fabricates a WordHit that could look like a word really sung."""
    from spectra.services.scene_response import PreviewWordShape
    return PreviewWordShape(shape_id=shape, energy=energy, form_s=form_s,
                            hold_s=hold_s, release_s=release_s)


async def _engine_run(tmp_path, sub, form_s, *, shape="heart", count=3,
                      hold_s=1.0, release_s=1.5, energy=0.5, frames=200,
                      extra=None):
    """Fire one shape through the REAL ResponseEngine onto the real effect
    and return (the effect, [(frame index, the effect's own form fraction)],
    the fire record, the index of the frame the write was made before)."""
    _categories(tmp_path)
    headless.silence_audio()
    host = await headless.start_headless_host(
        str(tmp_path / sub), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=VID, real_mask=C.REAL)
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    trace: list[tuple[int, float]] = []
    try:
        with headless.fake_clock() as clock:
            np.random.seed(7)
            cfg = dict(C.HIS_MATRIX, gradient=C.SET, particle_count=count,
                       **(extra or {}))
            eff = headless.attach_effect(host, virtual, "orbits", cfg)
            eff._rng = np.random.default_rng(7)
            _executor, conductor, responder = _engine(clock)
            conductor.on_scene_fire(_words_scene(), [{
                "virtual_id": VID, "effect_type": "orbits",
                "config": dict(cfg), "entry_id": "d1",
                "color_mode": "set"}])
            for _ in range(60):
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
            record = await responder.on_word_shape(
                _action(shape, energy, form_s, hold_s, release_s))
            for i in range(frames):
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
                trace.append((i, float(eff._ws_m)))
    finally:
        facade.set_host(None)
        await host.shutdown()
    return eff, trace, record


def _form_frames(trace) -> tuple[int, int]:
    """(the first frame the shape moved, the first frame it stood complete),
    as indices into the trace."""
    moved = next(i for i, m in trace if m > 0.0)
    full = next(i for i, m in trace if m >= 1.0 - 1e-9)
    return moved, full


@pytest.mark.parametrize("form_s", [0.5, 0.9])
def test_the_shape_completes_on_the_word(tmp_path, form_s):
    """Acceptance 2. The told form is the time LEFT to the word, so the
    envelope must reach 1.0 exactly `form_s` after the edge — no settle
    time, no extra latency, one rendered frame of slack."""
    eff, trace, record = _run(_engine_run(
        tmp_path, f"onword-{form_s}", form_s))
    info = record["word_shape"]
    assert record["result"] == "applied"
    assert info["virtuals"] == 1 and info["shape"] == "heart"
    assert info["form_s"] == pytest.approx(form_s)
    moved, full = _form_frames(trace)
    took_s = (full - moved + 1) * DT
    assert abs(took_s - form_s) <= DT + 1e-9, (
        f"form took {took_s:.4f}s, told {form_s}s")
    # ... and it was NOT already complete before then
    assert trace[full - 1][1] < 1.0
    # the keys landed on the real effect, all six of them
    for key in wsk.KEYS:
        assert key in eff._config, key
    told = wsk.told(eff._config)
    assert told is not None and told.shape == "heart"


def test_a_form_shorter_than_any_engine_would_send_is_handled(tmp_path):
    """Acceptance 2's tail: impossible by contract (the engine floors the
    form), so the only requirement is that the effect clamps rather than
    divides by zero."""
    for form_s in (0.0, 1e-4):
        _eff, trace, record = _run(_engine_run(
            tmp_path, f"tiny-{form_s}", form_s, frames=40))
        assert record["result"] == "applied"
        # complete on the very first frame it is seen, never NaN
        assert all(np.isfinite(m) for _i, m in trace)
        assert max(m for _i, m in trace) == pytest.approx(1.0)


# ── 3. nothing jumps ──────────────────────────────────────────────────────

@pytest.mark.parametrize("shape", ["heart", "diamond"])
@pytest.mark.parametrize("count,mode", [(C.FEW_N, "few"), (C.MANY_N, "many")])
def test_no_sudden_velocity_shifts_at_any_edge_of_the_blend(shape, count,
                                                            mode, capsys):
    """Acceptance 3, his "they need to smoothly accelerate and not have
    sudden velocity shifts", at the form's start, the hold's two edges and
    the release's end — against this same effect's OWN ordinary maximum on
    the same seed and the same audio. The numbers print with `-s`.

    WHAT IS BARRED WHERE, and why they are not the same thing (the check
    script's own `report_continuity` says this at length):

      * the per-frame SPEED change is the blend's, and it is bounded at ALL
        FOUR moments by the effect's own ordinary maximum — acceptance 3's
        bar verbatim;
      * the per-frame HEADING change is bounded the same way at the form's
        start and the release's end, the two moments where the blend
        actually moves;
      * at the HOLD's two edges what is asserted is the BLEND's own
        smoothness, with no magic number in it: the envelope's largest
        one-frame move over the WHOLE shape against the steepest a
        smoothstep of its own form and release could be (1.5 / its
        duration), and the most the blend could therefore move a blob
        there, against the ordinary maximum. Through the hold the envelope
        stands at 1.0 and leaves it with zero slope, so a hard turn in
        those frames is the OUTLINE (a heart's cleft turns 3.11 rad) or
        Orbits' own jog kick, which stalls or reverses a blob for a tenth
        of a second at loud Energy whether a shape stands or not — the
        untold control itself reaches 3.10 of the 3.14 rad a heading change
        can possibly be.

    A heading is only counted where the blob actually moved
    (`C.TURN_MIN_SPEED`, a tenth of a cell pitch in the frame), applied
    identically to the told run and the control — `orbits.py`'s own `p_om`
    guards itself the same way.
    """
    energy = 0.8
    told = _run(C.run(shape, energy, count, tag=f"t-{mode}"))
    bare = _run(C.run(None, energy, count, tag=f"b-{mode}"))
    d_spd, d_turn = C.speeds_and_turns(told)
    b_spd, b_turn = C.speeds_and_turns(bare)
    ord_s = max(float(a.max()) for a in b_spd if a.size)
    ord_t = max(float(a.max()) for a in b_turn if a.size)
    sharp = C.shape_sharpest_turn(shape)
    assert ord_s > 0.0 and ord_t > 0.0
    moments = {"form start": told.edge, "hold start": told.word,
               "hold end": told.hold_end, "release end": told.release_end}
    print(f"\n{mode} {shape}: ordinary max {ord_s:.1f} px/s, {ord_t:.3f} "
          f"rad; the outline's own sharpest turn {sharp:.3f} rad")
    for name, at in moments.items():
        s_ = C.window_max(d_spd, at)
        t_ = C.window_max(d_turn, at)
        blend = C.blend_speed_bound(told, at)
        print(f"  {name:12s} {s_:8.1f} px/s  {t_:.3f} rad   "
              f"(the blend itself: at most {blend:6.1f} px/s)")
        assert s_ <= ord_s + 1e-6, f"{name}: speed {s_} > ordinary {ord_s}"
        if name in ("form start", "release end"):
            assert t_ <= ord_t + 1e-6, (
                f"{name}: heading {t_} > ordinary {ord_t}")
        else:
            assert blend <= ord_s + 1e-6, (
                f"{name}: the blend could move a blob {blend} px/s, over "
                f"the ordinary {ord_s}")
    # the blend's own smoothness, over the whole shape and with no magic
    # number: the steepest a smoothstep of this form and release can be
    step, bar = C.envelope_step(told)
    print(f"  the envelope's largest one-frame move: {step:.4f} "
          f"(bar {bar:.4f})")
    assert step <= bar


@pytest.mark.parametrize("count,mode", [(C.FEW_N, "few"), (C.MANY_N, "many")])
def test_the_picture_never_jumps_more_than_it_already_does(count, mode):
    """Acceptance 3's other half. The plan's absolute 8% bar is not a
    property this effect has even untold — at his `trail_decay` 0.15 the
    smear loses 11% of its brightness every frame, so cells near the lit
    threshold wink out in blocks (13-20% frame to frame untold). The bar
    asserted is therefore the one acceptance 3 already uses for this
    effect's speed and heading: against the effect's OWN ordinary maximum,
    on the same seed and the same audio."""
    shape, energy = "heart", 0.2
    told = _run(C.run(shape, energy, count, tag=f"j-{mode}"))
    bare = _run(C.run(None, energy, count, tag=f"jb-{mode}"))
    spans = [(told.edge, told.word + 1),
             (told.hold_end, told.release_end + 1)]
    worst = max(C.lit_jump(told, lo, hi) for lo, hi in spans)
    ordinary = C.lit_jump(bare, 0, len(bare.frames))
    assert 0.0 < ordinary < 1.0
    assert worst <= ordinary, (
        f"{mode}: {worst:.1%} told vs this effect's own ordinary "
        f"{ordinary:.1%} untold")


# ── 4. it is the shape ────────────────────────────────────────────────────

@pytest.mark.parametrize("shape", list(word_shapes.shape_ids()))
@pytest.mark.parametrize("energy", list(C.ENERGIES))
@pytest.mark.parametrize("count,mode,bar", [
    (C.FEW_N, FX.WORD_SHAPE_FEW, C.BAR_FEW),
    (C.MANY_N, FX.WORD_SHAPE_MANY, C.BAR_MANY),
])
def test_the_clarity_bar_on_his_real_crystal(shape, energy, count, mode, bar,
                                             capsys):
    """Acceptance 4 — the row's own bar, on the real mask at SIZE 0.62,
    against `scripts/check_word_shapes.py`'s own pinned outline-cell count.
    Asserted AT THE HOLD; the word's own number is printed (see this
    module's docstring for why the word is not the bar)."""
    outline, n_out = C.outline_cells(shape)
    r = _run(C.run(shape, energy, count, tag=f"bar-{mode}"))
    assert r.mode == mode, f"latched {r.mode}, expected {mode}"
    cov_word = C.coverage(r.frames[r.word], outline)
    cov_hold = C.coverage(r.frames[r.mid_hold], outline)
    print(f"\n{mode} {shape} @ Energy {energy}: {n_out} outline cells, "
          f"word {cov_word:.0%}, hold {cov_hold:.0%}")
    assert cov_hold >= bar, (
        f"{mode} {shape}@{energy}: {cov_hold:.0%} of {n_out} outline cells "
        f"at the hold (bar {bar:.0%}); at the word {cov_word:.0%}")


@pytest.mark.parametrize("count,mode", [
    (C.FEW_N, FX.WORD_SHAPE_FEW), (C.MANY_N, FX.WORD_SHAPE_MANY)])
def test_at_the_hold_the_blobs_are_on_the_outline(count, mode):
    """FEW: every blob's CENTRE is on it (exactly, which is what proves the
    envelope really reaches 1.0 and the blend is the outline itself).
    MANY: every TETHER is — the beads wobble around theirs by design."""
    r = _run(C.run("star", 0.5, count, tag=f"onout-{mode}"))
    assert r.mode == mode
    xs, ys = (r.pos if mode == FX.WORD_SHAPE_FEW else r.tether)[r.mid_hold]
    assert np.size(xs) == count
    worst = float(C.dist_to_outline(xs, ys, "star").max())
    assert worst <= 1.0, f"{mode}: {worst:.3f} cell pitches off the outline"


# ── the mode, its latch and its threshold ─────────────────────────────────

def _told_write(shape="heart", seq=1, form_s=0.5, hold_s=2.0,
                release_s=0.75, level=0.5) -> dict:
    return wsk.keys_for(shape, seq, form_s, hold_s, release_s, level)


class _Rig:
    """A frame-stepped orbits on the real crystal mask, driven by direct
    told-key writes — the keys SpotFX sends."""

    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm
        self.i = 0

    def step(self, n=1, energy=0.5):
        for _ in range(n):
            self.i += 1
            with self.effect.lock:
                self.effect.audio_data_updated(C._Audio(self.i, energy))
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)

    def write(self, patch):
        with self.effect.lock:
            self.effect._apply_config(dict(patch), validate=False,
                                      fire_event=False)


_RIGS = [0]


async def _rig(count=3, **over) -> _Rig:
    _RIGS[0] += 1
    tag = f"rig-{_RIGS[0]}"
    headless.silence_audio()
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag, real_mask=C.REAL)
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    np.random.seed(7)
    eff = headless.attach_effect(
        host, virtual, "orbits",
        dict(C.HIS_MATRIX, gradient=C.SET, particle_count=count, **over))
    eff._rng = np.random.default_rng(7)
    return _Rig(host, virtual, clock, eff, cm)


async def _close(rig: _Rig):
    rig._cm.__exit__(None, None, None)
    await rig.host.shutdown()


def test_three_blobs_latch_few_and_eight_latch_many():
    async def main():
        for count, mode in ((3, FX.WORD_SHAPE_FEW),
                            (8, FX.WORD_SHAPE_MANY)):
            r = await _rig(count)
            try:
                r.step(120)
                r.write(_told_write())
                r.step(20)
                assert r.effect._ws_mode == mode, (count, r.effect._ws_mode)
            finally:
                await _close(r)

    _run(main())


def test_the_latch_holds_when_energy_changes_the_count_mid_shape():
    """Spec 2: an Energy-driven count change must not flip the geometry
    under a held shape — three blobs tracing one heart must not become
    eight beads on it halfway through the word."""
    async def main():
        r = await _rig(3)
        try:
            r.step(120)
            r.write(_told_write(hold_s=3.0))
            r.step(40)
            assert r.effect._ws_mode == FX.WORD_SHAPE_FEW
            r.write({"particle_count": 6})      # his scene, Energy rising
            r.step(40)
            assert r.effect.particle_count == 6
            assert r.effect._ws_mode == FX.WORD_SHAPE_FEW, "the latch broke"
            # ... and the NEXT word latches the count it finds
            r.step(300)                          # let it reset
            assert r.effect._ws_told is None
            r.write(_told_write(seq=2))
            r.step(20)
            assert r.effect._ws_mode == FX.WORD_SHAPE_MANY
        finally:
            await _close(r)

    _run(main())


def test_the_threshold_param_moves_the_boundary():
    """Spec 1: `word_shape_few` is a setting — "few" is a count <= it."""
    async def main():
        for few, mode in ((3, FX.WORD_SHAPE_FEW), (2, FX.WORD_SHAPE_MANY)):
            r = await _rig(3, word_shape_few=few)
            try:
                r.step(120)
                r.write(_told_write())
                r.step(20)
                assert r.effect._ws_mode == mode, (few, r.effect._ws_mode)
            finally:
                await _close(r)

    _run(main())


def test_only_two_modes_exist_and_few_b_was_never_built():
    """P1 B was a COMPARISON in the plan, not a second mode to ship (the
    Admiral approved P1 A). Nothing here may offer a choice between them."""
    assert FX.WORD_SHAPE_FEW == "few" and FX.WORD_SHAPE_MANY == "many"
    src = (ROOT / "fx/effects/orbits.py").read_text().lower()
    for token in ("few_b", "p1b", "p1_b", "word_shape_mode"):
        assert token not in src, f"{token!r} is in orbits.py"
    schema = FX.Orbits2d.schema()({})
    assert "word_shape_few" in schema and "word_shape_wobble" in schema


def test_size_is_divided_by_radius_scale_into_the_effects_own_space():
    """The one conversion this effect owes the shape library: SIZE is a
    fraction of the PANEL's half-height, and this effect's normalized space
    is `radius_scale` times that (Orbits2d._word_shape_scale)."""
    async def main():
        r = await _rig(3, radius_scale=1.8, word_shape_size=0.62)
        try:
            assert r.effect._word_shape_scale() == pytest.approx(0.62 / 1.8)
            r.write({"radius_scale": 1.0})
            assert r.effect._word_shape_scale() == pytest.approx(0.62)
        finally:
            await _close(r)

    _run(main())


# ── 7. the edges ──────────────────────────────────────────────────────────

def test_two_words_of_the_same_shape_both_edge():
    """The effect watches the SEQ, never the id (word_shape_keys' rule)."""
    async def main():
        r = await _rig(3)
        try:
            r.step(120)
            r.write(_told_write(seq=1, form_s=0.5, hold_s=0.5,
                                release_s=0.5))
            r.step(int(1.6 / DT))               # past total_s: self-reset
            assert r.effect._ws_told is None and r.effect._ws_m == 0.0
            r.write(_told_write(seq=2, form_s=0.5, hold_s=0.5,
                                release_s=0.5))
            r.step(5)
            assert r.effect._ws_told is not None
            assert r.effect._ws_m > 0.0, "the same shape id did not re-edge"
        finally:
            await _close(r)

    _run(main())


def test_a_second_word_mid_release_restarts_the_form_from_where_it_is():
    """Acceptance 7: no snap to zero. The new form starts at exactly the
    fraction standing, so the frame the word arrives on moves nothing."""
    async def main():
        r = await _rig(3)
        try:
            r.step(120)
            r.write(_told_write(seq=1, form_s=0.4, hold_s=0.3,
                                release_s=1.2))
            r.step(int(0.95 / DT))              # into the release
            mid = r.effect._ws_m
            assert 0.05 < mid < 0.95, mid
            r.write(_told_write(seq=2, form_s=0.6, hold_s=0.5,
                                release_s=0.9))
            r.step(1)
            assert r.effect._ws_m >= mid - 0.02, (mid, r.effect._ws_m)
            r.step(3)
            assert r.effect._ws_m > mid, "the new form is not rising"
            # ... and it completes: the new form restarts from `mid`, so it
            # takes LESS than its own form_s to stand complete
            seen = []
            for _ in range(int(0.6 / DT)):
                r.step(1)
                seen.append(r.effect._ws_m)
            assert max(seen) == pytest.approx(1.0)
        finally:
            await _close(r)

    _run(main())


def test_a_clearing_write_releases_from_the_current_fraction():
    """Acceptance 7: `told() is None` mid-shape releases, it does not
    vanish."""
    async def main():
        r = await _rig(3)
        try:
            r.step(120)
            r.write(_told_write(seq=1, form_s=0.4, hold_s=4.0,
                                release_s=0.9))
            r.step(int(0.5 / DT))
            assert r.effect._ws_m == pytest.approx(1.0)
            r.write(dict(wsk.NOT_TOLD))
            r.step(1)
            first = r.effect._ws_m
            assert 0.9 < first <= 1.0, first   # no step down
            seen = [first]
            for _ in range(int(0.9 / DT)):
                r.step(1)
                seen.append(r.effect._ws_m)
            assert seen == sorted(seen, reverse=True), "not monotone"
            assert seen[-1] == pytest.approx(0.0, abs=1e-6)
            assert r.effect._ws_told is None
        finally:
            await _close(r)

    _run(main())


def test_a_stale_persisted_seq_on_a_fresh_instance_never_fires():
    """The creation-baseline rule (fireworks' `burst_rockets`): an effect
    built from a config that still carries yesterday's SEQ must not draw a
    shape nobody sang."""
    async def main():
        r = await _rig(3, **_told_write(seq=97))
        try:
            r.step(60)
            assert r.effect._ws_seq == 97
            assert r.effect._ws_told is None and r.effect._ws_m == 0.0
            # ... and a real word after it still edges
            r.write(_told_write(seq=98))
            r.step(5)
            assert r.effect._ws_m > 0.0
        finally:
            await _close(r)

    _run(main())


def test_a_phase_arriving_mid_shape_takes_precedence():
    """Spec 6 / the plan's P3 A. A shape is never TOLD during a charge,
    lull or drop; one ARRIVING on a half-formed shape wins, and the shape
    releases from its own fraction rather than being cut."""
    async def main():
        r = await _rig(3)
        try:
            r.step(120)
            r.write(_told_write(seq=1, form_s=0.4, hold_s=4.0,
                                release_s=0.9))
            r.step(int(0.5 / DT))
            assert r.effect._ws_m == pytest.approx(1.0)
            r.write({"phase": "drop", "phase_progress": 0.0})
            r.step(1)
            assert r.effect._ws_releasing is True
            assert r.effect._ws_m > 0.9, "the shape was cut, not released"
            r.step(int(0.9 / DT) + 2)
            assert r.effect._ws_m == pytest.approx(0.0, abs=1e-6)
            assert r.effect._ws_told is None
            # the drop's own payoff happened regardless
            assert r.effect._phase in ("drop", "none")
        finally:
            await _close(r)

    _run(main())


def test_an_unknown_shape_id_is_simply_not_told():
    """A newer SpotFX's id must fall through to "not told" rather than take
    the whole write with it (word_shape_keys' own reason for a plain str)."""
    async def main():
        r = await _rig(3)
        try:
            r.step(60)
            r.write(_told_write(shape="dodecahedron", seq=1))
            r.step(10)
            assert r.effect._config[wsk.SHAPE_KEY] == "dodecahedron"
            assert r.effect._ws_told is None and r.effect._ws_m == 0.0
        finally:
            await _close(r)

    _run(main())


# ── 5, 6. no white, and what it costs ─────────────────────────────────────

@pytest.mark.parametrize("count,mode", [(C.FEW_N, "few"), (C.MANY_N, "many")])
def test_no_white_and_under_a_millisecond(count, mode, capsys):
    """Acceptance 5 and 6, both from the same pair of runs."""
    import statistics

    from fx.effects import phase_grammar
    told = _run(C.run("diamond", 0.8, count, tag=f"wc-{mode}"))
    bare = _run(C.run(None, 0.8, count, tag=f"wcb-{mode}"))
    w_told = max(phase_grammar.white_cells(f, C.WHITE)
                 for f in told.frames[told.edge:told.release_end + 1])
    w_bare = max(phase_grammar.white_cells(f, C.WHITE) for f in bare.frames)
    p_told = statistics.median(told.cost_ms[told.word:told.hold_end + 1])
    p_bare = statistics.median(bare.cost_ms)
    print(f"\n{mode}: white {w_told} told / {w_bare} untold of 976 cells; "
          f"p50 {p_told:.2f} ms told / {p_bare:.2f} ms untold")
    assert w_told <= w_bare + C.WHITE_SLACK
    assert p_told - p_bare < C.COST_BAR_MS


# ── 8. the wiring ─────────────────────────────────────────────────────────

def test_orbits_is_in_the_word_shape_effects_and_orbits1d_is_not():
    assert "orbits" in device_model.WORD_SHAPE_EFFECTS
    assert "orbits1d" not in device_model.WORD_SHAPE_EFFECTS
    # this row declares no per-effect minimum form — only Fish's does
    assert "orbits" not in device_model.WORD_SHAPE_FORM_MIN_S


def test_the_contract_fixtures_wired_tuple_names_this_row():
    """The Word Shapes conflict map: the first wave-1 row rewrites the
    contract test's assertion, every later row appends to its tuple."""
    import tests.test_word_shape_contract as contract
    assert "orbits" in contract.WIRED
    assert device_model.WORD_SHAPE_EFFECTS == frozenset(contract.WIRED)


def test_the_three_settings_are_registered_for_sonic_and_the_editor():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    orbits = registry["effects"]["orbits"]
    schema = FX.Orbits2d.schema()({})
    for key, want in (("word_shape_size", 0.62), ("word_shape_few", 3),
                      ("word_shape_wobble", 0.15)):
        assert schema[key] == want, key
        assert orbits["params"][key]["default"] == want, key
        assert orbits["defaults"][key] == want, key
        assert orbits["params"][key]["help_topic"] == "word-shapes", key


def test_the_skill_and_the_map_name_this_rows_proofs():
    skill = (ROOT / ".claude/skills/orbits-effect/SKILL.md").read_text()
    assert "WORD SHAPES" in skill
    for token in ("word_shape_size", "word_shape_few", "word_shape_wobble",
                  "check_orbits_word_shape.py"):
        assert token in skill, token
    mapping = json.loads(
        (ROOT / ".claude/skills/EFFECT_SCENE_MAP.json").read_text())
    files = mapping["effects"]["orbits-effect"]["files"]
    assert "scripts/check_orbits_word_shape.py" in files
    assert "tests/test_orbits_word_shape.py" in files


def test_the_envelope_and_the_inverse_smoothstep_agree():
    """`_inv_smoothstep` is what lets every edge start from the fraction
    already standing — so it must really invert the one ramp the envelope
    uses, to the precision a single frame can see."""
    for m in np.linspace(0.0, 1.0, 101):
        t = FX._inv_smoothstep(m)
        assert wsk.envelope(t, 1.0, 1.0, 1.0) == pytest.approx(m, abs=1e-9)
    assert FX._inv_smoothstep(-5.0) == pytest.approx(0.0, abs=1e-12)
    assert FX._inv_smoothstep(5.0) == pytest.approx(1.0, abs=1e-12)
    assert math.isfinite(FX._inv_smoothstep(0.5))
