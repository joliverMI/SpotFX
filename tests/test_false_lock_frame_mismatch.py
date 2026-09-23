"""Regression fixture for data/false-lock-continued-search/report.md — the
2026-09-22 false lock on MIA.

His two captures of the same recording under two Spotify URIs sit ~5375ms
apart in their own timelines (report §1, "The disconfirming check"). Live
audio that night matched the profile's own stored shape at +4274ms — a
perfectly self-consistent, unanimous correlation (report §1) that the
sweep's own hard-lock rule was RIGHT to trust. It is right as a MEASUREMENT
of the shape; the shape and his hand-placed marks just don't share a frame.

This test reproduces that exact class of false lock OFFLINE, using his real
captured audio (tests/fixtures/, copied read-only from
storage/audio_shapes/) and the production math/decision kernel verbatim —
`services.xcorr_core.xcorr_window_full`, `services.xcorr_evidence.
EvidenceAccumulator`, `services.xcorr_sweep.SweepEvaluator.lock_and_stop` —
never a re-implementation of the lock rule. It proves three things:

  (i)   The production rule DOES hard-lock here, confidently, within a
        handful of windows — property (a) from the report (keep searching
        longer, only commit once trailing windows agree) cannot catch this:
        once the correlation converges it stays unanimous. More spike
        detection measures the shape's own internal alignment more
        precisely; the shape is not what's wrong.
  (ii)  Ship 2's frame-mismatch advisory (services/frame_advisory.py) DOES
        fire on this lock against the room's real band that night (~-1100ms,
        report §1) — an ADVISORY only, recorded on the lock_history entry,
        never a refusal.
  (iii) The same evaluation with live=stored (a shape correlated against
        itself — i.e. one that IS in its own frame) locks near 0ms and the
        advisory stays quiet, so the rule doesn't cry wolf on an ordinary,
        correctly-framed lock.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from config import settings
from services import frame_advisory
from services.xcorr_core import difficulty_score, signed_square, xcorr_window_full
from services.xcorr_evidence import EvidenceAccumulator
from services.xcorr_sweep import SweepConfig, SweepEvaluator

FIXTURES = Path(__file__).parent / "fixtures"
STORED_NPZ = FIXTURES / "Bad Bunny, Drake - MIA.npz"
STORED_META = FIXTURES / "Bad Bunny, Drake - MIA.json"
OTHER_CAPTURE_NPZ = FIXTURES / "Bad Bunny, Drake - MIA (feat. Drake).npz"

# Bands in the order the production repro (report appendix,
# scratch/repro_false_lock_mia.py) uses.
_BAND_KEYS = ("rms_total", "rms_low", "rms_mid", "rms_high")
MAX_WINDOWS = 8

# His real MIA profile carries 19 hand-authored (non-ai_generated) triggers
# (report §1 / appendix "Shape/profile facts") — hardcoded here rather than
# read from live storage/profiles/ (tests never touch live storage).
MIA_HAS_AUTHORED_TRIGGERS = True

# The room's real band that night (report §1: "every other play tonight sat
# between -50 and -1125 ms; the whole-room drift gate read -1089ms").
ROOM_BAND_MS = -1100


def _run_sweep(*, live_npz: Path, uri: str) -> tuple[list[tuple[int, float]], float, bool, float]:
    """Drives the production kernel window-by-window exactly as
    scratch/repro_false_lock_mia.py does, but calls the REAL
    SweepEvaluator.lock_and_stop for the lock decision rather than
    reproducing its boolean expression. Returns (per-window (offset, r)
    list, final locked offset, whether it locked, final play-best Q)."""
    stored = np.load(STORED_NPZ)
    live = np.load(live_npz)
    meta = json.loads(STORED_META.read_text(encoding="utf-8"))
    cfg = SweepConfig.from_settings(settings)

    stored_ts = stored["timestamps_ms"].astype(float)
    bands = [signed_square(np.asarray(stored[k], float)) for k in _BAND_KEYS]
    frames = [
        (int(t), float(a), float(b), float(c), float(d))
        for t, a, b, c, d in zip(
            live["timestamps_ms"], live["rms_total"], live["rms_low"],
            live["rms_mid"], live["rms_high"],
        )
    ]

    acc = EvidenceAccumulator(max_offset_ms=35000)
    evaluator = SweepEvaluator(
        cfg, uri=uri, verification="auto", play_type="first",
        seed_offset_ms=0, accumulator=acc,
    )

    windows = [(int(w["start_ms"]), int(w["end_ms"])) for w in meta["xcorr_windows"]][:MAX_WINDOWS]
    play_best = 0.0
    per_window: list[tuple[int, float]] = []
    locked = False
    locked_offset = 0.0

    for win_start, win_end in windows:
        diff = difficulty_score(
            np.interp(np.arange(win_start, win_end, 25.0), stored_ts, bands[1]), bands[1],
        )
        landscape = xcorr_window_full(stored_ts, bands, frames, win_start, win_end, search_ms=30000)
        if landscape is None:
            continue
        r = np.asarray(landscape.r)
        shifts = np.asarray(landscape.shifts_ms)
        i = int(np.nanargmax(r))
        offset = -int(shifts[i])
        quality = float(r[i]) * diff
        acc.add_curve(-shifts.astype(float), r, diff)
        peak = acc.dominant()
        play_best = max(play_best, quality)
        per_window.append((offset, float(r[i])))
        if evaluator.lock_and_stop(play_best):
            locked = True
            locked_offset = float(peak.offset_ms)
            break

    return per_window, locked_offset, locked, play_best


def test_the_two_mia_captures_disagree_by_the_reported_5375ms():
    """Sanity check on the fixtures themselves before trusting anything
    built on top of them."""
    stored = np.load(STORED_NPZ)
    other = np.load(OTHER_CAPTURE_NPZ)
    stored_ts = stored["timestamps_ms"].astype(float)
    stored_total = signed_square(np.asarray(stored["rms_total"], float))
    grid = np.arange(0, 400_000, 25.0)
    stored_on_grid = np.interp(grid, stored_ts, stored_total)
    other_ts = other["timestamps_ms"].astype(float)
    other_total = signed_square(np.asarray(other["rms_total"], float))
    other_on_grid = np.interp(grid, other_ts, other_total)

    best_r, best_lag = -2.0, 0
    for lag_steps in range(int(4000 / 25), int(6800 / 25)):
        a = stored_on_grid[lag_steps:]
        b = other_on_grid[: len(a)]
        n = min(len(a), len(b))
        if n < 1000:
            continue
        a, b = a[:n], b[:n]
        if a.std() < 1e-9 or b.std() < 1e-9:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        if r > best_r:
            best_r, best_lag = r, lag_steps * 25

    assert best_r > 0.85
    assert best_lag == pytest.approx(5375, abs=100)


def test_production_rule_hard_locks_the_frame_mismatched_pair(caplog):
    """(i) The production lock rule genuinely hard-locks on the two-capture
    mismatch, unanimously, within MAX_WINDOWS — proving that "keep
    searching longer" (report §3, property a) and the post-lock mismatch
    monitor (property c) cannot distinguish this from a correct lock: the
    correlation itself is real and consistent, every window agreeing."""
    per_window, locked_offset, locked, play_best = _run_sweep(
        live_npz=OTHER_CAPTURE_NPZ, uri="spotify:track:false-lock-test-mia",
    )

    assert locked, "production rule did not hard-lock the frame-mismatched pair"
    assert len(per_window) <= MAX_WINDOWS
    assert locked_offset == pytest.approx(5376, abs=25)

    # Once the free-search correlation converges on the true 5375ms lag (the
    # first two windows are a blind ±30s global search with no history to
    # narrow it — same shape as the report's own "global center 0" search),
    # every later window agrees with the eventual lock, within the sweep's
    # own confirm tolerance. This unanimity is exactly why property (a)
    # (require K more agreeing windows before committing) cannot catch it.
    agreeing_from = next(
        idx for idx, (offset, _r) in enumerate(per_window)
        if abs(offset - locked_offset) <= 300
    )
    for offset, _r in per_window[agreeing_from:]:
        assert abs(offset - locked_offset) <= 300


def test_frame_advisory_fires_against_the_rooms_real_band():
    """(ii) Ship 2: the same hard lock, judged against the room's real band
    that night, is flagged frame_suspect — an advisory, not a refusal."""
    _per_window, locked_offset, locked, _play_best = _run_sweep(
        live_npz=OTHER_CAPTURE_NPZ, uri="spotify:track:false-lock-test-mia",
    )
    assert locked

    advisory = frame_advisory.evaluate(
        locked=locked,
        lock_offset_ms=int(round(locked_offset)),
        has_authored_triggers=MIA_HAS_AUTHORED_TRIGGERS,
        band_ms=ROOM_BAND_MS,
    )

    assert advisory.suspect is True
    assert advisory.room_band_ms == ROOM_BAND_MS
    assert advisory.distance_ms == abs(int(round(locked_offset)) - ROOM_BAND_MS)
    assert advisory.distance_ms > frame_advisory.FRAME_SUSPECT_DISTANCE_MS


def test_a_correctly_framed_lock_stays_quiet():
    """(iii) The same shape correlated against ITSELF (a lock genuinely in
    its own frame) locks near 0ms, and the advisory does not fire."""
    _per_window, locked_offset, locked, _play_best = _run_sweep(
        live_npz=STORED_NPZ, uri="spotify:track:false-lock-test-mia-self",
    )

    assert locked
    assert locked_offset == pytest.approx(0, abs=50)

    advisory = frame_advisory.evaluate(
        locked=locked,
        lock_offset_ms=int(round(locked_offset)),
        has_authored_triggers=MIA_HAS_AUTHORED_TRIGGERS,
        band_ms=ROOM_BAND_MS,
    )

    assert advisory.suspect is False
