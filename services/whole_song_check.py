"""
SpotFX — the end-of-play WHOLE-SONG CHECK (the missing per-song watchdog).

Why this exists (data/lock-investigation/report.md, 2026-10-12, §5.4 and §8
rec. 1; the Admiral's call 2026-10-13, option A: "he authored those triggers
on the waveform, so a whole-song check may correct saved offsets
automatically"): every per-play sweep searches only ±2.5–3.5 s around the
song's STORED offset, and the gates that keep repeating-phrase lookalikes
("twins") out — the in-song drift cap, the per-window envelope, the 0.20
"beat the old offset by" margin — also keep the truth out once the stored
value is more than ~3 s wrong. Nothing ever looked at the whole song, so a
stale or twin offset was re-saved every play (El Efecto: truth +11,750 ms vs
saved +325 since August; Ponle Dembow: truth +6,250 ms vs re-saved +1,225).

What it does, after a play ends, off the event loop, on the play's OWN
captured frames (already in memory — nothing is re-captured):

  1. Cut the stored shape into WINDOW_MS windows every STEP_MS, skipping
     flat ones (difficulty < 0.15, the sweep's own starting threshold).
  2. Score each window over ±SEARCH_MS of offsets with the PRODUCTION
     landscape (`xcorr_core.xcorr_window_full`, multi-band FFT NCC at 25 ms),
     limited to shifts the play's frames actually cover, and take its peak.
  3. Vote the peaks into VOTE_BIN_MS bins. The winner's support is every
     peak within CLUSTER_TOL_MS of the winning bin; the corrected offset is
     the median of those peaks (25 ms resolution, not the 250 ms bin).
  4. Score the SAVED offset (the value the next play would load) on the same
     windows with `xcorr_core.eval_at_shift`.

`decide()` then corrects the stored offset ONLY when every one of these
holds — each named so a refusal says which one failed:

  * at least `min_windows` windows were scored (a play skipped early can't
    testify about the whole song);
  * one offset wins at least `min_vote_fraction` of them (a twin-ambiguous
    song splits its vote and is left alone);
  * the winner's median r is at least `min_median_r`;
  * the winner's median r beats the saved offset's by `min_r_margin` (a song
    already right is never moved — it agrees, or its saved value scores as
    well as the winner);
  * the winner is at least `min_move_ms` from the saved offset (smaller
    differences are the per-play sweep's job — it searches ±2.5 s and
    resolves to 25 ms; this check is for what that search cannot see);
  * the stored offset is not user_verified (then it reports, never saves).

The thresholds are the report's offline run on his live audio: El Efecto
27/29 windows at r 0.95 vs 0.56 at the saved offset; Ponle Dembow 26/32 at
0.82 vs 0.53; and on all 20 songs that locked that night the vote agreed
with the lock. They are room settings (`xcorr_whole_song_*` in config.py),
editable on the Timing page and by Sonic.

The vote is pure (numpy only, no I/O, no settings read inside the math);
`services/auto_offset_service.py` runs it and performs the save. Every
check — correction or not — is appended to a bounded log
(storage/whole_song_checks.json) served at GET /api/lock-history/whole-song
and shown on the Timing page, and every correction is logged at WARNING.

THE SIGN CONVENTION is the sweep's (auto_offset_service module docstring):
offset_ms = −shift_ms, where shift_ms > 0 means the live signal sits LATER
than the stored shape. A positive offset fires triggers EARLIER.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from services.xcorr_core import (
    XCORR_BIN_MS,
    difficulty_score,
    eval_at_shift,
    xcorr_window_full,
)

logger = logging.getLogger(__name__)

# Geometry of the vote — the report's §5.4 method, fixed (the THRESHOLDS
# below it are the settings; the geometry is what those thresholds were
# measured on, so it is not a knob).
WINDOW_MS = 5000
STEP_MS = 5000
FIRST_START_MS = 5000
SEARCH_MS = 15000
VOTE_BIN_MS = 250
CLUSTER_TOL_MS = 300
MIN_DIFFICULTY = 0.15

SOURCE = "whole-song"

# Decision words. "corrected" is the only one that writes.
CORRECTED = "corrected"
AGREES = "agrees"
TOO_FEW_WINDOWS = "too_few_windows"
NO_CLEAR_MAJORITY = "no_clear_majority"
WEAK = "weak"
NOT_AHEAD = "not_ahead"
SMALL_MOVE = "small_move"
USER_VERIFIED = "user_verified"


@dataclass(frozen=True)
class WholeSongConfig:
    enabled: bool = True
    min_windows: int = 15
    min_vote_fraction: float = 0.70
    min_median_r: float = 0.80
    min_r_margin: float = 0.15
    min_move_ms: int = 750
    locked_every: int = 4

    @classmethod
    def from_settings(cls, settings) -> "WholeSongConfig":
        d = cls()
        return cls(
            enabled=bool(getattr(settings, "xcorr_whole_song_enabled", d.enabled)),
            min_windows=int(getattr(settings, "xcorr_whole_song_min_windows", d.min_windows)),
            min_vote_fraction=float(getattr(settings, "xcorr_whole_song_min_vote_fraction",
                                            d.min_vote_fraction)),
            min_median_r=float(getattr(settings, "xcorr_whole_song_min_r", d.min_median_r)),
            min_r_margin=float(getattr(settings, "xcorr_whole_song_min_r_margin", d.min_r_margin)),
            min_move_ms=int(getattr(settings, "xcorr_whole_song_min_move_ms", d.min_move_ms)),
            locked_every=int(getattr(settings, "xcorr_whole_song_locked_every", d.locked_every)),
        )


@dataclass
class VoteResult:
    """What the play's own audio says about where the song aligns."""
    n_windows: int
    winner_bin_ms: Optional[int]
    winner_offset_ms: Optional[int]   # median of the winning cluster's peaks
    wins: int
    vote_fraction: float
    median_r_winner: Optional[float]
    runner_up_bin_ms: Optional[int]
    runner_up_wins: int
    saved_offset_ms: int
    median_r_saved: Optional[float]
    n_saved_windows: int
    top_bins: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class Decision:
    action: str                     # one of the decision words above
    offset_ms: Optional[int]        # the offset to save (only for CORRECTED)
    reason: str                     # one plain sentence


