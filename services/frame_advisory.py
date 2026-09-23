"""SpotFX — frame-mismatch ADVISORY on a hard lock (Ship 2,
data/false-lock-continued-search/report.md section 4).

A hard lock that lands far from the room's own current timing band, on a
song carrying hand-authored (not ai_generated) triggers, is the shape this
scout report found: the captured audio SHAPE and the marks placed on it can
end up in two different timing frames (MIA/200 Mph, both ~4.2s off the room
tonight while every other play sat within ~1s). More trailing spike-detection
windows and the post-lock mismatch monitor cannot catch this — they both
re-measure the SAME shape's own internal alignment, which was perfectly
self-consistent in both cases (report sections 2-3). This module never
refuses, adjusts, or delays a lock: it only records a fact for a human to
check by ear, on the lock_history entry the Timing page and lock badge read.

Exact rule (report section 4, verbatim):
    abs(lock_offset_ms - room_center_ms) > FRAME_SUSPECT_DISTANCE_MS
    and any(not t.ai_generated for t in profile.triggers)

room_center_ms is the room's current plausibility band: the systemic
learner's centre (services/systemic_offset.py) when its confidence is at
least ROOM_BAND_MIN_CONFIDENCE, else the median of this session's own
locked plays. With neither available there is nothing to compare a lock
against, so the advisory stays silent rather than guessing — a fresh
session's very first lock is never flagged on the strength of nothing.

Order 30: nothing here ever moves a fire time, refuses a lock, or shortens
the audio lag. `evaluate()` is called AFTER a play's lock decision is
already final; its only output is a bool plus the numbers behind it.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

# The report's own threshold: on 2026-08-28..2026-09-22 history this flags
# 150 of 323 hard locks (46%) — a deliberately loose net meant to be checked
# by ear, not a tuned false-positive-minimizing cutoff.
FRAME_SUSPECT_DISTANCE_MS = 2000

# Below this the systemic learner's own centre is too thin a sample to trust
# as "the room's band" — matches settings.systemic_offset_min_confidence's
# default, but is its own constant: that setting gates whether the learner's
# bias is APPLIED at cold start, a different question from what this
# advisory treats as a plausible band to compare a lock against.
ROOM_BAND_MIN_CONFIDENCE = 0.25


@dataclass(frozen=True)
class FrameAdvisory:
    suspect: bool
    room_band_ms: Optional[int]
    distance_ms: Optional[int]


def room_band_ms(
    systemic_center_ms: Optional[int],
    systemic_confidence: float,
    session_locked_offsets_ms: Sequence[int],
) -> Optional[int]:
    """The room's current plausibility band, per the report's own rule.
    None when neither source has anything to offer — never a fabricated 0."""
    if systemic_center_ms is not None and systemic_confidence >= ROOM_BAND_MIN_CONFIDENCE:
        return int(systemic_center_ms)
    if session_locked_offsets_ms:
        return int(round(statistics.median(session_locked_offsets_ms)))
    return None


def evaluate(
    *,
    locked: bool,
    lock_offset_ms: int,
    has_authored_triggers: bool,
    band_ms: Optional[int],
) -> FrameAdvisory:
    """Advisory only. Returns suspect=False (never an error) whenever the
    rule's own preconditions aren't met: no hard lock, no band to compare
    against, or no hand-authored triggers to protect (a generated-only song
    has no marks whose frame could be wrong)."""
    if not locked or band_ms is None or not has_authored_triggers:
        return FrameAdvisory(suspect=False, room_band_ms=band_ms, distance_ms=None)
    distance = abs(int(lock_offset_ms) - int(band_ms))
    return FrameAdvisory(
        suspect=distance > FRAME_SUSPECT_DISTANCE_MS,
        room_band_ms=int(band_ms),
        distance_ms=distance,
    )
