"""ONE definition of a scene transition's crossfade, its anchor, and the
lead that lands that anchor on the mark — shared by the firing path and
the transition scrubbing-preview (2026-08-27,
fm/flare-preview-offsets-everywhere).

WHY THIS MODULE EXISTS. trigger_engine._scene_transition_lead_ms_for grew
these three quantities inline, and it needs the LIVE room to compute them
(the effect types currently on the virtuals, the room's own control state,
Force Scene's redirect). A transition PREVIEW asks the same question about
a hypothetical pair — "if the room were showing scene A and scene B fired,
where would the anchor land?" — which is the same arithmetic against
different inputs. The established rule in this codebase when a preview and
the firing path must agree about timing is to factor the computation out
and have both CALL it, never to re-derive it on the preview side (see
scene_response.kind_lead_ms's own docstring, and the whole reason
flare_preview._scratch_engine is shared with flare_preview_hold): a preview
that computes its own version of production's timing is a preview that can
lie, and this system's founding defect was exactly that class of lie.

THE THREE QUANTITIES, in the order they compose:

  crossfade_ms  — how long the blend takes. SceneV2.entry_ramp_ms wins,
                  else the room's flat global_transition_ms override, else
                  the intensity-scaled default (gentle 300ms at intensity
                  0 -> hard 200ms at 1). The `or` chain treats a falsy 0
                  as unset, which is load-bearing: his live room really
                  does carry global_transition_ms == 0 and must fall
                  through to the intensity-scaled default (SPEC §84).
                  IDENTICAL chain to scene_compiler.fire_scene's own — the
                  two must never disagree about how long the blend the
                  lead is aligning actually takes.

  anchor_frac   — WHERE in that blend the visual payoff happens. A
                  registered phased pair (transition_phases.TRANSITIONS —
                  particles<->radial and friends, 0.45) names its own;
                  every other pair takes the plain 0.5 MIDPOINT, his own
                  generalization of legacy's registry-only rule. That 0.5
                  fallback deliberately lives HERE, at the caller, not
                  inside the ported transition_phases module — see that
                  module's docstring for why, and note this file is now
                  that caller for both consumers instead of one of them.

  lead_ms       — anchor_frac x crossfade_ms, capped at
                  transition_phases.MAX_LEAD_MS. LEAD family: POSITIVE
                  MEANS EARLIER (fire_at = target - lead), the opposite
                  sense from every trigger_offset_ms in this codebase.
                  docs/SPECTRA_TIMING_CONVENTIONS.md's master table is the
                  authority on that collision; never add a lead to an
                  offset.

Pure functions, no I/O, no live reads — the caller supplies the room state
and the current effect types. That is what lets the preview ask about a
pair the room is not currently showing.
"""
from __future__ import annotations

from typing import Any, Optional

from spectra.services import transition_phases

# His generalization of legacy's registry-only behaviour, verbatim: "for
# transitions without such a mid-point, use halfway through the
# transition." Kept a named constant so the preview's ruler and the firing
# path can never draw/apply two different fallbacks.
MIDPOINT_ANCHOR_FRAC = 0.5


def crossfade_ms_for(scene: Any, room: Any, intensity: float) -> int:
    """The blend duration this scene's entry actually takes. Mirrors
    scene_compiler.fire_scene's own fallback chain exactly — including the
    falsy-0 semantics that let a zeroed global override fall through."""
    from spectra.services import room_controls
    return (getattr(scene, "entry_ramp_ms", 0) or room.global_transition_ms
            or room_controls.scene_transition_ms(room, intensity))


def anchor_frac_for(current_types: dict[str, Optional[str]],
                    writes: list[dict]) -> float:
    """Where the payoff lands in the crossfade, for a fire whose compiled
    `writes` land on virtuals currently showing `current_types`.

    Multiple matching switches take the MAX anchor — legacy's own rule,
    unchanged: "the dominant transition lands on the trigger, shorter ones
    bloom a hair early." Nothing registered on any write falls back to the
    plain midpoint above."""
    anchor = 0.0
    for w in writes:
        anchor = max(anchor, transition_phases.anchor_frac(
            current_types.get(w["virtual_id"]), w["effect_type"]))
    return anchor if anchor > 0.0 else MIDPOINT_ANCHOR_FRAC


def lead_ms_for(anchor_frac: float, crossfade_ms: int) -> int:
    """LEAD family — positive means EARLIER. 0 for a crossfade of no
    length: an instant switch has no anchor to move, it simply lands."""
    if crossfade_ms <= 0:
        return 0
    return min(round(anchor_frac * crossfade_ms), transition_phases.MAX_LEAD_MS)
