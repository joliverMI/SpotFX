"""
SpotFX — Post-recapture self-correction.

When a song is force-recaptured, the new capture's song-time frame can be
shifted relative to the old one: each capture derives its own song_start
estimate (poll jitter, acoustic-boundary vs Spotify-hint path, latency
compensation changes), so the same musical moment gets a different
timestamp. Every piece of timestamped data learned against the OLD frame —
hand-placed and AI triggers, per-Set-List xcorr offsets — would then fire
early or late by that shift.

At atomic-save commit time the old capture's files still exist as *.bak,
so the shift is measured directly instead of guessed: multi-band NCC
(xcorr_core.xcorr_window_full) of the old npz band signals against the new
capture's, probed at three windows across the song. When the windows agree
with strong correlation, everything timestamped is migrated by the measured
shift Δ:

  - SongProfile.triggers and setlist_triggers          → t + Δ
  - pending AI suggestion sets                         → t + Δ
  - meta.timestamp_offset_ms / offset_history          → offset + Δ
  - meta.setlist_offsets (locks, history, cut-in)      → offset + Δ
  - analyzed-trigger cache                             → invalidated
                                                         (regenerates from
                                                         the new librosa)

Sign convention: Δ = new_label − old_label of the same musical moment;
positive Δ means the music sits LATER in the new capture. xcorr_window_full
templates on the stored (old) signal and searches the live (new) one, so its
best_shift ("live late by X") equals Δ directly. The engine's fire clock is
`effective_now = now_ms + offset`, so an offset learned against the old
frame stays locked to the same music as `offset + Δ`.

All functions here are synchronous file/numpy work — call the orchestrator
via run_in_executor from async code.
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from config import AUDIO_SHAPES_DIR, settings
from services.xcorr_core import signed_square, xcorr_window_full

logger = logging.getLogger(__name__)

_BAND_KEYS = ("rms_total", "rms_low", "rms_mid", "rms_high")


@dataclass
class ShiftMeasurement:
    shift_ms: int
    r: float                              # mean r of the agreeing windows
    window_results: list[tuple[int, float]]  # per-window (shift_ms, r)


def _monotonic_view(ts: np.ndarray, bands: list[np.ndarray]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Old captures can contain a non-monotonic seam: ring-buffer pre-roll
    frames whose labels overlap the live frames appended after them. The
    live frames carry the trustworthy labels, so for any overlapping label
    region keep the LAST-written sample — scan from the end keeping strictly
    decreasing timestamps."""
    keep = np.zeros(len(ts), dtype=bool)
    hi = np.inf
    for i in range(len(ts) - 1, -1, -1):
        if ts[i] < hi:
            keep[i] = True
            hi = ts[i]
    return ts[keep], [b[keep] for b in bands]


def _load_npz_signals(path: Path) -> Optional[tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]]:
    """Return (ts, raw_bands, squared_bands) from a shape npz, monotonic-clean.
    squared bands come from the cached *_sq keys when present (legacy shapes
    recompute)."""
    try:
        npz = np.load(path)
        ts = npz["timestamps_ms"].astype(np.float64)
        raw = [npz[k].astype(np.float64) for k in _BAND_KEYS]
    except Exception as exc:
        logger.warning("Realign: could not load %s: %s", path.name, exc)
        return None
    if len(ts) < 50:
        return None
    sq = []
    for i, k in enumerate(_BAND_KEYS):
        key = k + "_sq"
        sq.append(npz[key].astype(np.float64) if key in npz.files else signed_square(raw[i]))
    ts, all_bands = _monotonic_view(ts, raw + sq)
    return ts, all_bands[:4], all_bands[4:]


