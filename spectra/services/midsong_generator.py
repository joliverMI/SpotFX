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

DENSITY (the Admiral's rollout decision, decision-rollout.md item 1):
before placement, only each song's strongest RoomControlState.
transition_max_per_song (default 12) mid-song candidates survive, ranked
by the ABSOLUTE bass-energy step (rhythmic_edges.bass_step_at) at each
candidate's own RAW section-boundary time — a comparable strength score
whether or not that moment actually crosses the sensitivity threshold as
a named edge. Ties (equal step magnitude, or no beat analysis at all —
every candidate scores 0.0) keep chronological order, since Python's sort
is stable. A song with `transition_max_per_song` or fewer candidates is
unaffected. Ranking happens BEFORE placement, on the boundary's own raw
time, so density and placement never fight over which moment "moved
first."

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
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import (
    analysis_reader, beat_snap, rhythmic_edges, room_controls, testbed_audio,
    trigger_store,
)

INTENSITY_FLOOR = 0.05
EDGE_TRIM_MS = 15_000


@dataclass(frozen=True)
class CandidateMoment:
    timestamp_ms: int
    intensity: float
    generator_key: str
    snap_grid: Optional[str] = None
    snap_moved_ms: Optional[int] = None


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
    max_per_song: Optional[int] = None,
) -> list[CandidateMoment]:
    """One CandidateMoment per surviving section boundary past the song's
    own start (see the module docstring's DENSITY section for what
    "surviving" means). Empty when no analysis is available yet —
    generation is a no-op, not an error, for an unanalyzed song.

    Every keyword defaults to the live RoomControlState — pass one
    explicitly to avoid that read (a caller that already has the current
    state, or an offline measurement script comparing settings for the
    SAME analysis) without needing to override every other knob too.
    `direction` is the one exception: it has no room-level setting (see
    the module docstring's PLACEMENT RULE R3 section), so its default is
    always rhythmic_edges.DEFAULT_DIRECTION ("both") — a caller (the test
    bed's generator:preview lane) passes it explicitly to explore the
    other two."""
    sections = analysis_reader.sections_for_uri(uri)
    if not sections:
        return []
    if (snap_enabled is None or window_beats is None or sensitivity is None
            or max_per_song is None):
        controls = room_controls.load_room_controls()
        if snap_enabled is None:
            snap_enabled = controls.midsong_snap_to_beat
        if window_beats is None:
            window_beats = controls.transition_window_beats
        if sensitivity is None:
            sensitivity = controls.transition_edge_sensitivity
        if max_per_song is None:
            max_per_song = controls.transition_max_per_song
    if direction is None:
        direction = rhythmic_edges.DEFAULT_DIRECTION

    ordered = sorted(sections, key=lambda s: int(s.get("start_ms", 0)))
    intensities = _normalized_intensities(ordered)
    mid = [(sec, intensity) for sec, intensity in zip(ordered, intensities)
          if int(sec.get("start_ms", 0)) > 0]  # exclude the song's own opening

    # DENSITY — keep the strongest max_per_song candidates by bass-energy
    # step size, ranked at each candidate's own RAW boundary time, BEFORE
    # placement (see the module docstring's DENSITY section). Resolved
    # once per song, not once per candidate.
    beat_series = rhythmic_edges.bass_step_series_for_uri(uri)
    scored = [
        (sec, intensity, int(sec.get("start_ms", 0)),
         rhythmic_edges.bass_step_at(beat_series[0], beat_series[1], int(sec.get("start_ms", 0)))
         if beat_series is not None else 0.0)
        for sec, intensity in mid
    ]
    if max_per_song and len(scored) > max_per_song:
        kept = sorted(range(len(scored)), key=lambda i: scored[i][3], reverse=True)[:max_per_song]
        kept.sort()  # restore chronological order
        scored = [scored[i] for i in kept]

    # The WAV-time -> song-time shift (see the module docstring's FRAME
    # FIX) — resolved once per song, not once per section.
    offset_ms = testbed_audio.capture_offset_ms_or_zero(uri)
    # Resolved once per song (not once per section) — place_cue would
    # otherwise re-read/re-parse the song's librosa analysis, its beat_this
    # cache and its capture-offset sidecar for every section.
    placement = beat_snap.resolve_song_placement(
        uri, window_beats=window_beats, sensitivity=sensitivity, direction=direction)
    if placement is not None and not snap_enabled:
        # Stage 2 (R1's downbeat fallback) only — stage 1 (the edge
        # search) always runs, per the module docstring's PLACEMENT RULE
        # R3 section.
        placement = replace(placement, grid=None)
    shifted_placement = _shift_song_placement(placement, offset_ms)

    out: list[CandidateMoment] = []
    for sec, intensity, raw_ms, _strength in scored:
        frame_ms = raw_ms + offset_ms
        result = beat_snap.place_with_resolved(
            frame_ms, placement=shifted_placement, window_beats=window_beats)
        # generator_key is keyed on the section's own RAW (WAV-time)
        # start_ms — the analysis moment, unaffected by the frame shift,
        # the density ranking, or placement — so toggling any of these
        # settings (or a recapture moving the capture offset) UPDATES the
        # same trigger's timestamp_ms rather than orphaning it under a
        # stale key and adding a new one (see the module docstring).
        out.append(CandidateMoment(
            result.timestamp_ms, intensity, f"section:{raw_ms}",
            result.snap_grid, result.snap_moved_ms))
    return out


def generate_for_song(uri: str) -> dict:
    """Deterministic, idempotent regeneration for one song. No RNG, no
    scene pick — see the module docstring. Returns a summary dict."""
    moments = candidate_moments(uri)
    existing = trigger_store.list_for_song(uri)
    by_key = {t.generator_key: t for t in existing
              if t.source == "generated" and t.generator_key}
    seen_keys: set[str] = set()

    added = updated = 0
    for m in moments:
        seen_keys.add(m.generator_key)
        current = by_key.get(m.generator_key)
        if current is None:
            trigger_store.upsert(uri, SpectraTrigger(
                timestamp_ms=m.timestamp_ms, source="generated",
                generator_key=m.generator_key,
                snap_grid=m.snap_grid, snap_moved_ms=m.snap_moved_ms,
                action=FireSceneAction(scene_id=None, intensity=m.intensity)))
            added += 1
        elif (current.timestamp_ms != m.timestamp_ms
              or current.action.kind != "fire_scene"
              or current.action.scene_id is not None
              or current.action.intensity != m.intensity
              or current.snap_grid != m.snap_grid
              or current.snap_moved_ms != m.snap_moved_ms):
            trigger_store.upsert(uri, current.model_copy(update={
                "timestamp_ms": m.timestamp_ms,
                "snap_grid": m.snap_grid,
                "snap_moved_ms": m.snap_moved_ms,
                "action": FireSceneAction(
                    scene_id=None, intensity=m.intensity,
                    color_set_id=getattr(current.action, "color_set_id", None)),
            }))
            updated += 1

    deleted = 0
    for key, stale in by_key.items():
        if key not in seen_keys:
            trigger_store.delete(uri, stale.id)
            deleted += 1

    skipped_authored = sum(1 for t in existing if t.source == "authored")
    return {
        "moments": len(moments),
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "skipped_authored": skipped_authored,
    }
