"""The SCENE-TO-SCENE TRANSITION scrubbing preview — half two of his own
sequencing for this system ("start with the flares, then we will do lull
charge drop"; a transition is the third thing a trigger can move, and the
one whose anchor rule differs from both).

WHAT IT SHOWS. The flare preview answers "when does this flare land against
the mark". This answers the same question for a scene change: the ruler
draws the transition's REAL, intensity-scaled crossfade — the same
`entry_ramp_ms or global_transition_ms or scene_transition_ms(room,
intensity)` chain scene_compiler.fire_scene itself resolves, so his live
`global_transition_ms == 0` falls through to the intensity-scaled default
exactly as it does in the show — and marks where its ANCHOR lands.

THE ANCHOR IS THE MIDDLE, and that is the settled law, not a choice made
here: of the three anchor families (his ruling 2026-08-20), a momentary
flare anchors its first switch's END to the mark, a DROP anchors its
START, and A SCENE TRANSITION ANCHORS ITS MIDDLE. "Middle" is
anchor_frac x crossfade — the plain 0.5 midpoint for an ordinary pair
(his own generalization of legacy's registry-only rule), or a registered
phased pair's own 0.45 (particles<->radial and friends,
transition_phases.TRANSITIONS) when the outgoing and incoming effect types
name one. Both come from spectra/services/scene_transition_lead.py, the
SAME module trigger_engine._scene_transition_lead_ms_for now calls: this
preview does not re-derive production's timing, it asks production's own
function. A preview that computes its own version of the show's timing is
a preview that can lie, and lying about exactly this is the defect that
started this whole system.

THE SIGN LAW IS THE FAMILY'S, UNCHANGED. trigger_mark_s and fire_at_s are
flare_preview's own functions, called — not copied, not re-derived:

    trigger_mark_s = anchor_s - offset_ms/1000     (OFFSET: negative=earlier)
    fire_at_s      = anchor_s - lead_ms/1000       (LEAD:  positive=earlier)

with `anchor_s` the ruler-layout position of the anchor moment. The drag
writes SceneV2.trigger_offset_ms (models/scene.py) — the scene-transition
member of the same field family as FlareKind.trigger_offset_ms and
SpectraTrigger.trigger_offset_ms, honoured on the firing path by
trigger_engine.tick()'s own _scene_offset_ms.

ONE RULER-LAYOUT DEPARTURE, and why it is not a second formula. A
transition's lead can be far longer than a flare's (up to
transition_phases.MAX_LEAD_MS = 5000ms, against a flare's fixed 220ms), so
flare_preview.animation_anchor_s's fixed 2s layout position would put the
crossfade's START off the left edge of the ruler and he could not see the
thing he is judging. anchor_s below therefore leaves room for the lead.
That is a LAYOUT choice about where to DRAW the anchor — explicitly what
animation_anchor_s's own docstring calls it ("a fixed ruler-LAYOUT choice,
never authored") — and every timing formula that consumes it is still the
shared one. The server computes it; the frontend only schedules against
what comes back.

Hardware-free, like flare_preview.build_timeline: a RecordingExecutor and
a fake clock, room_save stubbed on both scratch engines, live storage read
the same way a dry-run test-fire reads it. The LIVE half is
flare_preview_hold's general program hold (TransitionProgram below) — never
a second bespoke hold.
"""
from __future__ import annotations

from random import Random
from typing import Any, Optional

from spectra.models.scene import SceneV2
from spectra.services import (flare_preview, flare_preview_hold, room_controls,
                              scene_compiler, scene_transition_lead,
                              transition_phases)
from spectra.services.binding_resolver import FireContext
from spectra.services.fx_executor import RecordingExecutor

# Minimum ruler length, and the pad after the crossfade settles, so a
# looped preview visibly rests on the incoming scene before it resets.
MIN_TIMELINE_S = flare_preview.MIN_TIMELINE_S
TAIL_PAD_S = flare_preview.TAIL_PAD_S
# How much ruler is kept to the LEFT of the crossfade's start, so the
# outgoing scene is visible for a beat before the blend begins.
FRONT_PAD_S = 0.75
# How long the re-arm (putting the room back on the outgoing scene at the
# top of each lap) is given. Deliberately the hold's own tween-safe
# instant: a lap reset is not part of what he is judging, so it must not
# read as a second transition — see flare_preview_hold.REVERT_TRANSITION_MS
# for why 1ms rather than 0.
REARM_TRANSITION_MS = flare_preview_hold.REVERT_TRANSITION_MS


def animation_anchor_s(duration_s: float, lead_ms: int) -> float:
    """Where the transition's ANCHOR MOMENT (its middle, or a registered
    pair's own payoff phase) is DRAWN. A ruler-layout choice only — see the
    module docstring: it must leave room for a lead up to MAX_LEAD_MS so
    the crossfade's start stays on the ruler, which flare_preview's fixed
    2s position cannot for a long transition."""
    return max(flare_preview.animation_anchor_s(duration_s),
               lead_ms / 1000.0 + FRONT_PAD_S)


def _compile(scene: SceneV2, intensity: float, rng_seed: int) -> list[dict]:
    room = room_controls.load_room_controls()
    ctx = FireContext(intensity, rng=Random(rng_seed))
    resolved = scene_compiler.resolve_scene(scene, ctx)
    return scene_compiler.compile_scene(
        resolved, scene_compiler.room_active_set(),
        display_mode=room.display_mode,
        light_bg_color=room.display_light_bg_color)


