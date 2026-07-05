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
from dataclasses import dataclass
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

# Analysis format version stamped into meta + sidecar on completion.
# 2 = MFCC added; 3 = HPSS bass/snare onset passes + decluttered overall onsets.
LIBROSA_VERSION = 3

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


# Lookup index for librosa analysis files. Built lazily and updated when
# `analyze_async` saves a new analysis. The previous implementation globbed
# every `*.librosa.json` and parsed each on every Spotify poll — same
# anti-pattern as the audio_shape sidecar lookup, contributing to the
# json.decoder.raw_decode at the top of py-spy.
_librosa_index: dict[str, str] = {}
_librosa_index_built: list[bool] = [False]


def _build_librosa_index() -> None:
    _librosa_index.clear()
    for p in AUDIO_SHAPES_DIR.glob("*.librosa.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri = data.get("spotify_uri") or ""
        if uri:
            # Strip the ".librosa" suffix so the stem matches the audio shape
            # filename — handy for joining with `librosa_json_path(meta)`.
            _librosa_index[uri] = p.name
    _librosa_index_built[0] = True
    logger.info("Librosa index built: %d URIs", len(_librosa_index))


def get_analysis_by_uri(spotify_uri: str) -> Optional[LibrosaAnalysis]:
    """Find and load librosa analysis for a URI without requiring a loaded meta."""
    if not _librosa_index_built[0]:
        _build_librosa_index()
    fname = _librosa_index.get(spotify_uri)
    if fname is None:
        _build_librosa_index()
        fname = _librosa_index.get(spotify_uri)
        if fname is None:
            return None
    p = AUDIO_SHAPES_DIR / fname
    try:
        return LibrosaAnalysis(**json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


# ── WAV retention ─────────────────────────────────────────────────────────────

def _last_played_mtime(wav: Path) -> float:
    """
    Last-played proxy for a WAV: the audio-shape sidecar .json is rewritten
    every time the song plays (offset locks persist setlist_offsets/history),
    so its mtime tracks plays while the WAV mtime only tracks capture date.
    """
    mtime = wav.stat().st_mtime
    sidecar = wav.with_suffix(".json")
    try:
        mtime = max(mtime, sidecar.stat().st_mtime)
    except OSError:
        pass
    return mtime


def manage_wav_retention() -> None:
    """Delete least-recently-played WAVs when count exceeds settings.audio_wav_max_songs."""
    max_songs = settings.audio_wav_max_songs
    if max_songs <= 0:
        return
    wavs = sorted(AUDIO_SHAPES_DIR.glob("*.wav"), key=_last_played_mtime)
    to_delete = wavs[: max(0, len(wavs) - max_songs)]
    for p in to_delete:
        try:
            p.unlink()
            logger.info("WAV retention: deleted %s", p.name)
        except Exception as exc:
            logger.warning("WAV retention: could not delete %s: %s", p.name, exc)


# ── WAV↔NPZ alignment ─────────────────────────────────────────────────────────

def _measure_wav_npz_bias(meta: AudioShapeMeta) -> Optional[int]:
    """
    Measure the offset that maps WAV time to the NPZ (song-relative) timeline
    by cross-correlating the WAV's band RMS against the stored NPZ bands,
    reusing the benchmark harness. Measured fresh each time (no cache — the
    WAV/NPZ pair changes on recapture). Returns None when no ≥2-window xcorr
    consensus forms (e.g. sidecar has no xcorr_windows).
    """
    try:
        from bench.calibrate import measure_wav_bias
        from bench.replay import load_song_assets
        from bench.simulate import load_wav, make_frames

        stem = Path(meta.npz_file).stem
        assets = load_song_assets(stem)
        frames = make_frames(load_wav(assets["wav_path"]))
        return measure_wav_bias(assets, frames)
    except Exception as exc:
        logger.warning("WAV↔NPZ bias measurement failed for %s: %s", meta.title, exc)
        return None


# ── Onset detection helpers ───────────────────────────────────────────────────
# Factored into pure functions with explicit params so scripts/tune_onsets.py
# can grid-search candidates in memory without touching stored sidecars.

@dataclass
class OnsetParams:
    delta: float
    wait_ms: int
    min_strength: float
    fmin: Optional[int] = None
    fmax: Optional[int] = None


def overall_onset_params() -> OnsetParams:
    return OnsetParams(
        delta=settings.librosa_onset_delta,
        wait_ms=settings.librosa_onset_wait_ms,
        min_strength=settings.librosa_onset_min_strength,
    )


def bass_onset_params() -> OnsetParams:
    return OnsetParams(
        delta=settings.librosa_bass_onset_delta,
        wait_ms=settings.librosa_bass_onset_wait_ms,
        min_strength=settings.librosa_bass_min_strength,
        fmax=settings.librosa_bass_fmax,
    )


def snare_onset_params() -> OnsetParams:
    return OnsetParams(
        delta=settings.librosa_snare_onset_delta,
        wait_ms=settings.librosa_snare_onset_wait_ms,
        min_strength=settings.librosa_snare_min_strength,
        fmin=settings.librosa_snare_fmin,
        fmax=settings.librosa_snare_fmax,
    )


def compute_percussive(y: np.ndarray, sr: int, margin: float) -> np.ndarray:
    """
    Percussive component via HPSS, shared by the bass and snare detectors so
    sustained harmonic content (bass-guitar notes, pads) doesn't fire onsets.
    margin <= 1.0 disables the separation and returns y unchanged.
    """
    if margin <= 1.0:
        return y
    import librosa
    _, y_perc = librosa.effects.hpss(y, margin=(1.0, margin))
    return y_perc


def compute_onset_envelope(
    y: np.ndarray, sr: int, fmin: Optional[int] = None, fmax: Optional[int] = None,
) -> np.ndarray:
    """Band-limited onset-strength envelope with median aggregation across mel
    bands (median is less prone than mean to broadband noise inflating peaks)."""
    import librosa
    kwargs = {}
    if fmin:
        kwargs["fmin"] = fmin
    if fmax:
        kwargs["fmax"] = fmax
    if fmin or fmax:
        # Scale the mel-band count to the band's share of the full mel range:
        # 128 bands crammed into e.g. 0-250 Hz leaves most filters over empty
        # FFT bins, and median aggregation of mostly-empty bands returns an
        # all-zero envelope (no onsets at all).
        lo = float(fmin or 0.0)
        hi = float(fmax or sr / 2.0)
        full_mel = librosa.hz_to_mel(sr / 2.0)
        frac = (librosa.hz_to_mel(hi) - librosa.hz_to_mel(lo)) / full_mel
        kwargs["n_mels"] = int(np.clip(round(128 * frac), 8, 128))
    return librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median, **kwargs)


def pick_onset_frames(
    env: np.ndarray, sr: int, *,
    delta: float, wait_ms: int, min_strength: float, hop_length: int = 512,
) -> np.ndarray:
    """
    Peak-pick onset frames from an envelope. onset_detect normalizes the
    envelope 0-1 (normalize=True default), so delta and min_strength are both
    on a 0-1 scale. wait_ms enforces a minimum gap between onsets.
    """
    import librosa
    wait = max(1, round(wait_ms / 1000 * sr / hop_length))
    frames = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, units='frames', delta=delta, wait=wait,
    )
    frames = np.asarray(frames, dtype=int)
    frames = frames[frames < len(env)]
    if min_strength > 0 and len(frames):
        env_max = float(env.max()) if env.max() > 0 else 1.0
        frames = frames[(env[frames] / env_max) >= min_strength]
    return frames


