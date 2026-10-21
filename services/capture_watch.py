"""
SpotFX — the mid-song capture detectors (data/absorb-music-plan/report.md
§4.3): condemn a capture the moment it is certain to be discarded, instead of
finding out three minutes later.

Each detector is the EARLY form of a check `_finalize_capture` already makes
at the song's end, so a condemnation never disagrees with what finalize
would decide:

  gap             a frame arrives more than `audio_max_gap_ms` after the one
                  before it (139 of 187 measured failures). Seen on the very
                  next frame. Frames past the song's own duration are not
                  judged: finalize trims those at the track boundary.
  bad_timestamps  the capture's first sample is already at or past the song's
                  end — the "renders no shape" baseline. Seen on the first
                  live frame.
  coverage        the capture started so late that, even running to the
                  song's end, its span cannot reach `audio_shape_min_capture_pct`
                  of the song. Seen on the first live frame.

Two more detectors need the Spotify poll rather than a frame and live in the
runner (services/absorb.py): the parec governor's `seq` moving during the
capture (a silent elision the gap check can never see), and playback leaving
the Serenity device.

PURE: no I/O, no clock. `CaptureWatch.on_frame` returns a `Condemnation` at
most once per capture; audio_shape_service hands it to whoever listens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Slack on the coverage test: a capture's last frame can land a little past
# Spotify's own duration (the audio arrives `audio_latency_ms` late), so the
# reachable span is judged generously — this detector only fires when the
# shortfall is certain.
COVERAGE_SLACK_MS = 2000


@dataclass(frozen=True)
class Condemnation:
    uri: str
    reason: str          # "gap" | "bad_timestamps" | "coverage" | ...
    detail: str
    at_song_ms: int = 0


class CaptureWatch:
    def __init__(self, uri: str, duration_ms: int, max_gap_ms: int,
                 min_capture_pct: float) -> None:
        self.uri = uri
        self.duration_ms = int(duration_ms or 0)
        self.max_gap_ms = int(max_gap_ms)
        self.min_capture_pct = float(min_capture_pct)
        self.fired: Optional[Condemnation] = None
        self._first_checked = False

    def _fire(self, reason: str, detail: str, at_ms: int) -> Condemnation:
        self.fired = Condemnation(self.uri, reason, detail, at_ms)
        return self.fired

    def on_frame(self, ts_ms: int, prev_ts_ms: Optional[int],
                 first_ts_ms: Optional[int]) -> Optional[Condemnation]:
        """Judge one live frame BEFORE it is ingested. `prev_ts_ms` is the
        recorder's last timestamp (pre-roll and seam frames included — the
        same sequence finalize measures gaps over); `first_ts_ms` is the
        recorder's first, or this frame's when the recorder is empty."""
        if self.fired is not None:
            return None
        first = first_ts_ms if first_ts_ms is not None else ts_ms
        if not self._first_checked:
            self._first_checked = True
            if self.duration_ms > 0 and first >= self.duration_ms:
                return self._fire(
                    "bad_timestamps",
                    f"first sample at {first} ms, song is {self.duration_ms} ms",
                    ts_ms)
            if self.duration_ms > 0:
                reachable = self.duration_ms + COVERAGE_SLACK_MS - first
                need = self.duration_ms * self.min_capture_pct
                if reachable < need:
                    return self._fire(
                        "coverage",
                        f"capture starts at {first} ms; at most "
                        f"{reachable / self.duration_ms:.0%} of the song can be "
                        f"covered, the bar is {self.min_capture_pct:.0%}",
                        ts_ms)
        if prev_ts_ms is not None and (self.duration_ms <= 0 or ts_ms <= self.duration_ms):
            gap = ts_ms - prev_ts_ms
            if gap > self.max_gap_ms:
                return self._fire(
                    "gap",
                    f"{gap} ms gap at {prev_ts_ms} ms (limit {self.max_gap_ms} ms)",
                    ts_ms)
        return None


# ── the parec governor (read by the runner on the poll) ─────────────────────

def read_governor(path: str) -> Optional[dict]:
    """`{seq, dropped_total_ms}` from River's parec-governor status file, or
    None when it cannot be read — an unknown reading never condemns."""
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or "seq" not in data:
        return None
    try:
        return {"seq": int(data["seq"]),
                "dropped_total_ms": int(data.get("dropped_total_ms") or 0)}
    except (TypeError, ValueError):
        return None


def governor_moved(before: Optional[dict], after: Optional[dict]) -> Optional[str]:
    """A detail sentence when the governor dropped audio between two
    readings, else None. Either reading unknown → None."""
    if not before or not after:
        return None
    if after["seq"] == before["seq"]:
        return None
    dropped = after["dropped_total_ms"] - before["dropped_total_ms"]
    return (f"parec governor event seq {before['seq']}→{after['seq']}"
            + (f", {dropped} ms of audio dropped" if dropped > 0 else ""))