def _counter_bin(offset_ms: int) -> int:
    return int(round(offset_ms / float(VOTE_BIN_MS))) * VOTE_BIN_MS


def whole_song_vote(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    *,
    saved_offset_ms: int,
) -> Optional[VoteResult]:
    """Run the vote. `stored_bands` are the four SQUARED bands
    ([total, low, mid, high]) the sweep already loaded; `frames` the play's
    live capture. Returns None when there are no frames at all.

    Pure: no I/O, no settings, no logging of decisions."""
    if not frames or len(frames) < 2 or len(stored_ts) < 2:
        return None
    stored_ts = np.asarray(stored_ts, dtype=float)
    low_sq = np.asarray(stored_bands[1], dtype=float)
    lo = float(frames[0][0])
    hi = float(frames[-1][0])

    peaks: list[tuple[float, int]] = []          # (r, offset_ms)
    saved_rs: list[float] = []
    end_stored = int(min(float(stored_ts[-1]), hi))
    for s in range(FIRST_START_MS, end_stored - WINDOW_MS, STEP_MS):
        e = s + WINDOW_MS
        bins = np.arange(s, e, XCORR_BIN_MS, dtype=float)
        if difficulty_score(np.interp(bins, stored_ts, low_sq), low_sq) < MIN_DIFFICULTY:
            continue
        # Only shifts whose live counterpart the play's frames actually cover.
        s_lo = max(-SEARCH_MS, int(lo - s))
        s_hi = min(SEARCH_MS, int(hi - e))
        if s_hi <= s_lo:
            continue
        land = xcorr_window_full(stored_ts, stored_bands, frames, s, e,
                                 search_lo_ms=s_lo, search_hi_ms=s_hi)
        if land is None or land.top1 is None:
            continue
        shift, r = land.top1
        peaks.append((float(r), -int(shift)))
        # The saved offset, scored on the same window when the play covers it.
        if lo <= s - saved_offset_ms and e - saved_offset_ms <= hi:
            r_saved = eval_at_shift(stored_ts, stored_bands, frames, s, e,
                                    -int(saved_offset_ms))
            if r_saved is not None:
                saved_rs.append(float(r_saved))

    votes = collections.Counter(_counter_bin(off) for _r, off in peaks)
    if not votes:
        return VoteResult(
            n_windows=0, winner_bin_ms=None, winner_offset_ms=None, wins=0,
            vote_fraction=0.0, median_r_winner=None, runner_up_bin_ms=None,
            runner_up_wins=0, saved_offset_ms=int(saved_offset_ms),
            median_r_saved=(float(np.median(saved_rs)) if saved_rs else None),
            n_saved_windows=len(saved_rs), top_bins=[],
        )
    # Most-voted bin; ties broken toward the higher summed r so the answer is
    # deterministic and favours the stronger evidence.
    def _bin_strength(b: int) -> tuple[int, float]:
        return votes[b], sum(r for r, o in peaks if _counter_bin(o) == b)
    winner_bin = max(votes, key=_bin_strength)
    near = [(r, o) for r, o in peaks if abs(o - winner_bin) <= CLUSTER_TOL_MS]
    far = collections.Counter(_counter_bin(o) for r, o in peaks
                              if abs(o - winner_bin) > CLUSTER_TOL_MS)
    runner_bin, runner_wins = (far.most_common(1)[0] if far else (None, 0))
    return VoteResult(
        n_windows=len(peaks),
        winner_bin_ms=int(winner_bin),
        winner_offset_ms=int(round(float(np.median([o for _r, o in near])) / XCORR_BIN_MS)
                             * XCORR_BIN_MS),
        wins=len(near),
        vote_fraction=len(near) / float(len(peaks)),
        median_r_winner=float(np.median([r for r, _o in near])),
        runner_up_bin_ms=(int(runner_bin) if runner_bin is not None else None),
        runner_up_wins=int(runner_wins),
        saved_offset_ms=int(saved_offset_ms),
        median_r_saved=(float(np.median(saved_rs)) if saved_rs else None),
        n_saved_windows=len(saved_rs),
        top_bins=[(int(b), int(n)) for b, n in votes.most_common(3)],
    )


