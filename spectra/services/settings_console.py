"""The settings-console MECHANISM (standing order 5: "talk to the software;
do not build the Admiral a settings page"). This module is the whole
authority boundary — it has no import of, or dependency on, any LLM/agent
code (see settings_agent.py for that), so the boundary is provable by
reading this file alone: the only write path is apply_change(), it accepts
exactly one (key, value) pair, and every key/value is validated against
declared, server-owned data BEFORE anything is persisted. There is no
shell, file, HTTP, or service-control primitive reachable from here.

SCOPE (first build): the five RoomControlState fields (spectra/services/
room_controls.py) already labelled "agent-tellable room-wide switches" in
that module's own docstring — brightness, ambient mode/colour, the
global transition default, and the scene-change tier. force_scene_* is
deliberately excluded: it targets a scene by opaque id, which is a poor
fit for "set this setting to this value" (a picker action, not a voice
setting) — left for a later, deliberate registry extension, not silently
included because the field exists.

REGISTRY = the declared data. Bounds/choices are NOT re-typed here — they
are read live off RoomControlState's own pydantic Field(ge=, le=)
constraints and Literal[...] annotation (room_controls.field_bounds/
field_choices), so the registry can never state a looser range than the
model that actually enforces it.

apply_change() is the ONLY function that writes: it re-validates the
FULL candidate RoomControlState (current state with one field replaced)
through RoomControlState.model_validate — the exact model class GET/PUT
/api/room-controls binds to — then calls room_controls.save_room_controls
+ reconcile_ambient_if_changed, the same two calls the human PUT handler
makes. A rejected change never reaches save_room_controls.

Change log + undo: storage/spectra/settings_log.json, atomic tmp+replace,
bounded (SETTINGS_LOG_MAX_ENTRIES, oldest evicted first) — the "visible
record of what changed" + one-step-undo answer to mis-transcription risk
(voice dictation mangles his product names regularly — captain-shared.md).
undo_last_change() re-applies the previous value through apply_change()
itself, so an undo is validated exactly like any other change, never a
raw file poke.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, ValidationError

from spectra import config
from spectra.services import room_controls
from spectra.services.room_controls import RoomControlState

SETTINGS_LOG_MAX_ENTRIES = 200


class SettingSpec(BaseModel):
    key: str
    label: str
    kind: Literal["float", "int", "bool", "enum", "color"]
    description: str
    unit: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list[str]] = None


class SettingChangeError(Exception):
    """Carries a structured, tool-result-shaped payload — this IS what a
    rejected agent tool call sees, not a generic error string, so the model
    (and a human reading the change log) can see the legal range/choices
    and the nearest legal value rather than just "no"."""

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def payload(self) -> dict:
        return {"status": "rejected", "reason": self.message, **self.detail}


def _spec(key: str, label: str, description: str) -> SettingSpec:
    ge, le = room_controls.field_bounds(key)
    choices = room_controls.field_choices(key)
    annotation = RoomControlState.model_fields[key].annotation
    if choices:
        kind = "enum"
    elif annotation is bool:
        kind = "bool"
    elif key == "ambient_color":
        kind = "color"
    elif annotation is int:
        kind = "int"
    else:
        kind = "float"
    unit = {"brightness_multiplier": "fraction 0.0-1.0",
            "global_transition_ms": "ms"}.get(key)
    return SettingSpec(key=key, label=label, kind=kind, description=description,
                       unit=unit, min=ge, max=le, choices=choices)


# The explicit allowlist — the ONLY keys apply_change will ever accept,
# independent of what RoomControlState happens to declare. Adding a field
# to RoomControlState does NOT expose it to the agent; it has to be added
# here deliberately.
SETTINGS_REGISTRY: dict[str, SettingSpec] = {
    "brightness_multiplier": _spec(
        "brightness_multiplier", "Brightness",
        "Uniform room brightness multiplier, as a fraction from 0.0 (dark) "
        "to 1.0 (full) — convert a spoken percentage yourself (50% -> 0.5)."),
    "global_transition_ms": _spec(
        "global_transition_ms", "Transition",
        "Default scene-entry blend time in milliseconds, used when a scene "
        "doesn't author its own — convert spoken seconds to ms (2s -> 2000)."),
    "ambient_mode": _spec(
        "ambient_mode", "Ambient",
        "Ambient mode for the room's live Hue devices, one of three: "
        "'off' (never holds, the whole room performs), 'always' (Hue held "
        "lit at ambient_color at all times, other devices keep running "
        "the show regardless), 'auto' (Hue holds only while nothing is "
        "playing, releases the instant music starts, and returns on its "
        "own when it stops)."),
    "ambient_color": _spec(
        "ambient_color", "Ambient colour",
        "The ambient-mode hex colour, #rrggbb — translate a named colour "
        "('warm white', 'teal') to its nearest hex yourself."),
    "scene_change_mode": _spec(
        "scene_change_mode", "Scene changes",
        "What drives automatic scene changes: 'transitions' (song "
        "transitions only), 'analysed' (+ analysed mid-song moments), "
        "'full' (+ hand-authored triggers and response flares)."),
}


def describe_registry() -> list[dict]:
    return [spec.model_dump() for spec in SETTINGS_REGISTRY.values()]


def current_values() -> dict[str, Any]:
    state = room_controls.load_room_controls()
    return {key: getattr(state, key) for key in SETTINGS_REGISTRY}


def describe_current() -> dict:
    """The get_settings tool's return value / GET endpoint body: every
    declared setting with its live value, right beside its legal range —
    so 'what's the brightness right now' never needs a second round trip."""
    values = current_values()
    return {
        "settings": [
            {**spec.model_dump(), "value": values[key]}
            for key, spec in SETTINGS_REGISTRY.items()
        ],
    }


