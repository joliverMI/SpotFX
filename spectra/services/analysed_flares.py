"""ANALYSED FLARES — the transitions that did not make the cut fire as flares
(the Admiral, 2026-09-26, verbatim: "i also want all of the transitions
that didn't get selected because they didn't rank high enough to be treated
like flares").

midsong_generator's SCENE-CHANGE PLANNER (2026-10-04) takes each song's
strongest N moments as its ACTIONS (N = "total actions per minute" x
duration x the song's intensity mark), makes the strongest that fit the
minimum hold its SCENE CHANGES (stored as generated fire_scene triggers),
and leaves every other action to fire as a flare — at the scene's ordinary
flare intensity, never the double-intensity flare a deferred scene change
fires (the Admiral, 2026-10-04: "leftover transitions fire as normal-
intensity flares"). This module is the ONE computation of what those
leftovers become — `plan_for_song` — and it is read by two callers, never
copied into a third:

  - spectra.services.trigger_engine, which fires each flare moment at play
    time as the current scene's ordinary "flare" band;
  - GET /api/analysed-plan (spectra/api/analysed_plan.py), which the debug
    page's shape canvas draws as upcoming SCENE CHANGE / FLARE markers.

DERIVED AT PLAY TIME, NEVER STORED. The discarded candidates are fully
recoverable from the stored analysis (midsong_generator.plan_moments splits
the same ranked list it always ranked), so his storage/spectra/
triggers.json is untouched and every analysed song gets flares the first
time it plays after this ships. The flip side, stated: a flare moment is
never editable on the Timeline — it is not a trigger. The kept cues still
are.

SAME TIMING RULES. A flare moment is placed by the identical edge-then-
downbeat rule and frame shift the kept cues are (plan_moments places both
halves with one resolved SongPlacement), and trigger_engine fires it through
the same tick() crossing logic a stored fire_response trigger takes — the
same show clock, the trigger-level/kind-level offsets and the automatic
lead. Its intensity is its own section's normalized energy (the same number
a kept cue of that section would have carried), run through the same
render-intensity scaling at fire time.

SPACING (both values are named in the help topic 'analysed-flares'):
  - SCENE_CUE_CLEARANCE_MS — a flare within this distance of a scene cue
    that will fire (a kept candidate, or any enabled stored fire_scene
    trigger — the stored set can predate the current density setting) is
    dropped: a flare must never coincide with a scene change.
  - FLARE_MIN_SPACING_MS — flares closer than this to each other are
    thinned, keeping the stronger (higher intensity; earlier on a tie).

WHEN THEY FIRE is trigger_engine's decision (analysed_flares_allowed below
is the one rule, used by both callers): the effective per-song mode is
"analysed", or it is "full" and the song carries no authored trigger. Never
under "transitions", and never on a song carrying his own triggers under
"triggers_only" (the effective mode stays "triggers_only" there) — the same
scope as a deferred scene cue's double-intensity flare.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from spectra.models.trigger import SpectraTrigger
from spectra.services import midsong_generator

SCENE_CUE_CLEARANCE_MS = 2000
FLARE_MIN_SPACING_MS = 2000

FLARE_ID_PREFIX = "analysed-flare:"


@dataclass(frozen=True)
class FlareMoment:
    timestamp_ms: int
    intensity: float
    generator_key: str
    snap_grid: Optional[str] = None
    snap_moved_ms: Optional[int] = None

    @property
    def trigger_id(self) -> str:
        return FLARE_ID_PREFIX + self.generator_key


@dataclass(frozen=True)
class SongPlan:
    """scene_cues: the moments a generated scene change is planned (the
    kept candidates, chronological). flares: the flare moments, after both
    spacing rules. Both in song time, before any offset/lead — exactly the
    stored-trigger timestamp_ms convention."""
    scene_cues: list[midsong_generator.CandidateMoment]
    flares: list[FlareMoment]


def analysed_flares_allowed(effective_mode: str, song_has_authored: bool) -> bool:
    """THE rule for whether analysed flares (and the planned-events
    markers) apply to a song: see the module docstring's WHEN THEY FIRE.
    `effective_mode` is trigger_engine._effective_mode_for_song's answer,
    so "triggers_only" on a song with no authored trigger already arrives
    here as "analysed"."""
    if effective_mode == "analysed":
        return True
    return effective_mode == "full" and not song_has_authored


def _space(moments: list[FlareMoment], blocked: list[int]) -> list[FlareMoment]:
    clear = [m for m in moments
             if all(abs(m.timestamp_ms - b) >= SCENE_CUE_CLEARANCE_MS for b in blocked)]
    kept: list[FlareMoment] = []
    for m in sorted(clear, key=lambda m: (-m.intensity, m.timestamp_ms)):
        if all(abs(m.timestamp_ms - k.timestamp_ms) >= FLARE_MIN_SPACING_MS for k in kept):
            kept.append(m)
    return sorted(kept, key=lambda m: m.timestamp_ms)


def plan_for_song(uri: str, stored: Iterable[SpectraTrigger] = ()) -> SongPlan:
    """The planned analysed events for one song. `stored` is the song's
    stored trigger list (trigger_store.list_for_song) — its enabled
    fire_scene triggers join the kept candidates as scene cues a flare must
    stay clear of. Reads the analysis from disk: callers on the event loop
    run this in a worker thread."""
    plan = midsong_generator.plan_moments(uri)
    blocked = [m.timestamp_ms for m in plan.kept]
    blocked += [t.timestamp_ms + t.trigger_offset_ms for t in stored
                if t.enabled and t.action.kind == "fire_scene"]
    flares = [FlareMoment(m.timestamp_ms, m.intensity, m.generator_key,
                          m.snap_grid, m.snap_moved_ms)
              for m in plan.unselected]
    return SongPlan(list(plan.kept), _space(flares, blocked))


@dataclass(frozen=True)
class SceneCueMoment:
    """One analysed SCENE CHANGE moment, in song time with the trigger's own
    offset applied. `key` is the stored trigger's id, or "planned:" + the
    generator key for a planned (not yet stored) cue."""
    timestamp_ms: int
    intensity: float
    key: str


def scene_change_moments(
    stored: Iterable[SpectraTrigger],
    planned: Callable[[], Iterable[midsong_generator.CandidateMoment]],
) -> tuple[list[SceneCueMoment], Optional[str]]:
    """THE scene-change list for a song's analysed events: its enabled
    stored GENERATED fire_scene triggers (what actually fires), else — the
    first play, before auto-generation lands — the plan's kept cues, read
    through `planned` (called only in that case: it may read the analysis
    from disk). Returns (chronological moments, "stored" | "planned" |
    None). Read by GET /api/analysed-plan's markers and by
    trigger_engine.next_colour_cue (the trigger-timed colour journey), so
    the two can never disagree about when the next scene change is."""
    cues = [SceneCueMoment(t.timestamp_ms + t.trigger_offset_ms,
                           t.action.intensity, t.id)
            for t in stored
            if t.enabled and t.source == "generated"
            and t.action.kind == "fire_scene"]
    source: Optional[str] = "stored"
    if not cues:
        cues = [SceneCueMoment(m.timestamp_ms, m.intensity,
                               "planned:" + m.generator_key)
                for m in planned()]
        source = "planned" if cues else None
    cues.sort(key=lambda c: c.timestamp_ms)
    return cues, source
