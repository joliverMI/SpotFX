"""Deterministic, hardware-free timeline for previewing ONE flare kind in
isolation — the scrubbing preview timeline, flares first (his ask:
data/timeline-preview-scrub-flares-and-drop-sequences/HIS-VERBATIM-WORDS.md
— "bring up a timeline with any markers that are relevant, and preview
going across the timeline... so I can see it's evolution and help edit
where the trigger should land with respect to the effect"). Charge/lull/
drop sequences are explicitly NOT built here — his own sequencing: "start
with the flares, then we will do lull charge drop."

He asked for LIVE if it's easy, "catch up" pre-authorised if substantially
easier — this ships the catch-up path, and it is a better instrument for
his stated purpose than a literal live feed would be: the whole visible
shape of a flare kind (every glide/jump ResponseEngine.fire_kind would
issue, and exactly when) is a PURE function of the scene + kind +
intensity. It is computed ONCE, synchronously, against a scratch
DriftConductor/ResponseEngine pair wired to a RecordingExecutor (the S2
production dark-mode executor — no live storage write, no hardware touch)
and a caller-controlled fake clock, then handed to the frontend as a JSON
timeline it scrubs/loops/plays locally — no repeated backend calls per
frame, no render-thread polling. This is also what makes the two marker
kinds his brief calls out honest: `animation_start_s`/`animation_end_s`
are read directly off the real production constants (DICE_REROLL_GLIDE_MS,
PULSE_HOLD_S/hold_ms, PULSE_RELEASE_S, GAIN_GLIDE_S, color_jump_ramp_ms) —
never guessed, never a live capture that could itself lie about a fast
glide (see AGENTS.md's "Reading real Hue bulb state" / "CLIP v2 dynamics"
entries for why polling a live device is the wrong instrument for exactly
this question).

Read-only against live storage (room controls, the room's active colour
set/wheel position, sequencer curves) — the SAME reads a dry-run scene
test-fire already performs (scene_compiler.fire_scene, dry_run=True). This
module's OWN timeline computation (build_timeline, below) never writes:
both the scratch DriftConductor and ResponseEngine get `room_save=lambda
_st: None` so `on_scene_fire`'s "clear the journey destination" update and
a colour-jump kind's wheel-position landing are computed and reported but
never persisted, and `_scratch_engine` is always handed a RecordingExecutor
here — its `glide`/`jump` only ever append to an in-memory deque.

Opening the preview overlay DOES now reach his real fixtures, via a
SEPARATE module: spectra/services/flare_preview_hold.py fires the same
scene + kind this module computes against `_scratch_engine`'s SAME
resolve/compile path, just handed a live, fx_seam-backed executor instead
of a RecordingExecutor — see that module's own docstring for the full
mechanism and the revert-on-close/heartbeat-timeout/restart guarantees.
`_scratch_engine` takes its executor as a caller-supplied argument
specifically so the two callers (this module's dark timeline, that
module's live hold) share one resolve/compile/seed path and can never
silently diverge in what they compute.

TRUE SIMULATION (2026-08-21, data/preview-loops-and-fires-on-the-trigger,
his report: "the preview only happens once, it should happen every time,
and it should fire with the same timing as if the playhead was crossing a
trigger"): before this, the live hold fired instantly the moment the
overlay opened, no matter where the drawn trigger mark sat — the DRAWING
knew about the mark, the FIRING did not. `animation_anchor_s`/
`trigger_mark_s` below are the fix: a fixed ruler-layout position (where
"the animation starts" is drawn — never authored, purely a layout choice)
and the trigger mark's position derived from it via `kind.
trigger_offset_ms`, HIS sign convention (see FlareKind.trigger_offset_ms's
own docstring, models/scene.py, for the full ruling and the 2026-08-20
build's inverted-sign defect it corrects). Both numbers ride in every
build_timeline() response so the frontend's ruler draw AND its live-fire
loop (FlarePreviewOverlay.tsx) read the IDENTICAL values — one source of
truth, never two independently-computed anchors that could quietly
disagree.

FIRE-TIME LEAD (2026-08-21, fm/preview-must-hold-scene-changes, his ask:
the preview must use the app's own delay/offset setting when it fires, not
a hardcoded number or a private idea of timing — "the same lead the real
show applies must apply here, or the preview lies about when his flare
lands"). Before this, the live fire was scheduled at `animation_anchor_s`
unconditionally — a purely authored/manual position, with no reference to
the AUTOMATIC lead trigger_engine._response_switch_lead_ms computes for a
real trigger fire (the fixed DICE_REROLL_GLIDE_MS for a momentary param
glide, or the intensity-scaled color_rotate_ramp_ms for a colour-rotate
kind — see scene_response.kind_lead_ms, the per-kind extraction this reuses
verbatim rather than re-deriving). `fire_at_s` below is the fix, using
EXACTLY the composition #172 (SpectraTrigger.trigger_offset_ms landing in
trigger_engine.tick()) established for the sibling authored-offset field,
so the two never silently diverge in HOW an offset and an automatic lead
combine: `target := animation_anchor_s` (algebraically, since
`trigger_mark_s = animation_anchor_s - offset_ms/1000` already means
`trigger_mark_s + offset_ms/1000 == animation_anchor_s` for ANY offset —
his own authored offset is already baked into animation_anchor_s by
construction, the same way #172's `target_ms = timestamp_ms +
trigger_offset_ms` bakes the authored offset into its own target before
lead ever runs); `fire_at_s = target - lead_ms/1000`, lead acting in its
own native "positive = earlier" sense, exactly as production's `fire_at =
target_ms - lead_ms` does. This never changes `trigger_mark_s`'s own
formula or meaning — the drawn mark still reflects only his authored
offset — it only moves WHEN THE WRITE ACTUALLY HAPPENS, closer to the
mark by however long this kind's own switch/ramp needs to complete before
landing there, same as a real trigger fire would.

WHICH ANCHOR RULE (2026-08-27, fm/flare-preview-offsets-everywhere): the
lead above is only the MOMENTARY-FLARE family's answer — one of the three
settled anchor families (his ruling 2026-08-20: a momentary flare anchors
its first switch's END to the mark, a scene transition its MIDDLE, a drop
its START). Which one governs a fire is decided by the fire's EVENT CLASS,
not by the kind's type: trigger_engine._response_switch_lead_ms returns 0
unconditionally for `event_class == "drop"`, ahead of every other branch.
kind_lead_ms is class-blind by construction (it answers "what would this
kind need under the momentary rule"), so this module resolves the rule
itself — scene_response.kind_anchor_rule, from the classes the kind's
bands actually attach it to — and reports it as `anchor_rule` alongside
`attached_classes`. A kind attached ONLY to drop bands previews with
lead 0 and says so; before this it previewed a DICE_REROLL_GLIDE_MS head
start production would never have taken, which is precisely the preview
lying about when his flare lands. Latent rather than live in his stored
data (no real drop band attaches a qualifying kind today) — closed for the
same reason _response_switch_lead_ms made its own drop branch
unconditional rather than resting on that fact.
"""
from __future__ import annotations

