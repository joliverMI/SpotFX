"""SPECTRA mid-song trigger generation — front 3 of THE KEYSTONE
(decision-mid-song-model.md, binding): "song analysis GENERATES seeded
scene-change triggers that are ORDINARY AND EDITABLE" — the SAME
SpectraTrigger objects a human places by hand, through the same
trigger_store.upsert the authoring API uses. No separate schema, no
distinct execution path (spectra/models/trigger.py's own binding decision).

Analysis source: analysis_reader.sections_for_uri (the S2 bridge's own
read-only librosa reader — no spot-effects import, per the process-split
import discipline). LibrosaSection boundaries ARE "the analyzed transitions"
the legacy world already computes: each section's start_ms past the song's
own opening is one candidate mid-song scene-change moment. Sections are
already spaced by librosa_service's own min-distance floor
(min_dist_beats), so no extra spacing filter is applied here.

Intensity: each section's own energy_rms, per-song min-max renormalized
with a floor — the same minmax+floor convention
scripts/backfill_trigger_intensity.py established for the legacy world
(CLAUDE.md: raw energy_rms is max-normalized only, no floor subtraction,
so the quietest section of every song lands near 0.33, never near 0).

EDGE TRIM (Admiral, 2026-08-15): a cold open or fade-out drags the min-max
floor down, so genuinely quiet MIDDLE passages never read as low — his fix,
his words: "trim the first 15 seconds and last 15 seconds of a track when
we calculate the normalization", with those trimmed portions "set to zero
because they will probably be negative after the normalization." A section
is EDGE (excluded from the lo/hi that sets the floor) when its start falls
in the track's first EDGE_TRIM_MS or its end falls in the last EDGE_TRIM_MS
— the finest grain this data model offers (one energy_rms per section, no
sub-section timeline). An edge section's own intensity is then the SAME
stretch as a middle section but CLAMPED to [0, 1] with no floor added
(max(0.0, min(1.0, (v-lo)/span))) rather than raised to INTENSITY_FLOOR —
"probably negative" becomes exactly 0 rather than a floored 0.05, and a
genuinely loud edge section (an album that opens hot) isn't forced to 0
either. UNSTATED EDGE CASE, resolved and documented rather than guessed:
a track under ~2x EDGE_TRIM_MS has no middle section left after trimming
both ends. Rather than degrade to an all-zero or all-floored result, this
falls back to the PRE-TRIM behaviour entirely for that song — every
section counts toward lo/hi and none is force-clamped — the same "can't
apply gracefully -> keep the working baseline" pattern the rest of this
codebase uses (e.g. the bridge's stated degradations).

Scene choice: EVERY generated trigger's fire_scene action carries
scene_id=None — the pick is left to spectra.services.trigger_engine's
kernel routing AT FIRE TIME (curve × genre × affinity, the same selection
kernel the sequencer's own rolls use), not baked in here. Chosen because
LibrosaSection carries no scene reference today — only a structural label
(intro/verse/chorus/bridge/drop/outro) inferred from energy/density rank,
not an authored cue naming a SPECTRA scene. Should a future analysis stage
attach an explicit scene cue to a section, this generator is where it would
be threaded through as a baked scene_id instead — the fire_scene action
already supports both (spectra/models/trigger.py's own docstring).

Idempotent + edit-preserving: every generated trigger carries
source="generated" and generator_key=f"section:{start_ms}", stable across
regenerations of the SAME analysis. generate_for_song:
  - upserts a fresh generated trigger for every current section boundary
    with no matching still-generated trigger in storage,
  - updates a still-generated trigger's timestamp/intensity in place when
    the analysis moved it (re-running librosa can shift boundaries),
  - deletes a still-generated trigger whose generator_key no longer matches
    any current boundary (the analysis changed underneath it),
  - never touches a trigger whose source is "authored" — including a
    formerly-generated trigger a human edited: spectra/api/triggers.py's
    upsert_trigger stamps source="authored" on every write that arrives
    through the editing API, so an edited generated trigger has already
    left this function's reach by the time it runs again.

Whether a generated trigger fires at all is gated by the room-level
scene_change_mode setting (spectra/services/room_controls.py — "analysed"
or "full" allow it always; "transitions" never does; "triggers_only"
allows it only on a song with ZERO authored triggers of its own — see
trigger_engine._effective_mode_for_song), checked by trigger_engine at
fire time — generation and storage happen regardless of the setting, so
seeded triggers are always visible/editable on the timeline.

BEAT SNAP (Phase 2, 2026-09-22, spectra/services/beat_snap.py): once a
section boundary names a cue's EXISTENCE and approximate time (unchanged
by this), the cue's placed timestamp_ms is nudged onto the nearest
downbeat of a per-song grid — gated by RoomControlState.
midsong_snap_to_beat (default True; room_controls.py's own docstring).
generator_key stays keyed on the section's own RAW (unsnapped, WAV-time)
start_ms — the analysis moment that produced the cue never moves, so
toggling the setting or a grid becoming available/unavailable between
runs UPDATES the same trigger's timestamp_ms in place rather than
deleting and re-adding under a new key.

PLACEMENT RULE R3 (2026-09-23, data/transition-alignment-plan/report.md
sections 3/5 task 3; the Admiral's rollout approval on decision-
rollout.md): superseded Phase 2's plain downbeat snap above with
beat_snap.place_cue — R3 (nearest rhythmic edge within
RoomControlState.transition_window_beats of RoomControlState.
transition_edge_sensitivity) THEN R1 (this same downbeat snap, still
gated by midsong_snap_to_beat) THEN the raw boundary. See beat_snap.py's
own PLACEMENT RULE R3 docstring section for the exact composition and
room_controls.py's transition_window_beats/_edge_sensitivity docstrings
for the two knobs. Direction is fixed at rhythmic_edges.DEFAULT_DIRECTION
("both") for production generation — it is a test-bed-only exploration
knob (spectra/services/testbed_engines.py's generator:preview lane),
never promoted to a room setting.

DENSITY — A RATE, NOT A FLAT COUNT (2026-09-25, the Admiral's order:
"instead of a fixed transition count per song, do per minute. then
calculate total per song and use that number instead... and scale the
value with the mark percentage for that song"). RoomControlState.
transitions_per_minute (default 8) REPLACES the old flat
transition_max_per_song knob — resolve_transition_count() turns it into
a per-song total: `round(transitions_per_minute * duration_minutes *
effective_intensity_scale_factor(uri))`, clamped to
[1, RESULT_CAP_PER_SONG]. duration_minutes is the song's own analysed
length (max section end_ms — the same convention
_normalized_intensities already uses for edge trimming), never a stored
Spotify duration, since this function only ever has the analysis to work
from. effective_intensity_scale_factor is the SAME per-song factor the
show applies to render intensity — spectra.services.intensity_scale.
song_scaling_factor, automatic up to 125% or a manual mark up to 200%
(see effective_intensity_scale_factor's own docstring) — so a track he's
marked or that scores hot on genre+bass earns proportionally more
transitions, a dialed-down one fewer. The lower clamp (>= 1) is
unconditional: a song that generates at all always keeps at least one
cue, regardless of how short it is or how low the rate. The upper clamp
(RESULT_CAP_PER_SONG, its own docstring) is a sanity ceiling only — never
reached by an ordinary song at the default rate, so it is never what
"his rate" silently means in practice.

THE SCENE-CHANGE PLANNER (2026-10-04, data/scene-change-ranking-plan/
report.md; the Admiral's "use all recommendations"). His model: rank every
transition by how much the music changes, make the strongest ones the real
scene changes, fill the rest with flares. Measured before this, rank had no
effect at all — the minimum dwell gate decided first-come-first-served at
play time, so the top 10% of transitions became scene changes 38% of the
time, the same as the bottom. plan_moments() now plans it, in order:

  RANKING — each boundary's SECTION-ENERGY CHANGE, |energy_rms - the
    previous section's energy_rms| (section_energy_change). It replaced the
    one-beat bass jump (rhythmic_edges.bass_step_at), which did no better
    than chance at finding his own hand-placed marks (AUC 0.51 vs 0.58).
  PLACEMENT — unchanged: every boundary is placed by the frame shift and R3
    then R1 (below) before anything is chosen.
  DEDUPE — two boundaries placed on the same instant are one moment; the
    stronger keeps it (11.5% of candidates collided at window 16).
  TOTAL ACTIONS — the strongest resolve_transition_count() moments (the
    room bar's "Total actions per minute") are the song's actions; the rest
    are no action at all (MomentPlan.dropped).
  STRONGEST-FIRST FILL — walking the actions strongest first, each becomes
    a scene change if it fits the hold IN BOTH DIRECTIONS around the scene
    changes already chosen and the song-start pick at PLAN_START_MS: the
    hold is the dwell the show will latch for it (the longest enabled
    scene's dwell curve at its RENDER intensity, planning_hold_s, plus
    PLAN_HOLD_MARGIN_S), so a quiet cue blocks the timeline longer than a
    loud one. RoomControlState.scene_changes_per_minute (0 = off) is an
    optional ceiling on the count. Those become MomentPlan.kept — the
    stored scene-change cues. Every other action is MomentPlan.unselected,
    fired at play time as an ordinary flare (spectra.services.
    analysed_flares) — not the double-intensity deferral flare.
At play time a planned cue fires with dwell.PLANNED_CUE_TOLERANCE_S of
hold still allowed (trigger_engine's planned-scene path), and never picks
the scene already showing. Measured with the plan's validated simulator on
his 763 un-authored songs: the top 10% of transitions now become scene
changes 85% of the time (top 3 per song: 87%), ~2.8 changes a minute, and
0.0% of planned changes are deferred.

FRAME FIX (2026-09-23, data/transition-alignment-plan/report.md §2.1/§5
task 1): a section's own start_ms is in the CAPTURED-WAV's own frame
(services/librosa_service.py places every boundary on a beat of the WAV,
not the song), but the room's fire clock and a human's own authored
triggers both run in SONG time (spectra/services/bridge.py's
effective_position_ms, capture_alignment.py's own binding statement) —
and most captures start several seconds into the song (the time it takes
to detect what's playing). So every generated cue used to fire early by
exactly that gap; on 601 of his real songs where generated cues actually
fire, 17,226 of 19,490 cues sat on a song with a 2s-or-more gap (the
report's own corpus count). The fix: `frame_ms = raw_ms +
testbed_audio.capture_offset_ms_or_zero(uri)` — the WAV's own sample 0,
expressed in song time — is the moment actually placed and snapped;
`raw_ms` itself (the analysis moment / generator_key basis) never moves.
beat_snap's own downbeat grid — and, since PLACEMENT RULE R3 above,
its rhythmic-edge candidates too — are in the SAME WAV-time frame raw_ms
was in, so BOTH are shifted by the identical offset before the placement
search (`_shift_song_placement`, the SongPlacement analogue of
`_shift_song_grid`) — this is what beat_snap.py's own "ONE FRAME, NO
SHIFT" docstring still describes accurately: the comparison it performs is
unshifted and single-frame; only the frame itself (chosen by this caller,
once per song) has moved from WAV time to song time. A capture with no
measurable offset (testbed_audio.capture_offset_ms returns None, e.g. no
npz sidecar yet) shifts by exactly 0 — byte-identical to before this fix.

RE-ANALYSIS (2026-10-04, data/scene-change-ranking-plan/report.md §5, the
Admiral's "background refresh of a song on its next play when the stamp is
stale" plus a Sonic "refresh analysed triggers" command). Stored generated
cues used to be planned exactly once — auto-generation only ever runs for a
song with ZERO triggers — so a settings change, a generator fix (the frame
fix, R3) or a re-analysis never reached a song that already had cues: 554
of his songs still fired cues planned before the frame fix, ~9s early.

Every generated row now carries generator_stamp (generator_stamp() below):
a short digest of the analysed settings, GENERATOR_VERSION and the song's
own analysis inputs (its librosa analyzed_at, its capture offset, its
beat_this precompute, his manual intensity mark, and the moments he has
claimed by hand). A row without one, or with a different one, is STALE.
refresh_song_if_stale() re-plans ONE song in one batched write
(TriggerEngine.maybe_auto_generate runs it in a worker thread on the
song's first play edge); spectra/services/analysed_refresh.py walks the
whole library behind a dry run. Both share merge_song(), and both obey
the same safety rules, each of which is a test:
  - only source="generated" rows are ever written or deleted;
  - a song holding no generated row is never seeded (a song carrying only
    his own triggers stays exactly his);
  - a moment he edited or deleted by hand is never put back
    (spectra/services/analysed_claims.py);
  - a song whose analysis cannot be read keeps its stored cues — an
    unreadable file is never taken as "this song has no moments";
  - a song whose capture offset cannot be right (it would put the captured
    audio past the song's own end) keeps its stored cues — re-placing them
    by that offset would put them after the song is over.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import (
    analysed_claims, analysis_reader, beat_snap, rhythmic_edges, room_controls,
    testbed_audio, trigger_store,
)

logger = logging.getLogger(__name__)

INTENSITY_FLOOR = 0.05
EDGE_TRIM_MS = 15_000

GENERATOR_VERSION = "2"
"""Bumped whenever this module's own planning changes what it would store
for an unchanged song and unchanged settings — part of every generated
cue's generator_stamp, so a bump marks every stored analysed cue stale and
each song is re-planned on its next play (see RE-ANALYSIS below)."""

RESULT_CAP_PER_SONG = 200
"""Sanity ceiling on the per-song transition total transitions_per_minute
resolves to — NOT the density knob itself, which is the rate alone. At
the default rate (8/min) an ordinary song never gets close (a 25-minute
track would be needed to reach it), so this is never what "his rate"
silently means in practice; it exists only to stop a maxed-out rate on
an unusually long analysed file from producing an unusable density of
scene changes. Documented on the room bar's own help topic
('transitions-per-minute') rather than left as an invisible surprise."""


def effective_intensity_scale_factor(uri: str) -> float:
    """The per-song intensity_scale factor the show itself applies to
    this song's render intensity (2026-09-25, the Admiral's addendum:
    "scale the value with the mark percentage for that song") —
    spectra.services.intensity_scale.song_scaling_factor(uri, genres):
    automatic (genre + bass rank) up to 125%, or a manual per-track mark
    (intensity_scale_marks.py) up to 200% — the SAME resolution
    resolve_transition_count() below feeds into its rate x duration
    formula. Genres are only ever known while the exact song named by
    `uri` is the one currently loaded on the live bridge (Spotify's own
    track metadata, never stored per-song in SPECTRA's own storage) —
    read here from spectra.services.engine's bridge singleton, imported
    LAZILY (that module imports trigger_engine, which imports this one at
    module scope — a top-level import here would be circular). When this
    song isn't the one currently playing (the common case for a batch
    regeneration pass), genres fall back to an empty list — the exact
    same fallback intensity_scale.song_scaling_factor already uses for
    any song whose genres are unknown, so this is not a degraded case
    invented for this caller, only the ordinary "genre unknown" path."""
    from spectra.services import intensity_scale
    genres: list[str] = []
    try:
        from spectra.services import engine as engine_module
        bridge = getattr(engine_module, "bridge", None)
        if bridge is not None and bridge.track_uri() == uri:
            genres = bridge.track_genres()
    except Exception:
        genres = []
    return intensity_scale.song_scaling_factor(uri, genres)


def resolve_transition_count(
    uri: str, sections: list[dict], transitions_per_minute: float,
) -> int:
    """The per-song transition COUNT `transitions_per_minute` resolves to
    (see the module docstring's DENSITY section): `round(
    transitions_per_minute * duration_minutes *
    effective_intensity_scale_factor(uri))`, clamped to
    [1, RESULT_CAP_PER_SONG]. `duration_minutes` is the song's own
    analysed length (max section end_ms across ALL sections, including
    the excluded opening one — the same convention
    _normalized_intensities already uses to find the track's own edges),
    never a stored Spotify duration."""
    duration_ms = max((int(sec.get("end_ms", 0)) for sec in sections), default=0)
    minutes = duration_ms / 60000.0
    factor = effective_intensity_scale_factor(uri)
    total = round(transitions_per_minute * minutes * factor)
    return max(1, min(RESULT_CAP_PER_SONG, total))


@dataclass(frozen=True)
class CandidateMoment:
    timestamp_ms: int
    intensity: float
    generator_key: str
    snap_grid: Optional[str] = None
    snap_moved_ms: Optional[int] = None
    # THE RANK (see the module docstring's RANKING section): strength is the
    # section-energy change at this boundary; rank 1 is the song's strongest
    # moment of rank_of. None on a placement duplicate (it was never ranked).
    strength: float = 0.0
    rank: Optional[int] = None
    rank_of: Optional[int] = None


PLAN_START_MS = 1000
"""Where the planner assumes the song-start scene pick lands: the transition
fire happens on the URI-change edge, ~1s into the song (the plan's own
simulator, validated against his real show log at 62.1% vs 62.3%)."""

PLAN_HOLD_MARGIN_S = 0.5
"""Added to every planned hold — together with the 1.5s play-time tolerance
(dwell.PLANNED_CUE_TOLERANCE_S) it absorbs the difference between the
factor planned with (no genres offline) and the one the show plays with."""


def section_energy_shift(ordered: list[dict]) -> list[float]:
    """THE SIGNED FORM of the rank: each section's energy_rms minus the
    previous section's (positive = the music rises into this section), the
    song's own opening section scoring 0. section_energy_change() is its
    magnitude, and the Light Show's High/Low Triggers (spectra/services/
    show_cues.py) are its largest rise and largest fall — ONE score, so
    the cue a show is armed on and the scene change the planner ranks top
    can never disagree about what "the biggest shift" means."""
    out: list[float] = []
    prev: Optional[float] = None
    for sec in ordered:
        try:
            e = max(0.0, min(1.0, float(sec.get("energy_rms", 0.0))))
        except (TypeError, ValueError):
            e = 0.0
        out.append(0.0 if prev is None else e - prev)
        prev = e
    return out


def section_energy_change(ordered: list[dict]) -> list[float]:
    """THE RANK (2026-10-04): each section's |energy_rms - previous
    section's energy_rms|, raw, the song's own opening section scoring 0.
    His own model of the ranking ("by magnitude of change of intensity"),
    measured on his hand-placed marks at AUC 0.58 against the one-beat bass
    jump's 0.51 — see the module docstring's RANKING section."""
    return [abs(v) for v in section_energy_shift(ordered)]


_hold_curves_cache: Optional[tuple[Any, list[list]]] = None


def planning_hold_curves() -> list[list]:
    """Every enabled scene's own minimum-dwell curve (dwell.
    resolve_dwell_curve_points) — the planner holds each cue for the
    LONGEST of them, since which scene a cue fires is only decided at play
    time. Today every scene uses the default 16s -> 4s. Cached on the scene
    and curve-profile files' own (mtime, size), so a library walk parses
    them once and an edit is seen at once."""
    global _hold_curves_cache
    from spectra import config
    sig = []
    for path in (config.SCENES_FILE, config.SEQUENCER_FILE):
        try:
            st = path.stat()
            sig.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(path), None, None))
    if _hold_curves_cache is not None and _hold_curves_cache[0] == sig:
        return _hold_curves_cache[1]
    curves = _resolve_hold_curves()
    _hold_curves_cache = (sig, curves)
    return curves


def _resolve_hold_curves() -> list[list]:
    from spectra.services import dwell, scene_store
    curves: list[list] = []
    try:
        scenes = scene_store.list_all()
    except Exception:
        scenes = []
    for scene in scenes:
        if getattr(scene, "disabled", False):
            continue
        points = dwell.resolve_dwell_curve_points(scene)
        if points not in curves:
            curves.append(points)
    return curves or [dwell.DEFAULT_DWELL_CURVE]


def planning_hold_s(raw_intensity: float, factor: float, curves: list[list]) -> float:
    """Seconds a scene change at this cue's intensity holds the room before
    the next may fire, as the show will latch it: the dwell curve read at
    the RENDER intensity (raw x headroom x the song's factor), plus the
    planning margin."""
    from spectra.services import intensity_scale, selection_kernel
    render = intensity_scale.combine_measured_and_scale(raw_intensity, factor)
    return max(selection_kernel.curve_eval(points, render) for points in curves) + PLAN_HOLD_MARGIN_S


def _strongest_first_fill(
    by_strength: list[CandidateMoment], ordered: list[dict], factor: float,
    ceiling: Optional[int], hold_curves: list[list],
) -> list[CandidateMoment]:
    """THE STRONGEST-FIRST FILL (the module docstring's SCENE-CHANGE PLANNER):
    walk the actions strongest first; each becomes a scene change when it
    fits the hold IN BOTH DIRECTIONS around every scene change already
    chosen and the song-start pick — after an earlier change's hold has run
    out, and early enough that its own hold runs out before a later one —
    until `ceiling` (None = no ceiling) is reached. Returns the chosen, in
    strength order. Pure: no I/O."""
    try:
        start_raw = max(0.0, min(1.0, float(ordered[0].get("energy_rms", 0.5))))
    except (IndexError, TypeError, ValueError):
        start_raw = 0.5
    start_hold = planning_hold_s(start_raw, factor, hold_curves)
    chosen: list[tuple[int, float, CandidateMoment]] = []
    for c in by_strength:
        if ceiling is not None and len(chosen) >= ceiling:
            break
        t = c.timestamp_ms
        if (t - PLAN_START_MS) / 1000.0 < start_hold:
            continue
        hold = planning_hold_s(c.intensity, factor, hold_curves)
        fits = all(
            t != ta
            and not (ta < t and (t - ta) / 1000.0 < hold_a)
            and not (t < ta and (ta - t) / 1000.0 < hold)
            for ta, hold_a, _ in chosen)
        if fits:
            chosen.append((t, hold, c))
    return [c for _, _, c in chosen]


def section_intensities(sections: list[dict]) -> list[float]:
    """Each section's intensity as a generated cue at it carries (the
    per-song stretch below), for a reader outside this module — the Pulse
    feed (spectra/services/pulse_feed.py) feeds the Singles exactly this
    number, so a section reads the same to the effect as to the cue."""
    return _normalized_intensities(sections)


def _normalized_intensities(sections: list[dict]) -> list[float]:
    """Per-song min-max stretch of energy_rms with a floor — mirrors
    scripts/backfill_trigger_intensity.py's default `minmax` curve, plus
    the 2026-08-15 edge trim (see the module docstring's EDGE TRIM
    section): the first/last EDGE_TRIM_MS don't set the floor/ceiling, and
    their own values clamp to [0, 1] rather than being floored."""
    raw: list[float] = []
    for sec in sections:
        try:
            raw.append(max(0.0, min(1.0, float(sec.get("energy_rms", 0.0)))))
        except (TypeError, ValueError):
            raw.append(0.0)
    if not raw:
        return []
    duration_ms = max((int(sec.get("end_ms", 0)) for sec in sections), default=0)
    is_edge = [
        int(sec.get("start_ms", 0)) < EDGE_TRIM_MS
        or int(sec.get("end_ms", 0)) > duration_ms - EDGE_TRIM_MS
        for sec in sections
    ]
    middle = [v for v, edge in zip(raw, is_edge) if not edge]
    if not middle:
        # No middle left (a short track) — fall back to the pre-trim
        # behaviour for this song rather than degrade: every section
        # counts toward lo/hi, none is edge-clamped.
        middle = raw
        is_edge = [False] * len(raw)
    lo, hi = min(middle), max(middle)
    span = hi - lo
    if span <= 1e-9:
        return [0.5 for _ in raw]
    out = []
    for v, edge in zip(raw, is_edge):
        stretched = (v - lo) / span
        if edge:
            out.append(round(max(0.0, min(1.0, stretched)), 3))
        else:
            out.append(round(INTENSITY_FLOOR + stretched * (1.0 - INTENSITY_FLOOR), 3))
    return out


def _shift_song_grid(grid: Optional[beat_snap.SongGrid], offset_ms: int) -> Optional[beat_snap.SongGrid]:
    """Shift a WAV-time downbeat grid into song time by `offset_ms` — the
    identical shift applied to a section's own raw_ms (see the module
    docstring's FRAME FIX) — so a later beat_snap.snap_with_grid call
    compares two song-time values, keeping that function's own "ONE
    FRAME" comparison true of the frame this caller has chosen.
    `offset_ms == 0` (no measurable capture offset) returns `grid`
    unchanged, `None` included — byte-identical to before this fix."""
    if grid is None or offset_ms == 0:
        return grid
    return beat_snap.SongGrid(
        grid.grid_name,
        [d + offset_ms for d in grid.downbeats],
        grid.beat_length_ms,
    )


def _shift_song_placement(
    placement: Optional[beat_snap.SongPlacement], offset_ms: int,
) -> Optional[beat_snap.SongPlacement]:
    """The SongPlacement analogue of `_shift_song_grid` — shifts BOTH the
    rhythmic-edge candidates and the downbeat grid into song time by the
    identical `offset_ms` (see the module docstring's FRAME FIX section).
    `offset_ms == 0` or `placement is None` returns `placement` unchanged
    — byte-identical to before the frame fix / R3 existed."""
    if placement is None or offset_ms == 0:
        return placement
    return beat_snap.SongPlacement(
        [beat_snap.EdgeCandidate(e.time_ms + offset_ms, e.label) for e in placement.edges],
        _shift_song_grid(placement.grid, offset_ms),
        placement.beat_length_ms,
    )


def candidate_moments(
    uri: str, *,
    snap_enabled: Optional[bool] = None,
    window_beats: Optional[int] = None,
    sensitivity: Optional[float] = None,
    direction: Optional[str] = None,
    transitions_per_minute: Optional[float] = None,
) -> list[CandidateMoment]:
    """Every analysed moment the plan ACTS on — its scene changes and its
    flares together, chronological, each placed and ranked (a placement
    duplicate or a moment past the total-actions budget is no action and is
    not here). This is the placement-and-density view the test bed's
    Generator: Preview lane and the transition-alignment measurement read;
    which of these become stored scene changes is plan_moments().kept, and
    generate_for_song stores exactly that. Keywords as plan_moments()."""
    plan = plan_moments(
        uri, snap_enabled=snap_enabled, window_beats=window_beats,
        sensitivity=sensitivity, direction=direction,
        transitions_per_minute=transitions_per_minute)
    return sorted(plan.kept + plan.unselected, key=lambda m: m.timestamp_ms)


@dataclass(frozen=True)
class MomentPlan:
    """One song's plan (the module docstring's SCENE-CHANGE PLANNER).
    `kept` — the SCENE CHANGES the strongest-first fill chose, which
    generate_for_song stores as fire_scene triggers. `unselected` — every
    other action in the song's total-actions budget, placed by the
    IDENTICAL rule on the IDENTICAL clock, which spectra.services.
    analysed_flares fires at play time as ordinary flares (the Admiral,
    2026-10-04: "everything left becomes a flare"). `dropped` — moments
    that are no action at all: placement duplicates of a stronger moment,
    and moments past the budget. All chronological. `rank_of` — how many
    distinct moments were ranked."""
    kept: list[CandidateMoment]
    unselected: list[CandidateMoment]
    dropped: list[CandidateMoment] = field(default_factory=list)
    rank_of: int = 0


def plan_moments(
    uri: str, *,
    snap_enabled: Optional[bool] = None,
    window_beats: Optional[int] = None,
    sensitivity: Optional[float] = None,
    direction: Optional[str] = None,
    transitions_per_minute: Optional[float] = None,
    claimed: Optional[set[str]] = None,
    scene_changes_per_minute: Optional[float] = None,
    hold_curves: Optional[list[list]] = None,
) -> MomentPlan:
    """The song's MomentPlan — its scene changes, its flares and the
    moments that are no action, each placed and ranked (the module
    docstring's SCENE-CHANGE PLANNER). Empty when no analysis is available
    yet — generation is a no-op, not an error, for an unanalyzed song.

    `scene_changes_per_minute` (the optional ceiling, 0 = off) reads the
    room like the others; `hold_curves` (the dwell curves the fill holds
    each scene change for) defaults to planning_hold_curves().

    Every keyword defaults to the live RoomControlState — pass one
    explicitly to avoid that read (a caller that already has the current
    state, or an offline measurement script comparing settings for the
    SAME analysis) without needing to override every other knob too.
    `direction` is the one exception: it has no room-level setting (see
    the module docstring's PLACEMENT RULE R3 section), so its default is
    always rhythmic_edges.DEFAULT_DIRECTION ("both") — a caller (the test
    bed's generator:preview lane) passes it explicitly to explore the
    other two.

    `claimed` is the set of generator keys he has edited or deleted by hand
    (spectra/services/analysed_claims.py), read fresh when not given: those
    moments are his and never become a cue or a flare again."""
    sections = analysis_reader.sections_for_uri(uri)
    if not sections:
        return MomentPlan([], [])
    if (snap_enabled is None or window_beats is None or sensitivity is None
            or transitions_per_minute is None or scene_changes_per_minute is None):
        controls = room_controls.load_room_controls()
        if snap_enabled is None:
            snap_enabled = controls.midsong_snap_to_beat
        if window_beats is None:
            window_beats = controls.transition_window_beats
        if sensitivity is None:
            sensitivity = controls.transition_edge_sensitivity
        if transitions_per_minute is None:
            transitions_per_minute = controls.transitions_per_minute
        if scene_changes_per_minute is None:
            scene_changes_per_minute = controls.scene_changes_per_minute
    if direction is None:
        direction = rhythmic_edges.DEFAULT_DIRECTION

    ordered = sorted(sections, key=lambda s: int(s.get("start_ms", 0)))
    intensities = _normalized_intensities(ordered)
    if claimed is None:
        claimed = analysed_claims.claimed_keys(uri)
    strengths = section_energy_change(ordered)
    mid = [(sec, intensity, int(sec.get("start_ms", 0)), strength)
           for sec, intensity, strength in zip(ordered, intensities, strengths)
           if int(sec.get("start_ms", 0)) > 0  # exclude the song's own opening
           and f"section:{int(sec.get('start_ms', 0))}" not in claimed]

    total = resolve_transition_count(uri, ordered, transitions_per_minute)
    factor = effective_intensity_scale_factor(uri)
    duration_ms = max((int(sec.get("end_ms", 0)) for sec in ordered), default=0)
    ceiling = (max(1, round(scene_changes_per_minute * duration_ms / 60000.0 * factor))
               if scene_changes_per_minute and scene_changes_per_minute > 0 else None)

    # The WAV-time -> song-time shift (see the module docstring's FRAME
    # FIX) — resolved once per song, not once per section.
    offset_ms = testbed_audio.capture_offset_ms_or_zero(uri)
    placement = beat_snap.resolve_song_placement(
        uri, window_beats=window_beats, sensitivity=sensitivity, direction=direction)
    if placement is not None and not snap_enabled:
        placement = replace(placement, grid=None)
    shifted_placement = _shift_song_placement(placement, offset_ms)

    placed: list[CandidateMoment] = []
    for sec, intensity, raw_ms, strength in mid:
        result = beat_snap.place_with_resolved(
            raw_ms + offset_ms, placement=shifted_placement, window_beats=window_beats)
        placed.append(CandidateMoment(
            result.timestamp_ms, intensity, f"section:{raw_ms}",
            result.snap_grid, result.snap_moved_ms, strength=strength))

    # 1. DEDUPE — two transitions placed onto the same moment are one
    #    moment: the stronger keeps it (the earlier on a tie).
    by_moment: dict[int, CandidateMoment] = {}
    for c in placed:
        held = by_moment.get(c.timestamp_ms)
        if held is None or c.strength > held.strength:
            by_moment[c.timestamp_ms] = c
    unique = [c for c in placed if by_moment[c.timestamp_ms] is c]
    duplicates = [c for c in placed if by_moment[c.timestamp_ms] is not c]

    # 2. RANK — strongest section-energy change first; ties stay
    #    chronological (a stable sort over the chronological list).
    by_strength = sorted(unique, key=lambda c: -c.strength)
    rank_of = len(by_strength)
    ranked = {c.generator_key: replace(c, rank=i + 1, rank_of=rank_of)
              for i, c in enumerate(by_strength)}
    by_strength = [ranked[c.generator_key] for c in by_strength]

    # 3. TOTAL ACTIONS — the strongest `total` moments are the actions;
    #    the rest do nothing at all.
    pool, below = by_strength[:total], by_strength[total:]

    # 4. STRONGEST-FIRST FILL — see the module docstring.
    if hold_curves is None:
        hold_curves = planning_hold_curves()
    chosen = _strongest_first_fill(pool, ordered, factor, ceiling, hold_curves)
    chosen_keys = {c.generator_key for c in chosen}
    kept = sorted(chosen, key=lambda c: c.timestamp_ms)
    flares = sorted((c for c in pool if c.generator_key not in chosen_keys),
                    key=lambda c: c.timestamp_ms)
    dropped = sorted([ranked.get(c.generator_key, c) for c in duplicates] + below,
                     key=lambda c: c.timestamp_ms)
    return MomentPlan(kept, flares, dropped=dropped, rank_of=rank_of)


def _settings_part(controls: Any) -> dict:
    return {
        "rate": float(controls.transitions_per_minute),
        "window": int(controls.transition_window_beats),
        "sensitivity": float(controls.transition_edge_sensitivity),
        "snap": bool(controls.midsong_snap_to_beat),
        "ceiling": float(controls.scene_changes_per_minute),
        # the planner holds each scene change for the scenes' own dwell
        # curves — editing one changes which moments fit
        "holds": [[(float(p.x), float(p.y)) for p in points]
                  for points in planning_hold_curves()],
    }


def song_inputs(uri: str, *, claimed: Optional[set[str]] = None) -> dict:
    """The song-specific half of generator_stamp: what this song's plan is
    read from, beyond the room settings. Content values, never file times —
    a capture sidecar rewritten with the same numbers must not mark a song
    stale. The automatic intensity factor is deliberately NOT here: its
    genre half is only known while the song plays and its bass half drifts
    as the library grows, so stamping it would re-plan songs for reasons
    nobody chose. His manual mark is a choice, so it is here."""
    from spectra.services import intensity_scale_marks, testbed_cache
    doc = analysis_reader.librosa_analysis_for_stem(analysis_reader.stem_for_uri(uri))
    beat_this = testbed_cache.load(beat_snap.GRID_BEAT_THIS, uri)
    if claimed is None:
        claimed = analysed_claims.claimed_keys(uri)
    return {
        "analyzed_at": (doc or {}).get("analyzed_at"),
        "offset_ms": testbed_audio.capture_offset_ms_or_zero(uri),
        "beat_this": (beat_this or {}).get("computed_at"),
        "mark": intensity_scale_marks.get_mark(uri),
        "claimed": sorted(claimed),
    }


def generator_stamp(uri: str, controls: Any = None, *,
                    inputs: Optional[dict] = None) -> str:
    """THE stamp a generated cue planned for `uri` right now carries — see
    the module docstring's RE-ANALYSIS section. 16 hex chars of a SHA-1 over
    GENERATOR_VERSION, the analysed room settings and song_inputs()."""
    if controls is None:
        controls = room_controls.load_room_controls()
    payload = {
        "version": GENERATOR_VERSION,
        "settings": _settings_part(controls),
        "song": inputs if inputs is not None else song_inputs(uri),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def is_stale(rows: list[SpectraTrigger], stamp: str) -> bool:
    """True when any keyed generated row was planned under a different
    stamp (or none). Rows he owns never count."""
    return any(t.source == "generated" and t.generator_key
               and t.generator_stamp != stamp for t in rows)


@dataclass
class SongMerge:
    """What one song's stored generated cues must become to match a fresh
    plan — the ONE reconciliation both generation and re-analysis use."""
    upserts: list[SpectraTrigger] = field(default_factory=list)
    delete_ids: list[str] = field(default_factory=list)
    added: int = 0
    updated: int = 0      # placement, intensity or action changed
    restamped: int = 0    # only the stamp changed
    deleted: int = 0
    unchanged: int = 0
    moved_ms: list[int] = field(default_factory=list)   # |Δt| per moved cue
    skipped_authored: int = 0
    unkeyed_generated: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.upserts or self.delete_ids)

    def summary(self) -> dict:
        return {"added": self.added, "updated": self.updated,
                "restamped": self.restamped, "deleted": self.deleted,
                "unchanged": self.unchanged, "moved": len(self.moved_ms),
                "skipped_authored": self.skipped_authored}


def _desired_action(current: Optional[SpectraTrigger], m: CandidateMoment) -> FireSceneAction:
    return FireSceneAction(
        scene_id=None, intensity=m.intensity,
        color_set_id=getattr(current.action, "color_set_id", None) if current else None)


def merge_song(existing: list[SpectraTrigger], moments: list[CandidateMoment],
               stamp: Optional[str]) -> SongMerge:
    """Reconcile a song's stored rows with `moments` (pure — no I/O).

    Only source="generated" rows with a generator_key are ever in reach:
    one per key is updated in place (same id, so a pinned or already-fired
    cue keeps its identity), a key no longer planned is deleted, a planned
    key with no row is added, and a second row sharing a key is deleted.
    Every surviving generated row ends up carrying `stamp`. Authored rows
    and keyless generated rows are counted and left exactly as they are."""
    merge = SongMerge()
    by_key: dict[str, SpectraTrigger] = {}
    for t in existing:
        if t.source != "generated":
            merge.skipped_authored += 1
        elif not t.generator_key:
            merge.unkeyed_generated += 1
        elif t.generator_key in by_key:
            merge.delete_ids.append(t.id)
            merge.deleted += 1
        else:
            by_key[t.generator_key] = t

    seen: set[str] = set()
    for m in moments:
        seen.add(m.generator_key)
        current = by_key.get(m.generator_key)
        if current is None:
            merge.upserts.append(SpectraTrigger(
                timestamp_ms=m.timestamp_ms, source="generated",
                generator_key=m.generator_key,
                snap_grid=m.snap_grid, snap_moved_ms=m.snap_moved_ms,
                generator_stamp=stamp,
                action=_desired_action(None, m)))
            merge.added += 1
            continue
        content_differs = (
            current.timestamp_ms != m.timestamp_ms
            or current.action.kind != "fire_scene"
            or current.action.scene_id is not None
            or current.action.intensity != m.intensity
            or current.snap_grid != m.snap_grid
            or current.snap_moved_ms != m.snap_moved_ms)
        if content_differs:
            merge.upserts.append(current.model_copy(update={
                "timestamp_ms": m.timestamp_ms,
                "snap_grid": m.snap_grid,
                "snap_moved_ms": m.snap_moved_ms,
                "generator_stamp": stamp,
                "action": _desired_action(current, m),
            }))
            merge.updated += 1
            if current.timestamp_ms != m.timestamp_ms:
                merge.moved_ms.append(abs(m.timestamp_ms - current.timestamp_ms))
        elif current.generator_stamp != stamp:
            merge.upserts.append(current.model_copy(update={"generator_stamp": stamp}))
            merge.restamped += 1
        else:
            merge.unchanged += 1

    for key, stale in by_key.items():
        if key not in seen:
            merge.delete_ids.append(stale.id)
            merge.deleted += 1
    return merge


def _planning_kwargs(controls: Any) -> dict:
    return {
        "snap_enabled": controls.midsong_snap_to_beat,
        "window_beats": controls.transition_window_beats,
        "sensitivity": controls.transition_edge_sensitivity,
        "transitions_per_minute": controls.transitions_per_minute,
        "scene_changes_per_minute": controls.scene_changes_per_minute,
    }


@dataclass
class SongPlanResult:
    """One song's fresh plan plus its stamp — or why there is none."""
    uri: str
    moments: Optional[list[CandidateMoment]]
    stamp: Optional[str]
    reason: Optional[str] = None


OFFSET_SLACK_MS = 10_000
OFFSET_PAST_END_REASON = ("its capture offset cannot be right — it would put the "
                          "captured audio past the song's own end — so its stored "
                          "cues are kept until it is recaptured")


def capture_offset_past_end(uri: str) -> bool:
    """True when the song's measured capture offset (the song time of its
    WAV's first sample — the FRAME FIX's shift) cannot be right: it is at or
    past the track's own Spotify length, or the WAV starting that far in
    would run more than OFFSET_SLACK_MS past the song's end. Ten of his
    captures are like this (most flagged needs_recapture=offset_past_end by
    the capture service); shifting their sections by such an offset would
    place most or all cues after the song has ended, so a refresh would
    silently take the scene changes away from the song. A small offset
    (under the slack) is never doubted — that is ordinary detection lag."""
    sidecar = analysis_reader.capture_sidecar(uri) or {}
    duration = sidecar.get("duration_ms")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return False
    offset = testbed_audio.capture_offset_ms_or_zero(uri)
    if offset >= duration:
        return True
    if offset <= OFFSET_SLACK_MS:
        return False
    sections = analysis_reader.sections_for_uri(uri) or []
    length = max((int(sec.get("end_ms", 0)) for sec in sections), default=0)
    return offset + length > duration + OFFSET_SLACK_MS


def plan_song(uri: str, controls: Any = None) -> SongPlanResult:
    """Plan one song the way re-analysis stores it. moments is None (with
    a reason) when the song's analysis cannot be read — the caller then
    keeps whatever is stored rather than treating it as momentless."""
    if controls is None:
        controls = room_controls.load_room_controls()
    with analysis_reader.memoized_reads():
        if not analysis_reader.sections_for_uri(uri):
            return SongPlanResult(uri, None, None, "analysis unavailable")
        if capture_offset_past_end(uri):
            return SongPlanResult(uri, None, None, OFFSET_PAST_END_REASON)
        claimed = analysed_claims.claimed_keys(uri)
        inputs = song_inputs(uri, claimed=claimed)
        moments = plan_moments(uri, claimed=claimed, **_planning_kwargs(controls)).kept
    return SongPlanResult(uri, moments, generator_stamp(uri, controls, inputs=inputs))


def generate_for_song(uri: str) -> dict:
    """Deterministic, idempotent regeneration for one song — "⟳ Generate"
    and auto-generation on first play. No RNG, no scene pick — see the
    module docstring. One batched write (trigger_store.apply_batch), every
    generated row stamped. Unlike re-analysis this MAY seed a song that
    holds only his own triggers: it is only ever reached by his own press
    or for a song with no triggers at all. Returns a summary dict."""
    plan = plan_song(uri)
    if plan.moments is None:
        # No readable analysis: keep whatever is stored (an unreadable file
        # is never "this song has no moments").
        skipped = sum(1 for t in trigger_store.list_for_song(uri)
                      if t.source == "authored")
        return {"moments": 0, "added": 0, "updated": 0, "deleted": 0,
                "skipped_authored": skipped}
    with trigger_store.write_lock:
        existing = trigger_store.list_for_song(uri)
        merge = merge_song(existing, plan.moments, plan.stamp)
        if merge.changed:
            trigger_store.apply_batch(uri, merge.upserts, merge.delete_ids)
    return {"moments": len(plan.moments), "added": merge.added,
            "updated": merge.updated, "deleted": merge.deleted,
            "skipped_authored": merge.skipped_authored}


def refresh_song_if_stale(uri: str, controls: Any = None) -> dict:
    """RE-ANALYSIS of one song on its next play (the module docstring's
    RE-ANALYSIS section): re-plan and re-store this song's generated cues
    when any of them carries a stale stamp, in ONE batched write. A song
    holding no generated cue is never touched — that is what keeps a song
    of only his own triggers his. Returns {"status": "fresh" | "refreshed"
    | "skipped", ...counts}."""
    if controls is None:
        controls = room_controls.load_room_controls()
    rows = trigger_store.list_for_song(uri)
    if not any(t.source == "generated" for t in rows):
        return {"uri": uri, "status": "skipped", "reason": "no analysed cues stored"}
    with analysis_reader.memoized_reads():
        current = generator_stamp(uri, controls)
        if not is_stale(rows, current):
            return {"uri": uri, "status": "fresh", "stamp": current}
        plan = plan_song(uri, controls)
    if plan.moments is None:
        return {"uri": uri, "status": "skipped", "reason": plan.reason}
    with trigger_store.write_lock:
        rows = trigger_store.list_for_song(uri)
        if not any(t.source == "generated" for t in rows):
            return {"uri": uri, "status": "skipped", "reason": "no analysed cues stored"}
        merge = merge_song(rows, plan.moments, plan.stamp)
        if merge.changed:
            trigger_store.apply_batch(uri, merge.upserts, merge.delete_ids)
    logger.info("re-analysis: %s re-planned under stamp %s — %s", uri,
                plan.stamp, merge.summary())
    return {"uri": uri, "status": "refreshed", "stamp": plan.stamp,
            **merge.summary()}
