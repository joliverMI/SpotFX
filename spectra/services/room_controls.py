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
  force_scene_enabled/    the legacy Now Playing "Force Scene" control,
  force_scene_scene_id    ported verbatim (owner direction: reuse the old
                          system's design/behaviour, not reinvent it).
                          Legacy semantics (services/trigger_engine.py's
                          _forced_scene_event/_pick_scene_lanes): while
                          enabled, whenever a scene WOULD be picked
                          automatically, the forced scene fires instead - an
                          unconditional redirect, not a pause. Ported at the
                          single choke point every automatic SPECTRA scene
                          pick already funnels through, scene_sequencer.
                          fire_scene_by_id (sequencer rolls, trigger_engine's
                          fire_scene action, and its automatic transition
                          fire all call it) - one interception point, same
                          as legacy having one settings flag every pick site
                          checked. Only the SCENE is pinned; the caller's own
                          resolved colour set/intensity still applies, same
                          as legacy's "reassert with normal First/Rest."
                          force_scene_scene_id pointing at a missing scene is
                          treated as unset (silently falls through), same as
                          legacy's missing/non-scene event guard. SPECTRA has
                          no Scene Group concept yet, so the legacy group
                          member-rotation half of Force Scene has nothing to
                          port to - out of scope until groups exist. Editor
                          test-fires (POST /scenes/{id}/fire) bypass
                          fire_scene_by_id by design and are NOT redirected -
                          an explicit single fire is not "a scene being
                          picked."

Ambient is wired live (services/ambient.py) — the Dinner-Party half of the
room-MODES gap (gap report §3 row 5) is a separate, still-unbuilt mode;
ambient_enabled/_color here are Ambient's alone.

Storage: storage/spectra/room_controls.json — same atomic tmp+replace
discipline as color_journey.py's room_color.json.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import typing
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from spectra import config

SceneChangeMode = Literal["transitions", "analysed", "full"]

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


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
    force_scene_enabled: bool = False
    force_scene_scene_id: Optional[str] = None   # id of the scene held while enabled

    @field_validator("ambient_color")
    @classmethod
    def _validate_hex(cls, v: Optional[str]) -> Optional[str]:
        # Tightened for the settings-console agent (spectra/services/
        # settings_console.py): the field was previously an unvalidated
        # str, so ANY text round-tripped through the human colour-picker
        # path too. Real colour pickers only ever emit #rrggbb, so this
        # is not a behaviour change for the UI — it closes the gap for a
        # write path with no picker to constrain it.
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("must be a #rrggbb hex colour")
        return v


def field_bounds(name: str) -> tuple[Optional[float], Optional[float]]:
    """(ge, le) declared on a RoomControlState field, or (None, None) if the
    field carries no numeric bound (bool/enum/str fields). Single source of
    truth for the settings-console registry — it reads the SAME Field(ge=,
    le=) constraints this model enforces, so a range can't drift between
    what a human PUT accepts and what the agent is told is legal."""
    ge = le = None
    for constraint in RoomControlState.model_fields[name].metadata:
        if hasattr(constraint, "ge"):
            ge = constraint.ge
        if hasattr(constraint, "le"):
            le = constraint.le
    return ge, le


def field_choices(name: str) -> Optional[list[str]]:
    """Literal[...] choices declared on a RoomControlState field, or None."""
    args = typing.get_args(RoomControlState.model_fields[name].annotation)
    return list(args) if args and all(isinstance(a, str) for a in args) else None


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


async def reconcile_ambient_if_changed(previous: RoomControlState,
                                       new_state: RoomControlState) -> Optional[dict]:
    """The ambient-takeover half of a room-controls save, factored out so
    both the human PUT /api/room-controls handler (spectra/api/
    room_controls.py) and the settings-console agent's apply path
    (spectra/services/settings_console.py) drive the SAME live Hue
    reconcile on the SAME condition — one write choke point, so the agent
    can never diverge from what a human save does. Returns the
    ambient_result dict when the ambient fields actually changed, else
    None (no reconnect churn on an unrelated field's change)."""
    changed = (
        previous.ambient_enabled != new_state.ambient_enabled
        or (new_state.ambient_enabled and previous.ambient_color != new_state.ambient_color)
    )
    if not changed:
        return None
    from spectra.services import ambient
    return await ambient.reconcile(new_state.ambient_enabled, new_state.ambient_color)