def decide(vote: VoteResult, cfg: WholeSongConfig, *,
           verification: str = "auto_verified") -> Decision:
    """Whether this play's vote corrects the stored offset. Pure."""
    saved = int(vote.saved_offset_ms)
    if vote.n_windows < cfg.min_windows or vote.winner_offset_ms is None:
        return Decision(TOO_FEW_WINDOWS, None,
                        f"only {vote.n_windows} window(s) could be scored "
                        f"(need {cfg.min_windows}) — too little of the song to judge it")
    winner = int(vote.winner_offset_ms)
    if vote.vote_fraction < cfg.min_vote_fraction:
        return Decision(NO_CLEAR_MAJORITY, None,
                        f"no clear majority: {winner:+d} ms won {vote.wins}/{vote.n_windows} "
                        f"windows ({vote.vote_fraction:.0%} < {cfg.min_vote_fraction:.0%})"
                        + (f", runner-up {vote.runner_up_bin_ms:+d} ms with {vote.runner_up_wins}"
                           if vote.runner_up_bin_ms is not None else ""))
    if abs(winner - saved) < cfg.min_move_ms:
        return Decision(AGREES if abs(winner - saved) <= CLUSTER_TOL_MS else SMALL_MOVE, None,
                        f"the whole song agrees with the saved {saved:+d} ms "
                        f"(vote {winner:+d} ms, {vote.wins}/{vote.n_windows} windows)"
                        if abs(winner - saved) <= CLUSTER_TOL_MS else
                        f"vote {winner:+d} ms is within {cfg.min_move_ms} ms of the saved "
                        f"{saved:+d} ms — left to the per-play sweep")
    r_win = float(vote.median_r_winner or 0.0)
    if r_win < cfg.min_median_r:
        return Decision(WEAK, None,
                        f"{winner:+d} ms won {vote.wins}/{vote.n_windows} windows but its "
                        f"median r {r_win:.2f} is below {cfg.min_median_r:.2f}")
    r_saved = vote.median_r_saved
    if r_saved is not None and r_win - r_saved < cfg.min_r_margin:
        return Decision(NOT_AHEAD, None,
                        f"{winner:+d} ms (r {r_win:.2f}) is not clearly ahead of the saved "
                        f"{saved:+d} ms (r {r_saved:.2f}; need +{cfg.min_r_margin:.2f})")
    summary = (f"{saved:+d} → {winner:+d} ms: {vote.wins}/{vote.n_windows} windows at median "
               f"r {r_win:.2f}" + (f" vs {r_saved:.2f} at the saved offset"
                                    if r_saved is not None else ""))
    if verification == "user_verified":
        return Decision(USER_VERIFIED, None,
                        f"would correct {summary}, but the offset is user-verified — not saved")
    return Decision(CORRECTED, winner, summary)


