"""SONIC'S ROOM-EFFECT AUTHORITY — the settable fields of the Room Effects
page, and nothing else.

WHAT IS IN SCOPE, and it is exactly what the page's own controls set: an
effect's name, its three knobs (wavelength / speed / depth) and which of the
room's mapped fixtures it drives, plus the two reads a caller needs to work
out what to change. Bounds come off RoomEffectSpec's own Field(ge=, le=) —
never a second hand-typed copy — the same discipline
settings_console.SETTINGS_REGISTRY and scene_console.SCENE_SETTINGS_REGISTRY
already keep.

WHAT IS DELIBERATELY EXCLUDED, by name, because each is a different kind of
act rather than a setting:

  * STARTING OR STOPPING an effect. That drives his fixtures and holds the
    room. settings_agent.py's whole boundary argument is that no
    light-driving call exists in the code the model's tool_use can reach;
    adding one here would be the first.
  * RUNNING A MAPPING SYNC. It takes the room dark and needs a phone in
    someone's hand pointing at the fixtures. There is nothing an agent can
    usefully do about the second half.
  * THE AXIS CALIBRATION. It is two taps on a live camera picture — a pair
    of normalized coordinates whose meaning is entirely visual, the same
    reason force_scene_* is excluded from the settings registry (an opaque
    value a human picks by looking).
  * CREATING OR DELETING A ROOM. A room's identity is the phone position its
    map was taken from; naming one is a human act tied to standing
    somewhere, and deleting one throws measurements away.

Creating an EFFECT is in scope and is safe for the same reason
scene_console.create_scene is: it only ever builds a fresh RoomEffectSpec
with the model's own default id factory, so a created effect can never
collide with, and therefore never overwrite, an existing one.
"""
from __future__ import annotations

from typing import Any, Optional

from spectra.services import light_field, room_effects
from spectra.services.light_field_fields import KINDS
from spectra.services.sonic_ops import SonicOperation

#: The settable knobs, with their bounds read off the model itself.
KNOBS = ("wavelength", "speed", "depth")


def _bounds(name: str) -> tuple[float, float]:
    field = room_effects.RoomEffectSpec.model_fields[name]
    lo = hi = None
    for meta in field.metadata:
        lo = getattr(meta, "ge", None) if lo is None else lo
        hi = getattr(meta, "le", None) if hi is None else hi
    return float(lo), float(hi)


def knob_catalogue() -> dict[str, dict]:
    return {name: {"min": _bounds(name)[0], "max": _bounds(name)[1],
                   "default": room_effects.RoomEffectSpec.model_fields[name].default,
                   "units": {
                       "wavelength": "axis units — 1.0 is one full cycle from "
                                     "floor to ceiling",
                       "speed": "cycles per second; positive travels toward "
                                "the ceiling, 0 is a standing wave",
                       "depth": "how far the trough dips; 0 is an exact no-op, "
                                "1 reaches black",
                   }[name]}
            for name in KNOBS}


# ── handlers ───────────────────────────────────────────────────────────────

def _op_list_rooms() -> dict:
    rooms = light_field.load_rooms()
    return {"rooms": [{"id": r.id, "name": r.name,
                       "device_ids": r.device_ids,
                       "mapped": r.mapped_ids(),
                       "not_mapped": r.unmapped_ids(),
                       "axis_calibrated": r.axis.calibrated,
                       "weights": {f.emitter_id: round(f.weight, 3)
                                   for f in r.footprints if f.mapped}}
                      for r in rooms]}


def _op_list_room_effects() -> dict:
    return {"effects": [e.model_dump() for e in room_effects.load_effects()],
            "knobs": knob_catalogue(),
            "kinds": KINDS,
            "note": "Only 'dim_wave' drives lights in this build. The other "
                    "three kinds are the field interface and cannot be "
                    "created."}


def _op_create_room_effect(room_id: str, name: Optional[str] = None) -> dict:
    room = light_field.get_room(room_id)
    if room is None:
        return {"status": "rejected", "reason": f"no such room: {room_id!r}",
                "known_rooms": [r.id for r in light_field.load_rooms()]}
    spec = room_effects.RoomEffectSpec(room_id=room_id,
                                       name=name or "Dim Wave")
    room_effects.put_effect(spec)
    return {"status": "applied", "effect": spec.model_dump(),
            "summary": f"created Dim Wave '{spec.name}' on room '{room.name}'"}


