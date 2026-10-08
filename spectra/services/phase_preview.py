"""The CHARGE / LULL / DROP SEQUENCE scrubbing preview — the second half he
deliberately deferred ("start with the flares, then we will do lull charge
drop").

WHAT IT SHOWS, and why the ruler is the point. A flare is one moment; the
drop sequence is three, and their SHAPE is the thing he tunes. Each ramp is
computed by scene_response._phase_ramp_ms — production's own function, not
a re-derivation — which since 2026-08-20 STRETCHES a charge or lull to
~90% of the real gap to its build's end and hangs the remaining ~10% at
phase_progress = 1.0. That hang is his own spec, verbatim: "the single blob
waiting in lull should reach the center just and hang for just a moment,
maybe 10% of the lull time, before the explosion." The ruler draws ramp and
hang as separate bands per class so the hang is a thing he can SEE and set
the gaps against, which is exactly what a number in a settings form could
never give him. DROP IS NEVER STRETCHED (PHASE_RAMP_STRETCH_CLASSES) — it
stays the fixed snap.

THE GAPS ARE THE PARTNER GAPS. This ruler lays out a clean charge → lull →
drop with nothing between the marks, so the charge's gap is the distance to
its own lull and the lull's to its own drop — exactly what the firing path
resolves for a stored sequence under the PHASE PARTNER rule (spectra/
services/phase_partner.py: a build runs to its own lull or drop whatever
sits between). tests/test_phase_partner.py asserts the two agree rather
than trusting it.

THE ANCHORS, which differ per class and are the settled law rather than a
choice made here (his ruling 2026-08-20, data/drops-still-fire-early-star-
does-not-explode):

  charge, lull  END-anchored like a momentary flare — whatever lead
                trigger_engine._response_switch_lead_ms computes for that
                class's band at this intensity, read through the SAME
                functions (color_rotate_lead_ms, momentary_switch_would_
                glide). His settlement was about drop SPECIFICALLY and
                "must not leak into" the wider phase family; this module
                honours that by asking the same code.
  drop          START-anchored: it BEGINS on the mark, lead 0,
                unconditionally. _response_switch_lead_ms short-circuits
                for event_class == "drop" ahead of every other branch, and
                this module short-circuits identically rather than trusting
                that no drop band happens to carry a qualifying kind today.

THE OFFSETS. Each class's band carries its kinds' own
FlareKind.trigger_offset_ms, and the mark drawn here is still the BAND
ANCHOR — scene_response.band_trigger_offset_ms, min over every declared
kind's offset, zero included (fixed 2026-09-16,
spotfx-zero-offset-fires-on-mark) — which is where the firing path
relocates the whole fire, for a DROP band too: that drop rule pins the automatic anchor-family
LEAD, never his explicit hand on a marker. Kinds inside the fire no longer
land together at that anchor: each lands at its own per-kind offset
relative to it (scene_response's "PER-FLARE TRIGGER MOMENT"), so the mark
tells the truth about where the fire begins, and a kind authored after the
anchor lands that much after the mark.

WHY THE MARKS ARE NOT DRAGGABLE HERE, stated rather than quietly omitted: a
band's offset is an AGGREGATE over however many kinds it attaches, so a
drag would have to pick one kind to write it to, and picking would be
invention. The place a kind's own offset is authored already exists and is
per-kind by construction — the flare scrubbing preview's own marker. This
preview displays what those authored offsets add up to for each class, and
says so.

Hardware-free like flare_preview.build_timeline (RecordingExecutor, fake
clock, room_save stubbed). The LIVE half is PhaseSequenceProgram below,
running on flare_preview_hold's ONE shared program hold — it drives the
REAL vendored phase machinery (ResponseEngine.on_event -> _drive_phase's
`phase`/`phase_progress` writes on every phase-capable virtual), never a
mimic of it, and releases the phase at the end of each lap the way a track
change does (ResponseEngine.release_phases).
"""
from __future__ import annotations

from typing import Any, Optional

from spectra.models.scene import SceneV2
from spectra.services import flare_preview, flare_preview_hold
from spectra.services.scene_response import (DICE_REROLL_GLIDE_MS,
                                             PHASE_RAMP_HANG_FRACTION,
                                             PHASE_RAMP_MS,
                                             PHASE_RAMP_STRETCH_CLASSES,
                                             _phase_ramp_ms,
                                             band_trigger_offset_ms,
                                             color_rotate_lead_ms,
                                             momentary_switch_would_glide)

SEQUENCE: tuple[str, ...] = ("charge", "lull", "drop")