from random import Random
from typing import Any, Callable

from spectra.models.scene import FlareKind, SceneV2
from spectra.services import room_controls, scene_compiler
from spectra.services.binding_resolver import FireContext
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.scene_response import (ANCHOR_DROP_START, ResponseEngine,
                                             kind_anchor_rule,
                                             kind_attached_classes, kind_lead_ms)

# A scrub timeline must never look shorter than his own worked example (a
# 6s timeline holding a 3s effect) even when a kind's own computed shape is
# much shorter (e.g. an instant, non-glide dice re-roll) — a near-zero
# default timeline would read as broken, not "fast."
MIN_TIMELINE_S = 6.0
# Padding after the last write settles, so a looped preview visibly rests
# at baseline before it repeats instead of looping mid-glide.
TAIL_PAD_S = 2.0


def animation_anchor_s(duration_s: float) -> float:
    """Where "the animation starts" is drawn on the ruler / where the live
    loop actually issues its fire each cycle — a fixed ruler-LAYOUT choice,
    never authored, never derived from trigger_offset_ms (the trigger mark
    is what moves relative to this, not the other way around). Kept short
    of the ruler's own front edge even on a very short timeline so a
    negative offset still has room to draw its mark to the left of it."""
    return min(2.0, duration_s / 3)


def trigger_mark_s(anchor_s: float, offset_ms: int, duration_s: float) -> float:
    """Where the trigger mark sits, HIS sign convention (ruling 2026-08-21,
    data/preview-loops-and-fires-on-the-trigger — see FlareKind.
    trigger_offset_ms's own docstring for the full statement): negative
    offset = fire earlier, so the mark sits to the RIGHT of animation
    start; positive = fire later, mark to the LEFT. T = F - offset_ms/1000.
    Clamped into the visible ruler purely for drawing — the live-fire loop
    itself never reads this clamped value, only the unclamped anchor_s
    (an offset large enough to push the mark off-ruler still fires
    correctly, it just draws off the edge)."""
    t = anchor_s - offset_ms / 1000.0
    return max(0.0, min(duration_s, t))


