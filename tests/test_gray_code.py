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
