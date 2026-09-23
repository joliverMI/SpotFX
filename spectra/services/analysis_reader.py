"""Read-only analysis storage reader — the bridge's storage half.

SPECTRA's own reader for spot-effects' analysis artifacts (bridge contract:
one-directional, read-only, no spot-effects imports):

  storage/audio_shapes/<stem>.json          — capture sidecars carrying
      spotify_uri (the URI → stem index, same skip-librosa rule as the
      spot-effects reader: *.librosa.json shares the uri field and must not
      shadow the sidecar)
  storage/audio_shapes/<stem>.librosa.json  — librosa analysis; sections
      carry start_ms/end_ms/energy_rms (normalized 0–1 per song), beats
      carry ms + is_downbeat (beats_for_uri, read by the music-analysis
      test bed's librosa baseline engine)
  storage/training_profiles.json            — genre buckets

Section and beat times are read RAW — the standing librosa_offset_ms
rule: the stored `LibrosaAnalysis.librosa_offset_ms` field is noise (see
AGENTS.md), and sections_for_uri/beats_for_uri never apply it. That rule
is unrelated to and unchanged by section_energy_at()'s own capture-offset
shift below (data/transition-alignment-plan/report.md §2.1): a section's
start_ms/end_ms is in the CAPTURED-WAV frame, but a caller's own now_ms is
song-relative, so section_energy_at() shifts the comparison by the
capture offset (testbed_audio.capture_offset_ms, a measured, reliable
quantity — not librosa_offset_ms) before matching. section_energy_at() is
the ported signal_resolver._section_energy: containing section, else
nearest, clamped 0–1. Missing files degrade to None — the callers' stated
fallbacks apply (intensity 0.5 neutral, no genre bucket).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from spectra import config

logger = logging.getLogger(__name__)

# uri → audio-shape file stem. Built lazily, rebuilt on miss so freshly
# captured songs appear without a restart (the spot-effects index pattern).
_shape_index: dict[str, str] = {}
_index_built = False


def _build_index() -> dict[str, str]:
    global _shape_index, _index_built
    fresh: dict[str, str] = {}
    shapes_dir = config.AUDIO_SHAPES_DIR
    if shapes_dir.exists():
        for path in shapes_dir.glob("*.json"):
            if path.name.endswith(".librosa.json"):
                continue
            try:
                uri = json.loads(path.read_text(encoding="utf-8")).get(
                    "spotify_uri") or ""
            except Exception:
                continue
            if uri:
                fresh[uri] = path.stem
    _shape_index = fresh
    _index_built = True
    return fresh


def stem_for_uri(uri: str) -> Optional[str]:
    """uri -> audio-shape file stem, rebuilding the index once on a miss so
    a freshly captured song appears without a restart."""
    if not _index_built:
        _build_index()
    stem = _shape_index.get(uri)
    if stem is None:
        _build_index()
        stem = _shape_index.get(uri)
    return stem


def stem_index() -> dict[str, str]:
    """The whole uri -> stem index after ONE rebuild — for a bulk listing
    over many URIs. stem_for_uri() rebuilds the entire index (a glob +
    parse of every sidecar under AUDIO_SHAPES_DIR) on every MISS, which is
    right for a live lookup of one freshly captured song and wrong for a
    corpus walk, where every song without captured audio would pay a full
    rebuild per lookup.

    A rebuild builds a NEW dict and rebinds `_shape_index` in one
    assignment; it never clears the dict readers already hold. This index
    is read on the event-loop thread every tick (bridge.intensity() via
    section_energy_at) while the test bed's corpus listing rebuilds it
    from a worker thread, so every reader sees either the old complete
    index or the new complete one, and the returned dict is safe to hold
    across a whole walk."""
    _build_index()
    return _shape_index


def has_librosa_analysis(stem: Optional[str]) -> bool:
    """Whether <stem>.librosa.json EXISTS — a stat, deliberately not a
    parse. The whole-corpus listing needs one availability bit per song
    and discards everything a parse would build; against his real
    storage/audio_shapes/ that is 965 files and 417MB re-read on every
    listing (and every pin/unpin/promotion that invalidates it). A file
    that exists but holds no usable sections/beats still reports available
    here; the lane fetch (librosa_marks_for_stem, the ONE parse) is what
    answers that, and reports the lane unavailable."""
    if stem is None:
        return False
    return (config.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").exists()


def librosa_analysis_for_stem(stem: Optional[str]) -> Optional[dict]:
    """The parsed <stem>.librosa.json, or None when there is no stem, no
    file, or it doesn't parse — ONE read for every key a caller wants
    (sections, beats, ...) rather than one parse per key."""
    if stem is None:
        return None
    path = config.AUDIO_SHAPES_DIR / f"{stem}.librosa.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def sections_for_uri(uri: str) -> Optional[list]:
    doc = librosa_analysis_for_stem(stem_for_uri(uri))
    return (doc or {}).get("sections") or None


def beats_for_uri(uri: str) -> Optional[list]:
    """Raw beat list (each a LibrosaBeat dict: ms + is_downbeat + per-beat
    RMS/onset scores) from the same .librosa.json sections_for_uri reads —
    the test bed's own librosa baseline engine
    (spectra/services/testbed_engines.py) reads both off one
    librosa_analysis_for_stem() parse."""
    doc = librosa_analysis_for_stem(stem_for_uri(uri))
    return (doc or {}).get("beats") or None


def tempo_bpm_for_uri(uri: str) -> Optional[float]:
    """The song's librosa `tempo_bpm` (LibrosaAnalysis's own field,
    services/librosa_service.py), for anything that needs a beat-length
    estimate — the music-analysis test bed's per-lane tolerance default
    reads this, since a beat/downbeat lane's tolerance has to shrink with
    the song's tempo. None when there is no analysis or the field is
    missing/malformed."""
    doc = librosa_analysis_for_stem(stem_for_uri(uri))
    if not doc:
        return None
    try:
        bpm = float(doc.get("tempo_bpm"))
    except (TypeError, ValueError):
        return None
    return bpm if bpm > 0 else None


_CaptureOffsetSignature = Optional[tuple]
_capture_offset_cache: dict[str, tuple[_CaptureOffsetSignature, int]] = {}


def _capture_offset_for(uri: str) -> int:
    """testbed_audio.capture_offset_ms_or_zero(uri), cached per URI —
    section_energy_at is read on the event-loop thread every ~200ms tick
    (bridge.intensity(), TICK_S in trigger_engine.py), and the offset's own
    source (an .npz read, testbed_audio.load_npz_shape) is a real file
    parse with no caching of its own; re-reading it every tick would put
    synchronous file I/O on the hot tick path.

    SELF-HEALS on a live recapture, unlike a plain forever-cache: the entry
    is keyed on the sidecar .npz's own (mtime_ns, size) — a cheap stat()
    call, not the file parse itself — so a recapture that rewrites the
    .npz (a new mtime/size) invalidates the cached value on its very next
    read, the same "don't trust a value that changed underneath you"
    property _shape_index gets from rebuilding on a miss. Missing stem or
    missing .npz both key on signature None, so a song with no audio yet
    caches its 0 offset the same way until a capture actually lands.

    Imports testbed_audio LAZILY (inside this function, not at module
    scope): testbed_audio imports analysis_reader for stem_for_uri, so a
    module-level import here would be a circular import."""
    stem = stem_for_uri(uri)
    signature: _CaptureOffsetSignature = None
    if stem is not None:
        npz_path = config.AUDIO_SHAPES_DIR / f"{stem}.npz"
        try:
            st = npz_path.stat()
            signature = (st.st_mtime_ns, st.st_size)
        except OSError:
            signature = None
    cached = _capture_offset_cache.get(uri)
    if cached is not None and cached[0] == signature:
        return cached[1]
    from spectra.services import testbed_audio
    offset = testbed_audio.capture_offset_ms_or_zero(uri)
    _capture_offset_cache[uri] = (signature, offset)
    return offset


def section_energy_at(uri: str, now_ms: int) -> Optional[float]:
    """Librosa section energy at a playback position (song-relative ms —
    the position callers such as bridge.intensity() pass, from
    track_position_ms()).

    Sections carry start_ms/end_ms in the CAPTURED-WAV frame
    (services/librosa_service.py places every boundary on a beat of the
    WAV, not the song); a nonzero capture offset (the WAV's own sample 0,
    song-relative — testbed_audio.capture_offset_ms) means a raw
    start_ms/end_ms comparison against a song-relative now_ms looks up the
    WRONG section on any song whose capture didn't start at song time 0 —
    the same frame mismatch data/transition-alignment-plan/report.md
    §2.1 found in the generator's own cue placement. Shifted here by
    adding the offset to each section's own bound before comparing, so
    both sides of the comparison share the song-time frame; offset 0 (no
    capture-offset data, or a capture that started at song time 0) leaves
    every comparison exactly as before."""
    sections = sections_for_uri(uri)
    if not sections:
        return None
    offset_ms = _capture_offset_for(uri)
    best = None
    for sec in sections:
        start = int(sec.get("start_ms", 0)) + offset_ms
        end = int(sec.get("end_ms", 0)) + offset_ms
        if start <= now_ms < end:
            best = sec
            break
    if best is None:
        best = min(sections, key=lambda s: min(
            abs(int(s.get("start_ms", 0)) + offset_ms - now_ms),
            abs(int(s.get("end_ms", 0)) + offset_ms - now_ms)))
    try:
        return max(0.0, min(1.0, float(best.get("energy_rms"))))
    except (TypeError, ValueError):
        return None


def training_profile_for_genres(genres: list[str]) -> Optional[dict]:
    """Best-matching training-profile dict for a song's genres (the ported
    _find_profile_for_genres matching: case-insensitive substring either
    way, else the default profile), or None. genre_bucket() and
    intensity_scale.py's genre base both resolve through this one matcher
    so they never disagree about which profile a song belongs to."""
    path = config.TRAINING_PROFILES_FILE
    if not path.exists():
        return None
    try:
        profiles = list(json.loads(path.read_text(encoding="utf-8")).values())
    except Exception:
        return None
    lowered = [g.lower() for g in genres]
    for profile in profiles:
        for pg in profile.get("genres", []):
            pg_lower = pg.lower()
            if any(pg_lower in sg or sg in pg_lower for sg in lowered):
                return profile
    for profile in profiles:
        if profile.get("is_default"):
            return profile
    return None


def genre_bucket(genres: list[str]) -> Optional[str]:
    """Best-matching training-profile NAME for a song's genres, or None."""
    profile = training_profile_for_genres(genres)
    return profile.get("name") if profile else None
