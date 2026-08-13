"""The colour journey — room-level walk by default, per-scene OVERRIDE
first-class (owner's color-drift-scope answer, 2026-08-13).

THE TRANSITION SEMANTICS (binding; the S2 conductor executes exactly this):

The room owns ONE wheel position — shared room-colour state, the same truth
the sequencer's travel factor reads. A journey never owns a position of its
own; it only STEERS the room's. An override therefore takes CUSTODY of the
pen, never a fork of the story:

  INTO an overriding scene — the override starts steering FROM the room's
  current wheel position. No snap: the palette lands via the scene change's
  normal crossfade choreography, and the walk continues from wherever the
  room's story had reached, now at the override's pace and direction.

  OUT OF an overriding scene — the override hands the pen back. The room's
  own journey resumes FROM WHEREVER THE OVERRIDE LEFT THE WHEEL, walking at
  the room's pace and direction again. The room never snaps back to where
  it froze when the override began — that would yank the hue, exactly what
  room-level ownership exists to prevent.

Consequence, stated plainly: an override MOVES the room's colour story;
inherit-mode scenes that follow continue from the override's endpoint. One
continuous journey, custody changing hands, zero discontinuities.

Also binding here: rainbow/achromatic palettes have no wheel position, so
the walk PAUSES while one is live (step() is identity); pace_factor 0 on an
inherit scene holds the room walk while that scene shows.

Everything below is pure except the room-state store (storage/spectra/
room_color.json). S1 ships the model + semantics + editor surface; the S2
drift conductor calls step()/on_scene_enter()/on_scene_exit() on its legs.
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

# Default room journey: the slow blue-toward-purple rotation the design
# names (positive = increasing hue). ~2°/min ≈ a full lap in 3 hours.
DEFAULT_ROOM_DEGREES_PER_MIN = 2.0


class RoomColorState(BaseModel):
    journey: ColorJourneySpec = Field(
        default_factory=lambda: ColorJourneySpec(
            degrees_per_min=DEFAULT_ROOM_DEGREES_PER_MIN))
    wheel_position_deg: Optional[float] = None   # None until a chromatic set fires
    active_set_id: Optional[str] = None


class EffectiveJourney(BaseModel):
    """What actually steers the wheel while a given scene shows."""
    custody: str                        # "room" | "scene"
    degrees_per_min: float


def active_journey(room: RoomColorState, scene: SceneV2 | None) -> EffectiveJourney:
    """Resolve who steers and how fast. Inherit scales the room's pace by
    the scene's pace_factor (0 holds); an override replaces it outright."""
    if scene is not None and scene.color_journey.mode == "override":
        return EffectiveJourney(
            custody="scene",
            degrees_per_min=scene.color_journey.journey.degrees_per_min)
    factor = scene.color_journey.pace_factor if scene is not None else 1.0
    return EffectiveJourney(
        custody="room",
        degrees_per_min=room.journey.degrees_per_min * factor)


def step(journey: EffectiveJourney, wheel_deg: Optional[float],
         dt_s: float, *, palette_rainbow: bool = False) -> Optional[float]:
    """Advance the wheel by one conductor leg. Identity when no chromatic
    position exists yet or a rainbow/achromatic palette is live (the walk
    pauses — the binding exemption)."""
    if wheel_deg is None or palette_rainbow:
        return wheel_deg
    return (wheel_deg + journey.degrees_per_min * (dt_s / 60.0)) % 360.0


def on_scene_enter(room: RoomColorState, scene: SceneV2 | None) -> EffectiveJourney:
    """A scene takes the room: the effective journey starts steering from
    room.wheel_position_deg AS IS — custody transfers, the position does not
    move. (The palette swap itself rides the scene-change crossfade.)"""
    return active_journey(room, scene)


def on_scene_exit(room: RoomColorState, wheel_deg_at_exit: Optional[float]) -> RoomColorState:
    """An overriding scene ends: the room adopts the override's final wheel
    position and its own journey resumes from there. Returns the updated
    room state (callers persist via save_room())."""
    return room.model_copy(update={"wheel_position_deg": wheel_deg_at_exit})


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
