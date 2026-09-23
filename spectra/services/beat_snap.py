"""Phase 2 of the music-analysis plan (data/spotfx-music-analysis-plan/
report.md Part 5, sharpened by data/music-analysis-octave-scout/report.md)
— the Admiral's decision, 2026-09-22, verbatim: "we are still using the
old transition detection, but we are pinning it to a beat for better
precision... go for it."

Section detection (spectra/services/midsong_generator.py) stays the sole
source of a generated cue's EXISTENCE and its approximate time — this
module only nudges WHERE, within one beat, that cue actually lands, onto
the nearest downbeat of a per-song grid.

GRID CHOICE, per song (the scout report's own measured discriminator,
Q1/Q4): if a beat_this precompute exists for this song AND its tempo
reads at roughly HALF of librosa's own tempo_bpm
(ratio < HALF_TIME_RATIO), use beat_this's downbeats — its 8-beat PHRASE
grid is the one his Soy Peor marks actually sit on (25 of 45 flares land
on beat_this's own downbeat, the scout's Q1 bar-position histogram),
matching the Admiral's separate, earlier answer for that song ("every 8
is good"). Otherwise use librosa's downbeats — the scout's Q4 conclusion
is that beat_this is not a consistent win (a wash on Contra/Dopamine, a
loss on El Apagón), so it only earns a place where it demonstrably
matches his convention; librosa is always the fallback, never a second
tier to reach for.

NO LIVE beat_this EXECUTION, ever, from this module or from generation: a
missing precompute simply falls back to librosa (scout Q4's own
"defensible minimum" — beat_this is a request-path-forbidden ~100s/song
model, testbed_beatthis.py's own docstring).

ONE FRAME, NO SHIFT: a section boundary (analysis_reader.sections_for_uri)
and both downbeat grids (librosa's own beats, beat_this's marks) are all
computed by an analysis pass over the SAME captured WAV
(services/librosa_service.py: start_ms/beat ms are both int(t * 1000) off
the same `y` array, no offset applied to either) — so they already share
one coordinate frame, and this module compares them RAW, with no shift.
testbed_audio.capture_offset_ms_or_zero(uri) — the WAV-time -> song-time
shift spectra/api/testbed.py::_estimate_for applies — belongs only to a
CROSS-frame comparison (a WAV-relative engine mark against genuinely
song-time authored ground truth); applying it on just one side of this
module's same-frame comparison would introduce a constant bias equal to
the capture offset into every snap decision. A generated cue's own
UNSNAPPED time (a librosa section boundary) is left exactly as
midsong_generator has always placed it — already treated as song time by
every existing consumer (trigger_engine.tick(), the AGENTS.md "raw
convention" for librosa_offset_ms) — this module never touches that
number, only compares against it in its own native frame.

SNAP CAP: a nearest downbeat farther than ONE BEAT LENGTH
(60000 / librosa's own tempo_bpm) from the cue's unsnapped time is NOT
snapped — past that distance the grid has lost the plot for this cue (a
tempo change, a silent passage, a real grid gap), and an over-eager snap
would move the cue by more than the beat-alignment problem this exists to
fix. An unsnapped cue keeps exactly its section-boundary time and its
provenance records no grid (SpectraTrigger.snap_grid stays None).

Executable spec: scripts/check_midsong_beat_snap.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from spectra.services import analysis_reader, testbed_cache

GRID_LIBROSA: Literal["librosa"] = "librosa"
GRID_BEAT_THIS: Literal["beat_this"] = "beat_this"

# The scout report's own measured discriminator (Q1): beat_this reads Soy
# Peor and Dopamine at ~0.50x librosa's tempo (a real half-time phrase
# grid); Contra and El Apagón read at ~0.99x (the same octave). 0.6 sits
# cleanly between the two clusters with margin either side.
HALF_TIME_RATIO = 0.6


def _median_interval_ms(times: list[float]) -> Optional[float]:
    """Median of the successive gaps in a sorted time list — the scout
    report's own "median inter-beat interval of the full grid" method
    (Q1), robust to a few missed/extra beats at either end of a song."""
    if len(times) < 2:
        return None
    diffs = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    if not diffs:
        return None
    n = len(diffs)
    mid = n // 2
    return diffs[mid] if n % 2 else (diffs[mid - 1] + diffs[mid]) / 2.0


def _beat_this_cache(uri: str) -> Optional[list[dict]]:
    cached = testbed_cache.load(GRID_BEAT_THIS, uri)
    if cached is None:
        return None
    marks = cached.get("marks") or []
    return marks or None


def beat_this_bpm_for_uri(uri: str) -> Optional[float]:
    """beat_this's own tempo for this song, from the median inter-beat
    interval of its FULL grid (beat + downbeat marks together — a
    downbeat is a labelled subset of beats, not a disjoint stream, per
    testbed_beatthis.compute_marks_ms's own convention). None when
    nothing has been precomputed for this song, or too few marks to
    measure an interval."""
    marks = _beat_this_cache(uri)
    if not marks:
        return None
    times = sorted(float(m["time_ms"]) for m in marks
                   if m.get("kind") in ("beat", "downbeat"))
    interval = _median_interval_ms(times)
    if not interval or interval <= 0:
        return None
    return 60000.0 / interval


def _librosa_downbeats_ms(uri: str) -> Optional[list[int]]:
    """Librosa's own downbeat times, RAW — the same coordinate frame as
    analysis_reader.sections_for_uri's start_ms (see the module
    docstring's ONE FRAME, NO SHIFT); no capture-offset shift here."""
    beats = analysis_reader.beats_for_uri(uri)
    if not beats:
        return None
    out = sorted(int(b.get("ms", 0)) for b in beats if b.get("is_downbeat"))
    return out or None


def _beat_this_downbeats_ms(uri: str) -> Optional[list[int]]:
    """beat_this's own downbeat times, RAW — beat_this analyzes the same
    captured WAV librosa does, so its marks share the same frame as a
    section boundary too; no shift here either."""
    marks = _beat_this_cache(uri)
    if not marks:
        return None
    out = sorted(int(round(float(m["time_ms"])))
                for m in marks if m.get("kind") == "downbeat")
    return out or None


def choose_grid(uri: str) -> Optional[tuple[str, list[int]]]:
    """(grid_name, sorted RAW downbeat times — the same frame as a
    section boundary's own start_ms) for this song, or None when neither
    engine has anything usable. beat_this wins only when BOTH its
    precompute exists AND its tempo reads at roughly half librosa's own —
    never a preference on its own; librosa is the fallback whenever that
    condition doesn't hold or beat_this's own downbeat list turns out
    empty."""
    librosa_bpm = analysis_reader.tempo_bpm_for_uri(uri)
    beat_this_bpm = beat_this_bpm_for_uri(uri)
    if (librosa_bpm and beat_this_bpm
            and (beat_this_bpm / librosa_bpm) < HALF_TIME_RATIO):
        downbeats = _beat_this_downbeats_ms(uri)
        if downbeats:
            return GRID_BEAT_THIS, downbeats
    downbeats = _librosa_downbeats_ms(uri)
    if downbeats:
        return GRID_LIBROSA, downbeats
    return None


def _nearest(times: list[int], target: int) -> int:
    return min(times, key=lambda t: abs(t - target))


@dataclass(frozen=True)
class SnapResult:
    timestamp_ms: int
    grid: Optional[str] = None
    moved_ms: Optional[int] = None


@dataclass(frozen=True)
class SongGrid:
    """A song's chosen downbeat grid plus the beat length used for the
    snap cap — everything snap_with_grid needs, resolved once per song
    rather than once per cue (see resolve_song_grid)."""
    grid_name: str
    downbeats: list[int]
    beat_length_ms: float


def resolve_song_grid(uri: str) -> Optional[SongGrid]:
    """The per-song grid resolution snap() does on every call, factored
    out so a caller snapping many cues for the SAME song (e.g.
    midsong_generator.candidate_moments's per-section loop) can resolve
    it ONCE and reuse it via snap_with_grid — choose_grid alone re-reads
    and re-parses the song's librosa analysis and its beat_this cache on
    every call, all producing an identical answer for one song. None when
    there's no usable grid or no measurable tempo, matching snap()'s own
    unsnapped fallback."""
    choice = choose_grid(uri)
    if choice is None:
        return None
    grid_name, downbeats = choice
    librosa_bpm = analysis_reader.tempo_bpm_for_uri(uri)
    if not librosa_bpm or librosa_bpm <= 0:
        return None
    return SongGrid(grid_name, downbeats, 60000.0 / librosa_bpm)


def snap_with_grid(section_ms: int, grid: Optional[SongGrid]) -> SnapResult:
    """Snap one moment (song ms) against an already-resolved SongGrid —
    the pure, I/O-free half of snap(), capped at one beat length exactly
    as that module docstring's SNAP CAP describes. `grid=None` (no usable
    grid for this song) always returns the moment unsnapped."""
    if grid is None:
        return SnapResult(section_ms)
    nearest = _nearest(grid.downbeats, section_ms)
    moved = nearest - section_ms
    if abs(moved) > grid.beat_length_ms:
        return SnapResult(section_ms)
    return SnapResult(nearest, grid.grid_name, moved)


def snap(uri: str, section_ms: int) -> SnapResult:
    """Snap one generated cue's section-boundary time (song ms) to the
    nearest downbeat of this song's chosen grid, capped at one beat
    length. Never raises: a song with no usable grid, no measurable
    tempo, or a nearest downbeat farther than a beat away returns the
    section's own time UNSNAPPED (grid=None, moved_ms=None) — the module
    docstring's SNAP CAP. Resolves the grid fresh on every call; a caller
    snapping several moments for one song should use resolve_song_grid +
    snap_with_grid instead to resolve it once."""
    return snap_with_grid(section_ms, resolve_song_grid(uri))