# The default gap between one mark and the next, per class, when he hasn't
# said otherwise. Derived, never a fourth tuned number: PHASE_RAMP_MS is
# the ramp the class falls back to when the gap is UNKNOWABLE, and a ramp
# is 90% of its gap — so the gap that reproduces exactly that ramp is
# PHASE_RAMP_MS / (1 - HANG). Opening the preview therefore shows the
# tuned default shape, and moving a gap slider shows the stretch.
DEFAULT_GAP_MS = {cls: round(PHASE_RAMP_MS[cls] / (1.0 - PHASE_RAMP_HANG_FRACTION))
                  for cls in PHASE_RAMP_STRETCH_CLASSES}
# The drop is never stretched, so its "gap" is only how long the ruler
# holds it before the lap resets — the fixed snap plus room to watch the
# payoff land.
DROP_TAIL_MS = 2500

TAIL_PAD_S = flare_preview.TAIL_PAD_S
MIN_TIMELINE_S = flare_preview.MIN_TIMELINE_S
FRONT_PAD_S = 0.75


def class_lead_ms(scene: SceneV2, event_class: str, intensity: float,
                  virtuals: dict) -> int:
    """The lead the FIRING PATH would apply for this class's band — the
    same two contributors trigger_engine._response_switch_lead_ms takes a
    max over, and the same unconditional drop short-circuit ahead of them.
    Deliberately mirrored here rather than imported from trigger_engine:
    that method needs the LIVE active scene and live virtuals off the
    production engine singletons, which a preview of a hypothetical scene
    has no business reaching into. The BRANCH STRUCTURE is what must not
    diverge, and it is one short function in both places — see
    tests/test_phase_preview.py, which asserts the two agree for every
    class rather than trusting the mirroring."""
    if event_class == "drop":
        return 0
    lead = color_rotate_lead_ms(scene, event_class, intensity, virtuals)
    if momentary_switch_would_glide(scene, event_class, intensity, virtuals):
        lead = max(lead, DICE_REROLL_GLIDE_MS)
    return lead


def default_gaps() -> dict[str, int]:
    return dict(DEFAULT_GAP_MS)


def switch_for(scene: SceneV2, intensity: float, enabled: bool = True
               ) -> Optional[tuple[Any, Optional[SceneV2]]]:
    """THE DROP-LED SWITCH, as the preview shows it (spectra/services/
    drop_switch.py): the resolver's own decision for this scene at a drop
    where it has grown stale by repetition — deterministic for the scene,
    so open and every lap's fire agree — and the scene it would cut to.
    None when he asked the preview not to show it."""
    if not enabled:
        return None
    from spectra.services import drop_switch, scene_store
    try:
        settings = drop_switch.default_settings()
    except Exception:                                    # noqa: BLE001
        settings = drop_switch.SwitchSettings()
    plan = drop_switch.preview_plan(scene, intensity, settings=settings)
    target = scene_store.get_by_id(plan.to_scene_id) if plan.switch else None
    if plan.switch and target is None:
        return None
    return plan, target


def _switch_class(plan) -> Optional[str]:
    """Which mark the cut lands on: the drop, or (early) the charge."""
    from spectra.services import drop_switch
    if plan is None or not plan.switch:
        return None
    return "drop" if plan.moment == drop_switch.MOMENT_DROP else "charge"


