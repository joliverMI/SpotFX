"""SPECTRA's room-control surface — agent-tellable room-wide switches that
don't belong to any one scene (spectra-kept-equivalents, the owner's KEPT
legacy picks: decision-legacy-retirement-picks.md):

  brightness_multiplier  the legacy Brightness Multiplier action equivalent
                          (models.music_event.BrightnessAction) — dims/undims
                          the WHOLE room uniformly, applied at the write
                          seams (fx_executor for engine glides/jumps,
                          scene_compiler for scene-fire writes), never the
                          conductor's own carried baseline: the authored
                          "look" stays intact, only the OUTPUT is scaled.
  ambient_enabled/_color  the legacy ledfx_ambient / ledfx_ambient_color
                          action equivalents — room-level state only.
  global_transition_ms    the legacy ledfx_global_transition action
                          equivalent — the default ramp new scene-entry
                          blends use when a scene doesn't author its own
                          entry_ramp_ms (SceneV2.entry_ramp_ms == 0).

Scope is deliberately the CONTROLS, not the behaviour: ambient_enabled today
only records the switch (folding into the room-control surface instead of
staying a spot-effects bridge flag, per the owner's routing) — the full
Ambient/Dinner-Party room-MODES build (freezing devices, Hue white takeover)
is its own separate checklist item (gap report §3 row 5).

Storage: storage/spectra/room_controls.json — same atomic tmp+replace
discipline as color_journey.py's room_color.json.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Optional

from pydantic import BaseModel, Field

from spectra import config


class RoomControlState(BaseModel):
    brightness_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    ambient_enabled: bool = False
    ambient_color: Optional[str] = None   # hex; None = no colour authored yet
    # 0 = no room default (today's unchanged instant-jump behaviour for any
    # scene that doesn't author its own entry_ramp_ms). >0 becomes the
    # FALLBACK ramp scene_compiler.fire_scene uses when a scene's own
    # entry_ramp_ms is 0 — the legacy ledfx_global_transition equivalent.
    global_transition_ms: int = Field(default=0, ge=0, le=20000)


def apply_brightness(params: dict, multiplier: float) -> dict:
    """Scale brightness/background_brightness IN a params dict by the room
    multiplier, if present — the uniform write-seam scaling. Never mutates
    the input; returns it unchanged (same object) when neither key is
    present or the multiplier is a no-op (1.0), so callers can skip a copy
    on the common case."""
    if multiplier == 1.0:
        return params
    out = None
    for key in ("brightness", "background_brightness"):
        if key in params and isinstance(params[key], (int, float)):
            if out is None:
                out = dict(params)
            out[key] = max(0.0, min(1.0, params[key] * multiplier))
    return out if out is not None else params


def load_room_controls() -> RoomControlState:
    path = config.ROOM_CONTROLS_FILE
    if path.exists():
        try:
            return RoomControlState(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return RoomControlState()


def save_room_controls(state: RoomControlState) -> None:
    path = config.ROOM_CONTROLS_FILE
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