def onsets_from_frames(env: np.ndarray, frames: np.ndarray, sr: int) -> list[LibrosaOnset]:
    import librosa
    env_max = float(env.max()) if env.max() > 0 else 1.0
    times = librosa.frames_to_time(frames, sr=sr)
    return [
        LibrosaOnset(ms=int(t * 1000), strength=round(float(env[f]) / env_max, 3))
        for t, f in zip(times, frames)
    ]


def pick_onsets(
    env: np.ndarray, sr: int, *,
    delta: float, wait_ms: int, min_strength: float, hop_length: int = 512,
) -> list[LibrosaOnset]:
    frames = pick_onset_frames(
        env, sr, delta=delta, wait_ms=wait_ms, min_strength=min_strength, hop_length=hop_length,
    )
    return onsets_from_frames(env, frames, sr)


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
    # Full-spectrum, on raw y (sections reuse onset_frames for density).
    op = overall_onset_params()
    onset_env = compute_onset_envelope(y, sr)
    onset_frames = pick_onset_frames(
        onset_env, sr, delta=op.delta, wait_ms=op.wait_ms, min_strength=op.min_strength,
    )
    onsets = onsets_from_frames(onset_env, onset_frames, sr)

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

    # ── Bass + snare onsets (shared percussive component) ─────────────────
    y_perc = compute_percussive(y, sr, settings.librosa_hpss_margin)
    bp, sp = bass_onset_params(), snare_onset_params()
    bass_env = compute_onset_envelope(y_perc, sr, fmin=bp.fmin, fmax=bp.fmax)
    snare_env = compute_onset_envelope(y_perc, sr, fmin=sp.fmin, fmax=sp.fmax)
    bass_onsets = pick_onsets(
        bass_env, sr, delta=bp.delta, wait_ms=bp.wait_ms, min_strength=bp.min_strength)
    snare_onsets = pick_onsets(
        snare_env, sr, delta=sp.delta, wait_ms=sp.wait_ms, min_strength=sp.min_strength)

    # Dense scoring passes: the per-beat *_score buckets feed the embedded
    # trigger generator, so they must reflect true hit density (rapid kick
    # rolls) — a permissive pick, not the decluttered display lists above.
    sd, sw = settings.librosa_score_delta, settings.librosa_score_wait_ms
    onsets_dense = pick_onsets(onset_env, sr, delta=sd, wait_ms=sw, min_strength=0.0)
    bass_dense   = pick_onsets(bass_env,  sr, delta=sd, wait_ms=sw, min_strength=0.0)
    snare_dense  = pick_onsets(snare_env, sr, delta=sd, wait_ms=sw, min_strength=0.0)

    # ── Structural sections ────────────────────────────────────────────────
    sections = _detect_sections(y, sr, beat_frames, tempo_bpm, onset_frames)

    # ── Harmonic changes ──────────────────────────────────────────────────
    harmonic_changes = _detect_harmonic_changes(y, sr, beat_frames)

    # ── Per-beat event scores (onset / bass / snare / harmonic) ───────────
    onset_scores, bass_scores, snare_scores, harmonic_scores = _compute_beat_event_scores(
        beat_times, onsets_dense, bass_dense, snare_dense, harmonic_changes,
    )

    # ── Per-beat MFCC features ──────────────────────────────────────────
    # 13 MFCCs + 13 delta-MFCCs, beat-synced and z-score normalised per song.
    mfcc_raw = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_delta_raw = librosa.feature.delta(mfcc_raw)
    bf_clip = np.clip(beat_frames, 0, mfcc_raw.shape[1] - 1)
    mfcc_sync = librosa.util.sync(mfcc_raw, bf_clip, aggregate=np.mean)     # (13, n_beats)
    mfcc_delta_sync = librosa.util.sync(mfcc_delta_raw, bf_clip, aggregate=np.mean)
    # Z-score normalise each coefficient across beats (cross-song comparability)
    for row in range(mfcc_sync.shape[0]):
        mu, std = mfcc_sync[row].mean(), mfcc_sync[row].std()
        if std > 1e-9:
            mfcc_sync[row] = (mfcc_sync[row] - mu) / std
        else:
            mfcc_sync[row] = 0.0
        mu_d, std_d = mfcc_delta_sync[row].mean(), mfcc_delta_sync[row].std()
        if std_d > 1e-9:
            mfcc_delta_sync[row] = (mfcc_delta_sync[row] - mu_d) / std_d
        else:
            mfcc_delta_sync[row] = 0.0
    n_mfcc_beats = mfcc_sync.shape[1]

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
            snare_onset_score=round(snare_scores[i],   3),
            harmonic_score  =round(harmonic_scores[i], 3),
            mfcc=[round(float(mfcc_sync[c, i]), 3) for c in range(13)] if i < n_mfcc_beats else [],
            mfcc_delta=[round(float(mfcc_delta_sync[c, i]), 3) for c in range(13)] if i < n_mfcc_beats else [],
        )
        for i, t in enumerate(beat_times[:-1])  # last beat dropped
    ]

    # ── Capture start offset ───────────────────────────────────────────────
    # The WAV starts at t=0 (start of capture), but audio shape timestamps
    # are song-relative (capture begins mid-song). Preferred seed: xcorr the
    # WAV against the stored NPZ bands (the WAV writer and the RMS block
    # timestamps disagree by a per-song bias, typically ~1 s). Fallback when
    # no xcorr consensus forms: assume the WAV starts at timestamps_ms[0].
    capture_offset_ms = 0
    bias = _measure_wav_npz_bias(meta)
    if bias is not None:
        capture_offset_ms = int(bias)
        logger.info("Librosa offset seeded from WAV↔NPZ xcorr: %+d ms (%s)", bias, meta.title)
    else:
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
        snare_onsets=snare_onsets,
        sections=sections,
        harmonic_changes=harmonic_changes,
    )

    jpath = librosa_json_path(meta)
    jpath.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    # Keep the URI index in sync so the next get_analysis_by_uri call hits
    # the cached path instead of rescanning the audio_shapes directory.
    if meta.spotify_uri:
        _librosa_index[meta.spotify_uri] = jpath.name

    # Stamp the sidecar with the analysis format version
    meta.librosa_version = LIBROSA_VERSION
    sidecar_path = (AUDIO_SHAPES_DIR / meta.npz_file).with_suffix(".json")
    if sidecar_path.exists():
        try:
            sidecar_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar_data["librosa_version"] = LIBROSA_VERSION
            sidecar_path.write_text(json.dumps(sidecar_data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not update sidecar librosa_version: %s", exc)

    logger.info(
        "Librosa analysis complete: %s — %.1f BPM, %d beats, %d onsets, %d bass, %d snare, %d sections, %d harmonic",
        meta.title, tempo_bpm, len(beats), len(onsets), len(bass_onsets), len(snare_onsets),
        len(sections), len(harmonic_changes),
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


def _detect_bass_onsets(
    y: np.ndarray, sr: int, params: Optional[OnsetParams] = None,
) -> list[LibrosaOnset]:
    """
    Kick / sub-bass hits: low-frequency onset envelope (fmax ~250 Hz) over the
    percussive component (pass y_perc from compute_percussive so sustained
    bass-guitar notes don't fire).
    """
    p = params or bass_onset_params()
    env = compute_onset_envelope(y, sr, fmin=p.fmin, fmax=p.fmax)
    return pick_onsets(env, sr, delta=p.delta, wait_ms=p.wait_ms, min_strength=p.min_strength)


def _detect_snare_onsets(
    y: np.ndarray, sr: int, params: Optional[OnsetParams] = None,
) -> list[LibrosaOnset]:
    """
    Snare / clap hits: mid-band onset envelope over the percussive component.
    Snares are a broadband burst with dominant 1.5-6 kHz energy; hi-hats
    concentrate above ~6-8 kHz at lower energy, so the band limit plus the
    strength floor suppresses hat false-positives without a second pass.
    """
    p = params or snare_onset_params()
    env = compute_onset_envelope(y, sr, fmin=p.fmin, fmax=p.fmax)
    return pick_onsets(env, sr, delta=p.delta, wait_ms=p.wait_ms, min_strength=p.min_strength)


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
    snare_onsets: list[LibrosaOnset],
    harmonic_changes: list[LibrosaHarmonicChange],
) -> tuple[list[float], list[float], list[float], list[float]]:
    """
    For each beat interval, sum the strength/novelty of events that land in it.
    Returns four parallel lists (onset, bass, snare, harmonic scores),
    each normalised 0–1 across the song (max = 1.0).
    """
    n = len(beat_times)
    if n == 0:
        return [], [], [], []

    beat_ms = (beat_times * 1000).astype(int)

    # Cell boundaries: each beat owns [beat_ms[i], beat_ms[i+1]).
    # The last beat owns [beat_ms[-1], beat_ms[-1] + median_interval) so late
    # onsets that fall after the final beat timestamp don't pile into it.
    median_interval = int(np.median(np.diff(beat_ms))) if n > 1 else 500
    cell_end = np.append(beat_ms[1:], beat_ms[-1] + median_interval)

    onset_raw    = np.zeros(n)
    bass_raw     = np.zeros(n)
    snare_raw    = np.zeros(n)
    harmonic_raw = np.zeros(n)

    for o in onsets:
        idx = int(np.searchsorted(beat_ms, o.ms, side='right')) - 1
        if 0 <= idx < n and o.ms < cell_end[idx]:
            onset_raw[idx] += o.strength

    for bo in bass_onsets:
        idx = int(np.searchsorted(beat_ms, bo.ms, side='right')) - 1
        if 0 <= idx < n and bo.ms < cell_end[idx]:
            bass_raw[idx] += bo.strength

    for so in snare_onsets:
        idx = int(np.searchsorted(beat_ms, so.ms, side='right')) - 1
        if 0 <= idx < n and so.ms < cell_end[idx]:
            snare_raw[idx] += so.strength

    for hc in harmonic_changes:
        idx = int(np.searchsorted(beat_ms, hc.ms, side='right')) - 1
        if 0 <= idx < n and hc.ms < cell_end[idx]:
            harmonic_raw[idx] += hc.novelty

    # Drop the last beat — it's a partial cell and accumulates trailing events.
    onset_raw    = onset_raw[:-1]
    bass_raw     = bass_raw[:-1]
    snare_raw    = snare_raw[:-1]
    harmonic_raw = harmonic_raw[:-1]

    def _norm(arr: np.ndarray) -> list[float]:
        m = float(arr.max())
        return (arr / m).tolist() if m > 0 else arr.tolist()

    return _norm(onset_raw), _norm(bass_raw), _norm(snare_raw), _norm(harmonic_raw)


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
    """Run analysis in a single-use subprocess so all numpy/librosa heap is
    returned to the OS when the worker exits (max_tasks_per_child=1).
    On success, pre-generate and persist analyzed triggers for this URI so
    the next playback is a cache hit instead of paying the ~1s pipeline cost.
    """
    import asyncio
    from concurrent.futures import ProcessPoolExecutor
    try:
        loop = asyncio.get_event_loop()
        with ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) as pool:
            result = await loop.run_in_executor(pool, analyze_sync, meta)
    except Exception as exc:
        logger.error("Librosa analysis failed for %s: %s", meta.title, exc)
        return None

    if result is not None and getattr(meta, "spotify_uri", None):
        async def _prewarm(uri=meta.spotify_uri, title=meta.title):
            try:
                from services import analyzed_trigger_store
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: analyzed_trigger_store.generate_for_uri(uri, save_cache=True),
                )
            except Exception as exc:
                logger.warning("Analyzed-trigger pre-generation failed for %s: %s", title, exc)
        asyncio.create_task(_prewarm())
    return result
