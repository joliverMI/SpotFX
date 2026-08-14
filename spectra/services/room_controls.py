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
                          action equivalents. This state is the durable
                          record; the live takeover itself (freezing the
                          room's Hue devices, holding them at ambient_color
                          over direct bridge REST) is driven by
                          services/ambient.py, reconciled from
                          api/room_controls.py's PUT handler whenever these
                          fields change.
  global_transition_ms    the legacy ledfx_global_transition action
                          equivalent — the default ramp new scene-entry
                          blends use when a scene doesn't author its own
                          entry_ramp_ms (SceneV2.entry_ramp_ms == 0).
  scene_change_mode  the Admiral's binding settings model (decision-
                          mid-song-model.md + its 2026-08-14 framing
                          correction + the settings-model brief,
                          corr=c14a9bcee40e6df9), replacing front 3's plain
                          midsong_triggers_enabled bool with three
                          understandable, ADDITIVE tiers:
                            "transitions" — a scene change on every song
                              transition only (the automatic kernel-picked
                              fire trigger_engine._fire_transition drives
                              on every genuine song-to-song change — see
                              its module docstring). Nothing else.
                            "analysed"    — transitions PLUS the analysed
                              mid-song moments midsong_generator seeds
                              (source="generated" triggers).
                            "full"        — everything: transitions +
                              generated mid-song triggers + the owner's
                              own hand-authored triggers (source=
                              "authored") + response-engine flares (both
                              bridge-classified and trigger-driven —
                              services/engine.fire_response_event's own
                              gate). Default, and the closest match to
                              pre-existing behaviour (authored triggers and
                              flares had no gate at all before this field).
                          Checked by trigger_engine.tick() (generated vs.
                          authored gating) and engine.fire_response_event
                          (flare gating) — the same seams the old bool
                          switch used. "transitions" and "analysed" are
                          NOT redundant: they differ in whether generated
                          mid-song triggers fire, exactly the old switch's
                          two states.

Ambient is wired live (services/ambient.py) — the Dinner-Party half of the
room-MODES gap (gap report §3 row 5) is a separate, still-unbuilt mode;
ambient_enabled/_color here are Ambient's alone.

Storage: storage/spectra/room_controls.json — same atomic tmp+replace
discipline as color_journey.py's room_color.json.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Literal, Optional

from pydantic import BaseModel, Field

from spectra import config

SceneChangeMode = Literal["transitions", "analysed", "full"]


class RoomControlState(BaseModel):
    brightness_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    ambient_enabled: bool = False
    ambient_color: Optional[str] = None   # hex; None = no colour authored yet
    # 0 = no room default (today's unchanged instant-jump behaviour for any
    # scene that doesn't author its own entry_ramp_ms). >0 becomes the
    # FALLBACK ramp scene_compiler.fire_scene uses when a scene's own
    # entry_ramp_ms is 0 — the legacy ledfx_global_transition equivalent.
    global_transition_ms: int = Field(default=0, ge=0, le=20000)
    scene_change_mode: SceneChangeMode = "full"


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
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return RoomControlState()
        # One-way migration from the retired midsong_triggers_enabled bool
        # (pre this settings model) — True mapped to "full" (the closest
        # match to its actual pre-existing behaviour: generated triggers on,
        # and authored triggers/flares always fired regardless of the old
        # switch), False to "transitions" (the owner had deliberately dialed
        # generated triggers off, so the pure baseline is the most faithful
        # read of that intent).
        if "scene_change_mode" not in raw and "midsong_triggers_enabled" in raw:
            raw["scene_change_mode"] = ("full" if raw.pop("midsong_triggers_enabled")
                                        else "transitions")
        else:
            raw.pop("midsong_triggers_enabled", None)
        try:
            return RoomControlState(**raw)
        except Exception:
            return RoomControlState()
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