def _op_set_room_effect(effect_id: str, key: str, value: Any) -> dict:
    spec = next((e for e in room_effects.load_effects() if e.id == effect_id), None)
    if spec is None:
        return {"status": "rejected", "reason": f"no such effect: {effect_id!r}",
                "known_effects": [e.id for e in room_effects.load_effects()]}
    if key not in KNOBS + ("name", "device_ids"):
        return {"status": "rejected",
                "reason": f"{key!r} is not a settable room-effect field",
                "settable": list(KNOBS) + ["name", "device_ids"]}
    before = getattr(spec, key)
    try:
        # Re-validated through the SAME model the human save path binds to,
        # so an out-of-range knob is refused identically either way.
        updated = room_effects.RoomEffectSpec(
            **{**spec.model_dump(), key: value})
    except Exception as exc:                           # noqa: BLE001
        return {"status": "rejected", "reason": str(exc)}
    if key == "device_ids":
        room = light_field.get_room(spec.room_id)
        mapped = set(room.mapped_ids()) if room else set()
        unknown = [d for d in updated.device_ids if d not in mapped]
        if unknown:
            return {"status": "rejected",
                    "reason": f"these are not mapped in this room and cannot "
                              f"be driven: {unknown}",
                    "mapped": sorted(mapped)}
    room_effects.put_effect(updated)
    return {"status": "applied", "key": key, "before": before,
            "after": getattr(updated, key),
            "effect": updated.model_dump(),
            "summary": f"{key} {before!r} -> {getattr(updated, key)!r} on "
                       f"'{updated.name}'",
            "note": "A change to a RUNNING effect takes hold the next time it "
                    "is started — starting and stopping are his press, not "
                    "mine."}


OPERATIONS: dict[str, SonicOperation] = {
    "list_rooms": SonicOperation(
        name="list_rooms", domain="room", kind="read",
        summary="Every mapped room — its fixtures, which of them have a "
                "measured light footprint, and how much light each lands.",
        instructions=(
            "Call this first for anything room-related. A room's map records "
            "WHERE each fixture's light lands, never where its LEDs are. A "
            "device in `not_mapped` has no footprint yet and cannot be driven "
            "by a room effect; mapping one needs a phone camera and is not "
            "something you can do — say so and point at the Rooms page."),
        input_schema={"type": "object", "properties": {},
                      "additionalProperties": False},
        handler=_op_list_rooms),
    "list_room_effects": SonicOperation(
        name="list_room_effects", domain="room", kind="read",
        summary="Every authored room effect, its knobs, and their real "
                "bounds and units.",
        instructions=(
            "`knobs` carries each knob's min/max/default and what its units "
            "mean, read off the model itself — quote those rather than "
            "guessing. Only 'dim_wave' is built; the other kinds are the "
            "field interface and cannot be created."),
        input_schema={"type": "object", "properties": {},
                      "additionalProperties": False},
        handler=_op_list_room_effects),
    "create_room_effect": SonicOperation(
        name="create_room_effect", domain="room", kind="write",
        summary="Create a Dim Wave on a room (name only — the knobs start at "
                "their defaults).",
        instructions=(
            "Takes a room_id from list_rooms. Always creates a NEW effect "
            "with a fresh id, so it can never overwrite an existing one. It "
            "does not start it: running an effect drives his fixtures and "
            "holds the room, which is his press on the Room Effects page."),
        input_schema={
            "type": "object",
            "properties": {"room_id": {"type": "string"},
                           "name": {"type": "string"}},
            "required": ["room_id"], "additionalProperties": False},
        handler=_op_create_room_effect),
    "set_room_effect": SonicOperation(
        name="set_room_effect", domain="room", kind="write",
        summary="Set one field of a room effect: wavelength, speed, depth, "
                "name, or which mapped fixtures it drives.",
        instructions=(
            "Call list_room_effects first for the id and the legal range. "
            "wavelength is in AXIS units (1.0 = one full cycle floor to "
            "ceiling), speed is cycles per second (positive travels toward "
            "the ceiling, 0 is a standing wave), depth is how far the trough "
            "dips (0 is an exact no-op). device_ids may only name fixtures "
            "that room has actually MAPPED; an empty list means every mapped "
            "fixture. A change to an effect that is currently running takes "
            "hold the next time it is started."),
        input_schema={
            "type": "object",
            "properties": {
                "effect_id": {"type": "string"},
                "key": {"type": "string",
                        "enum": list(KNOBS) + ["name", "device_ids"]},
                "value": {}},
            "required": ["effect_id", "key", "value"],
            "additionalProperties": False},
        handler=_op_set_room_effect),
}
