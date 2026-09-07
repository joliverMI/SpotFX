"""THE TWO REDUCTIONS, and they are the whole of what leaves this machine.

The A/V-sync instrument measures ONE number — how far the lights are behind
(or ahead of) the sound, as seen and heard from where the camera stands.
Its server half (`spectra/services/av_sync_session.py`) never receives audio
or video: it receives two low-rate NUMBER STREAMS, and this module is where
the kiosk produces them. The browser client
(`spectra/web/src/avsync/capture.ts`) produces the SAME two streams from a
phone; the server cannot tell which reduced them, and that is the point.

  AUDIO   one log-energy number per ~11 ms hop (~90/s):
          `10·log10(mean(x²))`, floored at −90 dB, over float samples in
          [-1, 1]. Byte for byte the definition in the browser's
          `spectra-envelope` AudioWorklet AND in the server's own reference
          tap (`av_sync_audio_ref.log_energy_db`) — one envelope
          definition, three implementations, deliberately identical.
  VIDEO   per frame: one MEAN brightness plus a 4×4 grid of region means
          (`luminanceOf` in capture.ts), 0–255.

WHY THE BROWSER'S 32×24 CANVAS IS NOT REPRODUCED HERE, and why that is
faithful rather than a shortcut. The browser draws each frame onto a 32×24
canvas because reading a full-size frame back out of a canvas every frame is
expensive in a page; the 4×4 grid it then computes is a partition of the
frame into proportional regions, and a box-mean downscale followed by a
proportional partition gives the SAME region means as the partition alone.
This module therefore partitions the camera's own grey8 frame directly, with
the identical index arithmetic (`min(GRID-1, floor(y/cellH))`), and skips a
lossy intermediate that would only add quantisation.
`tests/test_avsync_reduce.py` asserts that equality against a line-for-line
port of `luminanceOf` rather than asserting it in prose.

UNITS, stated because a unit mismatch is a silent wrong answer:
  * grey8 from `camera.V4L2Camera` is already luma — ffmpeg's `-pix_fmt
    gray` — so there is no RGB→luma step here. A camera delivering
    limited-range (16–235) luma differs from the browser's full-range canvas
    by a fixed scale and offset; the correlator high-passes and
    differentiates both sides, so a scale/offset changes no lag. What it
    would change — an absolute brightness comparison — this instrument never
    makes.
  * PCM arrives as signed 16-bit and is divided by 32768 before the log, so
    the dB values are on the same [-1,1] scale the worklet and the server
    tap both use.

COST, measured on this repo's build machine rather than asserted: the video
reduction is 0.72 ms for a 320×180 frame (2.2 % of one core at 30 fps) and
the audio reduction 30 µs per hop (0.3 % of one core at 94 hops/s), which is
why there is no numpy here and why the client's dependency closure is still
exactly httpx + websockets (`scripts/check_capture_client_deps.py`).
"""
from __future__ import annotations

import array
import math
import operator
from typing import Iterable, Optional

#: The browser's own constants, mirrored (capture.ts). GRID is on the wire
#: — the server correlates each of the 16 regions separately and keeps the
#: one that actually responded — so it is not ours to change alone.
GRID = 4
#: The envelope's silence floor, identical to
#: `av_sync_audio_ref.SILENCE_FLOOR_DB`. A floor rather than −inf so a
#: silent hop is a number the correlator can resample.
SILENCE_FLOOR_DB = -90.0
#: Full-scale for signed 16-bit PCM. Dividing by this (not 32767) is what
#: the rest of the world means by "unit scale", and a half-LSB is 0.0003 dB.
PCM_FULL_SCALE = 32768.0


def log_energy_db(samples: Iterable[float]) -> float:
    """`10·log10(mean square)` with a silence floor — the ONE envelope
    definition this instrument has. `samples` are floats in [-1, 1]."""
    total = 0.0
    n = 0
    for s in samples:
        total += s * s
        n += 1
    if n == 0 or total <= 0.0:
        return SILENCE_FLOOR_DB
    return max(SILENCE_FLOOR_DB, 10.0 * math.log10(total / n))


