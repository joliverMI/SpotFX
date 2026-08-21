"""Per-scene minimum dwell — the rebuild under the real definition of a
song transition (2026-08-20, data/plan-make-dwell-meaningful-under-the-
rea-4p73/{report,HIS-DECISION}.md). His words: dwell was built as if "song
transition" meant between songs; it actually means transitions WITHIN a
song, or a scene trigger call — the path his ~22,000 real fire_scene
triggers all use, and the one the OLD dwell (SelectorEntry.dwell_weight,
gated only inside the sequencer's own song-transition roll) never touched
at all.

This module is the new meaning: a MINIMUM HOLD TIME per scene, gated at
scene_sequencer.fire_scene_by_id — the single choke point every automatic
scene-change path (sequencer roll, trigger fire_scene action, automatic
transition) already funnels through. The manual editor Fire button never
reaches that choke point (unchanged, exempt by construction); a Force
Scene pin bypasses this gate the same way it already bypasses disabled/
mode-availability, but the override is NAMED
(fire_scene_by_id's own overrode_dwell=True), never silent.

Curve, not a scalar — SceneV2.dwell_curve (spectra/models/scene.py) reuses
the SAME CurvePoint shape and the SAME shared named-profile store
(spectra/services/sequencer_store.py) the sequencer's own likelihood
curves use ("the curve selector he already has," not a parallel control).
y is SECONDS here, not a likelihood weight; x is intensity, 0..1.
DEFAULT_DWELL_CURVE is his exact numbers, not a suggestion: 16s at
intensity 0, 4s at intensity 1, linear between.

His four answered questions (HIS-DECISION.md), each now a specification:
  A. No clock reset on an update effect — a minimum is a floor, not
     something a busy song can keep re-arming.
  B. Intensity LATCHES at entry — dwell_seconds is computed once, from the
     intensity the scene actually fired at (the `intensity` fire_scene_by_id
     was called with), never re-evaluated while the dwell is running.
  C. Gates every AUTOMATIC path via fire_scene_by_id; manual Fire is
     exempt (never reaches this choke point); Force Scene wins but is
     named (overrode_dwell).
  D. A deferred scene change (still inside the active scene's dwell
     window) fires an UPDATE EFFECT instead —
     spectra.services.engine.fire_scene_update_event. Originally the
     existing on_update/SceneV2.update_kind mechanism; 8 of his 9 real
     scenes had no update_kind authored, so that first cut of on_update
     landed on nothing for almost every hold — he'd anticipated the
     staging ("they might not be defined yet, but we will do those soon")
     but the gap still made a hold indistinguishable from a broken engine,
     so on_update was replaced same-day (2026-08-20, his ask: "make update
     scene act like a double intensity flare until we build it out
     specifically") to fire the scene's own ordinary flare response at 2x
     intensity — nothing new to author, works on every scene he already
     has; see scene_response.ResponseEngine.on_update's own docstring. The
     hold is never silent either way: fire_scene_by_id records every
     deferral to fire_history's "deferred" bucket (requested scene,
     remaining dwell, and the update seam's own result), so "why didn't
     the room change" is a log lookup, not a mystery.

State is process-global, not per-scene-sequencer-instance. The OLD dwell's
"current scene" bookkeeping lived only on SceneSequencer's own instance
(_active_id), updated in exactly two places, and went stale the instant a
SPECTRA-native trigger fired a different scene mid-song — the report's own
§1 finding. This module is fed by the ONE function every real fire
(sequencer roll, trigger, automatic transition) already passes through, so
that staleness cannot recur here structurally, not just by convention.
In-memory only, like every other engine runtime state in this app (drift,
response surges) — a cold start has no active scene tracked, so the very
first fire after a restart is never deferred.

NOT THE SAME "GAP" AS THE CHARGE/LULL RAMP STRETCH (scene_response.py's
`_phase_ramp_ms`/`_next_trigger_gap_ms`, landed the same week as this
module, #150) — checked deliberately, not assumed, since both features
reason about timing near a trigger. `_next_trigger_gap_ms` is FORWARD-
looking: milliseconds from one trigger to the NEXT one this song will
actually fire, read straight off the trigger schedule, used only to pace
a charge/lull param glide. `remaining_s()` here is BACKWARD-looking: how
much of the CURRENT scene's own latched minimum (an authored curve, not a
schedule) is still owed, counted from when that scene last actually
fired. They don't share a computation, a data source, or a call path —
there is nothing to keep "in sync" between them, so this is not a
duplicated-formula drift risk.

There IS one real, un-mitigated interaction between the two, worth naming
rather than discovering live: a charge/lull ramp stretches toward the
NEXT trigger's timestamp regardless of what that trigger will actually do
when it arrives — if it's a `fire_scene` action and the room's active
scene hasn't cleared its own minimum yet, this module converts it into an
update effect instead of the scene switch the build visually promised.
Neither mechanism predicts the other's outcome (nor should it try to —
`_next_trigger_gap_ms` would have to simulate dwell's own future state,
which depends on things that haven't happened yet: another fire landing
first, Force Scene, a restart). If this reads as a real visual mismatch
on his room, it is a product question for him — not something to
"fix" by inventing cross-mechanism prediction here.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from spectra.models.sequencer import CurvePoint

if TYPE_CHECKING:
    from spectra.models.scene import SceneV2

DEFAULT_DWELL_CURVE: list[CurvePoint] = [
    CurvePoint(x=0.0, y=16.0),
    CurvePoint(x=1.0, y=4.0),
]

_active_scene_id: Optional[str] = None
_active_scene_name: Optional[str] = None
_entered_at_ms: Optional[int] = None
_dwell_seconds: float = 0.0


def resolve_dwell_curve_points(scene: "SceneV2") -> list[CurvePoint]:
    """scene.dwell_curve resolved named profile -> inline one-off ->
    DEFAULT_DWELL_CURVE — his exact 16s/4s default, not flat 1.0
    (unlike a plain SelectorEntry's "no curve" fallback, an unset per-scene
    minimum must still mean something). A dangling curve_ref (a named
    profile deleted out from under this scene) falls back to the default
    the same way selection_kernel.resolve_curve falls back to flat for a
    dangling sequencer ref."""
    attachment = getattr(scene, "dwell_curve", None)
    if attachment is None:
        return DEFAULT_DWELL_CURVE
    if attachment.curve_ref is not None:
        from spectra.services import sequencer_store
        profile = sequencer_store.load_curves().get(attachment.curve_ref)
        return profile.points if profile is not None else DEFAULT_DWELL_CURVE
    if attachment.inline_points is not None:
        return attachment.inline_points
    return DEFAULT_DWELL_CURVE


def dwell_seconds(scene: "SceneV2", intensity: float) -> float:
    """The scene's own minimum hold at one fixed intensity — piecewise-
    linear, clamped flat outside the curve's outer points (curve_eval's
    existing behaviour), so an intensity outside [0, 1] never raises."""
    from spectra.services import selection_kernel as kernel
    return kernel.curve_eval(resolve_dwell_curve_points(scene), intensity)


def remaining_s(now_ms: Optional[int] = None) -> float:
    """Seconds still owed on the ACTIVE scene's own latched minimum — 0.0
    once elapsed, or when nothing is tracked yet (cold start, or a restart
    with no fire since)."""
    if _entered_at_ms is None:
        return 0.0
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    elapsed_s = (now_ms - _entered_at_ms) / 1000.0
    return max(0.0, _dwell_seconds - elapsed_s)


def active_scene_id() -> Optional[str]:
    return _active_scene_id


def note_fired(scene: "SceneV2", intensity: float, *,
               now_ms: Optional[int] = None) -> None:
    """Latch dwell state for the scene that just actually fired — call
    exactly ONCE per real (non-deferred) fire, right after the compile+fire
    succeeds. Answer B: intensity is read HERE, once, from the intensity
    the scene fired at — never re-evaluated later, so a moving live
    intensity can't shrink or stretch an in-progress hold. Answer A (no
    reset on an update effect) falls out of this function simply never
    being called from the deferral path — only a real fire ever moves the
    entry timestamp forward."""
    global _active_scene_id, _active_scene_name, _entered_at_ms, _dwell_seconds
    _active_scene_id = scene.id
    _active_scene_name = scene.name
    _entered_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    _dwell_seconds = dwell_seconds(scene, intensity)


def reset() -> None:
    """Test/executable-spec seam for this module's process-global state —
    the same shape preview_pause.clear()/color_set_groups' cursor reset
    already use."""
    global _active_scene_id, _active_scene_name, _entered_at_ms, _dwell_seconds
    _active_scene_id = None
    _active_scene_name = None
    _entered_at_ms = None
    _dwell_seconds = 0.0


def status() -> dict:
    tracked = _entered_at_ms is not None
    return {
        "active_scene_id": _active_scene_id,
        "active_scene_name": _active_scene_name,
        "dwell_seconds": round(_dwell_seconds, 2) if tracked else None,
        "remaining_s": round(remaining_s(), 2) if tracked else None,
    }
