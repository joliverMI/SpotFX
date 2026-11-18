"""STAR's WORD SHAPE (Word Shapes plan row W1.6, 2026-11-15) — the
Admiral: "STAR: change the radial shape so it matches the shape if
possible. This one might be excluded or need some thought", and his Q7 A:
"include — the outline morphs into the shape, the spin eases to a stop so
the shape stands upright, resumes on release".

Everything runs on the star harness (tests/star_harness.py: a real Melt
strip under a real Radial — Star samples the strip and renders BLACK
without it) through the PRODUCTION ResponseEngine on the FacadeExecutor,
with a Words band carrying a `word_shape` kind.

  1. UNTOLD IS TODAY'S, byte for byte, against the PINNED module hosted
     beside today's in the same room on the same strip — over a busy and a
     parked rig and with the `random_sign` spin roll exercised BOTH WAYS
     (and at its historical zero), because a stopped spin is not the
     shape's doing (the squadron leader's memory).
  2. COMPLETE ON THE WORD: the form fraction reads 1.0 within one rendered
     frame of `edge + form_s`, for 0.5 s and 0.9 s, and a zero form is
     handled rather than divided by.
  3. IT IS THE SHAPE: the outline the effect draws equals
     `SIZE x polar(theta)` on 360 angles within half a cell, and the
     RENDERED field is that same law cell by cell; the clarity bar on the
     real hex mask for all three shapes at both Energies.
  4. THE SPIN EASES TO A STOP: the governed advance is the ungoverned one
     times `1 - m` through the form, EXACTLY zero through the hold, and
     back from the music over the release. A phase takes the governor back.
  5. THE STAR WAVE IS HELD for the whole shape and carries on after.
  6. AN EDGE MORPH AT MID-HOLD is deferred to the release.
  7. THE BAND SCROLL still advances during the hold (the shape is never a
     frozen picture), and the shape adds no white.
  8. TWO WORDS BACK TO BACK both edge; a second word inside the release
     re-forms from the current fraction; a clearing write lets go from the
     current fraction; a stale SEQ on a fresh instance never fires.
  9. THE WIRING: WORD_SHAPE_EFFECTS, the registered param, the skill, the
     map, and the contract fixture.
"""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_star_word_shape import (BAR_COST_MS, BAR_COVERED,  # noqa: E402
                                   BAR_INSIDE, BAR_FIELD,
                                   BAR_RADIUS_CELLS, Frame, clarity, cost,
                                   outline_cells, radius_error, smoothness,
                                   untold_baseline, words_scene, worst)
from check_word_shapes import load_panel  # noqa: E402
from fx import device_model  # noqa: E402
from fx.effects import radial, word_shape_keys as wsk, word_shapes  # noqa: E402
from spectra.services import scene_response  # noqa: E402
from star_harness import (COLS, ROWS, STAR, STRIP, STRIP_N,  # noqa: E402
                          StarRoom, star_room)
from strip_phase_harness import DT, PALETTE, _AudioFrame, run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# The commit this row was built on (W0.3, the whole engine contract merged):
# a PINNED ref, never a moving one — a byte-identity proof against `master`
# retires itself the day the next change lands.
BASELINE_REF = "5db75fe6774437100383b3a0bed31aa90642cce1"
TWIN = "crystal-pinned"
SHAPES = ("heart", "star", "diamond")


# ── the room ────────────────────────────────────────────────────────────────

def _words_room(tmp, *, radial_cfg=None, twin=None):
    """A star room (strip + crystal), optionally with a SECOND crystal
    running another registered effect type on the same strip, stepped
    identically — the byte-identity proof's own rig."""
    rcfg = {"source_virtual": STRIP, "edges": 6, "polygon": True,
            "star": 0.3, "twist": 0.0, "spin": 0.55,
            "background_brightness": 0.0, "gradient": PALETTE}
    rcfg.update(radial_cfg or {})
    mcfg = {"gradient": PALETTE, "speed": 0.08, "reactivity": 0.3,
            "blur": 1.0, "brightness": 1.0, "background_brightness": 0.0}
    spec = {STRIP: ("melt", STRIP_N, 1, mcfg),
            STAR: ("radial", COLS * ROWS, ROWS, rcfg)}
    if twin:
        spec[TWIN] = (twin, COLS * ROWS, ROWS, dict(rcfg))
    return _TwinRoom(tmp, spec, layer=True, scene=words_scene())


