"""THE TWO REDUCTIONS, against known signals and against the browser.

The kiosk A/V-sync client (`spectra/capture_client/avsync_reduce.py`)
produces the two number streams the server correlates. If either is wrong
in shape or in units, the server still produces a number — a plausible,
confident, WRONG one — so these are asserted against things that cannot
move: a synthesised tone burst whose onset hop is arithmetic, a frame whose
bright quadrant is arithmetic, and a LINE-FOR-LINE PORT of the browser's own
`luminanceOf` (spectra/web/src/avsync/capture.ts), which is the definition
this reduction has to agree with.

No hardware, no server, no network."""
from __future__ import annotations

import math
import struct

import pytest

from spectra.capture_client.avsync_reduce import (GRID, PCM_FULL_SCALE,
                                                  SILENCE_FLOOR_DB,
                                                  FrameReducer, SampleClock,
                                                  grid_spans, log_energy_db,
                                                  pcm16_hop_db)

# ── the browser's own reduction, ported line for line ─────────────────────
# capture.ts::luminanceOf. It takes RGBA; a grey frame expands to R=G=B=v,
# and 0.299 + 0.587 + 0.114 == 1.0 exactly, so the browser's luma of a grey
# pixel IS its grey value — which is why a grey8 camera frame needs no
# conversion before this comparison means anything.