# ── Timeline continuity (a seek or a pause is not a new offset) ──────────────
# The capture clock runs from the play's fixed song start, so a seek or a
# pause mid-song shifts every later frame against the song by the jump — and
# a whole-song vote over those frames would read the jump as the song's
# offset (a 10 s scrub at 20 s in would "win" by a landslide at offset+10 s).
# The sweep feeds `TimelineWatch` Spotify's own progress beside the capture
# clock once a second; the vote only ever sees the frames BEFORE the first
# break (seek, pause, stop, or the song changing).
TIMELINE_TOL_MS = 2000      # Spotify poll jitter is a few hundred ms
TIMELINE_SETTLE_MS = 3000   # take the baseline once the song has settled
TIMELINE_GUARD_MS = 1000    # frames this close before the break are dropped too


class TimelineWatch:
    """Where the play's capture stopped describing one continuous run of
    the song. Pure; fed by the sweep's frame loop."""

    def __init__(self) -> None:
        self.baseline_ms: Optional[float] = None
        self.break_ms: Optional[int] = None
        self.reason: Optional[str] = None

    def note(self, frame_ms: int, progress_ms: Optional[float], *,
             same_song_playing: bool) -> None:
        if self.break_ms is not None:
            return
        if not same_song_playing or progress_ms is None:
            self.break_ms, self.reason = int(frame_ms), "stopped or changed song"
            return
        drift = float(progress_ms) - float(frame_ms)
        if self.baseline_ms is None:
            if frame_ms >= TIMELINE_SETTLE_MS:
                self.baseline_ms = drift
            return
        if abs(drift - self.baseline_ms) > TIMELINE_TOL_MS:
            self.break_ms = int(frame_ms)
            self.reason = f"seek or pause ({drift - self.baseline_ms:+.0f} ms jump)"

    def trim(self, frames: list) -> list:
        if self.break_ms is None:
            return list(frames)
        cut = self.break_ms - TIMELINE_GUARD_MS
        return [f for f in frames if f[0] < cut]


def should_check(*, locked: bool, locked_plays_since_check: int,
                 cfg: WholeSongConfig) -> bool:
    """Cadence: every play that did not hard-lock; every `locked_every`-th
    play that did (0 = never after a hard lock). `locked_plays_since_check`
    counts THIS play when it locked."""
    if not cfg.enabled:
        return False
    if not locked:
        return True
    return cfg.locked_every > 0 and locked_plays_since_check >= cfg.locked_every


# ── The settings (one definition of their names, kinds and legal ranges) ──────
# Served and validated by routers/lock_history_router.py (Timing page) and
# reached by Sonic through that same route (spectra/services/lock_console.py).

class SettingRejected(ValueError):
    """A settings patch named an unknown key or an out-of-range value."""


SETTINGS: dict[str, dict] = {
    "xcorr_whole_song_enabled": {
        "kind": "bool",
        "label": "Whole-song check on",
        "help": "Check each play's own audio against the whole song after it "
                "ends, and correct a stored offset that is clearly wrong."},
    "xcorr_whole_song_min_windows": {
        "kind": "int", "min": 5, "max": 60,
        "label": "Minimum windows",
        "help": "How many 5-second stretches of the song must be scored before "
                "the check may judge it (15 = about 75 s of the song)."},
    "xcorr_whole_song_min_vote_fraction": {
        "kind": "float", "min": 0.5, "max": 1.0,
        "label": "Majority needed",
        "help": "Share of the scored stretches one offset must win (0.70 = 70%)."},
    "xcorr_whole_song_min_r": {
        "kind": "float", "min": 0.5, "max": 0.99,
        "label": "Minimum match strength",
        "help": "Median correlation r the winning offset must reach (0-1)."},
    "xcorr_whole_song_min_r_margin": {
        "kind": "float", "min": 0.0, "max": 0.6,
        "label": "Lead over the saved offset",
        "help": "How much higher the winner's median r must be than the saved "
                "offset's before the saved offset is replaced."},
    "xcorr_whole_song_min_move_ms": {
        "kind": "int", "min": 300, "max": 5000,
        "label": "Smallest correction (ms)",
        "help": "Differences smaller than this are left to the per-play sweep."},
    "xcorr_whole_song_locked_every": {
        "kind": "int", "min": 0, "max": 50,
        "label": "Also check every Nth locked play",
        "help": "Plays that did not lock are always checked; this also checks "
                "every Nth play that did (0 = never after a lock)."},
    "xcorr_withhold_resave_min_repeats": {
        "kind": "int", "min": 0, "max": 20,
        "label": "Withhold a re-save after N stronger finds",
        "help": "When this many windows found one other offset beating the one "
                "about to be saved, don't re-save it (0 = off)."},
}


