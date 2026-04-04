"""
SpotFX — Librosa analysis service.

Analyses a saved WAV file for a captured song and extracts:
  - tempo + beats (with downbeat labels every beats_per_bar beats)
  - onsets (note/transient attacks with relative strength)
  - structural section boundaries
  - harmonic change points

Results are saved as  {stem}.librosa.json  alongside the .npz/.json sidecar.
WAV files are retained for up to settings.audio_wav_max_songs songs; older
files are deleted when a new one is written.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from config import AUDIO_SHAPES_DIR, settings
from models.audio_shape import AudioShapeMeta
from models.librosa_analysis import (
    LibrosaAnalysis, LibrosaBeat, LibrosaOnset, LibrosaSection, LibrosaHarmonicChange,
)

logger = logging.getLogger(__name__)

# ── Path helpers ──────────────────────────────────────────────────────────────

def wav_path(meta: AudioShapeMeta) -> Path:
    stem = Path(meta.npz_file).stem
    return AUDIO_SHAPES_DIR / f"{stem}.wav"


def librosa_json_path(meta: AudioShapeMeta) -> Path:
    stem = Path(meta.npz_file).stem
    return AUDIO_SHAPES_DIR / f"{stem}.librosa.json"


def has_wav(meta: AudioShapeMeta) -> bool:
    return wav_path(meta).exists()


def get_analysis(meta: AudioShapeMeta) -> Optional[LibrosaAnalysis]:
    """Load saved librosa JSON for a song, or None if not yet analysed."""
    p = librosa_json_path(meta)
    if not p.exists():
        return None
    try:
        return LibrosaAnalysis(**json.loads(p.read_text(encoding="utf-8")))
    except Exception as exc:
        logger.warning("Failed to load librosa JSON for %s: %s", meta.title, exc)
        return None


def get_analysis_by_uri(spotify_uri: str) -> Optional[LibrosaAnalysis]:
    """Find and load librosa analysis for a URI without requiring a loaded meta."""
    for p in AUDIO_SHAPES_DIR.glob("*.librosa.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("spotify_uri") == spotify_uri:
                return LibrosaAnalysis(**data)
        except Exception:
            pass
    return None


# ── WAV retention ─────────────────────────────────────────────────────────────

def manage_wav_retention() -> None:
    """Delete oldest WAV files when count exceeds settings.audio_wav_max_songs."""
    max_songs = settings.audio_wav_max_songs
    if max_songs <= 0:
        return
    wavs = sorted(AUDIO_SHAPES_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    to_delete = wavs[: max(0, len(wavs) - max_songs)]
    for p in to_delete:
        try:
            p.unlink()
            logger.info("WAV retention: deleted %s", p.name)
        except Exception as exc:
            logger.warning("WAV retention: could not delete %s: %s", p.name, exc)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze_sync(meta: AudioShapeMeta) -> LibrosaAnalysis:
    """
    Run librosa analysis on the WAV for *meta* and save the result.
    Blocking — call via run_in_executor in async contexts.
    """
    import librosa
    import scipy.ndimage
    from scipy.signal import find_peaks

    wpath = wav_path(meta)
    logger.info("Librosa analysis started: %s", wpath.name)

    # Load at native sample rate; mono
    y, sr = librosa.load(str(wpath), sr=None, mono=True)

    # ── Tempo + beats ──────────────────────────────────────────────────────
    tempo_val, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    # tempo_val may be a numpy scalar or array in different librosa versions
    tempo_bpm = float(np.atleast_1d(tempo_val)[0])
    beat_frames = np.array(beat_frames, dtype=int)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    beats_per_bar = 4

    # ── Onsets ────────────────────────────────────────────────────────────
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sr, units='frames', delta=settings.librosa_onset_delta,
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    # Normalise strength to 0–1
    env_max = float(onset_env.max()) if onset_env.max() > 0 else 1.0
    onsets = [
        LibrosaOnset(ms=int(t * 1000), strength=round(float(onset_env[f]) / env_max, 3))
        for t, f in zip(onset_times, onset_frames)
        if f < len(onset_env)
    ]

    # ── Downbeat phase detection ───────────────────────────────────────────
    # For each candidate phase (0–beats_per_bar-1), average the onset envelope
    # at those beat positions — downbeats tend to have the strongest attacks.
    if settings.librosa_downbeat_phase >= 0:
        downbeat_phase = int(settings.librosa_downbeat_phase) % beats_per_bar
    else:
        best_phase, best_score = 0, -1.0
        phase_scores = []
        for phase in range(beats_per_bar):
            db_times = beat_times[phase::beats_per_bar]
            if len(db_times) == 0:
                phase_scores.append(0.0)
                continue
            db_frames = np.clip(
                librosa.time_to_frames(db_times, sr=sr), 0, len(onset_env) - 1
            )
            score = float(np.mean(onset_env[db_frames]))
            phase_scores.append(round(score, 3))
            if score > best_score:
                best_score, best_phase = score, phase
        downbeat_phase = best_phase
        logger.debug(
            "Downbeat phase auto-detected as %d for %s (per-phase scores: %s)",
            downbeat_phase, meta.title, phase_scores,
        )

    # ── Per-beat RMS energy (four bands) ──────────────────────────────────
    rms_t_arr, rms_b_arr, rms_m_arr, rms_h_arr = _compute_beat_rms(y, sr, beat_times)

    # ── Bass onsets ────────────────────────────────────────────────────────
    bass_onsets = _detect_bass_onsets(y, sr)

    # ── Structural sections ────────────────────────────────────────────────
    sections = _detect_sections(y, sr, beat_frames, tempo_bpm, onset_frames)

    # ── Harmonic changes ──────────────────────────────────────────────────
    harmonic_changes = _detect_harmonic_changes(y, sr, beat_frames)

    # ── Per-beat event scores (onset / bass onset / harmonic) ─────────────
    onset_scores, bass_scores, harmonic_scores = _compute_beat_event_scores(
        beat_times, onsets, bass_onsets, harmonic_changes,
    )

    # onset/bass/harmonic_scores are already trimmed (last beat dropped)
    beats = [
        LibrosaBeat(
            ms=int(t * 1000),
            is_downbeat=((i - downbeat_phase) % beats_per_bar == 0),
            rms_total=round(rms_t_arr[i], 3),
            rms_bass =round(rms_b_arr[i], 3),
            rms_mid  =round(rms_m_arr[i], 3),
            rms_high =round(rms_h_arr[i], 3),
            onset_score     =round(onset_scores[i],    3),
            bass_onset_score=round(bass_scores[i],     3),
            harmonic_score  =round(harmonic_scores[i], 3),
        )
        for i, t in enumerate(beat_times[:-1])  # last beat dropped
    ]

    # ── Capture start offset ───────────────────────────────────────────────
    # The WAV starts at t=0 (start of capture), but audio shape timestamps
    # are song-relative (capture begins mid-song). Seed librosa_offset_ms
    # from timestamps_ms[0] in the NPZ so marks align by default.
    capture_offset_ms = 0
    npz_path = AUDIO_SHAPES_DIR / meta.npz_file
    if npz_path.exists():
        try:
            npz_data = np.load(str(npz_path))
            ts = npz_data["timestamps_ms"] if "timestamps_ms" in npz_data else None
            if ts is not None and len(ts) > 0:
                capture_offset_ms = int(ts[0])
        except Exception as exc:
            logger.warning("Could not read capture offset from NPZ for %s: %s", meta.title, exc)

    analysis = LibrosaAnalysis(
        spotify_uri=meta.spotify_uri,
        title=meta.title,
        artist=meta.artist,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        tempo_bpm=round(tempo_bpm, 2),
        beats_per_bar=beats_per_bar,
        downbeat_phase=downbeat_phase,
        librosa_offset_ms=capture_offset_ms,
        beats=beats,
        onsets=onsets,
        bass_onsets=bass_onsets,
        sections=sections,
        harmonic_changes=harmonic_changes,
    )

    jpath = librosa_json_path(meta)
    jpath.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "Librosa analysis complete: %s — %.1f BPM, %d beats, %d onsets, %d bass, %d sections, %d harmonic",
        meta.title, tempo_bpm, len(beats), len(onsets), len(bass_onsets), len(sections), len(harmonic_changes),
    )
    return analysis


def _detect_sections(
    y: np.ndarray, sr: int, beat_frames: np.ndarray, tempo_bpm: float,
    onset_frames: np.ndarray,
) -> list[LibrosaSection]:
    """
    Segment the song into structural sections using beat-synced MFCC recurrence.
    Each section is enriched with energy_rms, onset_density_per_s, and an
    inferred label (intro/verse/chorus/bridge/drop/outro).
    """
    import librosa
    import scipy.ndimage
    from scipy.signal import find_peaks

    duration_s = len(y) / sr

    if len(beat_frames) < 8:
        energy = float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
        return [LibrosaSection(
            start_ms=0, end_ms=int(duration_s * 1000),
            label="full", energy_rms=round(energy, 4), onset_density_per_s=0.0,
        )]

    # Beat-synced MFCC features
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_delta = librosa.feature.delta(mfcc)
    features = np.vstack([mfcc, mfcc_delta])
    bf = np.clip(beat_frames, 0, features.shape[1] - 1)
    features_sync = librosa.util.sync(features, bf, aggregate=np.median)

    # Self-similarity matrix
    R = librosa.segment.recurrence_matrix(features_sync, width=3, mode='affinity', sym=True)

    # Smooth and compute novelty as row-sum second-order difference
    R_smooth = scipy.ndimage.median_filter(R, size=(1, 7))
    row_sums = R_smooth.sum(axis=1)
    novelty = np.diff(row_sums, prepend=row_sums[0])
    # Rectify — we only care about drops (structural boundaries are where coherence drops)
    novelty = np.clip(-novelty, 0, None)
    if novelty.max() > 0:
        novelty /= novelty.max()

    # Minimum distance between sections — use config value, minimum 4 beats
    min_dist_beats = max(4, settings.librosa_section_min_beats)

    peaks, props = find_peaks(
        novelty,
        distance=min_dist_beats,
        height=settings.librosa_section_min_height,
    )

    # Convert beat-space peak indices to actual timestamps
    boundary_frames = []
    for p in peaks:
        if p < len(bf):
            boundary_frames.append(int(bf[p]))

    boundary_times_s = [0.0] + list(librosa.frames_to_time(boundary_frames, sr=sr)) + [duration_s]
    # Deduplicate and sort
    boundary_times_s = sorted(set(round(t, 3) for t in boundary_times_s))

    # Pre-compute onset times for density calc
    onset_times_s = librosa.frames_to_time(onset_frames, sr=sr)

    # Build raw sections with energy + density
    raw: list[dict] = []
    for i in range(len(boundary_times_s) - 1):
        start_s = boundary_times_s[i]
        end_s   = boundary_times_s[i + 1]
        seg = y[int(start_s * sr): int(end_s * sr)]
        energy = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
        dur    = end_s - start_s
        count  = int(np.sum((onset_times_s >= start_s) & (onset_times_s < end_s)))
        density = count / dur if dur > 0 else 0.0
        raw.append({"start_s": start_s, "end_s": end_s, "energy": energy, "density": density})

    # Normalise energy and density to 0–1 across all sections
    max_e = max(r["energy"] for r in raw) or 1.0
    max_d = max(r["density"] for r in raw) or 1.0
    for r in raw:
        r["energy_norm"]  = r["energy"]  / max_e
        r["density_norm"] = r["density"] / max_d

    # Rank each section by energy (0 = lowest, 1 = highest)
    sorted_e = sorted(r["energy_norm"] for r in raw)
    n = len(raw)

    def _infer_label(energy_norm: float, density_norm: float, position: float) -> str:
        rank = sorted_e.index(energy_norm) / max(n - 1, 1)
        if position < 0.12:
            return "intro"
        if position > 0.88:
            return "outro"
        if rank > 0.70:
            if density_norm > 0.60:
                return "drop"
            return "chorus"
        if rank < 0.30:
            return "verse"
        return "bridge"

    sections = []
    for r in raw:
        pos = ((r["start_s"] + r["end_s"]) / 2) / duration_s
        label = _infer_label(r["energy_norm"], r["density_norm"], pos)
        sections.append(LibrosaSection(
            start_ms=int(r["start_s"] * 1000),
            end_ms=int(r["end_s"] * 1000),
            label=label,
            energy_rms=round(r["energy_norm"], 4),
            onset_density_per_s=round(r["density"], 3),
        ))

    # Fallback
    if not sections:
        energy = float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
        sections = [LibrosaSection(
            start_ms=0, end_ms=int(duration_s * 1000),
            label="full", energy_rms=round(energy, 4), onset_density_per_s=0.0,
        )]

    return sections


def _detect_bass_onsets(y: np.ndarray, sr: int) -> list[LibrosaOnset]:
    """
    Detect onsets using a low-frequency (bass) onset envelope (fmax=250 Hz).
    Captures kick-drum and sub-bass hits that the full-spectrum detector under-weights.
    """
    import librosa

    bass_env = librosa.onset.onset_strength(y=y, sr=sr, fmax=settings.librosa_bass_fmax)
    bass_frames = librosa.onset.onset_detect(
        onset_envelope=bass_env, sr=sr, units='frames', delta=settings.librosa_bass_onset_delta,
    )
    bass_times = librosa.frames_to_time(bass_frames, sr=sr)
    env_max = float(bass_env.max()) if bass_env.max() > 0 else 1.0
    return [
        LibrosaOnset(ms=int(t * 1000), strength=round(float(bass_env[f]) / env_max, 3))
        for t, f in zip(bass_times, bass_frames)
        if f < len(bass_env)
    ]


def _compute_beat_rms(
    y: np.ndarray, sr: int, beat_times: np.ndarray,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """
    For each beat interval compute normalised 0–1 RMS for four bands:
      total, bass (<250 Hz), mid (250–4000 Hz), high (>4000 Hz).

    Returns four parallel lists (total, bass, mid, high).
    """
    from scipy.signal import butter, sosfilt

    nyq = sr / 2.0

    def _lpf(data: np.ndarray, fc: float) -> np.ndarray:
        sos = butter(4, fc / nyq, btype='low', output='sos')
        return sosfilt(sos, data)

    def _hpf(data: np.ndarray, fc: float) -> np.ndarray:
        sos = butter(4, fc / nyq, btype='high', output='sos')
        return sosfilt(sos, data)

    def _bpf(data: np.ndarray, lo: float, hi: float) -> np.ndarray:
        sos = butter(4, [lo / nyq, hi / nyq], btype='band', output='sos')
        return sosfilt(sos, data)

    y_bass = _lpf(y, 250.0)
    y_mid  = _bpf(y, 250.0, 4000.0)
    y_high = _hpf(y, 4000.0)

    beat_samples = (beat_times * sr).astype(int)
    n = len(beat_times)

    def _rms(seg: np.ndarray) -> float:
        return float(np.sqrt(np.mean(seg ** 2))) if len(seg) > 0 else 0.0

    rms_t = np.zeros(n)
    rms_b = np.zeros(n)
    rms_m = np.zeros(n)
    rms_h = np.zeros(n)

    for i in range(n):
        s0 = int(beat_samples[i])
        s1 = int(beat_samples[i + 1]) if i + 1 < n else len(y)
        rms_t[i] = _rms(y[s0:s1])
        rms_b[i] = _rms(y_bass[s0:s1])
        rms_m[i] = _rms(y_mid[s0:s1])
        rms_h[i] = _rms(y_high[s0:s1])

    def _norm(arr: np.ndarray) -> list[float]:
        m = float(arr.max())
        return (arr / m).tolist() if m > 0 else arr.tolist()

    return _norm(rms_t), _norm(rms_b), _norm(rms_m), _norm(rms_h)


def _compute_beat_event_scores(
    beat_times: np.ndarray,
    onsets: list[LibrosaOnset],
    bass_onsets: list[LibrosaOnset],
    harmonic_changes: list[LibrosaHarmonicChange],
) -> tuple[list[float], list[float], list[float]]:
    """
    For each beat interval, sum the strength/novelty of events that land in it.
    Returns three parallel lists (onset_scores, bass_onset_scores, harmonic_scores),
    each normalised 0–1 across the song (max = 1.0).
    """
    n = len(beat_times)
    if n == 0:
        return [], [], []

    beat_ms = (beat_times * 1000).astype(int)

    # Cell boundaries: each beat owns [beat_ms[i], beat_ms[i+1]).
    # The last beat owns [beat_ms[-1], beat_ms[-1] + median_interval) so late
    # onsets that fall after the final beat timestamp don't pile into it.
    median_interval = int(np.median(np.diff(beat_ms))) if n > 1 else 500
    cell_end = np.append(beat_ms[1:], beat_ms[-1] + median_interval)

    onset_raw    = np.zeros(n)
    bass_raw     = np.zeros(n)
    harmonic_raw = np.zeros(n)

    for o in onsets:
        idx = int(np.searchsorted(beat_ms, o.ms, side='right')) - 1
        if 0 <= idx < n and o.ms < cell_end[idx]:
            onset_raw[idx] += o.strength

    for bo in bass_onsets:
        idx = int(np.searchsorted(beat_ms, bo.ms, side='right')) - 1
        if 0 <= idx < n and bo.ms < cell_end[idx]:
            bass_raw[idx] += bo.strength

    for hc in harmonic_changes:
        idx = int(np.searchsorted(beat_ms, hc.ms, side='right')) - 1
        if 0 <= idx < n and hc.ms < cell_end[idx]:
            harmonic_raw[idx] += hc.novelty

    # Drop the last beat — it's a partial cell and accumulates trailing events.
    onset_raw    = onset_raw[:-1]
    bass_raw     = bass_raw[:-1]
    harmonic_raw = harmonic_raw[:-1]

    def _norm(arr: np.ndarray) -> list[float]:
        m = float(arr.max())
        return (arr / m).tolist() if m > 0 else arr.tolist()

    return _norm(onset_raw), _norm(bass_raw), _norm(harmonic_raw)


def _detect_harmonic_changes(y: np.ndarray, sr: int, beat_frames: np.ndarray) -> list[LibrosaHarmonicChange]:
    """
    Detect chord/tonal change points using chroma CQT novelty.
    Returns a list of LibrosaHarmonicChange objects.
    """
    import librosa
    from scipy.signal import find_peaks

    if len(beat_frames) < 4:
        return []

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    bf = np.clip(beat_frames, 0, chroma.shape[1] - 1)
    chroma_sync = librosa.util.sync(chroma, bf, aggregate=np.median)

    # Column-to-column L1 distance as novelty
    diff = np.sum(np.abs(np.diff(chroma_sync, axis=1)), axis=0)
    diff = np.pad(diff, (0, 1), mode='edge')

    if diff.max() > 0:
        diff_norm = diff / diff.max()
    else:
        return []

    peaks, _ = find_peaks(diff_norm, distance=settings.librosa_harmonic_min_beats,
                          height=settings.librosa_harmonic_min_height)

    changes = []
    times = librosa.frames_to_time(bf, sr=sr)
    for p in peaks:
        if p < len(times):
            changes.append(LibrosaHarmonicChange(
                ms=int(times[p] * 1000),
                novelty=round(float(diff_norm[p]), 3),
            ))

    return changes


# ── Async wrapper ─────────────────────────────────────────────────────────────

async def analyze_async(meta: AudioShapeMeta) -> Optional[LibrosaAnalysis]:
    """Run analysis in a thread executor so it doesn't block the event loop."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, analyze_sync, meta)
    except Exception as exc:
        logger.error("Librosa analysis failed for %s: %s", meta.title, exc)
        return None
