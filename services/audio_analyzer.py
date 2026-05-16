"""
SpotFX — Audio Shape recorder and Music Mark detector.

AudioShapeRecorder:
  Consumes AudioFrame objects from AudioCaptureStream and accumulates them
  into rolling arrays, then saves a .npz file when recording is complete.

MusicMarkDetector:
  Analyses the accumulated data to detect music marks (bass drops, power
  shifts, etc.).  Can run post-capture or incrementally.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from config import AUDIO_SHAPES_DIR, settings
from models.audio_shape import AudioShapeMeta, MusicMark, MarkType
from api.audio_capture import AudioFrame

logger = logging.getLogger(__name__)


class AudioShapeRecorder:
    """
    Accumulates AudioFrame objects and saves to .npz + sidecar JSON.
    """

    def __init__(self, spotify_uri: str, title: str, artist: str, duration_ms: int, genres: list[str] | None = None):
        self.meta = AudioShapeMeta(
            spotify_uri=spotify_uri,
            title=title,
            artist=artist,
            duration_ms=duration_ms,
            sample_interval_ms=int(settings.audio_chunk_size / settings.audio_sample_rate * 1000),
            npz_file=self._npz_name(artist, title),
            genres=genres or [],
        )
        self._timestamps: list[int] = []
        self._rms_total: list[float] = []
        self._rms_low: list[float] = []
        self._rms_mid: list[float] = []
        self._rms_high: list[float] = []

    @staticmethod
    def _npz_name(artist: str, title: str) -> str:
        safe = lambda s: "".join(c for c in s if c not in r'\/:*?"<>|')
        return f"{safe(artist)} - {safe(title)}.npz"

    def ingest(self, frame: AudioFrame) -> None:
        # Per-ingest gap diagnostic: when an inter-sample gap exceeds half the
        # discard threshold, log it immediately with the song-position so we
        # can correlate gaps to specific moments (track transitions, CPU
        # spikes, etc.) without waiting for the post-capture discard.
        if self._timestamps:
            from config import settings as _s
            gap = frame.timestamp_ms - self._timestamps[-1]
            warn_at = max(60, int(_s.audio_max_gap_ms * 0.5))
            if gap >= warn_at:
                logger.warning(
                    "Capture gap %dms at song-time=%dms in %s — %s",
                    gap, frame.timestamp_ms, self.meta.npz_file,
                    "WILL DISCARD" if gap > _s.audio_max_gap_ms else "still under limit",
                )
        self._timestamps.append(frame.timestamp_ms)
        self._rms_total.append(frame.rms_total)
        self._rms_low.append(frame.rms_low)
        self._rms_mid.append(frame.rms_mid)
        self._rms_high.append(frame.rms_high)

    def trim_after(self, boundary_ms: int) -> int:
        """Drop frames whose song-relative timestamp_ms > boundary_ms.

        Used by audio_shape_service to trim the previous song's tail at the
        acoustic track boundary. Returns the number of frames dropped.
        """
        if not self._timestamps:
            return 0
        keep = 0
        for t in self._timestamps:
            if t > boundary_ms:
                break
            keep += 1
        dropped = len(self._timestamps) - keep
        if dropped <= 0:
            return 0
        del self._timestamps[keep:]
        del self._rms_total[keep:]
        del self._rms_low[keep:]
        del self._rms_mid[keep:]
        del self._rms_high[keep:]
        return dropped

    def save(self) -> Path:
        """Compute rolling averages and persist to disk."""
        AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
        npz_path = AUDIO_SHAPES_DIR / self.meta.npz_file
        meta_path = npz_path.with_suffix(".json")

        ts = np.array(self._timestamps, dtype=np.int32)
        rms_t = np.array(self._rms_total, dtype=np.float32)
        rms_l = np.array(self._rms_low, dtype=np.float32)
        rms_m = np.array(self._rms_mid, dtype=np.float32)
        rms_h = np.array(self._rms_high, dtype=np.float32)

        sr_ms = self.meta.sample_interval_ms or 23
        win_1s = max(1, int(1000 / sr_ms))
        win_5s = max(1, int(5000 / sr_ms))
        avg_1s = _rolling_mean(rms_t, win_1s)
        avg_5s = _rolling_mean(rms_t, win_5s)

        # Pre-compute signed-square bands (`x · |x|`) so xcorr at session
        # start doesn't have to redo them on every play. auto_offset_service
        # falls back to live computation when these keys are missing (legacy
        # shapes), so this is purely a cache.
        rms_t_sq = (rms_t * np.abs(rms_t)).astype(np.float32)
        rms_l_sq = (rms_l * np.abs(rms_l)).astype(np.float32)
        rms_m_sq = (rms_m * np.abs(rms_m)).astype(np.float32)
        rms_h_sq = (rms_h * np.abs(rms_h)).astype(np.float32)

        np.savez_compressed(
            npz_path,
            timestamps_ms=ts,
            rms_total=rms_t,
            rms_low=rms_l,
            rms_mid=rms_m,
            rms_high=rms_h,
            avg_rms_1s=avg_1s,
            avg_rms_5s=avg_5s,
            rms_total_sq=rms_t_sq,
            rms_low_sq=rms_l_sq,
            rms_mid_sq=rms_m_sq,
            rms_high_sq=rms_h_sq,
        )

        self.meta.capture_complete = True
        meta_path.write_text(self.meta.model_dump_json(indent=2), encoding="utf-8")
        # Keep the URI index in sync so the next load_audio_shape_meta()
        # hits the cached path without rescanning the directory.
        if self.meta.spotify_uri:
            _audio_shape_index[self.meta.spotify_uri] = meta_path.stem
        logger.info("Audio shape saved: %s", npz_path.name)
        return npz_path


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Simple causal rolling mean (O(n) via cumsum)."""
    out = np.empty_like(arr)
    cumsum = np.cumsum(np.insert(arr, 0, 0))
    for i in range(len(arr)):
        start = max(0, i - window + 1)
        out[i] = (cumsum[i + 1] - cumsum[start]) / (i - start + 1)
    return out


