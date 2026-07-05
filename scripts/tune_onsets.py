"""
SpotFX — Onset-detection parameter tuning (librosa v3 bass / snare / overall).

Grid-searches the onset detector params against the triggerless-training songs
without touching stored sidecars: per song, onset envelopes are computed once
per unique (margin, band) and the cheap peak-pick stage sweeps
(delta, wait_ms, min_strength) against the cached envelopes.

Score per detector/song (components reported separately):
  P_grid   0.30  fraction of onsets within ±max(70ms, 0.1·beat) of the
                 half-beat grid (beats + midpoints) — off-grid clutter scores low
  D        0.25  density band score (onsets per beat inside a target band)
  R_energy 0.25  fraction of high-energy beats (band RMS > 0.5) with ≥1 onset
  R_trig   0.20  fraction of verified enabled trigger timestamps with an onset
                 within ±150 ms (snare is scored on the union with the bass
                 winner's onsets — flare hits land on either)

The hpss margin is shared config (librosa_hpss_margin), so the bass grid picks
it and the snare grid is restricted to the bass winner's margin.

Usage:
  .venv/bin/python scripts/tune_onsets.py                       # all detectors
  .venv/bin/python scripts/tune_onsets.py --detector bass --top 20
  .venv/bin/python scripts/tune_onsets.py --profile "Trap/Reggaeton"
  .venv/bin/python scripts/tune_onsets.py --apply               # write winners into config.py
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import AUDIO_SHAPES_DIR  # noqa: E402
from models.audio_shape import AudioShapeMeta  # noqa: E402
from services.librosa_service import (  # noqa: E402
    compute_onset_envelope, compute_percussive, get_analysis_by_uri, pick_onset_frames,
)
from services.profile_manager import load_profile_by_uri  # noqa: E402
from scripts.score_triggers import load_training_profiles  # noqa: E402

HOP = 512
TRIG_TOL_MS = 150

# ── Parameter grids ───────────────────────────────────────────────────────────

BASS_GRID = {
    "fmax":         [120, 150, 250],
    "delta":        [0.15, 0.25, 0.35, 0.5],
    "wait_ms":      [60, 100, 150],
    "min_strength": [0.0, 0.1, 0.2],
    "margin":       [1.0, 3.0],   # 1.0 = HPSS disabled (baseline)
}

SNARE_GRID = {
    "fmin":         [1200, 1500, 2000],
    "fmax":         [5000, 6000, 8000],
    "delta":        [0.15, 0.25, 0.35, 0.5],
    "wait_ms":      [60, 100, 150],
    "min_strength": [0.0, 0.1, 0.2],
    # margin fixed to the bass winner's (shared librosa_hpss_margin)
}

OVERALL_GRID = {
    "delta":        [0.07, 0.12, 0.2, 0.3],
    "wait_ms":      [30, 50, 80],
    "min_strength": [0.0, 0.1],
}

# Target onsets-per-beat bands for the density component
DENSITY_BANDS = {"bass": (0.4, 1.2), "snare": (0.25, 1.0), "overall": (1.0, 3.0)}
# Which per-beat RMS band gates the energy-recall component
ENERGY_FIELD = {"bass": "rms_bass", "snare": "rms_mid", "overall": "rms_total"}

WEIGHTS = {"P_grid": 0.30, "D": 0.25, "R_energy": 0.25, "R_trig": 0.20}


# ── Song loading ──────────────────────────────────────────────────────────────

@dataclass
class Song:
    uri: str
    title: str
    meta: AudioShapeMeta
    sr: int = 0
    beats_ms: np.ndarray = field(default_factory=lambda: np.zeros(0))
    half_grid: np.ndarray = field(default_factory=lambda: np.zeros(0))
    beat_tol_ms: float = 70.0
    rms: dict[str, np.ndarray] = field(default_factory=dict)
    offset_ms: int = 0
    trig_ms: np.ndarray = field(default_factory=lambda: np.zeros(0))  # song-relative, verified only
    envs: dict[tuple, np.ndarray] = field(default_factory=dict)       # (margin,fmin,fmax[,'legacy']) → env


def collect_training_uris(profile_filter: str | None) -> list[str]:
    uris: list[str] = []
    for tp in load_training_profiles().values():
        if profile_filter and tp.name != profile_filter:
            continue
        for u in (tp.training_uris or []) + (tp.embedded_only_uris or []):
            if u not in uris:
                uris.append(u)
    return uris


def resolve_meta_by_uri() -> dict[str, AudioShapeMeta]:
    metas: dict[str, AudioShapeMeta] = {}
    for jp in AUDIO_SHAPES_DIR.glob("*.json"):
        if jp.name.endswith(".librosa.json"):
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if "npz_file" not in data or "spotify_uri" not in data:
                continue
            metas[data["spotify_uri"]] = AudioShapeMeta(**data)
        except Exception:
            continue
    return metas


def load_songs(uris: list[str], max_songs: int = 0) -> list[Song]:
    metas = resolve_meta_by_uri()
    songs: list[Song] = []
    skipped: list[str] = []
    for uri in uris:
        meta = metas.get(uri)
        if meta is None:
            skipped.append(f"{uri} (no audio shape)")
            continue
        stem = Path(meta.npz_file).stem
        if not (AUDIO_SHAPES_DIR / f"{stem}.wav").exists():
            skipped.append(f"{meta.title} ({meta.artist}) — no WAV, needs re-capture")
            continue
        la = get_analysis_by_uri(uri)
        if la is None or len(la.beats) < 8:
            skipped.append(f"{meta.title} — no/short librosa analysis")
            continue

        beats_ms = np.array([b.ms for b in la.beats], dtype=float)
        mids = (beats_ms[:-1] + beats_ms[1:]) / 2.0
        bi = float(np.median(np.diff(beats_ms)))

        profile = load_profile_by_uri(uri)
        trig_ms = np.zeros(0)
        if profile and profile.verified and profile.triggers:
            trig_ms = np.array(sorted(
                t.timestamp_ms for t in profile.triggers if t.enabled), dtype=float)

        songs.append(Song(
            uri=uri,
            title=f"{meta.title} — {meta.artist}",
            meta=meta,
            beats_ms=beats_ms,
            half_grid=np.sort(np.concatenate([beats_ms, mids])),
            beat_tol_ms=max(70.0, 0.1 * bi),
            rms={k: np.array([getattr(b, k) for b in la.beats]) for k in
                 ("rms_bass", "rms_mid", "rms_total")},
            offset_ms=la.librosa_offset_ms,
            trig_ms=trig_ms,
        ))
        if max_songs and len(songs) >= max_songs:
            break
    if skipped:
        print(f"Skipped {len(skipped)} song(s):")
        for s in skipped:
            print(f"  - {s}")
    return songs


# ── Envelope cache ────────────────────────────────────────────────────────────

def build_env_caches(songs: list[Song], detectors: list[str]) -> None:
    """Load each WAV once and cache every envelope the grids will need."""
    import librosa

    margins = sorted(set(BASS_GRID["margin"]))
    for i, song in enumerate(songs, 1):
        t0 = time.perf_counter()
        wav = AUDIO_SHAPES_DIR / f"{Path(song.meta.npz_file).stem}.wav"
        y, sr = librosa.load(str(wav), sr=None, mono=True)
        song.sr = sr

        perc = {m: compute_percussive(y, sr, m) for m in margins}

        if "bass" in detectors:
            for m, fmax in itertools.product(margins, BASS_GRID["fmax"]):
                song.envs[(m, None, fmax)] = compute_onset_envelope(perc[m], sr, fmax=fmax)
            # v2-legacy envelope: raw y, mean aggregation, default 128 mels
            song.envs[("legacy", None, 250)] = librosa.onset.onset_strength(y=y, sr=sr, fmax=250)
        if "snare" in detectors:
            for m, fmin, fmax in itertools.product(
                    margins, SNARE_GRID["fmin"], SNARE_GRID["fmax"]):
                song.envs[(m, fmin, fmax)] = compute_onset_envelope(perc[m], sr, fmin=fmin, fmax=fmax)
        if "overall" in detectors:
            song.envs[(1.0, None, None)] = compute_onset_envelope(y, sr)
            song.envs[("legacy", None, None)] = librosa.onset.onset_strength(y=y, sr=sr)

        print(f"  [{i}/{len(songs)}] envelopes cached: {song.title[:60]} "
              f"({time.perf_counter() - t0:.1f}s, {len(song.envs)} envs)")
        del y, perc


# ── Metric ────────────────────────────────────────────────────────────────────

def _nearest_dist(sorted_ref: np.ndarray, values: np.ndarray) -> np.ndarray:
    if len(sorted_ref) == 0 or len(values) == 0:
        return np.full(len(values), np.inf)
    idx = np.searchsorted(sorted_ref, values)
    lo = np.clip(idx - 1, 0, len(sorted_ref) - 1)
    hi = np.clip(idx, 0, len(sorted_ref) - 1)
    return np.minimum(np.abs(values - sorted_ref[lo]), np.abs(values - sorted_ref[hi]))


def _density_score(count: int, n_beats: int, lo: float, hi: float) -> float:
    x = count / max(1, n_beats)
    if lo <= x <= hi:
        return 1.0
    if x < lo:
        return max(0.0, (x - lo / 2) / (lo / 2))
    return max(0.0, (2 * hi - x) / hi)


def score_song(song: Song, onset_ms: np.ndarray, detector: str,
               extra_trig_onsets: np.ndarray | None = None) -> dict[str, float]:
    lo, hi = DENSITY_BANDS[detector]
    comps: dict[str, float] = {}

    d = _nearest_dist(song.half_grid, onset_ms)
    comps["P_grid"] = float(np.mean(d <= song.beat_tol_ms)) if len(onset_ms) else 0.0
    comps["D"] = _density_score(len(onset_ms), len(song.beats_ms), lo, hi)

    rms = song.rms[ENERGY_FIELD[detector]]
    hot = np.where(rms[:-1] > 0.5)[0]  # last beat has no interval end
    if len(hot):
        counts = np.histogram(onset_ms, bins=song.beats_ms)[0]
        comps["R_energy"] = float(np.mean(counts[hot] > 0))
    else:
        comps["R_energy"] = 1.0

    if len(song.trig_ms):
        cand = onset_ms if extra_trig_onsets is None else np.sort(
            np.concatenate([onset_ms, extra_trig_onsets]))
        dt = _nearest_dist(cand + song.offset_ms, song.trig_ms)
        comps["R_trig"] = float(np.mean(dt <= TRIG_TOL_MS))
    return comps


def composite(comps: dict[str, float]) -> float:
    used = {k: w for k, w in WEIGHTS.items() if k in comps}
    total = sum(used.values())
    return sum(comps[k] * w for k, w in used.items()) / total


# ── Sweep ─────────────────────────────────────────────────────────────────────

def onset_times_ms(song: Song, env_key: tuple, delta: float, wait_ms: int,
                   min_strength: float) -> np.ndarray:
    frames = pick_onset_frames(
        song.envs[env_key], song.sr,
        delta=delta, wait_ms=wait_ms, min_strength=min_strength, hop_length=HOP,
    )
    return frames * HOP / song.sr * 1000.0


def sweep(songs: list[Song], detector: str, combos: list[dict],
          env_key_fn, extra_by_song: dict[str, np.ndarray] | None = None) -> list[dict]:
    results = []
    for combo in combos:
        per_song_comps = []
        onsets_per_s = []
        for song in songs:
            oms = onset_times_ms(song, env_key_fn(combo), combo["delta"],
                                 combo["wait_ms"], combo["min_strength"])
            extra = (extra_by_song or {}).get(song.uri)
            per_song_comps.append(score_song(song, oms, detector, extra))
            dur_s = (song.beats_ms[-1] - song.beats_ms[0]) / 1000.0
            onsets_per_s.append(len(oms) / dur_s if dur_s > 0 else 0.0)
        agg = {}
        for k in WEIGHTS:
            vals = [c[k] for c in per_song_comps if k in c]
            if vals:
                agg[k] = float(np.mean(vals))
        results.append({
            "combo": combo,
            "score": float(np.mean([composite(c) for c in per_song_comps])),
            "onsets_per_s": float(np.mean(onsets_per_s)),
            **agg,
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def print_table(detector: str, results: list[dict], top: int, baseline: dict | None) -> None:
    print(f"\n=== {detector.upper()} — top {min(top, len(results))} of {len(results)} combos ===")
    cols = ["score", "P_grid", "D", "R_energy", "R_trig", "onsets_per_s"]
    header = "  ".join(f"{c:>9}" for c in cols)
    print(f"{'rank':>4}  {header}  params")
    rows = results[:top]
    if baseline:
        rows = rows + [baseline]
    for i, r in enumerate(rows):
        label = "BASE" if r is baseline else f"{i + 1:>4}"
        vals = "  ".join(f"{r.get(c, float('nan')):>9.3f}" for c in cols)
        print(f"{label}  {vals}  {r['combo']}")


# ── Apply winners to config.py ────────────────────────────────────────────────

CONFIG_KEYS = {
    "bass": {
        "fmax": ("librosa_bass_fmax", int),
        "delta": ("librosa_bass_onset_delta", float),
        "wait_ms": ("librosa_bass_onset_wait_ms", int),
        "min_strength": ("librosa_bass_min_strength", float),
        "margin": ("librosa_hpss_margin", float),
    },
    "snare": {
        "fmin": ("librosa_snare_fmin", int),
        "fmax": ("librosa_snare_fmax", int),
        "delta": ("librosa_snare_onset_delta", float),
        "wait_ms": ("librosa_snare_onset_wait_ms", int),
        "min_strength": ("librosa_snare_min_strength", float),
    },
    "overall": {
        "delta": ("librosa_onset_delta", float),
        "wait_ms": ("librosa_onset_wait_ms", int),
        "min_strength": ("librosa_onset_min_strength", float),
    },
}


def apply_to_config(winners: dict[str, dict]) -> None:
    cfg_path = PROJECT_ROOT / "config.py"
    text = cfg_path.read_text(encoding="utf-8")
    changes = []
    for detector, combo in winners.items():
        for param, (key, typ) in CONFIG_KEYS[detector].items():
            if param not in combo:
                continue
            new_val = typ(combo[param])
            pattern = rf"(?m)^(\s*{key}: (?:int|float) = )[-0-9.]+"
            matches = re.findall(pattern, text)
            if len(matches) != 1:
                print(f"REFUSING to apply: {key} matched {len(matches)} lines in config.py")
                sys.exit(1)
            text, _ = re.subn(pattern, rf"\g<1>{new_val}", text)
            changes.append(f"  {key} → {new_val}")
    cfg_path.write_text(text, encoding="utf-8")
    print("\nApplied to config.py:")
    print("\n".join(changes))


# ── Main ──────────────────────────────────────────────────────────────────────

def _combos(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, v)) for v in itertools.product(*(grid[k] for k in keys))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-search librosa onset params")
    parser.add_argument("--detector", choices=["bass", "snare", "overall", "all"], default="all")
    parser.add_argument("--profile", type=str, help="Restrict to one training profile")
    parser.add_argument("--uri", type=str, help="Restrict to one song URI")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--max-songs", type=int, default=0)
    parser.add_argument("--pick", type=int, default=1, help="Rank to apply (1 = best)")
    parser.add_argument("--apply", action="store_true", help="Write winners into config.py")
    args = parser.parse_args()

    detectors = ["bass", "snare", "overall"] if args.detector == "all" else [args.detector]

    uris = [args.uri] if args.uri else collect_training_uris(args.profile)
    if not uris:
        print("No training URIs found.")
        sys.exit(1)
    songs = load_songs(uris, max_songs=args.max_songs)
    print(f"\nLoaded {len(songs)} song(s) "
          f"({sum(1 for s in songs if len(s.trig_ms))} with verified triggers)")
    if not songs:
        sys.exit(1)

    print("\nCaching onset envelopes (one WAV load per song)...")
    build_env_caches(songs, detectors)

    winners: dict[str, dict] = {}
    bass_margin = 3.0
    bass_onsets_by_song: dict[str, np.ndarray] = {}

    if "bass" in detectors:
        results = sweep(songs, "bass", _combos(BASS_GRID),
                        lambda c: (c["margin"], None, c["fmax"]))
        legacy = sweep(songs, "bass",
                       [{"delta": 0.10, "wait_ms": 30, "min_strength": 0.0}],
                       lambda c: ("legacy", None, 250))[0]
        legacy["combo"] = {"v2-legacy": "delta=0.10, no wait/floor/HPSS, mean agg"}
        print_table("bass", results, args.top, legacy)
        pick = results[min(args.pick, len(results)) - 1]
        winners["bass"] = pick["combo"]
        bass_margin = pick["combo"]["margin"]
        for song in songs:
            bass_onsets_by_song[song.uri] = onset_times_ms(
                song, (bass_margin, None, pick["combo"]["fmax"]),
                pick["combo"]["delta"], pick["combo"]["wait_ms"], pick["combo"]["min_strength"])

    if "snare" in detectors:
        print(f"\n(snare grid fixed to hpss margin {bass_margin} — shared config with bass)")
        results = sweep(songs, "snare", _combos(SNARE_GRID),
                        lambda c: (bass_margin, c["fmin"], c["fmax"]),
                        extra_by_song=bass_onsets_by_song or None)
        print_table("snare", results, args.top, None)
        winners["snare"] = results[min(args.pick, len(results)) - 1]["combo"]

    if "overall" in detectors:
        results = sweep(songs, "overall", _combos(OVERALL_GRID),
                        lambda c: (1.0, None, None))
        legacy = sweep(songs, "overall",
                       [{"delta": 0.07, "wait_ms": 30, "min_strength": 0.0}],
                       lambda c: ("legacy", None, None))[0]
        legacy["combo"] = {"v2-legacy": "delta=0.07, no wait/floor, mean agg"}
        print_table("overall", results, args.top, legacy)
        winners["overall"] = results[min(args.pick, len(results)) - 1]["combo"]

    print("\nWinners:")
    for det, combo in winners.items():
        print(f"  {det}: {combo}")

    if args.apply:
        apply_to_config(winners)
    else:
        print("\n(dry run — pass --apply to write these into config.py)")


if __name__ == "__main__":
    main()
