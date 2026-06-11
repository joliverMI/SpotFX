"""
Per-song WAV↔NPZ alignment calibration.

The stored full-song WAVs are not sample-aligned with their NPZ shapes: the
WAV writer may include ring-buffer pre-roll, so the WAV's t=0 can sit up to
a few seconds before the shape's t=0. That bias is a property of the stored
artifacts, not of the matcher — so the harness measures it once per song
(clean frames, high-difficulty windows, consensus gate) and every scenario's
expected offset becomes `true_offset_ms + wav_bias_ms`.

Biases are cached in storage/benchmarks/wav_bias.json. Songs where no
confident consensus emerges return None and should be skipped by benchmarks.
"""
from __future__ import annotations

import json
from typing import Optional

from bench.corpus import BENCH_DIR
from services import xcorr_core

_CACHE_PATH = BENCH_DIR / "wav_bias.json"
_SEARCH_MS = 4000      # bias observed up to ~1-2s; leave headroom
_MIN_R = 0.55
_AGREE_TOL_MS = 150


def _dense_best(stored_ts, stored_bands, frames, win_start, win_end,
                search_ms: int):
    """Best (offset_ms, r) scanning EVERY 25 ms shift — no coarse step, no
    production gates. Calibration must not inherit the matcher's coarse-step
    aliasing or twin rejection (we want ground truth, not matcher behavior)."""
    import numpy as np
    BIN = xcorr_core.XCORR_BIN_MS
    bins = np.arange(win_start, win_end, BIN, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    band_info = []
    for band_idx, stored_rms in enumerate(stored_bands):
        template = xcorr_core.agc_normalize(np.interp(bins, stored_ts, stored_rms))
        if template.std() < 1e-6:
            continue
        band_info.append((band_idx, (template - template.mean()) / template.std()))
    if not band_info:
        return None

    grid_start = win_start - search_ms
    grid_ts = np.arange(grid_start, win_end + search_ms + BIN, BIN, dtype=float)
    n_grid = len(grid_ts)
    live_grid = {}
    for band_idx, _ in band_info:
        live_rms = xcorr_core.agc_normalize(xcorr_core.signed_square(
            np.array([f[1 + band_idx] for f in frames], dtype=float)))
        live_grid[band_idx] = np.interp(grid_ts, live_ts, live_rms, left=0.0, right=0.0)
    base_idx = int(round((win_start - grid_start) / BIN))

    best = None
    for shift in range(-search_ms, search_ms + 1, BIN):
        off = base_idx + shift // BIN
        if off < 0 or off + n_bins > n_grid:
            continue
        r_sum, n_valid = 0.0, 0
        for band_idx, tnorm in band_info:
            sig = live_grid[band_idx][off: off + n_bins]
            if sig.std() < 1e-6:
                continue
            r_sum += float(np.dot(tnorm, (sig - sig.mean()) / sig.std())) / n_bins
            n_valid += 1
        if not n_valid:
            continue
        r = r_sum / n_valid
        if best is None or r > best[1]:
            best = (-shift, r)
    return best


def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True),
                           encoding="utf-8")


def measure_wav_bias(assets: dict, frames: list) -> Optional[int]:
    """Measure the WAV↔NPZ offset from clean (undegraded) frames using the
    top-difficulty cached windows. Returns the median of agreeing
    measurements, or None when no ≥2-window consensus forms."""
    meta = assets["meta"]
    stored_ts = assets["stored_ts"]
    stored_bands = assets["stored_bands"]
    wins = sorted(
        (meta.xcorr_windows or []),
        key=lambda w: float(w.get("difficulty", 0)),
        reverse=True,
    )[:6]
    last_ts = frames[-1][0] if frames else 0

    offsets: list[int] = []
    for w in wins:
        ws, we = int(w["start_ms"]), int(w["end_ms"])
        if we + 1000 > last_ts:
            continue
        frames_now = [f for f in frames if f[0] <= we + 1000]
        res = _dense_best(stored_ts, stored_bands, frames_now, ws, we, _SEARCH_MS)
        if res is not None and res[1] >= _MIN_R:
            offsets.append(int(res[0]))
        if len(offsets) >= 4:
            break

    if len(offsets) < 2:
        return None
    offsets.sort()
    med = offsets[len(offsets) // 2]
    agreeing = [o for o in offsets if abs(o - med) <= _AGREE_TOL_MS]
    if len(agreeing) < 2:
        return None
    return int(round(sum(agreeing) / len(agreeing)))


def wav_bias(stem: str, assets: Optional[dict] = None,
             clean_frames: Optional[list] = None) -> Optional[int]:
    """Cached per-song WAV↔NPZ bias. Computes (and persists) on first use."""
    cache = _load_cache()
    if stem in cache:
        return cache[stem]
    if assets is None:
        from bench.replay import load_song_assets
        assets = load_song_assets(stem)
    if clean_frames is None:
        from bench.simulate import load_wav, make_frames
        clean_frames = make_frames(load_wav(assets["wav_path"]))
    bias = measure_wav_bias(assets, clean_frames)
    cache[stem] = bias
    _save_cache(cache)
    return bias