def _rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    """Causal rolling maximum (O(n·w); fine for one-time post-capture use)."""
    out = np.empty_like(arr)
    for i in range(len(arr)):
        out[i] = np.max(arr[max(0, i - window + 1):i + 1])
    return out


# ── Music Mark Detector ───────────────────────────────────────────────────────

class MusicMarkDetector:
    """
    Analyses AudioShapeMeta data to detect music marks.
    All thresholds are heuristic and tunable via config settings.
    """

    def detect(self, npz_path: Path) -> list[MusicMark]:
        """Load .npz and return detected MusicMark list."""
        data = np.load(npz_path)
        ts    = data["timestamps_ms"].astype(int)
        rms_t = data["rms_total"]
        rms_l = data["rms_low"]
        avg_1s = data["avg_rms_1s"]
        avg_5s = data["avg_rms_5s"]

        # Sample rate in ms (median inter-sample gap)
        sr_ms = max(1, int(np.median(np.diff(ts)))) if len(ts) > 1 else 11

        # 300ms fast average — tighter than avg_1s for quicker crossing detection
        win_300ms = max(1, int(300 / sr_ms))
        avg_300ms = _rolling_mean(rms_t, win_300ms)

        # Local 20-second rolling mean for quiet detection
        win_20s = max(1, int(settings.quiet_baseline_window_s * 1000 / sr_ms))
        avg_20s = _rolling_mean(rms_t, win_20s)

        marks: list[MusicMark] = []
        marks += self._detect_power_shifts(ts, avg_300ms, avg_1s, avg_5s)
        marks += self._detect_bass_pattern(ts, rms_l, sr_ms)
        marks += self._detect_quiet(ts, avg_1s, rms_l, avg_20s, sr_ms)
        marks += self._detect_bass_drops(ts, rms_l, rms_t, avg_1s, avg_5s, sr_ms)
        marks.sort(key=lambda m: m.timestamp_ms)
        logger.info(
            "Mark detection complete: %d total — power=%d bass=%d quiet=%d drops=%d",
            len(marks),
            sum(1 for m in marks if m.mark_type in ("power_up", "power_down")),
            sum(1 for m in marks if m.mark_type in ("bass_start", "bass_end")),
            sum(1 for m in marks if m.mark_type == "quiet"),
            sum(1 for m in marks if m.mark_type == "bass_drop"),
        )
        return marks

    def _detect_power_shifts(self, ts, avg_fast, avg_1s, avg_5s) -> list[MusicMark]:
        """Large upward or downward shifts vs the 5s baseline.

        UP   uses avg_300ms / avg_5s — fast response, catches leading edge of rises.
        DOWN uses avg_1s   / avg_5s — smoother; avoids false PD from ratio inversion
             (after a fast rise avg_5s slowly catches up and would briefly push a fast
             ratio below the threshold, firing a spurious power_down).
        2-second cooldown between marks of the same type.
        """
        marks = []
        ratio_up   = avg_fast / (avg_5s + 1e-9)
        ratio_down = avg_1s   / (avg_5s + 1e-9)
        last_up_ts   = -2000
        last_down_ts = -2000
        for i in range(1, len(ratio_up)):
            t = int(ts[i])
            if ratio_up[i] > 1.4 and ratio_up[i - 1] <= 1.4 and t - last_up_ts >= 2000:
                marks.append(MusicMark(mark_type="power_up", timestamp_ms=t, confidence=0.7))
                last_up_ts = t
            elif ratio_down[i] < 0.55 and ratio_down[i - 1] >= 0.55 and t - last_down_ts >= 2000:
                marks.append(MusicMark(mark_type="power_down", timestamp_ms=t, confidence=0.7))
                last_down_ts = t
        logger.debug("power_shifts: max_ratio_up=%.2f max_ratio_down=%.2f marks=%d",
                     float(np.max(ratio_up)), float(np.max(ratio_down)), len(marks))
        return marks

    def _detect_bass_pattern(self, ts, rms_l, sr_ms) -> list[MusicMark]:
        """Detect sustained rhythmic bass starts and ends — two-stage detection.

        Stage 1 (SLOW signal, 500ms smoother): drives the hysteresis state machine.
          A 500ms window bridges inter-beat gaps, so state doesn't toggle beat-to-beat.
          Enter bass state: slow_smooth >= p45
          Exit  bass state: slow_smooth <  p25

        Stage 2 (FAST signal, 50ms smoother): finds the actual leading edge.
          When slow confirms a bass_start transition, we look back up to 500ms to find
          the earliest sample where the fast signal was above p45 — i.e., the first beat.
          This gives a stamp ~250–400ms earlier than the slow confirmation point.

        Confirmation windows: 500ms for start, 1.5s for end.
        Stamp is at the FAST leading edge for starts, at slow-transition-onset for ends.
        3-second cooldown between marks of the same type.
        """
        pos = rms_l[rms_l > 0]
        if not len(pos):
            return []

        win_50  = max(1, int(50  / sr_ms))
        win_500 = max(1, int(500 / sr_ms))
        fast = _rolling_mean(rms_l, win_50)   # probe: resolves individual beats
        slow = _rolling_mean(rms_l, win_500)  # confirm: stable across beat gaps

        p45 = float(np.percentile(pos, 45))
        p25 = float(np.percentile(pos, 25))

        # Binary state driven by SLOW signal — avoids inter-beat oscillation
        state = np.zeros(len(rms_l), dtype=bool)
        in_b = False
        for i in range(len(slow)):
            if not in_b and slow[i] >= p45:
                in_b = True
            elif in_b and slow[i] < p25:
                in_b = False
            state[i] = in_b

        min_end  = max(1, int(1500 / sr_ms))   # 1.5 s sustained before bass_end
        cooldown = 3000

        marks = []
        last_start_ts = -cooldown
        last_end_ts   = -cooldown
        confirmed = False
        pending: tuple | None = None   # (target: bool, since_index: int)

        for i in range(len(state)):
            if pending is not None:
                target, since = pending
                if state[i] != target:
                    pending = None      # transient — transition canceled
                elif (i - since + 1) >= (win_500 if target else min_end):
                    if target:
                        # Look back in FAST signal to find the first beat above p45
                        look_start = max(0, since - win_500)
                        onset = since
                        for j in range(look_start, since + 1):
                            if fast[j] >= p45:
                                onset = j
                                break
                        t = int(ts[onset])
                        if t - last_start_ts >= cooldown:
                            marks.append(MusicMark(mark_type="bass_start", timestamp_ms=t, confidence=0.65))
                            last_start_ts = t
                    else:
                        t = int(ts[since])
                        if t - last_end_ts >= cooldown:
                            marks.append(MusicMark(mark_type="bass_end", timestamp_ms=t, confidence=0.65))
                            last_end_ts = t
                    confirmed = target
                    pending = None
            else:
                if state[i] != confirmed:
                    pending = (state[i], i)

        logger.debug("bass_pattern: p45=%.4f p25=%.4f marks=%d", p45, p25, len(marks))
        return marks

    def _detect_quiet(self, ts, avg_1s, rms_l, avg_20s, sr_ms) -> list[MusicMark]:
        """Mark the falling edge of a prolonged quiet zone.

        Quiet = avg_1s drops below 30% of the 20s rolling mean AND bass is low.
        Must be sustained for quiet_min_duration_ms before stamping.
        Mark is placed at the falling edge (onset of quiet, not when confirmed).
        5-second cooldown between marks.
        """
        min_samples = max(1, int(settings.quiet_min_duration_ms / sr_ms))
        cooldown_ms = 5000

        quiet_mask = avg_1s < (avg_20s * 0.60)

        marks = []
        last_mark_ts = -cooldown_ms
        in_quiet = False
        quiet_start_i = 0

        for i in range(len(quiet_mask)):
            if not in_quiet and quiet_mask[i]:
                quiet_start_i = i
                in_quiet = True
            elif in_quiet and not quiet_mask[i]:
                in_quiet = False
            # Once quiet has been sustained long enough, stamp the falling edge
            if in_quiet and (i - quiet_start_i) == min_samples:
                t = int(ts[quiet_start_i])
                if t - last_mark_ts >= cooldown_ms:
                    marks.append(MusicMark(mark_type="quiet", timestamp_ms=t, confidence=0.70))
                    last_mark_ts = t

        min_ratio = float(np.min(avg_1s / (avg_20s + 1e-9)))
        logger.debug("quiet: min_ratio=%.3f threshold=0.60 marks=%d", min_ratio, len(marks))
        return marks

    def _detect_bass_drops(self, ts, rms_l, rms_t, avg_1s, avg_5s, sr_ms) -> list[MusicMark]:
        """Detect bass drop events via 3-phase pattern: buildup → lull → impact.

        All three phases must be satisfied (bass-focused):
          Impact:  rms_low / song_bass_avg > 1.4 AND previous frame rms_low was low
          Lull:    mean(rms_low) in [500ms–6s] before impact < bass 30th percentile
                   (avoids false negatives when vocals raise total RMS during the lull)
          Buildup: mean(rms_low) in [6–15s] before impact > 30th percentile of rms_low
        5-second cooldown between drops.
        """
        lull_lo  = max(1, int(500  / sr_ms))
        lull_hi  = max(1, int(6000 / sr_ms))   # extended from 4s to catch longer buildups
        build_lo = lull_hi
        build_hi = max(1, int(15000 / sr_ms))

        bass_p30  = float(np.percentile(rms_l[rms_l > 0], 30)) if (rms_l > 0).any() else 0.0
        song_avg_l = float(np.mean(rms_l[rms_l > 0])) if (rms_l > 0).any() else 1e-9
        bass_impact = rms_l / (song_avg_l + 1e-9)

        marks = []
        last_drop_ts = -5000

        for i in range(build_hi, len(ts)):
            # Impact: bass spikes above song average; previous frame was clearly below
            if bass_impact[i] < 1.2 or bass_impact[i - 1] >= 0.9:
                continue

            # Lull: low bass in pre-impact window (bass-specific, immune to vocal energy)
            ls, le = max(0, i - lull_hi), max(0, i - lull_lo)
            if le <= ls or float(np.mean(rms_l[ls:le])) > bass_p30:
                continue

            # Buildup: window before lull must have had meaningful bass activity
            bs, be = max(0, i - build_hi), max(0, i - build_lo)
            if be <= bs or float(np.mean(rms_l[bs:be])) < bass_p30:
                continue

            t = int(ts[i])
            if t - last_drop_ts >= 5000:
                marks.append(MusicMark(mark_type="bass_drop", timestamp_ms=t, confidence=0.75))
                last_drop_ts = t

        logger.debug("bass_drops: max_bass_impact=%.2f marks=%d", float(np.max(bass_impact)), len(marks))
        return marks


