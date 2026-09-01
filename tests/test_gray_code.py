"""THE DECODE, AGAINST A KNOWN ARRANGEMENT — and against deliberately
broken stacks.

The commissioning test's whole claim is that it is judged against truth
rather than admired for plausibility. That claim is worth nothing unless
the decoder itself is first proven against an arrangement whose answer is
known before it runs — and proven to FAIL when the stack is wrong. Both
halves are here; the frozen table's own judging lives in
`tests/test_commissioning.py`.
"""
from __future__ import annotations

import numpy as np

from spectra.services import gray_code as gc

W, H = 320, 180


def _line(n: int, y: float = 0.5, x0: float = 0.08, x1: float = 0.92):
    return {i: (x0 + (x1 - x0) * i / max(1, n - 1), y) for i in range(n)}


def test_bits_needed_matches_the_plans_own_arithmetic():
    # "10 patterns + inverses + dark and full references ~= 22 captures"
    # for his real composition (560 + 28 + 60 + 28 + 60 = 736 pixels).
    assert gc.bits_needed(736) == 10
    assert 2 + 2 * gc.bits_needed(736) == 22
    assert gc.bits_needed(1) == 1
    assert gc.bits_needed(1024) == 10
    assert gc.bits_needed(1025) == 11


def test_gray_neighbours_differ_by_exactly_one_bit():
    """The property the whole scheme rests on: a camera pixel straddling two
    LEDs misreads at most one bit and lands on a NEIGHBOUR."""
    idx = np.arange(0, 4096)
    g = gc.gray(idx)
    changed = np.array([bin(int(a) ^ int(b)).count("1")
                        for a, b in zip(g[:-1], g[1:])])
    assert set(changed.tolist()) == {1}


def test_pattern_string_is_index_aligned_and_skips_unused_pixels():
    # pixel 0 unused (-1), then composition indices 3, 4, 5
    arr = np.array([-1, 3, 4, 5])
    s = gc.pattern_string(arr, 0)
    assert len(s) == 4 and s[0] == "0"
    expect = "".join(str(int(gc.pattern_bits(np.array([i]), 0)[0]))
                     for i in (3, 4, 5))
    assert s[1:] == expect
    assert gc.pattern_string(arr, 0, invert=True)[1:] == \
        "".join("1" if c == "0" else "0" for c in expect)


def test_round_trip_of_the_code_itself():
    idx = np.arange(0, 5000)
    assert np.array_equal(gc.from_gray(gc.gray(idx)), idx)


def test_decode_recovers_a_known_arrangement():
    layout = _line(64)
    dark, full, pairs = gc.synthetic_stack(layout, width=W, height=H,
                                           radius_px=2.0)
    out = gc.decode_stack(dark, full, pairs, total=64)
    assert len(out.seen) == 64
    err = [np.hypot(out.positions[i][0] - layout[i][0],
                    out.positions[i][1] - layout[i][1]) for i in out.seen]
    # well inside one camera pixel in x (1/320 = 0.003) — the arrangement
    # comes back, not merely something plausible
    assert float(np.median(err)) < 0.006
    # and the ORDER comes back too
    xs = [out.positions[i][0] for i in range(64)]
    assert xs == sorted(xs)


def test_decode_recovers_a_two_dimensional_arrangement():
    """The TV case in miniature: a wrapped rectangle, not a straight line."""
    per = 16
    step = 0.6 / per
    layout = {}
    for i in range(per):                      # top edge, left -> right
        layout[i] = (0.2 + step * i, 0.2)
    for i in range(per):                      # right edge, top -> bottom
        layout[per + i] = (0.8, 0.2 + step * i)
    for i in range(per):                      # bottom edge, right -> left
        layout[2 * per + i] = (0.8 - step * i, 0.8)
    dark, full, pairs = gc.synthetic_stack(layout, width=W, height=H,
                                           radius_px=2.0)
    out = gc.decode_stack(dark, full, pairs, total=3 * per)
    assert len(out.seen) == 3 * per
    err = [np.hypot(out.positions[i][0] - layout[i][0],
                    out.positions[i][1] - layout[i][1]) for i in out.seen]
    assert float(np.median(err)) < 0.01