class _TwinRoom(StarRoom):
    """StarRoom, but EVERY crystal is turned (and fed audio) identically —
    StarRoom only ever turns the one named STAR."""

    def step(self, n: int = 1):
        for _ in range(n):
            self.clock.advance(DT)
            self.i += 1
            audio = _AudioFrame(self.i)
            for vid, v in self.virtuals.items():
                eff = self.effects[vid]
                if hasattr(eff, "audio_data_updated") and (
                        type(eff)._strip_phase or vid != STRIP):
                    with eff.lock:
                        eff.audio_data_updated(audio)
                if vid != STRIP and hasattr(eff, "_reactive_advance"):
                    with eff.lock:
                        adv = self.rev_s * DT
                        eff._reactive_advance += adv
                        eff._frame_adv += adv
                        eff.spin_total = (eff.spin_total + adv) % 1.0
                f = v.assemble_frame()
                if f is not None:
                    v.assembled_frame = f
                    v.flush(f)
                    self.frames[vid].append(
                        np.array(f, dtype=np.float64, copy=True))

    def matrix_of(self, vid):
        return np.asarray(self.effects[vid].matrix, dtype=np.float64)


_PINNED: dict = {}


def _pinned_type():
    """fx/effects/radial.py as of BASELINE_REF, registered as a SECOND
    effect type beside today's (an Effect subclass registers under its
    module's last name segment — fx/utils.py's BaseRegistry)."""
    if "name" in _PINNED:
        return _PINNED["name"]
    name = "radial_pre_word_shape"
    try:
        src = subprocess.run(
            ["git", "show", f"{BASELINE_REF}:fx/effects/radial.py"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                                 # noqa: BLE001
        pytest.skip(f"cannot read {BASELINE_REF}:fx/effects/radial.py "
                    f"({exc}) — the byte-identity claim is NOT checked")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # The baseline predates the 2026-11-18 rotation halving (ROTATION_SPEED_
    # SCALE 0.8 -> 0.4 and the per-frame cap 18 -> 9 deg,
    # data/star-curve-study/report.md), which is a deliberate change of the
    # picture and nothing to do with Word Shapes. Give the twin today's
    # rotation constants so this test keeps isolating the ONE claim it is for:
    # that an UNTOLD Word Shapes module renders what the pre-Word-Shapes one
    # did. They are module globals read at call time, so patching them here is
    # enough; the schema's own base_rotation Range was bound at class creation
    # and is only wider, which accepts every value this test uses.
    for const in ("ROTATION_SPEED_SCALE", "CHARGE_SPIN_REV_S",
                  "ROTATION_CAP_DEG_FRAME", "ROTATION_CAP_REV_FRAME"):
        if hasattr(module, const):
            setattr(module, const, getattr(radial, const))
    _PINNED["name"] = name
    return name


# ── 1. untold is today's ────────────────────────────────────────────────────

@pytest.mark.parametrize("spin,rev_s,label", [
    (0.55, 0.15, "busy, spin +"),
    (-0.55, 0.15, "busy, spin -"),
    (0.55, 0.0, "parked, spin +"),
    (0.0, 0.15, "the historical random_sign zero"),
])
def test_untold_is_byte_identical_to_the_pinned_module(tmp_path, spin, rev_s,
                                                       label):
    pinned = _pinned_type()

    async def main():
        room = _words_room(tmp_path, twin=pinned,
                           radial_cfg={"spin": spin, "base_rotation": 0.4,
                                       "star_wave": True})
        room.rev_s = rev_s
        async with room:
            room.step(320)
            today = np.stack([room.matrix_of(STAR)])
            before = np.stack([room.matrix_of(TWIN)])
            return (np.array(room.frames[STAR]), np.array(room.frames[TWIN]),
                    today, before)

    mine, theirs, _t, _b = run(main())
    assert mine.shape == theirs.shape and mine.size
    assert mine.max() > 0.0, "a dark run would prove nothing"
    assert np.array_equal(mine, theirs), label


# ── 2. complete on the word ─────────────────────────────────────────────────

def _fire(room, shape="heart", energy=0.8, form_s=None, hold_s=1.0,
          release_s=0.6):
    """One told write through the real ResponseEngine's Words section."""
    action = scene_response.PreviewWordShape(
        shape_id=shape, energy=energy,
        form_s=0.5 if form_s is None else form_s,
        hold_s=hold_s, release_s=release_s)
    return room.responder.on_word_shape(action), action


@pytest.mark.parametrize("form_s", [0.5, 0.9])
def test_the_form_completes_on_the_word(tmp_path, form_s):
    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            coro, action = _fire(room, form_s=form_s)
            record = await coro
            assert record["result"] == "applied"
            assert record["kinds"][0]["virtuals"] == 1, (
                "the told write must reach the crystal")
            star = room.star
            # the told write rides a 1 ms tween (fx_executor.JUMP_MS: "a
            # 1 ms tween lands next frame == an instant jump"), exactly as
            # every other told key does, so the EDGE is the first rendered
            # frame after the write and the shape's clock starts there
            assert star._shape is None, "nothing has landed yet"
            frames = int(math.ceil(form_s / DT))
            room.step(frames - 1)
            assert star._shape is not None
            assert star._shape_m < 1.0, "not complete before the word"
            room.step(1)
            assert star._shape_m == 1.0, (
                "complete within one rendered frame of edge + form_s")
            return action

    run(main())


def test_a_zero_form_is_complete_at_once_and_never_divides_by_zero(tmp_path):
    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            await _fire(room, form_s=0.0, hold_s=0.3, release_s=0.3)[0]
            room.step(1)
            assert room.star._shape_m == 1.0
            room.step(room.secs(1.0))
            assert room.star._shape is None

    run(main())


# ── 3. it is the shape ──────────────────────────────────────────────────────

@pytest.mark.parametrize("shape_id", SHAPES)
@pytest.mark.parametrize("energy", [0.2, 0.8])
def test_the_clarity_bar_on_the_real_mask(tmp_path, shape_id, energy):
    """The row's own bar, measured by the check script's own helpers on his
    real `crystal-mapper` mask (so the test and the printed evidence can
    never disagree)."""
    panel = load_panel()
    shots, _art = run(clarity(tmp_path, panel, shape_id, energy))
    for where in ("word", "mid-hold"):
        frame, rad = shots[where]
        assert frame.inside >= BAR_INSIDE, (
            f"{shape_id} {where}: only {frame.inside:.1%} of the lit cells "
            f"lie in the shape")
        # STAR has no light of its own: the bar is read against the cells
        # whose own strip pixel is lit (the script's docstring says why).
        assert frame.covered_strip >= BAR_COVERED, (
            f"{shape_id} {where}: {frame.covered_strip:.1%} of the area "
            f"cells the strip lights are lit")
        assert rad <= BAR_RADIUS_CELLS, (
            f"{shape_id} {where}: the outline is {rad:.3f} cells off")
        assert frame.field_err <= BAR_FIELD, (
            f"{shape_id} {where}: the rendered field is {frame.field_err:.2e} "
            f"from the shape's own law")
        assert frame.white == 0, "no white"


@pytest.mark.parametrize("shape_id", SHAPES)
def test_the_outline_is_the_librarys_radius_per_angle(tmp_path, shape_id):
    """360 angles, half a cell — through the effect's own angle-space law
    AND its rendered field, both against `SIZE x polar(theta)`."""
    panel = load_panel()
    shape = word_shapes.get(shape_id).prime()

    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            await _fire(room, shape=shape_id, form_s=0.5, hold_s=1.0)[0]
            room.step(room.secs(0.9))
            star = room.star
            assert star._shape_m == 1.0
            size = star._word_shape_size()
            err = radius_error(star, shape, size, panel)
            rn, th = _normalized_of(panel, star)
            want = rn / np.maximum(np.asarray(shape.polar(th)) * size, 1e-9)
            field = np.asarray(star._last_u)
            return err, float(np.abs(field - want).max())

    err, field_err = run(main())
    assert err <= BAR_RADIUS_CELLS, f"{shape_id}: {err:.3f} cells"
    assert field_err <= BAR_FIELD, f"{shape_id}: field {field_err:.2e}"


def _normalized_of(panel, star):
    from check_star_word_shape import normalized
    return normalized(panel, star)


def test_a_diamond_is_the_four_sided_polygon_and_a_heart_is_not_a_polygon():
    """The plan's own words for the three shapes: the diamond is the
    four-sided polygon Star already draws, the star five points, the heart
    new. All three are star-shaped about the centre, so `polar` exists for
    each — the one thing this row's divisor needs."""
    for sid in SHAPES:
        assert word_shapes.get(sid).star_shaped
    diamond = word_shapes.get("diamond")
    # four corners: the radius per angle has exactly four maxima
    th = np.linspace(0, 2 * math.pi, 721, endpoint=False)
    r = np.asarray(diamond.polar(th))
    peaks = int(((r > np.roll(r, 1)) & (r >= np.roll(r, -1))).sum())
    assert peaks == 4, peaks
    star = np.asarray(word_shapes.get("star").polar(th))
    peaks = int(((star > np.roll(star, 1)) & (star >= np.roll(star, -1))).sum())
    assert peaks == 5, peaks


# ── 4. the spin eases to a stop ─────────────────────────────────────────────

@pytest.mark.parametrize("shape_id", SHAPES)
@pytest.mark.parametrize("energy", [0.2, 0.8])
def test_the_hold_is_perfectly_still_and_no_frame_jumps(tmp_path, shape_id,
                                                        energy):
    """The plan's acceptance 3, measured against what this effect does on
    its OWN: Melt's breathing alone moves the lit count by up to 18% of
    itself in one rendered frame with no shape anywhere, so the shape's
    contribution is measured with the strip FROZEN and read against that
    baseline. The two claims that hold unconditionally: the hold does not
    move at all, and no frame of the form or the release is worse than the
    effect's own untold worst."""
    panel = load_panel()
    base60, base30, _white, _track = run(untold_baseline(tmp_path, panel))
    track, adv, env = run(smoothness(tmp_path, panel, shape_id, energy))
    full = [i for i, m in enumerate(env) if m >= 1.0]
    form, last = full[0], full[-1] + 1
    end = next((i for i, m in enumerate(env[last:], last) if m <= 0.0),
               len(env) - 1) + 1
    assert worst(track, form, last) == 0.0, "the hold must not move at all"
    assert max(abs(a) for a in adv[form:last]) == 0.0, (
        "the pattern must not turn through the hold")
    jf, jr = worst(track, 0, form + 1), worst(track, last - 1, end)
    jf2 = worst(track, 0, form + 1, stride=2)
    jr2 = worst(track, last - 1, end, stride=2)
    assert max(jf, jr) <= base60, (
        f"{shape_id} E{energy}: form {jf:.1%} / release {jr:.1%} against the "
        f"effect's own untold worst {base60:.1%}")
    assert max(jf2, jr2) <= base30, (
        f"{shape_id} E{energy}: at 30 fps form {jf2:.1%} / release "
        f"{jr2:.1%} against untold {base30:.1%}")
    # and the turn comes back from the music over the release
    assert abs(adv[min(end, len(adv) - 1)]) > 0.0


def test_the_governed_advance_is_the_free_one_times_one_minus_m(tmp_path):
    """The governor's curve, frame by frame: with the release filter off
    (the effect's own default) the advance Star takes is exactly what the
    rig put in times `1 - m`, and the SHAPE is what scales it — not the
    scene's `random_sign` roll, which cannot reach `spin` any more."""
    async def main():
        room = _words_room(tmp_path, radial_cfg={"spin": 0.0,
                                                 "spin_ease_in_s": 0.0})
        room.rev_s = 0.15
        async with room:
            room.step(room.secs(1.0))
            star = room.star
            free = room.rev_s * DT
            await _fire(room, form_s=0.5, hold_s=0.4, release_s=0.5)[0]
            rows = []
            for _ in range(room.secs(1.6)):
                prev = star.spin_total
                room.step(1)
                got = ((star.spin_total - prev + 0.5) % 1.0) - 0.5
                rows.append((star._shape_m, got))
            return free, rows

    free, rows = run(main())
    assert rows
    for m, got in rows:
        assert got == pytest.approx(free * (1.0 - m), abs=1e-12), (m, got)
    assert any(m == 1.0 and got == 0.0 for m, got in rows)
    assert any(m == 0.0 and got == pytest.approx(free) for m, got in rows)


def test_a_phase_landing_mid_shape_takes_the_governor_back(tmp_path):
    """The plan's W1.6 spec 5. A shape is never TOLD during a charge, lull
    or drop (P3 A, the engine's own gate), but one can ARRIVE mid-shape —
    and then the phase's own choreography owns the motion, unscaled."""
    async def main():
        room = _words_room(tmp_path, radial_cfg={"spin": 0.0,
                                                 "spin_ease_in_s": 0.0})
        room.rev_s = 0.15
        async with room:
            room.step(room.secs(1.0))
            star = room.star
            await _fire(room, form_s=0.3, hold_s=2.0, release_s=0.3)[0]
            room.step(room.secs(0.5))
            assert star._shape_m == 1.0
            prev = star.spin_total
            room.step(1)
            assert ((star.spin_total - prev + 0.5) % 1.0) - 0.5 == 0.0
            await room.phase("charge", gap_ms=2000, intensity=0.8)
            room.step(room.secs(0.3))
            prev = star.spin_total
            room.step(1)
            moved = abs(((star.spin_total - prev + 0.5) % 1.0) - 0.5)
            assert star._shape_m == 1.0, "the shape is still standing"
            return moved

    assert run(main()) > 0.0, "a charge mid-shape must still turn the star"


# ── 5. the star wave is held ────────────────────────────────────────────────

def test_the_star_wave_is_held_for_the_whole_shape_and_carries_on_after(tmp_path):
    async def main():
        async with _words_room(tmp_path,
                               radial_cfg={"star_wave": True}) as room:
            room.step(room.secs(1.0))
            star = room.star
            await _fire(room, form_s=0.4, hold_s=0.6, release_s=0.4)[0]
            room.step(1)
            held, phase = star.star, star._wave_phase
            seen = []
            for _ in range(room.secs(1.4) - 2):
                room.step(1)
                seen.append((star._shape_m, star.star, star._wave_phase))
            after = []
            for _ in range(room.secs(0.5)):
                room.step(1)
                after.append(star.star)
            return held, phase, seen, after

    held, phase, seen, after = run(main())
    standing = [(m, v, p) for m, v, p in seen if m > 0.0]
    assert standing
    for _m, value, p in standing:
        assert value == held and p == phase, "the wave is frozen, not paused"
    assert len({round(v, 9) for v in after}) > 1, "it sways again after"


# ── 6. a deferred Edge Morph ────────────────────────────────────────────────

def test_an_edges_change_at_mid_hold_lands_only_after_the_release(tmp_path):
    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            star = room.star
            assert star.edges == 6
            await _fire(room, form_s=0.3, hold_s=0.8, release_s=0.4)[0]
            room.step(room.secs(0.6))
            assert star._shape_m == 1.0
            with star.lock:
                star._apply_config({"edges": 4}, validate=False,
                                   fire_event=False)
            assert star.edges == 6, "deferred — the hold keeps its own shape"
            assert star._shape_edges_defer == 4
            assert star._morph is None
            room.step(room.secs(0.3))      # still inside the hold
            assert star.edges == 6
            room.step(room.secs(0.3))      # the release has started
            return star.edges, star._morph, star._shape_edges_defer

    edges, morph, defer = run(main())
    assert edges == 4, "the release morphs back into the NEW edge count"
    assert morph is not None and morph["from"] == 6
    assert defer is None


def test_an_edges_change_and_back_while_a_shape_stands_leaves_nothing_pending(tmp_path):
    """A change and a change BACK must not land the first one at the
    release — the deferral is re-read from the config on every write."""
    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            star = room.star
            await _fire(room, form_s=0.3, hold_s=1.0, release_s=0.3)[0]
            room.step(room.secs(0.6))
            with star.lock:
                star._apply_config({"edges": 4}, validate=False,
                                   fire_event=False)
            assert star._shape_edges_defer == 4
            with star.lock:
                star._apply_config({"edges": 6}, validate=False,
                                   fire_event=False)
            assert star._shape_edges_defer is None
            room.step(room.secs(1.2))
            return star.edges, star._shape

    edges, left = run(main())
    assert edges == 6 and left is None


def test_an_edges_change_with_no_shape_standing_is_todays_morph(tmp_path):
    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            star = room.star
            with star.lock:
                star._apply_config({"edges": 3}, validate=False,
                                   fire_event=False)
            return star.edges, star._morph, star._shape_edges_defer

    edges, morph, defer = run(main())
    assert edges == 3 and defer is None
    assert morph is not None and morph["from"] == 6


# ── 7. the bands keep flowing, and no white ─────────────────────────────────

def test_the_band_scroll_advances_through_the_hold(tmp_path):
    """His "the colours still flowing out through the bands": the shape
    freezes the geometry, never the strip Star samples."""
    async def main():
        async with _words_room(tmp_path) as room:
            room.step(room.secs(1.0))
            await _fire(room, form_s=0.3, hold_s=1.2, release_s=0.3)[0]
            room.step(room.secs(0.4))
            assert room.star._shape_m == 1.0
            strips, frames = [], []
            for _ in range(room.secs(0.8)):
                room.step(1)
                strips.append(np.array(
                    room.virtuals[STRIP].assembled_frame, copy=True))
                frames.append(room.matrix_of(STAR))
            return strips, frames

    strips, frames = run(main())
    moved = max(float(np.abs(strips[i] - strips[0]).max())
                for i in range(1, len(strips)))
    assert moved > 1.0, "the strip itself must still be moving"
    changed = max(float(np.abs(frames[i] - frames[0]).max())
                  for i in range(1, len(frames)))
    assert changed > 1.0, "the shape must not be a frozen picture"


def test_the_cost_of_a_holding_shape(tmp_path):
    untold_ms, held_ms = run(cost(tmp_path))
    assert held_ms - untold_ms <= BAR_COST_MS, (
        f"untold {untold_ms:.3f} ms, holding {held_ms:.3f} ms")


# ── 8. the edges of the told write ──────────────────────────────────────────

def test_two_words_of_the_same_shape_back_to_back_both_edge(tmp_path):
    async def main():
        async with _words_room(tmp_path) as room:
            star = room.star
            room.step(room.secs(1.0))
            await _fire(room, form_s=0.3, hold_s=0.3, release_s=0.3)[0]
            room.step(room.secs(0.95))
            assert star._shape is None, "the first shape resets itself"
            seq1 = star._shape_seq
            await _fire(room, form_s=0.3, hold_s=0.3, release_s=0.3)[0]
            room.step(1)
            return seq1, star._shape_seq, star._shape is not None

    seq1, seq2, standing = run(main())
    # STRICTLY GREATER, not seq1 + 1 (Word Shapes row W4.1): the counter is
    # one clock-seeded source for the whole PROCESS now
    # (fx/effects/word_shape_keys.next_seq) rather than a per-engine 1, 2,
    # 3 — which is what made every preview lap after the first write the
    # same 1 and draw nothing. What this test is about is unchanged: the
    # effect edges on the SEQ CHANGING, never on the shape id.
    assert seq2 > seq1 and standing


def test_a_second_word_inside_the_release_reforms_from_where_it_is(tmp_path):
    async def main():
        async with _words_room(tmp_path) as room:
            star = room.star
            room.step(room.secs(1.0))
            await _fire(room, form_s=0.3, hold_s=0.2, release_s=0.6)[0]
            room.step(room.secs(0.7))      # inside the release
            m_before = star._shape_m
            assert 0.0 < m_before < 1.0
            await _fire(room, form_s=0.4, hold_s=0.3, release_s=0.3)[0]
            room.step(1)
            return m_before, star._shape_m

    before, after = run(main())
    assert after >= before - 0.02, (before, after)
    assert after > 0.0, "never a snap to zero"


def test_a_clearing_write_lets_go_from_where_it_is(tmp_path):
    async def main():
        async with _words_room(tmp_path) as room:
            star = room.star
            room.step(room.secs(1.0))
            await _fire(room, form_s=0.3, hold_s=2.0, release_s=0.5)[0]
            room.step(room.secs(0.5))
            assert star._shape_m == 1.0
            with star.lock:
                star._apply_config(dict(wsk.NOT_TOLD), validate=False,
                                   fire_event=False)
            assert star._shape is not None, "it releases, it does not vanish"
            room.step(1)
            m1 = star._shape_m
            room.step(room.secs(0.3))
            m2 = star._shape_m
            room.step(room.secs(0.4))
            return m1, m2, star._shape

    m1, m2, left = run(main())
    assert m1 < 1.0 and 0.0 < m2 < m1
    assert left is None


def test_a_stale_seq_on_a_fresh_instance_never_fires(tmp_path):
    """The creation baseline (fireworks' "phase-key creation-baseline
    rule"): a persisted config still carrying a shape write must render the
    polygon, not re-form the word."""
    async def main():
        told = wsk.keys_for("heart", 7, 0.5, 0.8, 0.7, 0.8)
        async with _words_room(tmp_path, radial_cfg=told) as room:
            room.step(room.secs(0.5))
            return room.star._shape, room.star._shape_m, room.star._shape_seq

    shape, m, seq = run(main())
    assert shape is None and m == 0.0 and seq == 7


def test_an_unknown_shape_id_is_not_told(tmp_path):
    async def main():
        told = dict(wsk.keys_for("heart", 3, 0.5, 0.8, 0.7, 0.8))
        told[wsk.SHAPE_KEY] = "dodecahedron"
        async with _words_room(tmp_path) as room:
            room.step(room.secs(0.5))
            with room.star.lock:
                room.star._apply_config(told, validate=False,
                                        fire_event=False)
            room.step(2)
            return room.star._shape, room.star._shape_m

    shape, m = run(main())
    assert shape is None and m == 0.0


# ── 9. the wiring ───────────────────────────────────────────────────────────

def test_star_is_the_only_effect_this_row_wires():
    assert "radial" in device_model.WORD_SHAPE_EFFECTS
    assert "radial" not in device_model.WORD_SHAPE_FORM_MIN_S, (
        "STAR takes the Energy-paced form as approved — no floor of its own")


def test_the_told_keys_ride_only_the_dedicated_write():
    schema = radial.Radial2d.schema()({})
    for key in wsk.KEYS:
        assert key in schema
        assert key in radial.Radial2d.ADVANCED_KEYS
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    params = registry["effects"]["radial"]["params"]
    for key in wsk.KEYS:
        assert key not in params, "a told key is never an editor surface"
    assert params["word_shape_size"]["default"] == schema["word_shape_size"]
    assert schema["word_shape_size"] == radial.DEFAULT_WORD_SHAPE_SIZE == 0.62
    assert params["word_shape_size"]["help_topic"] == "word-shapes"
    # the help-content rule (AGENTS.md): the topic exists, and it no longer
    # says that no effect draws a shape
    help_src = (ROOT / "spectra/web/src/help/helpContent.ts").read_text()
    assert "'word-shapes'" in help_src
    assert "No effect draws a shape yet" not in help_src
    assert "STAR draws it in its own outline" in help_src


def test_the_skill_and_the_map_name_this_rows_files():
    skill = (ROOT / ".claude/skills/radial-effect/SKILL.md").read_text()
    assert "WORD SHAPE" in skill.upper()
    assert "word_shape_size" in skill
    mapping = json.loads(
        (ROOT / ".claude/skills/EFFECT_SCENE_MAP.json").read_text())
    files = mapping["effects"]["radial-effect"]["files"]
    assert "scripts/check_star_word_shape.py" in files
    assert "tests/test_star_word_shape.py" in files