def pcm16_hop_db(pcm: bytes) -> float:
    """The same quantity straight off a signed-16-bit little-endian hop —
    the shape a capture device actually hands over.

    The sum of squares is taken on the RAW integers (exact, and `map` keeps
    it at C speed) and scaled once at the end, which is algebraically
    identical to squaring the normalised floats and measurably cheaper."""
    if len(pcm) < 2:
        return SILENCE_FLOOR_DB
    a = array.array("h")
    a.frombytes(pcm[:len(pcm) - (len(pcm) % 2)])
    if _NEEDS_BYTESWAP:                                # pragma: no cover
        a.byteswap()
    if not a:
        return SILENCE_FLOOR_DB
    total = sum(map(operator.mul, a, a))
    if total <= 0:
        return SILENCE_FLOOR_DB
    mean_square = (total / len(a)) / (PCM_FULL_SCALE * PCM_FULL_SCALE)
    return max(SILENCE_FLOOR_DB, 10.0 * math.log10(mean_square))


#: `array('h')` is NATIVE-endian and the wire format is little-endian, so a
#: big-endian host has to swap. Decided once, here, rather than assumed.
_NEEDS_BYTESWAP = array.array("h", b"\x01\x00")[0] != 1


# ── the video reduction ────────────────────────────────────────────────────

def grid_spans(length: int, grid: int = GRID) -> list:
    """The pixel spans each grid column/row covers, computed with the
    BROWSER'S OWN expression (`min(grid-1, floor(i / (length/grid)))`) so
    the two partitions cannot disagree at a boundary.

    Returned as `[(start, stop), ...]`, one per grid cell; a span can be
    empty when `length < grid`, which the caller reports as a zero the way
    the browser's `counts[k] ? … : 0` does."""
    if length <= 0 or grid <= 0:
        return [(0, 0)] * max(0, grid)
    cell = length / grid
    spans = [[length, 0] for _ in range(grid)]
    for i in range(length):
        g = min(grid - 1, int(i / cell))
        spans[g][0] = min(spans[g][0], i)
        spans[g][1] = max(spans[g][1], i + 1)
    return [(lo, hi) if hi > lo else (0, 0) for lo, hi in spans]