def _nearest_legal(spec: SettingSpec, value: Any) -> Any:
    if spec.kind in ("float", "int") and isinstance(value, (int, float)):
        lo = spec.min if spec.min is not None else value
        hi = spec.max if spec.max is not None else value
        clamped = max(lo, min(hi, value))
        return int(round(clamped)) if spec.kind == "int" else clamped
    return None


def validate_change(key: str, value: Any) -> tuple[RoomControlState, RoomControlState]:
    """Returns (previous, candidate) on success. Raises SettingChangeError
    (never a bare pydantic ValidationError — callers need the structured
    detail) on an unknown key or an out-of-range/wrong-type value. Never
    writes anything."""
    if key not in SETTINGS_REGISTRY:
        raise SettingChangeError(
            f"{key!r} is not a settings-console setting",
            allowed_keys=sorted(SETTINGS_REGISTRY))

    previous = room_controls.load_room_controls()
    candidate_dict = previous.model_dump()
    candidate_dict[key] = value
    try:
        candidate = RoomControlState.model_validate(candidate_dict)
    except ValidationError as exc:
        spec = SETTINGS_REGISTRY[key]
        raise SettingChangeError(
            f"{value!r} is not a legal value for {key!r}",
            spec=spec.model_dump(),
            nearest_legal_value=_nearest_legal(spec, value),
            pydantic_errors=[e["msg"] for e in exc.errors()],
        ) from exc
    return previous, candidate


def _atomic_write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log() -> list[dict]:
    path = config.SETTINGS_LOG_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _append_log(entry: dict) -> None:
    log = _load_log()
    log.append(entry)
    while len(log) > SETTINGS_LOG_MAX_ENTRIES:
        log.pop(0)
    _atomic_write_json(config.SETTINGS_LOG_FILE, log)


def load_log(limit: int = 50) -> list[dict]:
    """Most-recent-first, the console's visible "what changed" record."""
    return list(reversed(_load_log()))[:limit]


async def apply_change(key: str, value: Any, source: str = "agent") -> dict:
    """THE write choke point. Validates (raises SettingChangeError on
    failure, nothing persisted), then writes through room_controls' own
    save + ambient-reconcile — the same two calls PUT /api/room-controls
    makes — and appends one durable, visible change-log entry."""
    previous, candidate = validate_change(key, value)
    room_controls.save_room_controls(candidate)
    ambient_result = await room_controls.reconcile_ambient_if_changed(previous, candidate)

    entry = {
        "id": str(uuid.uuid4()),
        "ts_ms": int(time.time() * 1000),
        "key": key,
        "old_value": getattr(previous, key),
        "new_value": getattr(candidate, key),
        "source": source,
        "undone": False,
    }
    _append_log(entry)

    result = {"status": "applied", **entry}
    if ambient_result is not None:
        result["ambient_result"] = ambient_result
    return result


async def undo_last_change() -> dict:
    """Reverts the most recent not-yet-undone change by re-applying its
    old_value through apply_change() itself — an undo is validated exactly
    like any forward change, never a raw file poke, and it leaves its own
    new log entry (source="undo") rather than deleting history."""
    log = _load_log()
    target = None
    for entry in reversed(log):
        if not entry.get("undone"):
            target = entry
            break
    if target is None:
        raise SettingChangeError("nothing to undo")

    result = await apply_change(target["key"], target["old_value"], source="undo")

    log = _load_log()
    for entry in log:
        if entry["id"] == target["id"]:
            entry["undone"] = True
            break
    _atomic_write_json(config.SETTINGS_LOG_FILE, log)

    return result