def fire_at_s(anchor_s: float, lead_ms: int) -> float:
    """When the live-fire loop actually issues its /fire call — the write
    itself, not the drawn mark. `target := anchor_s` here always (see this
    module's own "FIRE-TIME LEAD" docstring section for the algebraic proof
    that his authored offset is already baked into anchor_s by construction
    of trigger_mark_s above), so this is #172's `fire_at = target - lead_ms`
    composition with nothing left to add. NOT clamped into [0, duration_s]
    — unlike trigger_mark_s (a pure drawing value), the frontend's own loop
    wraps a negative or over-long delay correctly via plain modular
    real-time arithmetic against whatever the CURRENT duration_s is, so
    clamping here would silently shrink a lead that's genuinely longer than
    the gap to the ruler's front edge."""
    return anchor_s - lead_ms / 1000.0


class _FakeClock:
    """A controllable clock for RecordingExecutor/DriftConductor/
    ResponseEngine's own `clock` callables. Every write this module issues
    happens in one synchronous burst (no real asyncio.sleep) — advancing
    `t` between phases is what gives each recorded write its real relative
    offset (e.g. a momentary release recorded at `t=hold_s`, matching
    production's engine._release_after_hold(asyncio.sleep(hold_s)) exactly,
    just computed instantly instead of actually waited)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance_to(self, t: float) -> None:
        self.t = max(self.t, t)


def _scratch_engine(scene: SceneV2, intensity: float,
                    clock: Callable[[], float], executor: Any
                    ) -> tuple[DriftConductor, ResponseEngine, list[dict]]:
    """Seed a conductor+responder pair exactly the way a real scene fire
    would (reusing scene_compiler.resolve_scene/compile_scene — the same
    resolution a dry-run scene test-fire performs, effect_steps/bindings
    included), wired to `executor` (a RecordingExecutor for this module's
    own dark timeline; flare_preview_hold.py hands in a live, fx_seam-backed
    one instead — the caller decides, this function only ever seeds). Every
    constructor injectable besides `room_save` is left at its own
    production default (a real, read-only storage load) — the same reads a
    dry-run test-fire already makes; only the write side is stubbed out.
    Returns the compiled writes too, alongside the pair — a caller that
    needs to apply them for real (flare_preview_hold's own "call the
    scene" step) must not re-derive them a second, possibly-diverging way."""
    conductor = DriftConductor(
        executor=executor, clock=clock,
        room_save=lambda _st: None,   # a preview must never move the room
        rng=Random(0))
    room = room_controls.load_room_controls()
    ctx = FireContext(intensity, rng=Random(1))
    resolved = scene_compiler.resolve_scene(scene, ctx)
    color_set = scene_compiler.room_active_set()
    writes = scene_compiler.compile_scene(
        resolved, color_set, display_mode=room.display_mode,
        light_bg_color=room.display_light_bg_color)
    # The ORIGINAL scene, bindings intact — not `resolved` — matches
    # scene_compiler.fire_scene's own on_scene_fired(scene, writes, ...)
    # call: `writes` bakes in the ONE binding resolution this fire made,
    # but conductor.scene must keep every ValueBinding pristine so a
    # dice-reroll kind (ResponseEngine._reroll) has something fresh to
    # re-resolve on each subsequent flare fire, exactly like production.
    conductor.on_scene_fire(scene, writes)
    responder = ResponseEngine(
        conductor=conductor, executor=executor, clock=clock,
        rng=Random(2),
        room_save=lambda _st: None)   # same rule for _color_jump's own save
    return conductor, responder, writes


async def build_timeline(scene: SceneV2, kind: FlareKind,
                         intensity: float) -> dict[str, Any]:
    """The isolated single-kind execution timeline: every write fire_kind
    (+ its scheduled releases) issues, with real relative timing, plus the
    derived animation_start_s/animation_end_s markers the scrub UI draws
    its second kind of marker from. `writes[].at_s` is relative to the
    EARLIEST write (== the fire instant, since every landing write is
    issued synchronously at t=0) — the frontend positions this whole block
    against its own independently-draggable trigger-alignment marker."""
    clock = _FakeClock()
    executor = RecordingExecutor(clock=clock)
    conductor, responder, _writes = _scratch_engine(scene, intensity, clock, executor)
    fire_record = await responder.fire_kind(kind, intensity)
    for hold_s in responder.pending_hold_groups():
        clock.advance_to(hold_s)
        await responder.flush_releases(hold_s)
    # The colour ROTATE-AND-BACK flare's own release queue (its fade-back
    # duration is intensity-scaled, so it can't share pending_hold_groups/
    # flush_releases' fixed PULSE_RELEASE_S — see scene_response.
    # _color_rotate's own docstring). Same drain shape, separate queue.
    for dwell_s in responder.pending_color_rotate_holds():
        clock.advance_to(dwell_s)
        await responder.flush_color_rotates(dwell_s)

    # Same registry-smoothness/color-rotate lead a REAL trigger fire would
    # compute for this exact kind (scene_response.kind_lead_ms — reused
    # verbatim, see this module's own "FIRE-TIME LEAD" docstring section),
    # read against the SAME conductor.virtuals this fire just ran against.
    #
    # ANCHOR RULE (2026-08-27, fm/flare-preview-offsets-everywhere): which
    # of the three settled anchor families governs is decided by the
    # CLASSES this kind's bands attach it to, not by the kind's own type —
    # a momentary kind attached only to DROP bands fires under the drop
    # rule (START on the mark, lead 0, trigger_engine._response_switch_
    # lead_ms's own unconditional branch) and previewing it at
    # kind_lead_ms's class-blind number would have the preview claim a
    # head start production never takes. See scene_response.
    # kind_anchor_rule for the full statement and why kind_lead_ms's own
    # "previewed in isolation is never a drop" reasoning was about the
    # kind's TYPE and therefore answered a different question.
    anchor_rule = kind_anchor_rule(scene, kind)
    attached_classes = sorted(kind_attached_classes(scene, kind.name))
    lead_ms = (0 if anchor_rule == ANCHOR_DROP_START
               else kind_lead_ms(kind, intensity, conductor.virtuals))

    writes = list(responder.executor.writes)
    if not writes:
        anchor_s = animation_anchor_s(MIN_TIMELINE_S)
        return {
            "kind_name": kind.name, "kind_type": kind.type,
            "intensity": round(intensity, 4),
            "result": fire_record.get("result", "no_visible_effect"),
            "animation_start_s": None, "animation_end_s": None,
            "duration_s": MIN_TIMELINE_S,
            "animation_anchor_s": round(anchor_s, 4),
            "trigger_mark_s": round(
                trigger_mark_s(anchor_s, kind.trigger_offset_ms, MIN_TIMELINE_S), 4),
            "lead_ms": lead_ms,
            "anchor_rule": anchor_rule,
            "attached_classes": attached_classes,
            "fire_at_s": round(fire_at_s(anchor_s, lead_ms), 4),
            "writes": [],
        }
    start_s = min(w["at"] for w in writes)
    end_s = max(w["at"] + w["duration_ms"] / 1000.0 for w in writes)
    duration_s = max(MIN_TIMELINE_S, (end_s - start_s) + TAIL_PAD_S + 2.0)
    anchor_s = animation_anchor_s(duration_s)
    return {
        "kind_name": kind.name,
        "kind_type": kind.type,
        "intensity": round(intensity, 4),
        "result": fire_record.get("result", "applied"),
        "animation_start_s": round(start_s - start_s, 4),
        "animation_end_s": round(end_s - start_s, 4),
        "duration_s": round(duration_s, 4),
        "animation_anchor_s": round(anchor_s, 4),
        "trigger_mark_s": round(
            trigger_mark_s(anchor_s, kind.trigger_offset_ms, duration_s), 4),
        "lead_ms": lead_ms,
        "anchor_rule": anchor_rule,
        "attached_classes": attached_classes,
        "fire_at_s": round(fire_at_s(anchor_s, lead_ms), 4),
        "writes": [
            {
                "seq": w["seq"],
                "at_s": round(w["at"] - start_s, 4),
                "kind": w["kind"],
                "virtual_id": w["virtual_id"],
                "effect_type": w["effect_type"],
                "params": w["params"],
                "duration_ms": w["duration_ms"],
            }
            for w in sorted(writes, key=lambda w: w["seq"])
        ],
    }
