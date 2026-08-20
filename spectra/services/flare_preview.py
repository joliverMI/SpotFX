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
test-fire already performs (scene_compiler.fire_scene, dry_run=True) — but
NEVER a write: both the scratch DriftConductor and ResponseEngine get
`room_save=lambda _st: None` so `on_scene_fire`'s "clear the journey
destination" update and a colour-jump kind's wheel-position landing are
computed and reported but never persisted. No fx_seam/executor.facade call
of any kind is reachable from this path — the RecordingExecutor's `glide`/
`jump` only ever append to an in-memory deque.
"""
from __future__ import annotations

from random import Random
from typing import Any

from spectra.models.scene import FlareKind, SceneV2
from spectra.services import room_controls, scene_compiler
from spectra.services.binding_resolver import FireContext
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.scene_response import ResponseEngine

# A scrub timeline must never look shorter than his own worked example (a
# 6s timeline holding a 3s effect) even when a kind's own computed shape is
# much shorter (e.g. an instant, non-glide dice re-roll) — a near-zero
# default timeline would read as broken, not "fast."
MIN_TIMELINE_S = 6.0
# Padding after the last write settles, so a looped preview visibly rests
# at baseline before it repeats instead of looping mid-glide.
TAIL_PAD_S = 2.0


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
                    clock: _FakeClock) -> tuple[DriftConductor, ResponseEngine]:
    """Seed a conductor+responder pair exactly the way a real scene fire
    would (reusing scene_compiler.resolve_scene/compile_scene — the same
    resolution a dry-run scene test-fire performs, effect_steps/bindings
    included), wired to a shared RecordingExecutor and fake clock. Every
    constructor injectable besides `room_save` is left at its own
    production default (a real, read-only storage load) — the same reads a
    dry-run test-fire already makes; only the write side is stubbed out."""
    executor = RecordingExecutor(clock=clock)
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
    return conductor, responder


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
    conductor, responder = _scratch_engine(scene, intensity, clock)
    fire_record = await responder.fire_kind(kind, intensity)
    for hold_s in responder.pending_hold_groups():
        clock.advance_to(hold_s)
        await responder.flush_releases(hold_s)

    writes = list(responder.executor.writes)
    if not writes:
        return {
            "kind_name": kind.name, "kind_type": kind.type,
            "intensity": round(intensity, 4),
            "result": fire_record.get("result", "no_visible_effect"),
            "animation_start_s": None, "animation_end_s": None,
            "duration_s": MIN_TIMELINE_S, "writes": [],
        }
    start_s = min(w["at"] for w in writes)
    end_s = max(w["at"] + w["duration_ms"] / 1000.0 for w in writes)
    duration_s = max(MIN_TIMELINE_S, (end_s - start_s) + TAIL_PAD_S + 2.0)
    return {
        "kind_name": kind.name,
        "kind_type": kind.type,
        "intensity": round(intensity, 4),
        "result": fire_record.get("result", "applied"),
        "animation_start_s": round(start_s - start_s, 4),
        "animation_end_s": round(end_s - start_s, 4),
        "duration_s": round(duration_s, 4),
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
