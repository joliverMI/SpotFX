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

PLACEMENT RULE R3 (2026-09-23, data/transition-alignment-plan/report.md
section 3, the Admiral's rollout approval on
data/transition-alignment-plan/decision-rollout.md): `place_cue`/
`place_with_resolved` are the composed rule — "for each section-boundary
cue, in song time, move it to the nearest bass-energy edge within W beats;
if none, apply [this module's own downbeat snap] (<= 1 beat); if that also
fails, leave the boundary where it is." Two stages:

  Stage 1 (R3 proper) — the nearest rhythmic edge within
  `window_beats * beat_length_ms` of the cue's own time, considering ONLY
  spectra/services/rhythmic_edges.py's `bass_up`/`bass_down` kinds —
  `gap_stop`/`gap_resume` are deliberately EXCLUDED from this search, even
  though the SAME two kinds join `bass_up`/`bass_down` under
  rhythmic_edges.py's own `direction` knob for the `edges` test-bed lane's
  DIFFERENT purpose (exploration). This matches the report's own reference
  implementation for its section 3 acceptance table exactly (data/
  transition-alignment-plan/evidence/score_rules.py: `steps = sorted(set(
  ev["up"] + ev["down"]))`), never folding gaps into R3 — see
  resolve_song_placement's own comment. `window_beats` is the SAME knob
  rhythmic_edges.edges_for_uri's own `window_beats` param reads for its
  gap-run-length threshold — see that module's own "THREE KNOBS" docstring
  section for why one knob governs both, even though this stage never
  reads the gap kinds it also gates. A found edge's provenance label is
  "edge:up"/"edge:down" — the report's own vocabulary (section 3:
  `snap_grid="edge:up"|"edge:down"|"librosa"|"beat_this"`).

  Stage 2 (R1, this module's own pre-existing downbeat snap, unchanged) —
  tried only when stage 1 finds nothing within the window. UNCONDITIONAL
  on `window_beats`/`sensitivity`/`direction` (edge detection always runs
  at whatever knobs are given); GATED on the caller's own
  `RoomControlState.midsong_snap_to_beat` — midsong_generator passes
  `grid=None` into `SongPlacement` when that setting is off, so stage 2 is
  the ONE part of place_cue the switch actually composes with (the field's
  own room_controls.py docstring: "the existing midsong_snap_to_beat
  switch composing (snap-to-beat becomes stage 2 of place_cue)").

  Neither stage fires — the section boundary's own raw time survives,
  `snap_grid=None`, `snap_moved_ms=None`, exactly like an unsnapped cue
  under the pre-R3 rule.

Frame handling is IDENTICAL to the grid-only rule above: `place_with_
resolved`/`SongPlacement` compare in whatever single frame the caller has
already put both operands into (this module still never shifts anything
itself — "ONE FRAME, NO SHIFT" is unchanged) — midsong_generator.py is the
one caller, and it shifts a SongPlacement's edges AND downbeat grid by the
identical capture offset it already shifts a bare SongGrid by.

Executable spec: scripts/check_midsong_beat_snap.py,
scripts/check_transition_alignment.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from spectra.services import analysis_reader, rhythmic_edges, testbed_cache

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


# ═══ PLACEMENT RULE R3 (module docstring's PLACEMENT RULE R3 section) ═════


@dataclass(frozen=True)
class EdgeCandidate:
    """One rhythmic-edge time, already collapsed to the report's own
    up/down provenance vocabulary — see rhythmic_edges.UP_KINDS/DOWN_KINDS."""
    time_ms: int
    label: Literal["edge:up", "edge:down"]


@dataclass(frozen=True)
class PlaceResult:
    timestamp_ms: int
    snap_grid: Optional[str] = None
    snap_moved_ms: Optional[int] = None


@dataclass(frozen=True)
class SongPlacement:
    """Everything place_with_resolved needs for ONE song, resolved once
    (the R3 analogue of SongGrid) — the rhythmic-edge candidates (always a
    list, possibly empty, once a song has usable beats; None only when the
    song has no measurable tempo at all — see resolve_song_placement) plus
    the R1 fallback SongGrid (None when snap-to-beat is off, or the song
    has no usable downbeat grid) and the beat length in ms, needed for the
    edge-window search even when `grid` is None."""
    edges: list[EdgeCandidate]
    grid: Optional[SongGrid]
    beat_length_ms: float


def resolve_song_placement(
    uri: str, *,
    window_beats: int = rhythmic_edges.DEFAULT_WINDOW_BEATS,
    sensitivity: float = rhythmic_edges.DEFAULT_SENSITIVITY,
    direction: str = rhythmic_edges.DEFAULT_DIRECTION,
) -> Optional[SongPlacement]:
    """None when there's no measurable tempo for this song at all (no
    usable beat analysis) — matching resolve_song_grid's own unsnapped-
    fallback convention. `grid` inside the returned SongPlacement is R1's
    ordinary downbeat-grid resolution (may itself be None on a song with a
    tempo but no downbeat grid) — a caller wanting stage 2 disabled
    (RoomControlState.midsong_snap_to_beat off) replaces it with
    `dataclasses.replace(placement, grid=None)` rather than this function
    growing a second "should I even look" parameter."""
    librosa_bpm = analysis_reader.tempo_bpm_for_uri(uri)
    if not librosa_bpm or librosa_bpm <= 0:
        return None
    beat_length_ms = 60000.0 / librosa_bpm
    raw_edges = rhythmic_edges.edges_for_uri(
        uri, window_beats=window_beats, sensitivity=sensitivity, direction=direction)
    edges: list[EdgeCandidate] = []
    if raw_edges:
        # R3's own edge candidates are bass_up/bass_down ONLY — the
        # report's own reference implementation for its section 3
        # acceptance table (data/transition-alignment-plan/evidence/
        # score_rules.py: `steps = sorted(set(ev["up"] + ev["down"]))`)
        # never folds gap_stop/gap_resume into R3's placement search, even
        # though the SAME two kinds join bass_up/bass_down under the
        # `edges` engine's own direction knob for a DIFFERENT purpose (the
        # test bed's "Rhythmic edges" lane — rhythmic_edges.py's own
        # "THREE KNOBS" docstring section). Keep the two uses separate:
        # this is placement, that is exploration.
        for kind in (rhythmic_edges.KIND_BASS_UP, rhythmic_edges.KIND_BASS_DOWN):
            label = "edge:up" if kind == rhythmic_edges.KIND_BASS_UP else "edge:down"
            edges.extend(EdgeCandidate(int(round(m.time_ms)), label)
                        for m in raw_edges.get(kind, []))
    return SongPlacement(edges, resolve_song_grid(uri), beat_length_ms)


def place_with_resolved(
    section_ms: int, *, placement: Optional[SongPlacement],
    window_beats: int = rhythmic_edges.DEFAULT_WINDOW_BEATS,
) -> PlaceResult:
    """The pure, I/O-free half of place_cue — R3 (nearest rhythmic edge
    within `window_beats` of `placement.beat_length_ms`) then R1 (this
    module's own downbeat snap, via placement.grid) then the section's own
    unmoved time. `placement=None` (no measurable tempo for this song at
    all) always returns `section_ms` unplaced, matching
    snap_with_grid(section_ms, grid=None)'s own convention.

    `window_beats` is clamped exactly as rhythmic_edges.edges_for_uri
    clamps its own copy of the same knob (rhythmic_edges.
    clamp_window_beats) — a caller passing 0 (below MIN_WINDOW_BEATS)
    gets the same one-beat-length floor a fresh edges_for_uri call would
    have used to build `placement.edges` in the first place, so the two
    never silently disagree on how wide the window actually is."""
    if placement is None:
        return PlaceResult(section_ms)
    window_ms = rhythmic_edges.clamp_window_beats(window_beats) * placement.beat_length_ms
    if placement.edges:
        nearest_edge = min(placement.edges, key=lambda e: abs(e.time_ms - section_ms))
        moved = nearest_edge.time_ms - section_ms
        # A NONZERO move only — an edge landing exactly AT the cue's own
        # raw time (moved == 0) still falls through to R1, matching the
        # report's own reference implementation for its section 3
        # acceptance table (data/transition-alignment-plan/evidence/
        # score_rules.py's `x if x != t else <R1 fallback>` — an
        # unmoved R3 result is indistinguishable there from "no edge
        # found," and R1 is what the acceptance numbers were measured
        # against in that exact case).
        if moved != 0 and abs(moved) <= window_ms:
            return PlaceResult(nearest_edge.time_ms, nearest_edge.label, moved)
    fallback = snap_with_grid(section_ms, placement.grid)
    return PlaceResult(fallback.timestamp_ms, fallback.grid, fallback.moved_ms)


def place_cue(
    uri: str, section_ms: int, *,
    window_beats: int = rhythmic_edges.DEFAULT_WINDOW_BEATS,
    sensitivity: float = rhythmic_edges.DEFAULT_SENSITIVITY,
    direction: str = rhythmic_edges.DEFAULT_DIRECTION,
    snap_enabled: bool = True,
) -> PlaceResult:
    """Place one generated cue's section-boundary time (song ms) by R3
    then R1, resolving the song's placement fresh on every call — a caller
    placing several moments for one song should use resolve_song_placement
    + place_with_resolved instead (midsong_generator.candidate_moments's
    own shape), same convention as snap()/resolve_song_grid+snap_with_grid
    above.

    `snap_enabled=False` disables stage 2 ONLY (R1's downbeat fallback) —
    stage 1 (the rhythmic-edge search) always runs at the given knobs,
    per the module docstring's PLACEMENT RULE R3 section."""
    placement = resolve_song_placement(
        uri, window_beats=window_beats, sensitivity=sensitivity, direction=direction)
    if placement is not None and not snap_enabled:
        placement = SongPlacement(placement.edges, None, placement.beat_length_ms)
    return place_with_resolved(section_ms, placement=placement, window_beats=window_beats)