def test_dead_pixels_are_simply_never_seen():
    """His hardware being wrong is a REPORTABLE outcome, not a crash: a
    pixel that emits nothing however it is patterned is absent from the
    decode, and everything either side of it still comes back."""
    layout = _line(64)
    dead = {17, 18, 40}
    dark, full, pairs = gc.synthetic_stack(layout, width=W, height=H,
                                           radius_px=2.0, dead=dead)
    out = gc.decode_stack(dark, full, pairs, total=64)
    assert set(out.missing) >= dead
    assert len(out.seen) >= 64 - len(dead) - 2


def test_a_corrupted_stack_does_not_quietly_produce_an_answer():
    """One bit's captures swapped for noise — the decode must lose pixels
    or place them wrongly, never return a confident, wrong-and-plausible
    arrangement."""
    layout = _line(64)
    dark, full, pairs = gc.synthetic_stack(layout, width=W, height=H,
                                           radius_px=2.0)
    rng = np.random.default_rng(3)
    broken = list(pairs)
    noise = np.clip(dark + rng.normal(0.0, 3.0, size=dark.shape), 0, 255)
    broken[2] = (noise, noise.copy())
    out = gc.decode_stack(dark, full, broken, total=64)
    good = gc.decode_stack(dark, full, pairs, total=64)
    assert len(out.seen) < len(good.seen)


def test_agreement_between_two_runs_of_the_same_room():
    layout = _line(48)
    a = gc.decode_stack(*_stack(layout, seed=1), total=48)
    b = gc.decode_stack(*_stack(layout, seed=2), total=48)
    got = gc.agreement(a, b)
    assert got["compared"] >= 40
    assert got["median_shift"] is not None and got["median_shift"] < 0.01


def _stack(layout, seed):
    dark, full, pairs = gc.synthetic_stack(layout, width=W, height=H,
                                           radius_px=2.0, noise=1.5, seed=seed)
    return dark, full, pairs


# ── THE FIELD REGIME (2026-09-01) ─────────────────────────────────────────
#
# His first two real runs failed the same way: 0 of 736 decoded, ~3,165
# "lit" camera pixels every one of them undecodable, 0 out of range, with
# abundant light in the frame. The raw frame kept from that pose says why —
# the whole composition arrives as three compact glows peaking at 99 of
# 255, 66 non-zero camera pixels of 57,600. These tests hold the decoder to
# what that regime does, so the failure cannot come back unnoticed.
# `scripts/check_commissioning.py` section 3c is the fuller instrument.

def _glow(total: int, span_px: float = 8.0, cx: float = 160.0,
          cy: float = 90.0):
    """A whole strip imaged into one small glow — his pose, in one fixture."""
    return {i: ((cx + (i / max(1, total - 1) - 0.5) * span_px) / W, cy / H)
            for i in range(total)}


def _dim_stack(layout, *, peak=99.0, noise=1.0, seed=11, radius_px=2.0):
    """His camera: per-pixel light calibrated so ALL-ON reaches `peak` of
    255, read noise, four frames averaged, each quantised to the grey8 the
    phone actually sends."""
    every, cache, rng = set(layout), {}, np.random.default_rng(seed)

    def raw(on, gain):
        return gc.render_frame(layout, on, width=W, height=H,
                               radius_px=radius_px, dark_level=2.0,
                               lit_level=2.0 + gain, blobs=cache,
                               window_sigmas=5.0)

    gain = peak / max(1e-9, float((raw(every, 1.0) - 2.0).max()))

    def shot(on):
        return np.mean([np.clip(np.round(raw(on, gain)
                                         + rng.normal(0.0, noise, (H, W))),
                                0, 255).astype(np.uint8).astype(np.float64)
                        for _ in range(4)], axis=0)

    return shot(set()), shot(every), [
        (shot({i for i in every if gc.pattern_bits(np.array([i]), b)[0]}),
         shot(every - {i for i in every
                       if gc.pattern_bits(np.array([i]), b)[0]}))
        for b in range(gc.bits_needed(len(layout)))]


