"""
SPECTRA — ENERGY: the one number the engine acts on and every screen shows
(the Admiral's approval of the Energy plan, 2026-10-28: "I approve the
energy changes"; the plan is https://claude.ai/artifact/2Dy1SnUgNQ2fJQomhk4dkh).

Before this module there were six numbers called "energy" or "intensity":
the top bar showed librosa's raw section loudness, generated cues carried a
stretched copy, his triggers carried values a backfill script once wrote,
drop sequences carried the detector's jump size, and the fire multiplied
whichever it was handed by 0.6 x the song's scale. This is the ONE
definition; every decision and every screen reads it.

THE DEFINITION, in order:
  1. SECTIONS IN SONG TIME. librosa's sections are in the captured WAV's
     frame; they are shifted by the measured capture offset
     (analysis_reader._capture_offset_for, the .npz's own first timestamp) —
     the frame the engine has read in since the 2026-09-23 frame fix. Never
     librosa's stored `librosa_offset_ms` (AGENTS.md records it unreliable).
  2. NORMALIZED PER SONG, BEFORE THE MARK: the quietest section is 0 and the
     loudest is 1 (his rule). The first and last EDGE_TRIM_MS don't set the
     range (his 2026-08-15 ruling: a quiet intro or a fade-out must not
     squash the middle) and clamp to 0..1. No floor. A song whose sections
     are all one level (or that has a single section) reads 1.0: its only
     level is its loudest.
  3. THE MARK MATH: x HEADROOM (0.8 — his comment on the plan: "Make it 0.8
     instead of 0.6") x the song's scale (his manual Mark, or the automatic
     genre + bass scale; intensity_scale.song_scaling_factor), capped at 1.0
     — and at AUTO_CEILING (0.75) when the song carries no manual Mark, so
     his 15 Aug ruling stands: only a song he marks goes higher.
  4. READ AT THE SHOW CLOCK — the moment the engine acts, never the raw
     Spotify position (engine.current_energy reads it there).
  5. LOOK-AHEAD (his rule, the plan's D2): a DROP or a SCENE CHANGE that sits
     within `look_ahead_ms()` (room setting energy_lookahead_s, 2 s) of the
     next section edge reads the NEXT section's Energy, higher or lower. A
     generated moment (a stored generated cue, a planned scene change, an
     analysed flare) carries its source section in its generator_key
     (`section:<WAV start ms>`), so it reads THAT section exactly and needs
     no threshold. Ordinary flares and the top bar read the present.

His triggers' stored ⚡ values are NOT read (the plan's D4, his comment:
"Stop using my trigger values"): every trigger reads Energy at its moment.
The stored field stays in his data until a later cleanup removes it.

Unknown (no analysis for the song) is None; callers hold NEUTRAL (0.5),
the long-standing "unknowable -> neutral, stated" convention.

Pure arithmetic is `normalize` and `Timeline.at`/`at_source`; `timeline(uri)`
does the I/O once per song (cached on the analysis file's own stat, the
capture offset and the song's scale), so the trigger clock can ask freely.
"""
from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

HEADROOM = 0.8
AUTO_CEILING = 0.75
EDGE_TRIM_MS = 15_000
NEUTRAL = 0.5
DEFAULT_LOOK_AHEAD_S = 2.0
SECTION_KEY_PREFIX = "section:"


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalize(raws: Sequence[float], starts: Sequence[int], ends: Sequence[int]) -> list[float]:
    """Step 2, pure: each section's loudness on the song's own 0..1 scale.
    The range comes from the middle sections (not within EDGE_TRIM_MS of the
    song's start or end, in the WAV's own frame); every section, edges
    included, is stretched by it and clamped. Fewer than two middle sections
    -> the range comes from all of them. A flat song -> 1.0 everywhere."""
    vals = [_clamp01(float(v)) for v in raws]
    if not vals:
        return []
    end_ms = max(ends) if ends else 0
    middle = [v for v, s, e in zip(vals, starts, ends)
              if s >= EDGE_TRIM_MS and e <= end_ms - EDGE_TRIM_MS]
    pool = middle if len(middle) >= 2 else vals
    lo, hi = min(pool), max(pool)
    span = hi - lo
    if span <= 1e-9:
        return [1.0] * len(vals)
    return [_clamp01((v - lo) / span) for v in vals]