def _build_shape_index() -> None:
    """Scan every audio_shape sidecar JSON once and populate the URI →
    filename index. Re-run on miss so newly-added files are picked up
    without rebooting. The previous implementation globbed-and-parsed all
    437+ files on every call (called once per Spotify poll AND once per
    xcorr window), which was the dominant CPU cost of the worker process
    (json.decoder.raw_decode at 85% in py-spy)."""
    _audio_shape_index.clear()
    for path in AUDIO_SHAPES_DIR.glob("*.json"):
        # `*.json` ALSO matches `*.librosa.json` — those have the same
        # spotify_uri field and would silently overwrite the audio-shape
        # index entry, causing load_audio_shape_meta to point at a librosa
        # file and fail to parse as AudioShapeMeta (returning None and
        # spuriously triggering a fresh capture for songs that already have
        # complete shapes). Skip them.
        if path.name.endswith(".librosa.json"):
            continue
        try:
            # We only need the spotify_uri field — but json.loads parses
            # the whole document. There's no compelling-enough win to
            # parse-by-prefix here since the index is built once per session.
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri = data.get("spotify_uri") or ""
        if uri:
            _audio_shape_index[uri] = path.stem
    _audio_shape_index_built[0] = True
    logger.info("Audio shape index built: %d URIs", len(_audio_shape_index))