def test_a_composition_imaged_into_a_glow_decodes_nothing_and_says_so():
    layout = _glow(736)
    out = gc.decode_stack(*_dim_stack(layout), total=736)
    assert len(out.seen) == 0
    # HIS SIGNATURE: light in the frame, and every lit pixel undecodable —
    # never a confident answer to a question the camera could not read.
    assert out.lit_pixels > 0
    assert out.undecodable_pixels == out.lit_pixels
    assert out.out_of_range_pixels == 0


def test_the_decode_says_which_bits_it_lost():
    """WHERE it dies, in the decode's own report: the low bits alternate
    faster than the camera can see and cancel against their inverses; the
    high bits are perfectly confident, so the stack is neither noise nor
    mistimed."""
    out = gc.decode_stack(*_dim_stack(_glow(736)), total=736)
    low = [c["median_strength"] for c in out.bit_contrast[:6]]
    high = [c["median_strength"] for c in out.bit_contrast[8:]]
    assert all(v < gc.BIT_CONFIDENCE for v in low)
    assert all(v > gc.BIT_CONFIDENCE for v in high)


def test_a_mistimed_stack_looks_nothing_like_it():
    """The discriminator that rules the hypothesis on file out: frames read
    at the wrong moment compare two DIFFERENT patterns, which differ — the
    low bits keep real contrast and pixels decode to wrong indices. His
    runs showed neither."""
    layout = _line(96)
    dark, full, pairs = gc.synthetic_stack(layout, width=W, height=H,
                                           radius_px=2.0)
    flat = [f for pair in pairs for f in pair]
    late = [full] + flat[:-1]
    out = gc.decode_stack(dark, full,
                          [(late[2 * b], late[2 * b + 1])
                           for b in range(len(pairs))], total=96)
    assert any(c["median_strength"] > gc.BIT_CONFIDENCE
               for c in out.bit_contrast[:4])
    # and it still produces CONFIDENT answers (wrong ones) — where his runs
    # produced none at all: every lit pixel undecodable, both times.
    assert out.undecodable_pixels < out.lit_pixels


def test_the_lit_gate_does_not_degenerate_on_a_small_composition():
    """THE GATE THAT REPORTED TWO NUMBERS DESCRIBING NOTHING: a 99th
    percentile of `full - dark` is zero when the composition covers 0.1% of
    the frame, and the gate then admitted every pixel of averaging noise
    (3,165 in his first run) — or, when the dark average came out no lower,
    none at all (his second)."""
    dark, full, _pairs = _dim_stack(_glow(736))
    bright = np.clip(full - dark, 0.0, None)
    _b, lit, peak, floor = gc.bright_and_lit(dark, full)
    old_peak = float(np.percentile(bright, 99.0))
    # the old peak landed in the read noise, two orders below the light it
    # was meant to measure...
    assert old_peak < 0.05 * peak
    old_lit = int((bright >= max(1e-9, old_peak * gc.LIT_FRACTION)).sum())
    assert peak > 50.0 and floor >= gc.MIN_BRIGHT_LEVELS
    # ...so the gate admitted the whole frame's worth of it.
    assert 0 < int(lit.sum()) < old_lit / 10


def test_the_resolution_report_answers_can_this_camera_read_it_at_all():
    dark, full, _ = _dim_stack(_glow(736))
    bad = gc.resolution_report(dark, full, total=736)
    assert bad["any_light"] and not bad["resolvable"]
    assert bad["camera_px_per_index"] < gc.MIN_CAMERA_PX_PER_INDEX
    assert bad["needed_camera_px"] == 1472

    # the same dim room, a composition small enough for this frame
    small = _line(88)
    d2, f2, p2 = _dim_stack(small)
    good = gc.resolution_report(d2, f2, total=88)
    assert good["resolvable"]
    assert len(gc.decode_stack(d2, f2, p2, total=88).seen) > 70


def test_a_frame_with_no_light_at_all_is_reported_as_such():
    """His second run: not one camera pixel came out above the dark
    reference. That is a fact about the room, not zero of 736 pixels."""
    flat = np.full((H, W), 7.0)
    report = gc.resolution_report(flat, flat.copy(), total=736)
    assert report["lit_pixels"] == 0 and not report["any_light"]
    assert not report["resolvable"]