def measure_capture_shift(old_npz: Path, new_npz: Path) -> Optional[ShiftMeasurement]:
    """Measure Δ = new-capture label − old-capture label of the same music.

    Templates three windows of the OLD signals at 25/50/75% of the shared
    span and NCC-searches each against the NEW signals over
    ±realign_search_ms. Returns None when the windows disagree or correlate
    weakly (captures of different edits/versions, broken shapes)."""
    old = _load_npz_signals(old_npz)
    new = _load_npz_signals(new_npz)
    if old is None or new is None:
        return None
    old_ts, _old_raw, old_sq = old
    new_ts, new_raw, _new_sq = new

    search_ms = int(settings.realign_search_ms)
    frames = list(zip(new_ts, new_raw[0], new_raw[1], new_raw[2], new_raw[3]))

    # Probe windows must stay where BOTH captures have data across the
    # whole search range, else the zero-padded edges poison the NCC.
    lo = max(old_ts[0], new_ts[0]) + search_ms
    hi = min(old_ts[-1], new_ts[-1]) - search_ms
    window_ms = int(settings.realign_window_s * 1000)
    results: list[tuple[int, float]] = []

    if hi - lo >= window_ms * 2:
        centers = [lo + (hi - lo) * f for f in (0.25, 0.5, 0.75)]
        spans = [(int(c - window_ms / 2), int(c + window_ms / 2)) for c in centers]
    elif hi - lo >= 8000:
        spans = [(int(lo), int(hi))]   # short song: one wide probe
    else:
        logger.info("Realign: overlap too short to measure (%.0fms)", hi - lo)
        return None

    for ws, we in spans:
        try:
            land = xcorr_window_full(old_ts, old_sq, frames, ws, we, search_ms=search_ms)
        except Exception as exc:
            logger.warning("Realign: window %d-%d failed: %s", ws, we, exc)
            continue
        if land is None or land.top1 is None:
            continue
        shift, r = land.top1
        results.append((int(shift), float(r)))

    min_r = float(settings.realign_min_r)
    good = [(s, r) for s, r in results if r >= min_r]
    if len(spans) == 1:
        good = [(s, r) for s, r in good if r >= float(settings.realign_single_window_min_r)]
        if not good:
            logger.info("Realign: single-window probe below threshold (%s)", results)
            return None
        return ShiftMeasurement(shift_ms=good[0][0], r=good[0][1], window_results=results)

    if len(good) < 2:
        logger.info("Realign: <2 confident windows (%s)", results)
        return None
    shifts = sorted(s for s, _ in good)
    if shifts[-1] - shifts[0] > int(settings.realign_agree_ms):
        logger.info("Realign: windows disagree (%s)", results)
        return None
    shift = int(round(float(np.median(shifts))))
    r = float(np.mean([r for _, r in good]))
    return ShiftMeasurement(shift_ms=shift, r=r, window_results=results)


# ── Migration helpers ─────────────────────────────────────────────────────────

def shift_offset_fields(sidecar_data: dict, old_meta: dict, shift_ms: int) -> dict:
    """Copy the learned-offset state from the old sidecar into the new one,
    shifted into the new capture's frame. Mutates and returns sidecar_data.

    perception_trim_ms values are user nudges layered ON TOP of the xcorr
    offset — the base offset absorbs Δ, so trims carry over unchanged.
    anti-corr state described the old shape and resets."""
    sidecar_data["timestamp_offset_ms"] = int(old_meta.get("timestamp_offset_ms", 0) or 0) + shift_ms
    sidecar_data["perception_trim_ms"] = int(old_meta.get("perception_trim_ms", 0) or 0)
    sidecar_data["offset_verification"] = old_meta.get("offset_verification", "unverified")
    sidecar_data["offset_quality"] = old_meta.get("offset_quality", 0.0)
    sidecar_data["offset_history"] = [
        {**h, "offset_ms": int(h.get("offset_ms", 0) or 0) + shift_ms}
        for h in (old_meta.get("offset_history") or [])
    ]
    migrated: dict[str, dict] = {}
    for sid, entry in (old_meta.get("setlist_offsets") or {}).items():
        e = dict(entry)
        if "timestamp_offset_ms" in e:
            e["timestamp_offset_ms"] = int(e.get("timestamp_offset_ms", 0) or 0) + shift_ms
        if e.get("observed_cut_in_ms"):
            e["observed_cut_in_ms"] = int(e["observed_cut_in_ms"]) + shift_ms
        e["history"] = [
            {**h, "offset_ms": int(h.get("offset_ms", 0) or 0) + shift_ms}
            for h in (e.get("history") or [])
        ]
        e["anti_corr_count"] = 0
        e.pop("last_anti_corr_at", None)
        migrated[sid] = e
    sidecar_data["setlist_offsets"] = migrated
    return sidecar_data


def apply_shift_to_profile(spotify_uri: str, shift_ms: int, duration_ms: int) -> tuple[int, int]:
    """Shift every trigger timestamp in the song's profile (main list and all
    per-Set-List overrides) by shift_ms, clamped to [0, duration].
    Returns (main_triggers_shifted, setlist_triggers_shifted)."""
    from services.profile_manager import load_profile_by_uri, save_profile

    profile = load_profile_by_uri(spotify_uri)
    if profile is None:
        return 0, 0

    def bump(triggers) -> int:
        n = 0
        for t in triggers:
            ts = t.timestamp_ms + shift_ms
            if duration_ms > 0:
                ts = min(ts, duration_ms)
            t.timestamp_ms = max(0, ts)
            n += 1
        return n

    n_main = bump(profile.triggers)
    n_setlist = sum(bump(lst) for lst in profile.setlist_triggers.values())
    if n_main or n_setlist:
        save_profile(profile)
    return n_main, n_setlist