def _current_types(from_scene: SceneV2, intensity: float) -> dict[str, Optional[str]]:
    """What effect type each virtual is showing while the OUTGOING scene is
    held — read from that scene's own compiled writes rather than from the
    live room, because a preview asks about a hypothetical pair the room
    may not currently be showing. This is the input
    trigger_engine._scene_transition_lead_ms_for takes from live virtuals."""
    return {w["virtual_id"]: w["effect_type"]
            for w in _compile(from_scene, intensity, rng_seed=11)}


def transition_shape(from_scene: SceneV2, to_scene: SceneV2,
                     intensity: float) -> dict[str, Any]:
    """crossfade/anchor/lead for this pair at this intensity — the three
    numbers the ruler draws and the fire loop schedules against, all from
    scene_transition_lead (production's own definitions)."""
    room = room_controls.load_room_controls()
    crossfade_ms = scene_transition_lead.crossfade_ms_for(to_scene, room, intensity)
    to_writes = _compile(to_scene, intensity, rng_seed=13)
    from_types = _current_types(from_scene, intensity)
    anchor_frac = scene_transition_lead.anchor_frac_for(from_types, to_writes)
    lead_ms = scene_transition_lead.lead_ms_for(anchor_frac, crossfade_ms)
    registered = any(
        transition_phases.find(from_types.get(w["virtual_id"]),
                               w["effect_type"]) is not None
        for w in to_writes)
    return {"crossfade_ms": crossfade_ms, "anchor_frac": anchor_frac,
            "lead_ms": lead_ms, "writes": to_writes,
            "anchor_source": "phased_pair" if registered else "midpoint"}


async def build_timeline(from_scene: SceneV2, to_scene: SceneV2,
                         intensity: float) -> dict[str, Any]:
    """The transition's scrub timeline. Every time is computed here; the
    frontend schedules against `cues` and draws against the markers, never
    deriving a moment of its own."""
    shape = transition_shape(from_scene, to_scene, intensity)
    crossfade_s = shape["crossfade_ms"] / 1000.0
    lead_s = shape["lead_ms"] / 1000.0
    duration_s = max(MIN_TIMELINE_S,
                     FRONT_PAD_S + lead_s + crossfade_s + TAIL_PAD_S)
    anchor_s = animation_anchor_s(duration_s, shape["lead_ms"])
    fire_at = flare_preview.fire_at_s(anchor_s, shape["lead_ms"])
    return {
        "from_scene_id": from_scene.id, "from_scene_name": from_scene.name,
        "to_scene_id": to_scene.id, "to_scene_name": to_scene.name,
        "intensity": round(intensity, 4),
        "duration_s": round(duration_s, 4),
        "crossfade_ms": shape["crossfade_ms"],
        "anchor_frac": shape["anchor_frac"],
        "anchor_source": shape["anchor_source"],
        "anchor_rule": "transition_middle",
        "lead_ms": shape["lead_ms"],
        "animation_anchor_s": round(anchor_s, 4),
        "trigger_mark_s": round(flare_preview.trigger_mark_s(
            anchor_s, to_scene.trigger_offset_ms, duration_s), 4),
        "fire_at_s": round(fire_at, 4),
        # Where the crossfade actually begins and ends on the ruler — the
        # accent band the overlay shades. START is the write itself, END is
        # one crossfade later; the anchor sits anchor_frac of the way
        # between them, ON the trigger mark when the offset is 0.
        "animation_start_s": round(fire_at, 4),
        "animation_end_s": round(fire_at + crossfade_s, 4),
        # The lap reset: put the room back on the outgoing scene so the
        # NEXT lap has something to transition FROM. Computed here (never
        # by the frontend) so the two cues can't drift apart.
        "cues": [
            {"step": "rearm", "at_s": 0.0,
             "label": f"reset to {from_scene.name}"},
            {"step": "fire", "at_s": round(fire_at, 4),
             "label": f"cross to {to_scene.name}"},
        ],
        "target_writes": [
            {"virtual_id": w["virtual_id"], "effect_type": w["effect_type"]}
            for w in shape["writes"]],
    }


class TransitionProgram(flare_preview_hold.PreviewProgram):
    """The LIVE half, as a program over the one shared hold: hold the
    OUTGOING scene (its writes are the snapshot basis and what a lap reset
    lands), then cross to the INCOMING one at its real crossfade.

    Two steps, both scheduled by the frontend against times this module
    computed: "rearm" puts the room back on the outgoing scene at the top
    of each lap (tween-safe instant, so a reset never reads as a second
    transition), "fire" performs the transition being judged."""

    steps = ("rearm", "fire")

    def __init__(self, from_scene: SceneV2, to_scene: SceneV2) -> None:
        self.hold_scene = from_scene
        self.to_scene = to_scene

    def extra_snapshot_writes(self, intensity: float) -> list[dict]:
        # The INCOMING scene can touch virtuals the outgoing one never
        # does; without these in the snapshot, closing the preview would
        # hand some virtuals back and silently keep the rest.
        return _compile(self.to_scene, intensity, rng_seed=13)

    async def execute(self, step: str, ctx) -> dict:
        if step == "rearm":
            await ctx.apply_scene(transition_ms=REARM_TRANSITION_MS)
            return {"result": "rearmed", "scene": self.hold_scene.name}
        if step != "fire":
            raise ValueError(f"unknown transition preview step: {step!r}")
        shape = transition_shape(self.hold_scene, self.to_scene, ctx.intensity)
        await ctx.apply_scene(writes=shape["writes"],
                              transition_ms=shape["crossfade_ms"])
        return {"result": "transitioned", "scene": self.to_scene.name,
                "crossfade_ms": shape["crossfade_ms"],
                "anchor_frac": shape["anchor_frac"]}
