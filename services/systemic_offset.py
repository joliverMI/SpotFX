"""
SpotFX — Systemic starting-offset learner.

A single device-wide bias that captures the *common* timing component of
recent confirmed xcorr locks — the part that no per-song baseline or
per-Set-List delta has corrected. It exists because a pipeline-level latency
change (e.g. restarting Spotify, a snapclient reconnect, an audio-routing
shuffle) shifts the live-audio-vs-Spotify-progress relationship for EVERY
song by a similar amount. Per-song slot history only re-learns that shift one
song at a time, over many plays; this learner spreads the correction across
the whole catalogue immediately.

What it records (the *prediction residual*):
    residual = confirmed_lock_ms  −  offset_loaded_at_song_start_ms

That difference is, by construction, exactly the slice neither the per-song
baseline nor the per-Set-List bias predicted. When the learner is doing its
job the loaded offset already includes its bias, so residuals shrink toward
zero and the estimate self-stabilises — no runaway feedback.

How strength grows / wanes (matches the user's spec):
  • "several songs in a row offset by a similar amount" → reinforcement.
    Confidence rises with the decayed *mass* of samples AND their agreement
    (tight clustering → high; scattered residuals → ~0, so a noisy mix can't
    manufacture a bias).
  • "wane when idle for long periods" → every sample's weight decays
    exponentially with age (half-life `systemic_offset_half_life_h`); samples
    older than `systemic_offset_max_age_h` are culled. After a long idle gap
    the surviving mass is tiny, so confidence collapses and a fresh session
    re-earns trust from scratch.

Applied bias = clamp(center × confidence, ±max). It is layered on top of the
per-song / per-Set-List resolution in trigger_engine._resolve_shape_offset as
a COLD-START aid only: this play's own xcorr re-lock overrides it within
seconds via TriggerEngine.apply_save, so the learner can never fight a real
in-song measurement.

All behaviour is gated behind `settings.systemic_offset_enabled` (default
False) — the prediction is inert (bias 0, confidence 0) until enabled.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from config import BASE_DIR, settings

logger = logging.getLogger(__name__)

_STORE_PATH = BASE_DIR / "storage" / "offset_bias.json"

# Module-level state. The whole app is one asyncio process, so a plain cache
# guarded by a lock is enough; record() persists synchronously after each
# confirmed save (a handful of writes per song — negligible).
_lock = threading.Lock()
_samples: Optional[list[dict]] = None   # lazily loaded; each: {residual_ms, quality, at}


@dataclass
class BiasPrediction:
    """Result of predict(). `bias_ms` is the ready-to-apply, confidence-scaled,
    clamped value; the rest are diagnostics for logging / the Debug page."""
    bias_ms: int          # what to actually add at cold start (0 below the floor)
    confidence: float     # 0..1
    center_ms: int        # robust center of recent residuals (pre-scaling)
    mass: float           # decayed sample mass
    n: int                # raw sample count after culling
    mad_ms: int           # weighted median absolute deviation (spread)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _load() -> list[dict]:
    global _samples
    if _samples is not None:
        return _samples
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        _samples = list(raw.get("samples") or [])
    except (FileNotFoundError, ValueError, OSError):
        _samples = []
    return _samples


def _persist() -> None:
    try:
        _STORE_PATH.write_text(
            json.dumps({"samples": _samples, "updated_at": _now().isoformat()},
                       indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("systemic_offset: could not persist %s: %s", _STORE_PATH, exc)


def _weighted_median(pairs: list[tuple[float, float]]) -> Optional[float]:
    """Weighted median of (value, weight) pairs. None if total weight ≤ 0."""
    items = sorted(pairs)
    total = sum(w for _, w in items)
    if total <= 0:
        return None
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= total / 2.0:
            return v
    return items[-1][0]


def record(residual_ms: int, quality: float) -> None:
    """Add one confirmed-save residual to the rolling history and persist.

    Caller computes `residual = confirmed_offset − loaded_offset_at_start`.
    Low-quality saves are dropped (a shaky lock shouldn't teach the whole
    catalogue). No-op unless the learner is enabled.
    """
    if not getattr(settings, "systemic_offset_enabled", False):
        return
    if float(quality) < float(getattr(settings, "systemic_offset_min_quality", 0.55)):
        return
    with _lock:
        samples = _load()
        samples.insert(0, {
            "residual_ms": int(residual_ms),
            "quality": round(float(quality), 3),
            "at": _now().isoformat(),
        })
        cap = int(getattr(settings, "systemic_offset_sample_cap", 40))
        del samples[cap:]
        _persist()
    logger.info(
        "systemic_offset: recorded residual %+dms (Q=%.2f, %d samples)",
        int(residual_ms), float(quality), len(_samples or []),
    )


def predict(now: Optional[datetime] = None) -> BiasPrediction:
    """Compute the current cold-start bias from decayed, agreement-weighted
    residuals. Inert (all-zero) when disabled. Pure w.r.t. `now` so tests can
    pin the clock."""
    empty = BiasPrediction(0, 0.0, 0, 0.0, 0, 0)
    if not getattr(settings, "systemic_offset_enabled", False):
        return empty

    now = now or _now()
    half_life_h = float(getattr(settings, "systemic_offset_half_life_h", 3.0))
    max_age_h = float(getattr(settings, "systemic_offset_max_age_h", 24.0))
    full_mass = float(getattr(settings, "systemic_offset_full_mass", 3.0))
    spread_tol = float(getattr(settings, "systemic_offset_spread_tol_ms", 1500))
    min_conf = float(getattr(settings, "systemic_offset_min_confidence", 0.25))
    max_bias = int(getattr(settings, "systemic_offset_max_bias_ms", 5000))

    with _lock:
        samples = list(_load())

    weighted: list[tuple[float, float]] = []   # (residual, weight)
    for s in samples:
        at = _parse(s.get("at", ""))
        if at is None:
            continue
        age_h = (now - at).total_seconds() / 3600.0
        if age_h < 0 or age_h > max_age_h:
            continue
        decay = 0.5 ** (age_h / half_life_h) if half_life_h > 0 else 1.0
        w = float(s.get("quality", 0.0)) * decay
        if w > 0:
            weighted.append((float(s.get("residual_ms", 0)), w))

    if not weighted:
        return empty

    mass = sum(w for _, w in weighted)
    center = _weighted_median(weighted)
    if center is None:
        return empty
    mad = _weighted_median([(abs(v - center), w) for v, w in weighted]) or 0.0

    count_conf = min(1.0, mass / full_mass) if full_mass > 0 else 1.0
    agree_conf = max(0.0, min(1.0, 1.0 - (mad / spread_tol))) if spread_tol > 0 else 1.0
    confidence = count_conf * agree_conf

    bias = 0
    if confidence >= min_conf:
        bias = int(round(center * confidence))
        bias = max(-max_bias, min(max_bias, bias))

    return BiasPrediction(
        bias_ms=bias,
        confidence=round(confidence, 3),
        center_ms=int(round(center)),
        mass=round(mass, 3),
        n=len(weighted),
        mad_ms=int(round(mad)),
    )


def reset() -> None:
    """Drop all learned history (test helper / manual recalibration)."""
    global _samples
    with _lock:
        _samples = []
        _persist()