def apply_shift_to_suggestions(spotify_uri: str, shift_ms: int, duration_ms: int) -> int:
    """Shift a pending (under-review) AI suggestion set, if one exists."""
    from services.suggestion_store import load_suggestion_set, save_suggestion_set

    track_id = spotify_uri.split(":")[-1]
    ss = load_suggestion_set(track_id)
    if ss is None or not ss.suggestions:
        return 0
    for s in ss.suggestions:
        for attr in ("timestamp_ms", "original_timestamp_ms"):
            ts = getattr(s, attr, None)
            if ts is None:
                continue
            ts = ts + shift_ms
            if duration_ms > 0:
                ts = min(ts, duration_ms)
            setattr(s, attr, max(0, ts))
    save_suggestion_set(ss)
    return len(ss.suggestions)


def invalidate_analyzed_cache(spotify_uri: str) -> None:
    """Drop the cached analyzed triggers so they regenerate from the fresh
    librosa analysis (their timestamps came from the old capture's beats)."""
    from services import analyzed_trigger_store
    track_id = spotify_uri.split(":")[-1]
    # The cache is one file per track; the store has no delete API.
    analyzed_trigger_store._path_for(track_id).unlink(missing_ok=True)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def realign_after_recapture(spotify_uri: str, stem: str, duration_ms: int) -> dict:
    """Run the full self-correction pass for a just-committed force-recapture.

    Must be called AFTER the atomic-save checks pass but BEFORE the *.bak
    files are deleted (it reads `{stem}.npz.bak` / `{stem}.json.bak`).
    Synchronous — run via executor. Never raises; returns a summary dict and
    records it in the new sidecar's last_realign_* fields."""
    old_npz = AUDIO_SHAPES_DIR / f"{stem}.npz.bak"
    old_sidecar = AUDIO_SHAPES_DIR / f"{stem}.json.bak"
    new_npz = AUDIO_SHAPES_DIR / f"{stem}.npz"
    sidecar = AUDIO_SHAPES_DIR / f"{stem}.json"

    summary: dict = {"status": "", "shift_ms": 0, "r": 0.0,
                     "triggers": 0, "setlist_triggers": 0, "suggestions": 0,
                     "offsets_migrated": False}

    # The old capture's librosa beats no longer describe the new WAV — always
    # regenerate analyzed triggers, whatever the measurement says.
    try:
        invalidate_analyzed_cache(spotify_uri)
    except Exception as exc:
        logger.warning("Realign: analyzed-cache invalidation failed: %s", exc)

    old_meta: dict = {}
    try:
        if old_sidecar.exists():
            old_meta = json.loads(old_sidecar.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Realign: could not read old sidecar: %s", exc)

    if not settings.realign_enabled:
        summary["status"] = "disabled"
    elif not old_npz.exists():
        summary["status"] = "no_baseline"
    else:
        m = measure_capture_shift(old_npz, new_npz)
        if m is None:
            summary["status"] = "low_confidence"
        else:
            summary["shift_ms"] = m.shift_ms
            summary["r"] = round(m.r, 3)
            # Offsets always carry over (continuity beats relearning); trigger
            # rewrites only when the shift is big enough to hear.
            summary["offsets_migrated"] = True
            if abs(m.shift_ms) >= int(settings.realign_apply_min_ms):
                summary["status"] = "applied"
                try:
                    n_main, n_sl = apply_shift_to_profile(spotify_uri, m.shift_ms, duration_ms)
                    summary["triggers"], summary["setlist_triggers"] = n_main, n_sl
                except Exception as exc:
                    logger.warning("Realign: trigger shift failed: %s", exc)
                try:
                    summary["suggestions"] = apply_shift_to_suggestions(
                        spotify_uri, m.shift_ms, duration_ms)
                except Exception as exc:
                    logger.warning("Realign: suggestion shift failed: %s", exc)
            else:
                summary["status"] = "no_shift"

    # Record the outcome (and migrate offsets) into the new sidecar.
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if summary["offsets_migrated"] and old_meta:
            shift_offset_fields(data, old_meta, summary["shift_ms"])
        if old_meta:
            # Chronic-recapture history is a diagnostic record — carry it over.
            data["needs_recapture_flag_count"] = int(
                old_meta.get("needs_recapture_flag_count") or 0)
        data["last_realign_status"] = summary["status"]
        data["last_realign_shift_ms"] = summary["shift_ms"]
        data["last_realign_r"] = summary["r"]
        data["last_realign_at"] = datetime.datetime.now(datetime.UTC).isoformat()
        sidecar.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Realign: sidecar update failed: %s", exc)

    logger.info(
        "Realign %s: %s (shift %+dms r=%.3f, %d+%d triggers, %d suggestions)",
        stem, summary["status"], summary["shift_ms"], summary["r"],
        summary["triggers"], summary["setlist_triggers"], summary["suggestions"],
    )
    return summary