async def build_timeline(scene: SceneV2, intensity: float, *,
                         gaps: Optional[dict[str, int]] = None,
                         drop_switch_enabled: bool = True) -> dict[str, Any]:
    """The three-mark sequence timeline. `gaps` is how far each stretching
    class's next mark sits ahead of it — the very thing the ramp stretches
    to fill, so it is the one control that changes the drawn shape.

    `drop_switch` in the result is the drop-led switch the resolver would
    make here (switch_for): the target, the moment, the hand-off, what the
    lull is told, and `cut_s` — where on this ruler the cut lands."""
    resolved_gaps = {**DEFAULT_GAP_MS, **(gaps or {})}

    # A scratch pair, purely so the lead functions can read the effect
    # types/baselines a real fire would (same reads flare_preview makes).
    from spectra.services.fx_executor import RecordingExecutor
    clock = flare_preview._FakeClock()
    conductor, _responder, _writes = flare_preview._scratch_engine(
        scene, intensity, clock, RecordingExecutor(clock=clock))
    virtuals = conductor.virtuals

    marks: list[dict[str, Any]] = []
    at_ms = 0
    for cls in SEQUENCE:
        gap_ms = resolved_gaps.get(cls) if cls in PHASE_RAMP_STRETCH_CLASSES else None
        ramp_ms = _phase_ramp_ms(cls, gap_ms)
        # The HANG is whatever is left of the gap once the ramp finishes —
        # free, because nothing writes phase_progress again until the next
        # phase event fires (see _phase_ramp_ms's own docstring).
        hang_ms = max(0, (gap_ms or 0) - ramp_ms)
        offset_ms = band_trigger_offset_ms(scene, cls, intensity)
        lead_ms = class_lead_ms(scene, cls, intensity, virtuals)
        marks.append({
            "event_class": cls,
            # Where the MARK sits: the class's own slot, relocated by its
            # band's authored offset in HIS sign (negative = earlier) —
            # the same relocation trigger_engine.tick() performs.
            "mark_ms": at_ms + offset_ms,
            "slot_ms": at_ms,
            "trigger_offset_ms": offset_ms,
            "lead_ms": lead_ms,
            "ramp_ms": ramp_ms,
            "hang_ms": hang_ms,
            "gap_ms": gap_ms,
            "stretched": cls in PHASE_RAMP_STRETCH_CLASSES and gap_ms is not None,
            "anchor_rule": ("drop_start" if cls == "drop" else "switch_end"),
        })
        at_ms += (gap_ms if gap_ms is not None
                  else PHASE_RAMP_MS[cls] + DROP_TAIL_MS)

    front_pad_ms = round(FRONT_PAD_S * 1000)
    max_lead_ms = max(m["lead_ms"] for m in marks)
    shift_ms = front_pad_ms + max_lead_ms - min(m["mark_ms"] for m in marks)
    for m in marks:
        m["mark_s"] = round((m["mark_ms"] + shift_ms) / 1000.0, 4)
        # THE ONE FORMULA, called not re-derived: fire_at = mark - lead,
        # the LEAD family's own native sense (positive = earlier). The
        # authored OFFSET already moved mark_ms, exactly as tick() applies
        # it before any lead — never the two added under one sign.
        m["fire_at_s"] = round(flare_preview.fire_at_s(m["mark_s"], m["lead_ms"]), 4)
        m["ramp_start_s"] = m["fire_at_s"]
        m["ramp_end_s"] = round(m["fire_at_s"] + m["ramp_ms"] / 1000.0, 4)
        m["hang_end_s"] = round(m["ramp_end_s"] + m["hang_ms"] / 1000.0, 4)

    end_s = max(m["hang_end_s"] for m in marks)
    duration_s = max(MIN_TIMELINE_S, end_s + TAIL_PAD_S)
    cues = [{"step": m["event_class"], "at_s": m["fire_at_s"],
             "label": f"{m['event_class']} fires"} for m in marks]
    # The lap's own reset: release the phase the way a track change does,
    # so the next lap starts from a clean, unarmed effect rather than
    # inheriting a charge that never ended.
    cues.append({"step": "release", "at_s": round(duration_s - 0.25, 4),
                 "label": "release the phase"})
    switch = switch_for(scene, intensity, drop_switch_enabled)
    switch_out: Optional[dict[str, Any]] = None
    if switch is not None:
        from spectra.services import drop_switch
        from spectra.services.scene_response import LullContext
        plan, _target = switch
        switch_out = plan.as_dict()
        cls = _switch_class(plan)
        mark = next((m for m in marks if m["event_class"] == cls), None)
        switch_out["cut_s"] = mark["fire_at_s"] if mark else None
        lull_gap = resolved_gaps.get("lull")
        told = drop_switch.handoff_for(plan, LullContext(
            scene=scene, intensity=intensity, gap_ms=lull_gap,
            lull_s=(lull_gap or 0) / 1000.0,
            virtuals={vid: st.effect_type for vid, st in virtuals.items()}),
            target_scene=_target)
        switch_out["lull_told"] = {"keep": told.keep,
                                   "next": dict(told.next_effect)}
    return {
        "scene_id": scene.id, "scene_name": scene.name,
        "intensity": round(intensity, 4),
        "drop_switch": switch_out,
        "duration_s": round(duration_s, 4),
        "gaps": resolved_gaps,
        "hang_fraction": PHASE_RAMP_HANG_FRACTION,
        "marks": marks,
        "cues": cues,
        # Which virtuals the vendored phase machinery will actually reach —
        # empty means this scene has no phase-capable effect live and the
        # sequence would drive nothing, which the overlay says out loud
        # rather than looping an invisible preview.
        "phase_targets": _phase_targets(virtuals),
    }


def _phase_targets(virtuals: dict) -> list[str]:
    from fx import device_model
    return [vid for vid, st in virtuals.items()
            if getattr(st, "effect_type", None) in device_model.PHASE_EFFECTS]