def mark_math(normalized: float, factor: float, marked: bool) -> float:
    """Step 3, pure: x HEADROOM x the song's scale, capped at 1.0 (or at
    AUTO_CEILING for a song with no manual Mark)."""
    cap = 1.0 if marked else AUTO_CEILING
    return round(max(0.0, min(cap, normalized * HEADROOM * float(factor))), 4)


@dataclass(frozen=True)
class Section:
    start_ms: int          # song time
    end_ms: int            # song time
    wav_start_ms: int      # librosa's own start (the generator_key basis)
    raw: float             # librosa energy_rms, clamped
    normalized: float      # step 2
    energy: float          # step 3: what everything reads


@dataclass(frozen=True)
class Timeline:
    uri: str
    sections: tuple[Section, ...]
    factor: float
    marked: bool
    capture_offset_ms: int

    @property
    def cap(self) -> float:
        return 1.0 if self.marked else AUTO_CEILING

    def _index(self, ms: int) -> int:
        """The section holding `ms` (song time); before the first -> 0, after
        the last -> the last; in a gap between two -> the nearer one."""
        starts = [s.start_ms for s in self.sections]
        i = bisect.bisect_right(starts, ms) - 1
        if i < 0:
            return 0
        sec = self.sections[i]
        if ms < sec.end_ms or i == len(self.sections) - 1:
            return i
        nxt = self.sections[i + 1]
        return i if ms - sec.end_ms <= nxt.start_ms - ms else i + 1

    def at(self, ms: int, look_ahead_ms: int = 0) -> Optional[float]:
        if not self.sections:
            return None
        i = self._index(int(ms))
        if look_ahead_ms > 0 and i + 1 < len(self.sections):
            edge = self.sections[i + 1].start_ms
            if 0 <= edge - int(ms) <= look_ahead_ms:
                return self.sections[i + 1].energy
        return self.sections[i].energy

    def at_source(self, wav_start_ms: int) -> Optional[float]:
        """The section a generated moment came from, by its WAV-time start
        (the generator_key basis); None when no section starts there."""
        for s in self.sections:
            if s.wav_start_ms == int(wav_start_ms):
                return s.energy
        return None

    def as_dict(self) -> dict:
        return {
            "uri": self.uri, "factor": round(self.factor, 4), "marked": self.marked,
            "headroom": HEADROOM, "cap": self.cap,
            "capture_offset_ms": self.capture_offset_ms,
            "look_ahead_ms": look_ahead_ms(),
            "sections": [{"start_ms": s.start_ms, "end_ms": s.end_ms,
                          "raw": round(s.raw, 4), "normalized": round(s.normalized, 4),
                          "energy": s.energy} for s in self.sections],
        }


def build_timeline(uri: str, sections: list, capture_offset_ms: int,
                   factor: float, marked: bool) -> Timeline:
    """Steps 1-3 for one song's librosa sections, pure."""
    rows = []
    for sec in sections or []:
        try:
            rows.append((int(sec.get("start_ms", 0)), int(sec.get("end_ms", 0)),
                         float(sec.get("energy_rms") or 0.0)))
        except (TypeError, ValueError, AttributeError):
            continue
    rows.sort(key=lambda r: r[0])
    norm = normalize([r[2] for r in rows], [r[0] for r in rows], [r[1] for r in rows])
    out = tuple(Section(start_ms=s + capture_offset_ms, end_ms=max(e, s) + capture_offset_ms,
                        wav_start_ms=s, raw=_clamp01(v), normalized=round(n, 4),
                        energy=mark_math(n, factor, marked))
                for (s, e, v), n in zip(rows, norm))
    return Timeline(uri=uri, sections=out, factor=float(factor), marked=bool(marked),
                    capture_offset_ms=int(capture_offset_ms))


# ── I/O: the song's scale, its sections, a small cache ───────────────────

FRESH_S = 1.0          # how long a read of the song's scale or a room setting is reused
_factor_memo: dict[tuple, tuple[float, tuple[float, bool]]] = {}
_look_memo: list = [None, 0]


def _now() -> float:
    import time
    return time.monotonic()