# Lookup index for audio shape metadata. Populated lazily; mutated by
# AudioShapeRecorder.save() and the *_needs_recapture helpers below so
# subsequent lookups stay O(1). Mirror of the profile_manager pattern.
_audio_shape_index: dict[str, str] = {}
_audio_shape_index_built: list[bool] = [False]


def load_audio_shape_meta(spotify_uri: str) -> Optional[AudioShapeMeta]:
    """Find and load the sidecar JSON for a given Spotify URI."""
    if not _audio_shape_index_built[0]:
        _build_shape_index()
    filename = _audio_shape_index.get(spotify_uri)
    if filename is None:
        # Maybe a new shape file was dropped in — rescan once.
        _build_shape_index()
        filename = _audio_shape_index.get(spotify_uri)
        if filename is None:
            return None
    path = AUDIO_SHAPES_DIR / f"{filename}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AudioShapeMeta(**data)
    except Exception:
        return None


def flag_needs_recapture(spotify_uri: str, reason: str) -> bool:
    """Mark an audio shape as suggested-for-recapture. Called by runtime
    detectors (anti-corr persistence, repeated low Q, etc.) to record that
    this captured shape is no longer aligning reliably and should be
    re-recorded. An external script scans for shapes with
    `needs_recapture=True` and triggers fresh captures.

    `reason` is a short tag, e.g. "anti_corr_persistent",
    "low_q_streak", "no_uscore_windows", "section_twin_dominant".

    Returns True on success. Idempotent: if already flagged, only
    `needs_recapture_flag_count` and `needs_recapture_flagged_at` update.
    """
    import datetime
    if not _audio_shape_index_built[0]:
        _build_shape_index()
    filename = _audio_shape_index.get(spotify_uri)
    if filename is None:
        _build_shape_index()
        filename = _audio_shape_index.get(spotify_uri)
        if filename is None:
            return False
    path = AUDIO_SHAPES_DIR / f"{filename}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    data["needs_recapture"] = True
    data["needs_recapture_reason"] = reason
    data["needs_recapture_flagged_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    data["needs_recapture_flag_count"] = int(data.get("needs_recapture_flag_count") or 0) + 1
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def clear_needs_recapture(spotify_uri: str) -> bool:
    """Reset the recapture-suggested flag. Called by audio_shape_service after
    a fresh capture saves over the same URI. Returns True on success."""
    if not _audio_shape_index_built[0]:
        _build_shape_index()
    filename = _audio_shape_index.get(spotify_uri)
    if filename is None:
        _build_shape_index()
        filename = _audio_shape_index.get(spotify_uri)
        if filename is None:
            return False
    path = AUDIO_SHAPES_DIR / f"{filename}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    data["needs_recapture"] = False
    data["needs_recapture_reason"] = ""
    data["needs_recapture_flagged_at"] = ""
    # keep flag_count as a historical record so the script can prioritize chronic offenders
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def _librosa_path_for_uri(spotify_uri: str):
    """Return the Path to the .librosa.json file for a URI, or None if not found."""
    meta = load_audio_shape_meta(spotify_uri)
    if meta is None:
        return None
    npz_path = AUDIO_SHAPES_DIR / meta.npz_file
    base = npz_path.with_suffix("")
    path = base.parent / (base.name + ".librosa.json")
    return path if path.exists() else None


def load_beats_for_uri(spotify_uri: str) -> list | None:
    """
    Return the beats list from the cached librosa JSON for a given Spotify URI.
    Each beat is a dict with at least an 'ms' key.
    Returns None if the librosa file doesn't exist or has no beats.
    """
    path = _librosa_path_for_uri(spotify_uri)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        beats = data.get("beats", [])
        return beats if beats else None
    except Exception:
        return None


def load_tempo_for_uri(spotify_uri: str) -> float | None:
    """Return tempo_bpm from the librosa JSON for a URI, or None if unavailable."""
    path = _librosa_path_for_uri(spotify_uri)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("tempo_bpm") or None
    except Exception:
        return None