def current_settings(settings) -> dict:
    """The live values (config.Settings carries every key in SETTINGS)."""
    return {k: getattr(settings, k) for k in SETTINGS}


def validate_patch(patch: dict) -> dict:
    """Coerce + range-check a partial settings patch. Raises SettingRejected
    naming the first bad key; returns the coerced values otherwise."""
    if not isinstance(patch, dict) or not patch:
        raise SettingRejected("send at least one setting to change")
    out: dict = {}
    for key, value in patch.items():
        spec = SETTINGS.get(key)
        if spec is None:
            raise SettingRejected(f"unknown setting {key!r} — known: {', '.join(SETTINGS)}")
        kind = spec["kind"]
        if kind == "bool":
            if not isinstance(value, bool):
                raise SettingRejected(f"{key} must be true or false")
            out[key] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingRejected(f"{key} must be a number")
        if kind == "int":
            if float(value) != int(value):
                raise SettingRejected(f"{key} must be a whole number")
            value = int(value)
        else:
            value = float(value)
        if not (spec["min"] <= value <= spec["max"]):
            raise SettingRejected(f"{key} must be between {spec['min']} and {spec['max']} "
                                  f"(got {value})")
        out[key] = value
    return out


# ── The visible log ───────────────────────────────────────────────────────────

_STORE_PATH = Path(__file__).resolve().parent.parent / "storage" / "whole_song_checks.json"
_CAP = 300
_lock = threading.Lock()


def _read() -> list[dict]:
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as exc:                       # noqa: BLE001
        logger.warning("whole-song check log unreadable (%s) — starting fresh", exc)
        return []


def record(*, uri: str, title: str, artist: str, locked: bool,
           vote: Optional[VoteResult], decision: Decision,
           saved: Optional[bool] = None) -> dict:
    """Append one check to the bounded log (most recent first). `saved` is
    whether a correction was actually written (None when nothing was asked)."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "uri": uri,
        "title": title,
        "artist": artist,
        "play_locked": bool(locked),
        "action": decision.action,
        "reason": decision.reason,
        "old_offset_ms": vote.saved_offset_ms if vote else None,
        "new_offset_ms": decision.offset_ms,
        "vote_offset_ms": vote.winner_offset_ms if vote else None,
        "wins": vote.wins if vote else 0,
        "n_windows": vote.n_windows if vote else 0,
        "median_r": (round(vote.median_r_winner, 3)
                     if vote and vote.median_r_winner is not None else None),
        "median_r_saved": (round(vote.median_r_saved, 3)
                           if vote and vote.median_r_saved is not None else None),
        "runner_up_offset_ms": vote.runner_up_bin_ms if vote else None,
        "runner_up_wins": vote.runner_up_wins if vote else 0,
        "saved": saved,
    }
    with _lock:
        log = _read()
        log.insert(0, entry)
        del log[_CAP:]
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(log, indent=1), encoding="utf-8")
        os.replace(tmp, _STORE_PATH)
    return entry


def recent(limit: int = 50, *, corrections_only: bool = False) -> list[dict]:
    with _lock:
        log = _read()
    if corrections_only:
        log = [e for e in log if e.get("action") == CORRECTED]
    return log[:max(0, int(limit))]


def vote_as_dict(vote: Optional[VoteResult]) -> Optional[dict]:
    return asdict(vote) if vote is not None else None