def song_factor(uri: str) -> tuple[float, bool]:
    """(the song's scale, whether it is his manual Mark). The Mark wins;
    otherwise the automatic genre + bass scale, with genres only known while
    this song is the one playing (Spotify's own metadata, never stored).
    Reused for FRESH_S: the trigger clock asks several times a tick, and a
    Mark he sets reaches the room within a second."""
    genres: tuple = ()
    try:
        from spectra.services import engine as engine_module
        if engine_module.bridge.track_uri() == uri:
            genres = tuple(engine_module.bridge.track_genres() or ())
    except Exception:
        genres = ()
    key = (uri, genres)
    now = _now()
    hit = _factor_memo.get(key)
    if hit is not None and now - hit[0] < FRESH_S:
        return hit[1]
    from spectra.services import intensity_scale, intensity_scale_marks
    mark = intensity_scale_marks.get_mark(uri)
    if mark is not None:
        value = (float(mark), True)
    else:
        value = (float(intensity_scale.auto_scaling_factor(uri, list(genres))), False)
    if len(_factor_memo) > 64:
        _factor_memo.clear()
    _factor_memo[key] = (now, value)
    return value


def forget() -> None:
    """Drop every reused read (a Mark or a room setting just changed)."""
    _factor_memo.clear()
    _look_memo[0] = None
    with _lock:
        _cache.clear()


_lock = threading.Lock()
_cache: dict[str, tuple[tuple, Timeline]] = {}
_CACHE_MAX = 64


def _librosa_signature(uri: str) -> Optional[tuple]:
    from spectra import config
    from spectra.services import analysis_reader
    stem = analysis_reader.stem_for_uri(uri)
    if stem is None:
        return None
    try:
        st = (config.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").stat()
    except OSError:
        return None
    return (stem, st.st_mtime_ns, st.st_size)


def timeline(uri: Optional[str]) -> Optional[Timeline]:
    """The song's Energy timeline, or None with no analysis. Rebuilt when the
    analysis file, the capture offset or the song's scale changes."""
    if not uri:
        return None
    from spectra.services import analysis_reader
    sig = _librosa_signature(uri)
    if sig is None:
        return None
    offset = analysis_reader._capture_offset_for(uri)
    factor, marked = song_factor(uri)
    key = (sig, offset, round(factor, 6), marked)
    with _lock:
        hit = _cache.get(uri)
        if hit is not None and hit[0] == key:
            return hit[1]
    sections = analysis_reader.sections_for_uri(uri)
    if not sections:
        return None
    tl = build_timeline(uri, sections, offset, factor, marked)
    with _lock:
        while len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[uri] = (key, tl)
    return tl


def look_ahead_ms() -> int:
    """The room's look-ahead (energy_lookahead_s), in ms, reused for FRESH_S."""
    now = _now()
    if _look_memo[0] is not None and now - _look_memo[0] < FRESH_S:
        return _look_memo[1]
    try:
        from spectra.services import room_controls
        secs = room_controls.load_room_controls().energy_lookahead_s
    except Exception:
        secs = DEFAULT_LOOK_AHEAD_S
    _look_memo[0], _look_memo[1] = now, int(round(float(secs) * 1000))
    return _look_memo[1]


def energy_at(uri: Optional[str], ms: Optional[int], look_ahead: bool = False) -> Optional[float]:
    """Energy for `uri` at song-time `ms`; with `look_ahead`, the room's
    look-ahead for a drop or a scene change. None when unknowable."""
    if ms is None:
        return None
    tl = timeline(uri)
    if tl is None:
        return None
    return tl.at(int(ms), look_ahead_ms() if look_ahead else 0)


def source_ms(generator_key: Optional[str]) -> Optional[int]:
    """The WAV-time section start a generated moment came from, or None."""
    if not generator_key or not generator_key.startswith(SECTION_KEY_PREFIX):
        return None
    try:
        return int(generator_key[len(SECTION_KEY_PREFIX):])
    except ValueError:
        return None


def looks_ahead(kind: str, event_class: Optional[str] = None) -> bool:
    """Which moments look ahead (the plan's D2): scene changes and drops."""
    return kind == "fire_scene" or (kind == "fire_response" and event_class == "drop")


def energy_for_moment(uri: Optional[str], ms: Optional[int], kind: str,
                      event_class: Optional[str] = None,
                      generator_key: Optional[str] = None) -> Optional[float]:
    """Energy for one trigger-like moment: its own source section when it
    has one, else the look-ahead rule for its kind, else the present."""
    tl = timeline(uri)
    if tl is None or ms is None:
        return None
    src = source_ms(generator_key)
    if src is not None:
        hit = tl.at_source(src)
        if hit is not None:
            return hit
    look = look_ahead_ms() if looks_ahead(kind, event_class) else 0
    return tl.at(int(ms), look)