class FrameReducer:
    """One camera frame → (mean, 16 region means). The spans are computed
    once per frame SIZE, because a run holds one size for its whole life and
    recomputing them per frame is the only expensive part of this."""

    def __init__(self, width: int, height: int, grid: int = GRID) -> None:
        self.grid = grid
        self.resize(width, height)

    def resize(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self._cols = grid_spans(self.width, self.grid)
        self._rows = grid_spans(self.height, self.grid)

    @property
    def expected_bytes(self) -> int:
        return self.width * self.height

    def reduce(self, frame: bytes) -> tuple:
        """(mean, grid) for one grey8 frame, both rounded to 2 dp exactly
        as the browser rounds them. A frame that is not the expected size is
        a caller error and raises — silently reducing a short buffer would
        put a real number on the wire for pixels that were never captured."""
        want = self.expected_bytes
        if len(frame) != want:
            raise ValueError(
                f"grey8 frame is {len(frame)} bytes, expected "
                f"{want} for {self.width}x{self.height}")
        n = self.grid
        sums = [0] * (n * n)
        counts = [0] * (n * n)
        mv = memoryview(frame)
        cols = self._cols
        for gy, (y0, y1) in enumerate(self._rows):
            base = gy * n
            for y in range(y0, y1):
                row = mv[y * self.width:(y + 1) * self.width]
                for gx, (x0, x1) in enumerate(cols):
                    if x1 > x0:
                        sums[base + gx] += sum(row[x0:x1])
                        counts[base + gx] += x1 - x0
        grid = [round(sums[k] / counts[k], 2) if counts[k] else 0
                for k in range(n * n)]
        total = sum(sums)
        mean = round(total / want, 2) if want else 0.0
        return mean, grid


# ── the audio hop clock ────────────────────────────────────────────────────

class SampleClock:
    """WHEN A SAMPLE EXISTED, from a stream that can only say when a READ
    RETURNED.

    A capture device hands over whole periods, and the read that collects
    one can be delayed by anything the machine is doing — so a per-read
    timestamp carries the scheduler's jitter into every hop it stamps. What
    the stream DOES give exactly is a sample count, so this maps sample
    index → monotonic seconds through a single anchor:

        t(index) = anchor + index / rate

    and picks the anchor as the MINIMUM of `t_read − samples_read / rate`
    over the WARM-UP reads (see the freeze below) — the least-delayed read,
    exactly the way `av_sync_session.ClockMap` keeps the min-RTT ping rather
    than the last one. Every other read was late by definition, so the
    minimum is the best available estimate of an undelayed one.

    WHAT IT DOES NOT CORRECT, and this is named rather than hidden: the
    capture path's own latency — ADC, USB, the driver's buffer — is present
    in every read equally, so the minimum contains it too. That term makes
    the sound look like it arrived LATER than it did, which makes the
    measured audio lag LARGER and the lights therefore read relatively
    EARLIER; the server names it (`SYSTEMATIC_MIC_UNKNOWN`, direction
    "lights_look_earlier") because this client cannot measure it.

    AND THEN IT FREEZES, which is the half that matters to a correlation.
    An anchor that keeps improving is more accurate over time and LESS
    consistent: a genuinely fast read arriving mid-measurement would shift
    every subsequent hop earlier than every previous one, putting a step in
    the middle of the window being correlated. So the minimum is taken over
    the first `FREEZE_AFTER_READS` reads and then held for the life of the
    stream — one mapping for the whole capture. The client warms up for
    seconds before any measurement starts (`avsync_session.WARMUP_S`), so
    the anchor is always long frozen by the time a pattern runs.

    `spread_s` is the gap between the earliest and latest anchor candidate
    SEEN (before and after the freeze alike): read jitter, plus any drift
    between the sound card's clock and the system's. It is reported rather
    than corrected — a number a reader can see beats a correction nobody can
    check.
    """

    #: About a second of stream at the client's batch rate — long enough for
    #: the minimum to be a real minimum, short enough to be finished before
    #: the shortest warm-up.
    FREEZE_AFTER_READS = 12

    def __init__(self, rate_hz: float,
                 freeze_after_reads: int = FREEZE_AFTER_READS) -> None:
        self.rate_hz = float(rate_hz)
        self.freeze_after_reads = int(freeze_after_reads)
        self.samples = 0
        #: The anchor in use — the minimum over the warm-up, then held.
        self.anchor_s: Optional[float] = None
        #: Every candidate ever seen, frozen or not, so the freeze itself
        #: stays visible: a stream whose reads got faster after the warm-up
        #: is a fact a reader should be able to notice.
        self._min_seen_s: Optional[float] = None
        self._max_seen_s: Optional[float] = None
        self.reads = 0

    @property
    def frozen(self) -> bool:
        return self.reads >= self.freeze_after_reads

    def observe(self, t_read_s: float, samples_in_read: int) -> float:
        """Account for one read that returned `samples_in_read` samples at
        `t_read_s`, and return the monotonic time of its FIRST sample."""
        first_index = self.samples
        self.samples += int(samples_in_read)
        candidate = t_read_s - self.samples / self.rate_hz
        if not self.frozen and (self.anchor_s is None
                                or candidate < self.anchor_s):
            self.anchor_s = candidate
        if self._min_seen_s is None or candidate < self._min_seen_s:
            self._min_seen_s = candidate
        if self._max_seen_s is None or candidate > self._max_seen_s:
            self._max_seen_s = candidate
        self.reads += 1
        return self.at(first_index)

    def at(self, index: int) -> float:
        if self.anchor_s is None:
            raise RuntimeError("SampleClock has seen no reads")
        return self.anchor_s + index / self.rate_hz

    @property
    def spread_s(self) -> float:
        """Earliest to latest anchor candidate over the WHOLE stream."""
        if self._min_seen_s is None or self._max_seen_s is None:
            return 0.0
        return self._max_seen_s - self._min_seen_s

    @property
    def freeze_cost_s(self) -> float:
        """How much earlier the anchor WOULD have been had it kept
        improving — i.e. what holding it steady cost in absolute accuracy.
        Always ≥ 0, and reported rather than acted on: a consistent mapping
        across the correlation window is worth more than a closer one that
        moves inside it."""
        if self.anchor_s is None or self._min_seen_s is None:
            return 0.0
        return max(0.0, self.anchor_s - self._min_seen_s)
