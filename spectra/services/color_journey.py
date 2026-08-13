"""The colour journey — DESTINATION-DRIVEN room-level walk by default,
per-scene OVERRIDE first-class (owner's color-drift-scope answer 2026-08-13;
destination rework, the owner's five-updates order 2026-08-13).

THE DESTINATION MODEL (binding; the S2 conductor executes exactly this):

The room picks a DESTINATION colour set — a set fitting the criteria of the
shipped selector (curve × genre × wheel-travel) — and that destination
determines BOTH which set the room is heading toward AND the speed of
travel: pace is fixed at selection from the reference pace and the
destination's distance (destination_pace — near strolls, far hurries). The
room drifts slowly toward it along the shortest arc; ON ARRIVAL it selects
the next destination and sets off again. Never aimless creep: always a
target, per-destination pace. The destination is a BEARING, not an applied
palette — sets are applied by scene fires and flare jumps; the journey
rotates the active palette's hues toward the destination's wheel position.

THE TRANSITION SEMANTICS (unchanged from the shipped custody answer):

The room owns ONE wheel position — shared room-colour state, the same truth
the sequencer's travel factor reads. A journey never owns a position of its
own; it only STEERS the room's. An override therefore takes CUSTODY of the
pen, never a fork of the story:

  INTO an overriding scene — the override starts steering FROM the room's
  current wheel position. No snap: the palette lands via the scene change's
  normal crossfade choreography, and the walk continues from wherever the
  room's story had reached — the override picks ITS OWN destination, by the
  same selector, WITHIN ITS OWN PALETTE BOUNDS (the scene's accepted sets),
  at its own reference pace.

  OUT OF an overriding scene — the override hands the pen back. The room's
  own journey resumes FROM WHEREVER THE OVERRIDE LEFT THE WHEEL, picking a
  fresh room destination. The room never snaps back to where it froze when
  the override began — that would yank the hue, exactly what room-level
  ownership exists to prevent.

Custody changes therefore CLEAR the destination (the new custody reselects
under its own criteria on the next leg) but never move the wheel. The same
clearing happens when a flare colour jump or sequencer colour roll
teleports the wheel — the journey re-orients from the new point.

Consequence, stated plainly: an override MOVES the room's colour story;
inherit-mode scenes that follow continue from the override's endpoint. One
continuous journey, custody changing hands, zero discontinuities.

Also binding here: rainbow/achromatic palettes have no wheel position, so
the walk PAUSES while one is live (travel holds, destination kept);
pace_factor 0 on an inherit scene holds the room walk while that scene
shows (no destinations picked, none discarded). A rainbow SET is never a
destination — it is everywhere and nowhere on the wheel.

Everything below is pure except the room-state store (storage/spectra/
room_color.json). The S2 drift conductor calls step_toward() on its legs
and owns destination selection (it holds the selector's inputs).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from pydantic import BaseModel, Field

from spectra import config
from spectra.models.scene import ColorJourneySpec, SceneV2

logger = logging.getLogger(__name__)

# The owner's live room pace, carried forward as the effective default
# (set and confirmed live at 30 on 2026-08-13; never silently reverts to
# the old 2°/min design value).
DEFAULT_ROOM_DEGREES_PER_MIN = 30.0

# Per-destination pace: a destination REFERENCE_TRAVEL_DEG away travels at
# exactly the journey's reference pace; the scale clamps so near
# destinations still visibly move and far ones never sprint.
REFERENCE_TRAVEL_DEG = 90.0
PACE_SCALE_MIN = 0.5
PACE_SCALE_MAX = 2.0

# Within this of the destination counts as arrived (the leg lands exactly
# on the destination position, then reselects).
ARRIVAL_EPSILON_DEG = 0.5


class JourneyDestination(BaseModel):
    """The journey's current bearing: which set the room is heading toward,
    at what pace (fixed at selection — the destination determines it), and
    where the walk began (for progress reporting)."""
    set_id: str
    set_name: str = ""
    position_deg: float
    pace_deg_per_min: float
    from_deg: float
    rung: str = ""           # the selector rung that picked it (observability)


class RoomColorState(BaseModel):
    journey: ColorJourneySpec = Field(
        default_factory=lambda: ColorJourneySpec(
            degrees_per_min=DEFAULT_ROOM_DEGREES_PER_MIN))
    wheel_position_deg: Optional[float] = None   # None until a chromatic set fires
    active_set_id: Optional[str] = None
    destination: Optional[JourneyDestination] = None  # runtime bearing


class EffectiveJourney(BaseModel):
    """Who steers while a given scene shows, and their reference pace."""
    custody: str                        # "room" | "scene"
    degrees_per_min: float


def active_journey(room: RoomColorState, scene: SceneV2 | None) -> EffectiveJourney:
    """Resolve who steers and their reference pace. Inherit scales the
    room's pace by the scene's pace_factor (0 holds); an override replaces
    it outright."""
    if scene is not None and scene.color_journey.mode == "override":
        return EffectiveJourney(
            custody="scene",
            degrees_per_min=abs(
                scene.color_journey.journey.degrees_per_min))
    factor = scene.color_journey.pace_factor if scene is not None else 1.0
    return EffectiveJourney(
        custody="room",
        degrees_per_min=abs(room.journey.degrees_per_min) * factor)


def signed_travel(from_deg: float, to_deg: float) -> float:
    """Signed shortest arc from → to, in (-180, 180]."""
    return ((to_deg - from_deg + 540.0) % 360.0) - 180.0


def destination_pace(reference_deg_per_min: float, travel_deg: float) -> float:
    """The pace a destination fixes for itself: reference pace scaled by
    distance (near strolls, far hurries), clamped."""
    scale = min(max(travel_deg / REFERENCE_TRAVEL_DEG, PACE_SCALE_MIN),
                PACE_SCALE_MAX)
    return abs(reference_deg_per_min) * scale


def step_toward(wheel_deg: Optional[float], dest_deg: float,
                pace_deg_per_min: float, dt_s: float, *,
                palette_rainbow: bool = False,
                ) -> tuple[Optional[float], bool]:
    """Advance the wheel one leg toward the destination along the shortest
    arc. Returns (new_deg, arrived). Identity when no chromatic position
    exists yet or a rainbow/achromatic palette is live (the walk pauses —
    the binding exemption); arrival lands EXACTLY on the destination."""
    if wheel_deg is None or palette_rainbow:
        return wheel_deg, False
    remaining = signed_travel(wheel_deg, dest_deg)
    step = pace_deg_per_min * (dt_s / 60.0)
    if abs(remaining) <= max(step, ARRIVAL_EPSILON_DEG):
        return dest_deg % 360.0, True
    return (wheel_deg + (step if remaining > 0 else -step)) % 360.0, False


def progress(destination: JourneyDestination,
             wheel_deg: Optional[float]) -> float:
    """0..1 fraction of the walk completed, for the status strip."""
    if wheel_deg is None:
        return 0.0
    total = abs(signed_travel(destination.from_deg, destination.position_deg))
    if total < ARRIVAL_EPSILON_DEG:
        return 1.0
    remaining = abs(signed_travel(wheel_deg, destination.position_deg))
    return max(0.0, min(1.0, 1.0 - remaining / total))


def on_scene_enter(room: RoomColorState, scene: SceneV2 | None) -> EffectiveJourney:
    """A scene takes the room: the effective journey starts steering from
    room.wheel_position_deg AS IS — custody transfers, the position does not
    move. (The palette swap itself rides the scene-change crossfade; the
    conductor clears the destination so the new custody reselects.)"""
    return active_journey(room, scene)


def on_scene_exit(room: RoomColorState, wheel_deg_at_exit: Optional[float]) -> RoomColorState:
    """An overriding scene ends: the room adopts the override's final wheel
    position, drops the override's bearing, and its own journey resumes
    from there with a fresh room destination. Returns the updated room
    state (callers persist via save_room())."""
    return room.model_copy(update={"wheel_position_deg": wheel_deg_at_exit,
                                   "destination": None})


# ── room-state store ─────────────────────────────────────────────────────────

def load_room() -> RoomColorState:
    path = config.ROOM_COLOR_FILE
    if path.exists():
        try:
            return RoomColorState(**json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("room_color.json parse failed: %s", exc)
    return RoomColorState()


def save_room(state: RoomColorState) -> None:
    path = config.ROOM_COLOR_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(json.loads(state.model_dump_json()), fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