class PhaseSequenceProgram(flare_preview_hold.PreviewProgram):
    """The LIVE half, on the one shared hold: hold the scene, then drive
    the REAL phase machinery for each class in turn as its cue comes round,
    and release the phase at the end of the lap.

    Each step is a genuine ResponseEngine.on_event — the same call the
    bridge's classified charge/lull/drop and a fire_response trigger both
    make — so the effect-side choreography (blackhole's swallow, orbits'
    collapse, fireworks' rockets, the eye's lids) is the vendored code
    itself, exactly as in the show. The gap is threaded through, so the
    ramp the room renders is the ramp the ruler drew. It fires as the
    TRIGGER's relocated fire (anchor_relocated=True): each cue already sits
    at its band's anchor, the same relocation tick() applies, so a band's
    kinds land at their own moments here exactly as they do in the show.

    NO NEW RELEASE QUEUE. on_event can arm the momentary-release queue, the
    colour-rotate queue and a band's staggered kind batches (scene_response's
    "PER-FLARE TRIGGER MOMENT"); the hold drains all three
    (flare_preview_hold._schedule_responder_tail), as every drain point must
    (a queue missed at one of them has already shipped one real defect — see
    scene_response's colour-rotate note). release_phases() is a direct
    write, not a queue, so it adds nothing more to schedule."""

    steps = SEQUENCE + ("release",)

    def __init__(self, scene: SceneV2, gaps: Optional[dict[str, int]] = None,
                 switch: Optional[tuple[Any, Optional[SceneV2]]] = None) -> None:
        self.hold_scene = scene
        self.gaps = {**DEFAULT_GAP_MS, **(gaps or {})}
        # THE DROP-LED SWITCH (switch_for): (plan, target scene) or None.
        self.switch = switch if (switch and switch[0].switch and switch[1]) else None

    def _target_writes(self, intensity: float) -> list[dict]:
        from spectra.services import transition_preview
        return transition_preview._compile(self.switch[1], intensity, rng_seed=17)

    def extra_snapshot_writes(self, intensity: float) -> list[dict]:
        # the scene the cut lands on can reach virtuals the held one never
        # does — they must be in the snapshot too
        return self._target_writes(intensity) if self.switch else []

    async def execute(self, step: str, ctx) -> dict:
        if ctx.first_open:
            # Land the scene once so a phase-capable effect is actually
            # live to drive; later laps must NOT re-fire it, or every lap
            # would restart the effect underneath the sequence.
            await ctx.apply_scene()
        switched_at = _switch_class(self.switch[0]) if self.switch else None
        cut = None
        if switched_at is not None and step in SEQUENCE:
            plan, target = self.switch
            here = SEQUENCE.index(step)
            at = SEQUENCE.index(switched_at)
            if here >= at:
                writes = self._target_writes(ctx.intensity)
                if here == at:
                    # THE CUT, exactly as the trigger clock lands it: the
                    # target scene with no blend, then this member's own
                    # phase arm on the NEW effects
                    await ctx.apply_scene(writes=writes, transition_ms=0, cut=True)
                    cut = {"to_scene": target.name, "moment": plan.moment,
                           "handoff": plan.handoff}
                # every step on a fresh scratch pair: point it at the scene
                # the room now shows (the cut already put it there)
                ctx.conductor.on_scene_fire(target, writes)
            elif step == "lull" and plan.moment == "drop":
                from spectra.services import drop_switch
                ctx.responder.lull_handoff_resolver = (
                    lambda c: drop_switch.handoff_for(plan, c, target_scene=target))
        if step == "release":
            if switched_at is not None:
                # hand the next lap back its own scene (a cut, so the reset
                # never reads as a second transition)
                await ctx.apply_scene(transition_ms=0, cut=True)
            # force=True: each preview step runs on a fresh scratch pair, so
            # no _phase_armed state survives the step that armed it — and a
            # DROP arms nothing by production's own rule (_drive_phase only
            # arms charge/lull), which is exactly the end of a sequence. See
            # ResponseEngine.release_phases' own docstring; every production
            # call site keeps the guard.
            released = await ctx.responder.release_phases(force=True)
            return {"result": "phase_released", "virtuals": released}
        if step not in SEQUENCE:
            raise ValueError(f"unknown drop-sequence step: {step!r}")
        gap_ms = self.gaps.get(step) if step in PHASE_RAMP_STRETCH_CLASSES else None
        record = await ctx.responder.on_event(step, ctx.intensity, gap_ms,
                                              anchor_relocated=True)
        out = {"result": "phase_fired", "event_class": step,
               "gap_ms": gap_ms, "record": record}
        if cut is not None:
            out["drop_switch"] = cut
        return out
