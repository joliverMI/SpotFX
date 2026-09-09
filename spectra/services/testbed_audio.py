"""Test-bed audio retention — ITS OWN policy, deliberately independent of
production's `settings.audio_wav_max_songs` / `services/librosa_service.py`'s
`manage_wav_retention()` (data/spotfx-music-analysis-plan/report.md's
Methodology + "Two decisions this plan surfaces" #1, Admiral-approved
2026-09-09: test-bed audio pinning).

A pinned song's WAV is COPIED (never moved, never symlinked) from
`storage/audio_shapes/` into `storage/spectra/testbed/audio/` — a directory
`manage_wav_retention()`'s own glob (scoped to `AUDIO_SHAPES_DIR` only)
never reaches, so a pin structurally cannot be evicted by production's LRU
cap. Unpinning deletes only the copy; production's own WAV (if it still has
one) is never touched — this module never writes into `AUDIO_SHAPES_DIR`.

Alongside the WAV copy, a downsampled min/max peaks JSON is computed ONCE
at pin time (`_PEAKS_BUCKETS` buckets across the whole file) for the test
bed's waveform lane — the point of pinning at all is to have real audio for
offline engine precompute AND a real waveform to eyeball, so both land in
one action rather than a second "compute peaks" step he'd have to remember.

`pinned_audio.json` is the registry: `{uri: {pinned_at, source_wav_name}}`.
Absence from it means "not pinned" — production's own retention still
governs whether a source WAV to pin FROM even exists (see `pin()`'s own
refusal when it doesn't).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from spectra import config
from spectra.services import analysis_reader

logger = logging.getLogger(__name__)

_PEAKS_BUCKETS = 2000

# pin()/unpin() run off the event loop (spectra/api/testbed.py hands them to
# asyncio.to_thread — a WAV copy + decode is seconds of blocking I/O), so
# two presses can genuinely overlap; the registry is a read-modify-write
# and must not lose one of them.
_registry_lock = threading.Lock()


def _safe_stem(uri: str) -> str:
    return uri.replace(":", "_").replace("/", "_")


def _replace_with(path: Path, fill: Callable[[str], None]) -> None:
    """tmp + os.replace, the same atomic-landing shape every other store in
    this feature uses: `fill(tmp_path)` writes the whole file, and `path`
    either keeps its previous contents or becomes the complete new one —
    never a truncated copy a crash mid-write would leave behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    os.close(fd)
    try:
        fill(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_registry() -> dict:
    """A malformed or hand-edited file reads as an EMPTY registry, never as
    whatever it happened to parse to — pin()/unpin() do a read-modify-write
    of this, and a non-dict would raise mid-pin with the WAV copy already
    landed."""
    if config.TESTBED_PINNED_FILE.exists():
        try:
            data = json.loads(config.TESTBED_PINNED_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("testbed pinned_audio.json parse failed: %s", exc)
            return {}
        if isinstance(data, dict):
            return data
        logger.warning("testbed pinned_audio.json is a %s, not an object — "
                       "reading it as empty", type(data).__name__)
    return {}


def _save_registry(data: dict) -> None:
    _replace_with(config.TESTBED_PINNED_FILE,
                  lambda tmp: Path(tmp).write_text(json.dumps(data, indent=2),
                                                   encoding="utf-8"))


def wav_copy_path(uri: str) -> Path:
    return config.TESTBED_AUDIO_DIR / f"{_safe_stem(uri)}.wav"


def peaks_path(uri: str) -> Path:
    return config.TESTBED_AUDIO_DIR / f"{_safe_stem(uri)}.peaks.json"


def is_pinned(uri: str) -> bool:
    return uri in _load_registry()


def list_pinned() -> dict:
    return _load_registry()


def _compute_peaks(wav_path: Path) -> dict:
    """min/max envelope over `_PEAKS_BUCKETS` buckets — a lightweight
    waveform-lane render, not a full-resolution sample dump (a 4-minute
    44.1kHz WAV is ~44M samples; the browser only needs enough points to
    fill its own pixel width)."""
    import soundfile as sf
    data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    n = len(data)
    if n == 0:
        return {"sample_rate": sample_rate, "duration_ms": 0, "mins": [], "maxs": []}
    bucket_size = max(1, n // _PEAKS_BUCKETS)
    n_buckets = (n + bucket_size - 1) // bucket_size
    mins: list[float] = []
    maxs: list[float] = []
    for i in range(n_buckets):
        chunk = data[i * bucket_size:(i + 1) * bucket_size]
        if chunk.size == 0:
            continue
        mins.append(float(chunk.min()))
        maxs.append(float(chunk.max()))
    duration_ms = int(n / sample_rate * 1000)
    return {"sample_rate": sample_rate, "duration_ms": duration_ms,
            "mins": mins, "maxs": maxs}


def pin(uri: str) -> dict:
    """Copy production's current WAV for `uri` into the test bed's own
    retained-audio directory and compute its peaks. Refuses (returns
    {"status": "no_source_wav"}) when production has no WAV for this song
    right now — pinning can only retain audio that exists; it never
    triggers a (re)capture (that's a live-room action, out of this
    read-mostly module's scope — see the Rooms Phase-1 recapture note in
    the plan report)."""
    stem = analysis_reader.stem_for_uri(uri)
    if stem is None:
        return {"status": "unknown_song"}
    source = config.AUDIO_SHAPES_DIR / f"{stem}.wav"
    if not source.exists():
        return {"status": "no_source_wav"}

    dest = wav_copy_path(uri)
    _replace_with(dest, lambda tmp: shutil.copyfile(source, tmp))

    try:
        peaks = _compute_peaks(dest)
        _replace_with(peaks_path(uri),
                      lambda tmp: Path(tmp).write_text(json.dumps(peaks), encoding="utf-8"))
        peaks_ok = True
    except Exception as exc:
        logger.warning("testbed pin: peaks computation failed for %s: %s", uri, exc)
        peaks_ok = False

    with _registry_lock:
        registry = _load_registry()
        registry[uri] = {"pinned_at": time.time(), "source_wav_name": source.name}
        _save_registry(registry)
    logger.info("testbed audio pinned: %s (%s)", uri, source.name)
    return {"status": "pinned", "peaks_computed": peaks_ok}


def unpin(uri: str) -> bool:
    with _registry_lock:
        registry = _load_registry()
        if uri not in registry:
            return False
        del registry[uri]
        _save_registry(registry)
    for p in (wav_copy_path(uri), peaks_path(uri)):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    logger.info("testbed audio unpinned: %s", uri)
    return True


def status(uri: str, *, stem_index: Optional[dict[str, str]] = None,
           registry: Optional[dict] = None) -> dict:
    """`stem_index` / `registry`: snapshots (analysis_reader.stem_index(),
    list_pinned()) for a caller walking the whole corpus, so a listing
    reads each file once instead of once per song."""
    if registry is None:
        registry = _load_registry()
    entry = registry.get(uri)
    if not isinstance(entry, dict):
        entry = None
    stem = (analysis_reader.stem_for_uri(uri) if stem_index is None
            else stem_index.get(uri))
    has_source_wav = stem is not None and (config.AUDIO_SHAPES_DIR / f"{stem}.wav").exists()
    return {
        "pinned": entry is not None,
        "pinned_at": entry.get("pinned_at") if entry else None,
        "has_source_wav": has_source_wav,
        "has_peaks": peaks_path(uri).exists(),
    }


def capture_offset_ms(uri: str) -> Optional[int]:
    """The SONG-TIME of the WAV's first sample, or None when it cannot be
    established — a production capture starts MID-SONG (URI detection lags
    5-10s), so a pinned WAV's sample 0 is not song-time 0 and a waveform
    drawn from x=0 sits left of every mark lane by exactly this much.

    Read from the `.npz` sidecar's own first `timestamps_ms`, which is the
    song-relative stamp `AudioCaptureStream` gave the first PCM it held
    (`_pcm_start_song_ms`) — a measured quantity from the same capture.
    Deliberately NOT `LibrosaAnalysis.librosa_offset_ms`: AGENTS.md records
    that stored value as unreliable (nonzero on ~74% of analyses, outliers
    into the tens of thousands of seconds), and this module's own npz
    fallback lane already positions by these same timestamps.

    None means UNKNOWN and callers must say so rather than assume 0 — the
    npz can be absent (a pin whose sidecar aged out) or unreadable."""
    shape = load_npz_shape(uri)
    if not shape:
        return None
    stamps = shape.get("timestamps_ms") or []
    if not stamps:
        return None
    try:
        return max(0, int(stamps[0]))
    except (TypeError, ValueError):
        return None


def load_npz_shape(uri: str) -> Optional[dict]:
    """The coarse RMS-envelope fallback the report's own Methodology names
    ("the test bed should visibly say 'coarse energy view only, no
    waveform' rather than silently rendering nothing when a .wav has aged
    out") — read-only from production's `.npz` sidecar (retained for every
    played song, unlike the WAV; services/audio_analyzer.py's own
    save/load shape). Never touched by production's WAV-only retention cap,
    so this is available even for songs the test bed hasn't pinned."""
    stem = analysis_reader.stem_for_uri(uri)
    if stem is None:
        return None
    npz_path = config.AUDIO_SHAPES_DIR / f"{stem}.npz"
    if not npz_path.exists():
        return None
    try:
        data = np.load(npz_path)
        timestamps = data["timestamps_ms"].astype(int).tolist()
        return {
            "timestamps_ms": timestamps,
            "rms_total": data["rms_total"].astype(float).tolist(),
            "duration_ms": int(timestamps[-1]) if timestamps else 0,
        }
    except Exception as exc:
        logger.warning("testbed: failed to read npz shape for %s: %s", uri, exc)
        return None


def load_peaks(uri: str) -> Optional[dict]:
    p = peaks_path(uri)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