def luminance_of_browser(data, w, h, grid=GRID):
    cell_w = w / grid
    cell_h = h / grid
    sums = [0.0] * (grid * grid)
    counts = [0.0] * (grid * grid)
    total = 0.0
    for y in range(h):
        gy = min(grid - 1, int(y // cell_h))
        for x in range(w):
            i = (y * w + x) * 4
            lum = (0.299 * data[i] + 0.587 * data[i + 1]
                   + 0.114 * data[i + 2])
            gx = min(grid - 1, int(x // cell_w))
            k = gy * grid + gx
            sums[k] += lum
            counts[k] += 1
            total += lum
    out = [round(sums[k] / counts[k], 2) if counts[k] else 0
           for k in range(grid * grid)]
    return round(total / (w * h), 2), out


def rgba_of(grey: bytes) -> bytes:
    out = bytearray()
    for v in grey:
        out += bytes((v, v, v, 255))
    return bytes(out)


# ── 1. the video reduction ────────────────────────────────────────────────

def test_a_known_bright_quadrant_lands_in_the_right_grid_cell():
    """The whole light-side measurement rests on this: a region that got
    brighter has to be THAT region and not its neighbour."""
    w, h = 32, 24
    for cell in range(GRID * GRID):
        gy, gx = divmod(cell, GRID)
        img = bytearray([40]) * (w * h)
        for y in range(gy * (h // GRID), (gy + 1) * (h // GRID)):
            for x in range(gx * (w // GRID), (gx + 1) * (w // GRID)):
                img[y * w + x] = 200
        mean, grid = FrameReducer(w, h).reduce(bytes(img))
        assert grid[cell] == 200.0, (cell, grid)
        assert all(v == 40.0 for i, v in enumerate(grid) if i != cell)
        # one cell in sixteen went from 40 to 200
        assert mean == pytest.approx(40 + 160 / 16, abs=0.01)


@pytest.mark.parametrize("size", [(32, 24), (320, 180), (64, 48), (13, 7),
                                 # fewer pixels than grid cells in one or
                                 # both axes: cells go EMPTY, and which ones
                                 # is the browser's floor rule, not ours
                                 (3, 2), (5, 3), (2, 9)])
def test_it_matches_the_browsers_own_luminanceOf_exactly(size):
    w, h = size
    grey = bytes((x * 7 + y * 13) % 256
                 for y in range(h) for x in range(w))
    mine = FrameReducer(w, h).reduce(grey)
    theirs = luminance_of_browser(rgba_of(grey), w, h)
    assert mine == theirs, (mine, theirs)


def test_the_partition_is_the_browsers_even_when_it_does_not_divide():
    # 13 px over 4 cells: the browser's floor rule gives 4/3/3/3, and a
    # boundary off by one pixel is a light in the wrong region.
    assert grid_spans(13) == [(0, 4), (4, 7), (7, 10), (10, 13)]
    assert grid_spans(320) == [(0, 80), (80, 160), (160, 240), (240, 320)]
    # fewer pixels than cells: empty cells, reported as the browser's 0
    assert grid_spans(3) == [(0, 1), (1, 2), (2, 3), (0, 0)]


def test_a_short_frame_raises_rather_than_reducing_what_it_has():
    r = FrameReducer(32, 24)
    with pytest.raises(ValueError):
        r.reduce(bytes(32 * 24 - 1))


# ── 2. the audio reduction ────────────────────────────────────────────────

def _tone(n, rate, freq=440.0, amp=0.5):
    return [amp * math.sin(2 * math.pi * freq * i / rate) for i in range(n)]


def _pcm(samples):
    return b"".join(struct.pack("<h", max(-32768, min(32767, int(s * 32767))))
                    for s in samples)


def test_a_full_scale_signal_is_zero_dB_and_silence_is_the_floor():
    # a square wave at full scale has mean square 1 → 0 dB
    assert log_energy_db([1.0, -1.0] * 64) == pytest.approx(0.0, abs=1e-9)
    assert log_energy_db([0.0] * 64) == SILENCE_FLOOR_DB
    assert log_energy_db([]) == SILENCE_FLOOR_DB
    # a sine at amplitude a has mean square a²/2
    got = log_energy_db(_tone(4800, 48000, amp=0.5))
    assert got == pytest.approx(10 * math.log10(0.25 / 2), abs=0.05)


def test_pcm16_agrees_with_the_float_definition_to_a_hundredth_of_a_dB():
    """The server's reference tap and the browser's worklet both compute
    the float form; this client computes it from raw 16-bit words. If the
    two disagreed the audio lag would be measured against a differently
    shaped envelope."""
    samples = _tone(512, 48000, amp=0.4)
    quantised = [round(s * 32767) / PCM_FULL_SCALE for s in samples]
    assert pcm16_hop_db(_pcm(samples)) == pytest.approx(
        log_energy_db(quantised), abs=0.01)
    assert pcm16_hop_db(b"\x00\x00" * 512) == SILENCE_FLOOR_DB
    assert pcm16_hop_db(b"") == SILENCE_FLOOR_DB


def test_a_tone_burst_puts_its_onset_in_the_arithmetically_right_hop():
    """The load-bearing property of the envelope: WHERE the energy rises.
    A burst starting at sample 5·hop must show up at hop index 5, not 4 or
    6 — an off-by-one hop is 11 ms of silent error in the measurement."""
    rate, hop = 48000, 512
    onset_hop = 5
    quiet = [0.0005] * (onset_hop * hop)
    loud = _tone(hop * 4, rate, amp=0.7)
    pcm = _pcm(quiet + loud + [0.0005] * (hop * 3))
    hops = [pcm16_hop_db(pcm[i * hop * 2:(i + 1) * hop * 2])
            for i in range(len(pcm) // (hop * 2))]
    rises = [i for i in range(1, len(hops)) if hops[i] - hops[i - 1] > 20]
    assert rises == [onset_hop], hops
    assert hops[onset_hop] > -10 and hops[onset_hop - 1] < -50


# ── 3. the sample clock ───────────────────────────────────────────────────

def _drive(clock, delays, *, n, true_start=100.0):
    return [clock.observe(true_start + (k + 1) * n / clock.rate_hz + d, n)
            for k, d in enumerate(delays)]


def test_the_sample_clock_keeps_read_jitter_out_of_the_envelope():
    """Reads are late by a random amount; the hop timestamps must not be.
    The anchor is the LEAST delayed read seen during the warm-up, so once
    it is frozen every hop lands on the grid the samples themselves define
    and the SPACING — which is what the correlator uses — is exact."""
    rate, hop, batch = 48000.0, 512, 8
    n = hop * batch
    clock = SampleClock(rate, freeze_after_reads=4)
    delays = [0.030, 0.002, 0.045, 0.011] + [0.011, 0.070, 0.005]
    starts = _drive(clock, delays, n=n)
    # the best read of the warm-up was 2 ms late, so every hop AFTER the
    # freeze is 2 ms late and exactly one batch apart
    for k in range(4, len(delays)):
        assert starts[k] == pytest.approx(100.0 + k * n / rate + 0.002,
                                          abs=1e-9)
    assert clock.frozen and clock.reads == len(delays)
    assert clock.spread_s == pytest.approx(0.068, abs=1e-9)


def test_the_anchor_freezes_so_one_fast_read_cannot_step_a_live_window():
    """AN ANCHOR THAT KEEPS IMPROVING PUTS A STEP IN THE MIDDLE OF THE
    MEASUREMENT. A genuinely fast read arriving after the warm-up must not
    move hops that are already being correlated against hops that are not."""
    rate, n = 48000.0, 4096
    clock = SampleClock(rate, freeze_after_reads=3)
    _drive(clock, [0.020, 0.010, 0.015], n=n)
    anchor = clock.anchor_s
    late = clock.observe(100.0 + 4 * n / rate + 0.000001, n)
    assert clock.anchor_s == anchor
    assert late == pytest.approx(anchor + 3 * n / rate, abs=1e-9)
    # ...and it is still VISIBLE that a faster read was seen, and what
    # holding the anchor steady cost in absolute accuracy
    assert clock.spread_s == pytest.approx(0.019999, abs=1e-5)
    assert clock.freeze_cost_s == pytest.approx(0.009999, abs=1e-5)


def test_the_sample_clock_refuses_to_answer_before_it_has_seen_a_read():
    with pytest.raises(RuntimeError):
        SampleClock(48000).at(0)
