"""Sonic's SCENE/FLARE mechanism — the widened half of standing order 5's
settings console (see settings_console.py for the original five-setting
half this deliberately extends, "the way he built it, not looser"). His own
words on the ask: "I want the Sonic agent in the settings console to be
able to manage things like the flares and the settings within the scenes
and creating scenes etc."

THE AUTHORITY BOUNDARY LIVES IN THIS MECHANISM, same posture as
settings_console.py: this module has no import of, or dependency on, any
LLM/agent code, and no import of settings_console.py or room_controls.py —
provably confined to the scene/flare domain by reading its own imports.
The only things it can ever write are SceneV2 objects through
scene_store.save(); there is no shell, file (beyond its own bounded change
log), HTTP, or service-control primitive reachable from here.

THE ONE STRUCTURAL SAFETY PROPERTY THAT PROTECTS HIS AUTHORED SCENES: every
mutation below either (a) targets an EXISTING scene by its own id and
changes exactly one declared field or one named flare kind (never replaces
the scene wholesale, never touches `devices`), or (b) is create_scene,
which only ever calls `SceneV2(name=...)` — id is `Field(default_factory=
lambda: str(uuid.uuid4()))` on the model itself, so a created scene can
structurally never collide with, and therefore never overwrite, any
existing scene id. There is no delete/overwrite-by-id operation in the
enumerated set at all — deliberately excluded, the same "left for a later,
deliberate registry extension" posture settings_console.py takes with
force_scene_*.

OPERATIONS (below, at module bottom) is the SAME declaration that both
enforces (settings_agent.ALL_OPERATIONS is built from this dict; a name not
in it cannot be dispatched) and documents (its catalogue_entry() is what
the "list operations" meta-tool hands Sonic) — see sonic_ops.py's own
docstring for why that coupling is deliberate. Every write operation here
follows the SAME two-step shape settings_console.py's apply_change() does:
a pure `_validate_*` that raises SceneOpError and never writes, called by
an `apply_*` that writes + logs only after validation succeeds — so a
rejected change never reaches scene_store.save().

READS ARE FILTERED, NEVER A FULL-SCENE DUMP (the Admiral's token-efficiency
requirement: "a library that keeps growing ... will outgrow anything that
works by loading everything"): list_scenes_index() returns only
id/name/labels; get_scene_settings()/list_flare_kinds() return only the
enumerated scalar settings / flare-kind summaries for ONE named scene;
get_flare_kind() returns full detail for exactly one named kind. Nothing
here ever returns a scene's full `devices` list — device/effect editing is
NOT in this registry (out of scope for tonight's ask; a future, deliberate
extension, not a silent omission — the exact "manage flares, settings
within scenes, and create scenes" surface he asked for is what's built).

SCENE_SETTINGS_REGISTRY mirrors settings_console.SETTINGS_REGISTRY's own
discipline: bounds are READ off the real pydantic Field(ge=, le=)
constraints on SceneV2/PhaseBlend/PhaseChoreography/SceneColorJourney via
_model_field_bounds() (the same technique room_controls.field_bounds()
uses, generalized to accept any BaseModel subclass), never re-typed by
hand — a registry entry cannot silently claim a looser range than the
model that actually enforces it. color_journey.mode and
choreography.transition_mode are deliberately NOT in the registry: the
former needs a companion journey spec (not a pure scalar toggle), the
latter has no declared enum/bounds to read a legal range from — both are
human-only via the Scenes page UI, not silently included because the
field exists.

Change log: storage/spectra/scene_agent_log.json, separate from
settings_console's own settings_log.json (the domain separation is
deliberate, not an oversight) — no undo endpoint (not asked for; a scalar
mis-transcription here is fixed the same way a human fixes it, by editing
the scene in the UI or telling Sonic the corrected value)."""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from typing import Any, Callable, Optional

from pydantic import BaseModel, ValidationError

from spectra import config
from spectra.models.scene import (FlareKind, PhaseBlend, PhaseChoreography,
                                  SceneColorJourney, SceneV2)
from spectra.services import scene_store
from spectra.services.sonic_ops import SonicOperation


class SceneSettingSpec(BaseModel):
    key: str
    label: str
    kind: str            # "int" | "float" | "bool"
    description: str
    instructions: str
    unit: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    nullable: bool = False


class SceneOpError(Exception):
    """Carries a structured, tool-result-shaped payload — same contract as
    settings_console.SettingChangeError, kept as its own type (not shared)
    so this module has zero import of settings_console.py."""

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def payload(self) -> dict:
        return {"status": "rejected", "reason": self.message, **self.detail}


def _errs(exc: ValidationError) -> list[str]:
    return [e["msg"] for e in exc.errors()]


def _model_field_bounds(model_cls: type[BaseModel], field_name: str) -> tuple[Optional[float], Optional[float]]:
    """(ge, le) declared on model_cls's own field — the single source of
    truth for SCENE_SETTINGS_REGISTRY's bounds, same technique as
    room_controls.field_bounds(), generalized to any BaseModel subclass so
    it also covers the nested PhaseBlend/PhaseChoreography/
    SceneColorJourney submodels a plain top-level reflection couldn't
    reach."""
    ge = le = None
    for constraint in model_cls.model_fields[field_name].metadata:
        if hasattr(constraint, "ge"):
            ge = constraint.ge
        if hasattr(constraint, "le"):
            le = constraint.le
    return ge, le


def _spec(key: str, model_cls: type[BaseModel], field_name: str, label: str, kind: str,
         description: str, instructions: str, unit: Optional[str] = None,
         nullable: bool = False) -> SceneSettingSpec:
    ge, le = _model_field_bounds(model_cls, field_name)
    return SceneSettingSpec(key=key, label=label, kind=kind, description=description,
                            instructions=instructions, unit=unit, min=ge, max=le,
                            nullable=nullable)


# key -> (getter, setter), each operating on a live SceneV2 instance. The
# registry key names spell out the nested path with underscores
# (phase_blend_charge_ramp_ms -> scene.phase_blend.charge_ramp_ms) so a key
# is self-describing without a caller needing to know the model shape.
_ACCESSORS: dict[str, tuple[Callable[[SceneV2], Any], Callable[[SceneV2, Any], None]]] = {
    "entry_ramp_ms": (
        lambda s: s.entry_ramp_ms,
        lambda s, v: setattr(s, "entry_ramp_ms", v)),
    "phase_blend_charge_ramp_ms": (
        lambda s: s.phase_blend.charge_ramp_ms,
        lambda s, v: setattr(s.phase_blend, "charge_ramp_ms", v)),
    "phase_blend_lull_ramp_ms": (
        lambda s: s.phase_blend.lull_ramp_ms,
        lambda s, v: setattr(s.phase_blend, "lull_ramp_ms", v)),
    "choreography_enabled": (
        lambda s: s.choreography.enabled,
        lambda s, v: setattr(s.choreography, "enabled", v)),
    "choreography_transition_ms": (
        lambda s: s.choreography.transition_ms,
        lambda s, v: setattr(s.choreography, "transition_ms", v)),
    "choreography_anchor_frac": (
        lambda s: s.choreography.anchor_frac,
        lambda s, v: setattr(s.choreography, "anchor_frac", v)),
    "color_journey_pace_factor": (
        lambda s: s.color_journey.pace_factor,
        lambda s, v: setattr(s.color_journey, "pace_factor", v)),
    "accept_all_sets": (
        lambda s: s.accept_all_sets,
        lambda s, v: setattr(s, "accept_all_sets", v)),
}

SCENE_SETTINGS_REGISTRY: dict[str, SceneSettingSpec] = {
    "entry_ramp_ms": _spec(
        "entry_ramp_ms", SceneV2, "entry_ramp_ms", "Entry blend", "int",
        "How long this scene blends in when it fires, in milliseconds. 0 "
        "means an instant cut.",
        "Convert spoken seconds to ms yourself (1.5s -> 1500)."),
    "phase_blend_charge_ramp_ms": _spec(
        "phase_blend_charge_ramp_ms", PhaseBlend, "charge_ramp_ms",
        "Charge ramp", "int",
        "How long a musical 'charge' build ramps in for this scene, in ms. "
        "Leave unset (null) to use the room's default charge ramp.",
        "Pass null to clear back to the default; otherwise convert spoken "
        "seconds to ms.", nullable=True),
    "phase_blend_lull_ramp_ms": _spec(
        "phase_blend_lull_ramp_ms", PhaseBlend, "lull_ramp_ms",
        "Lull ramp", "int",
        "How long a musical 'lull' build-down ramps in for this scene, in "
        "ms. Leave unset (null) to use the room's default lull ramp.",
        "Pass null to clear back to the default; otherwise convert spoken "
        "seconds to ms.", nullable=True),
    "choreography_enabled": _spec(
        "choreography_enabled", PhaseChoreography, "enabled",
        "Phase choreography on", "bool",
        "Whether this scene times an early, anticipated crossfade to a "
        "musical payoff at all.",
        "true/false only."),
    "choreography_transition_ms": _spec(
        "choreography_transition_ms", PhaseChoreography, "transition_ms",
        "Choreography crossfade", "int",
        "How long the choreographed crossfade itself takes, in ms.",
        "Convert spoken seconds to ms yourself."),
    "choreography_anchor_frac": _spec(
        "choreography_anchor_frac", PhaseChoreography, "anchor_frac",
        "Choreography anchor", "float",
        "Where in the crossfade the musical payoff should land, as a "
        "fraction from 0 (start) to 1 (end). 0.45 fires the crossfade a "
        "little early so the peak lands on the beat.",
        "Convert a spoken percentage yourself (45% -> 0.45)."),
    "color_journey_pace_factor": _spec(
        "color_journey_pace_factor", SceneColorJourney, "pace_factor",
        "Colour journey pace", "float",
        "How fast this scene's colours drift relative to the room's normal "
        "pace. 1.0 = normal, 0 = frozen while this scene shows, 2.0 = "
        "twice as fast. Matters most while this scene inherits the room's "
        "journey rather than overriding it.",
        "No fixed ceiling — anything from 0 up is legal; ask him if an "
        "unusually large number was really intended."),
    "accept_all_sets": _spec(
        "accept_all_sets", SceneV2, "accept_all_sets",
        "Accepts every colour set", "bool",
        "Whether every colour set not globally opted out is allowed to "
        "play with this scene (true), or only the scene's own accepted "
        "list (false, edited in the Scenes page Colour Sets tab).",
        "true/false only."),
}


# ═══ atomic JSON log — its own small helper, deliberately not imported
# from settings_console.py (see module docstring: zero cross-domain
# imports) ═══════════════════════════════════════════════════════════════

SCENE_LOG_MAX_ENTRIES = 200


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
    path = config.SCENE_AGENT_LOG_FILE
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
    while len(log) > SCENE_LOG_MAX_ENTRIES:
        log.pop(0)
    _atomic_write_json(config.SCENE_AGENT_LOG_FILE, log)


def load_log(limit: int = 50) -> list[dict]:
    return list(reversed(_load_log()))[:limit]


# ═══ reads — filtered/narrow, never a full scene dump ═══════════════════

def list_scenes_index() -> dict:
    return {"scenes": [{"id": s.id, "name": s.name, "labels": s.labels}
                       for s in scene_store.list_all()]}


def get_scene_settings(scene_id: str) -> dict:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    settings = {}
    for key, spec in SCENE_SETTINGS_REGISTRY.items():
        getter, _ = _ACCESSORS[key]
        settings[key] = {
            "value": getter(scene), "label": spec.label, "kind": spec.kind,
            "description": spec.description, "unit": spec.unit,
            "min": spec.min, "max": spec.max, "nullable": spec.nullable,
        }
    return {"scene_id": scene.id, "name": scene.name, "settings": settings}


def list_flare_kinds(scene_id: str) -> dict:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    return {"scene_id": scene.id, "name": scene.name, "flare_kinds": [
        {"name": k.name, "type": k.type, "jump": k.jump, "gain": k.gain,
         "hold_ms": k.hold_ms, "param_names": sorted(k.params)}
        for k in scene.flare_kinds
    ]}


def get_flare_kind(scene_id: str, name: str) -> dict:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    kind = next((k for k in scene.flare_kinds if k.name == name), None)
    if kind is None:
        raise SceneOpError(
            f"scene {scene.name!r} has no flare kind named {name!r}",
            known_kinds=sorted(k.name for k in scene.flare_kinds))
    return {"scene_id": scene.id, "name": scene.name, "flare_kind": kind.model_dump()}


# ═══ create_scene — always a fresh id, can never overwrite ═════════════

def _validate_create_scene(name: str, labels: Optional[list[str]] = None) -> SceneV2:
    name = (name or "").strip()
    if not name:
        raise SceneOpError("a new scene needs a non-empty name")
    try:
        return SceneV2(name=name, labels=list(labels or []))
    except ValidationError as exc:
        raise SceneOpError(f"not a legal scene: {_errs(exc)}", pydantic_errors=_errs(exc)) from exc


async def apply_create_scene(name: str, labels: Optional[list[str]] = None,
                             source: str = "agent") -> dict:
    scene = _validate_create_scene(name, labels)
    scene_store.save(scene)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "create_scene", "scene_id": scene.id, "scene_name": scene.name,
             "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ set_scene_setting — one enumerated scalar field on one scene ═══════

def _validate_scene_setting(scene_id: str, key: str, value: Any) -> tuple[SceneV2, SceneV2]:
    if key not in SCENE_SETTINGS_REGISTRY:
        raise SceneOpError(f"{key!r} is not a scene setting",
                           allowed_keys=sorted(SCENE_SETTINGS_REGISTRY))
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    candidate = scene.model_copy(deep=True)
    _, setter = _ACCESSORS[key]
    setter(candidate, value)
    try:
        candidate = SceneV2.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        spec = SCENE_SETTINGS_REGISTRY[key]
        raise SceneOpError(
            f"{value!r} is not a legal value for {key!r}",
            spec=spec.model_dump(), pydantic_errors=_errs(exc)) from exc
    return scene, candidate


async def apply_scene_setting(scene_id: str, key: str, value: Any,
                              source: str = "agent") -> dict:
    previous, candidate = _validate_scene_setting(scene_id, key, value)
    scene_store.save(candidate)
    getter, _ = _ACCESSORS[key]
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "set_scene_setting", "scene_id": scene_id, "scene_name": candidate.name,
             "key": key, "old_value": getter(previous), "new_value": getter(candidate),
             "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ set_flare_kind — upsert one NAMED flare kind by name ═══════════════

def _validate_set_flare_kind(scene_id: str, **kind_fields: Any) -> tuple[SceneV2, SceneV2, str]:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    try:
        kind = FlareKind.model_validate(kind_fields)
    except ValidationError as exc:
        raise SceneOpError(
            f"{kind_fields.get('name')!r} is not a legal flare kind: {_errs(exc)}",
            pydantic_errors=_errs(exc)) from exc
    candidate = scene.model_copy(deep=True)
    names = [k.name for k in candidate.flare_kinds]
    if kind.name in names:
        candidate.flare_kinds[names.index(kind.name)] = kind
        op = "updated"
    else:
        candidate.flare_kinds.append(kind)
        op = "created"
    try:
        candidate = SceneV2.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        raise SceneOpError(
            f"flare kind {kind.name!r} would make scene {scene.name!r} invalid: {_errs(exc)}",
            pydantic_errors=_errs(exc)) from exc
    return scene, candidate, op


async def apply_flare_kind(scene_id: str, *, name: str, type: str,  # noqa: A002 (mirrors FlareKind.type)
                           jump: Optional[str] = None, params: Optional[dict] = None,
                           gain: float = 1.0, hold_ms: Optional[int] = None,
                           source: str = "agent") -> dict:
    scene, candidate, op = _validate_set_flare_kind(
        scene_id, name=name, type=type, jump=jump, params=params or {},
        gain=gain, hold_ms=hold_ms)
    scene_store.save(candidate)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": f"flare_kind_{op}", "scene_id": scene_id, "scene_name": candidate.name,
             "flare_kind": name, "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ remove_flare_kind — by name; refuses if still referenced ═══════════

def _validate_remove_flare_kind(scene_id: str, name: str) -> tuple[SceneV2, SceneV2]:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    if name not in {k.name for k in scene.flare_kinds}:
        raise SceneOpError(
            f"scene {scene.name!r} has no flare kind named {name!r}",
            known_kinds=sorted(k.name for k in scene.flare_kinds))
    candidate = scene.model_copy(deep=True)
    candidate.flare_kinds = [k for k in candidate.flare_kinds if k.name != name]
    try:
        candidate = SceneV2.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        raise SceneOpError(
            f"cannot remove flare kind {name!r} from {scene.name!r} — still "
            f"referenced: {_errs(exc)}", pydantic_errors=_errs(exc)) from exc
    return scene, candidate


async def apply_remove_flare_kind(scene_id: str, name: str, source: str = "agent") -> dict:
    scene, candidate = _validate_remove_flare_kind(scene_id, name)
    scene_store.save(candidate)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "flare_kind_removed", "scene_id": scene_id, "scene_name": candidate.name,
             "flare_kind": name, "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ operation wrappers — catch SceneOpError HERE so settings_agent.py's
# dispatcher never needs to know this module's exception type ════════════

def _op_list_scenes() -> dict:
    return list_scenes_index()


def _op_get_scene_settings(scene_id: str) -> dict:
    try:
        return get_scene_settings(scene_id)
    except SceneOpError as exc:
        return exc.payload()


def _op_list_flare_kinds(scene_id: str) -> dict:
    try:
        return list_flare_kinds(scene_id)
    except SceneOpError as exc:
        return exc.payload()


def _op_get_flare_kind(scene_id: str, name: str) -> dict:
    try:
        return get_flare_kind(scene_id, name)
    except SceneOpError as exc:
        return exc.payload()


async def _op_create_scene(name: str, labels: Optional[list[str]] = None) -> dict:
    try:
        return await apply_create_scene(name, labels)
    except SceneOpError as exc:
        return exc.payload()


async def _op_set_scene_setting(scene_id: str, key: str, value: Any) -> dict:
    try:
        return await apply_scene_setting(scene_id, key, value)
    except SceneOpError as exc:
        return exc.payload()


async def _op_set_flare_kind(scene_id: str, name: str, type: str,  # noqa: A002
                             jump: Optional[str] = None, params: Optional[dict] = None,
                             gain: float = 1.0, hold_ms: Optional[int] = None) -> dict:
    try:
        return await apply_flare_kind(
            scene_id, name=name, type=type, jump=jump, params=params, gain=gain,
            hold_ms=hold_ms)
    except SceneOpError as exc:
        return exc.payload()


async def _op_remove_flare_kind(scene_id: str, name: str) -> dict:
    try:
        return await apply_remove_flare_kind(scene_id, name)
    except SceneOpError as exc:
        return exc.payload()


# ═══ OPERATIONS — the one declaration (see module docstring + sonic_ops.py) ═

OPERATIONS: dict[str, SonicOperation] = {
    "list_scenes": SonicOperation(
        name="list_scenes", domain="scene", kind="read",
        summary="List every scene's id, name, and labels.",
        instructions=(
            "Always cheap, however many scenes exist — id/name/labels "
            "only, never the full scene. Call this first to find a "
            "scene_id by name before any other scene operation."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_list_scenes),
    "get_scene_settings": SonicOperation(
        name="get_scene_settings", domain="scene", kind="read",
        summary="Read one scene's settable settings (entry blend, phase "
                "ramps, choreography, colour-journey pace, colour-set "
                "acceptance) with their current values and legal ranges.",
        instructions=(
            "scene_id from list_scenes. Returns exactly the keys "
            "set_scene_setting will accept for this scene — nothing else "
            "about the scene (no devices, no flares)."),
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"], "additionalProperties": False},
        handler=_op_get_scene_settings),
    "list_flare_kinds": SonicOperation(
        name="list_flare_kinds", domain="scene", kind="read",
        summary="List a scene's named flare kinds (name/type/jump/gain/"
                "hold_ms/param names) without their full parameter detail.",
        instructions="scene_id from list_scenes. Call get_flare_kind for one kind's full parameter detail before editing it.",
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"], "additionalProperties": False},
        handler=_op_list_flare_kinds),
    "get_flare_kind": SonicOperation(
        name="get_flare_kind", domain="scene", kind="read",
        summary="Read one named flare kind's full definition on one scene.",
        instructions="scene_id + name from list_flare_kinds.",
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}, "name": {"type": "string"}},
            "required": ["scene_id", "name"], "additionalProperties": False},
        handler=_op_get_flare_kind),
    "create_scene": SonicOperation(
        name="create_scene", domain="scene", kind="write",
        summary="Create a new, empty scene shell with a name.",
        instructions=(
            "Always makes a BRAND NEW scene with a fresh id — it can never "
            "overwrite an existing scene, even if the name matches one "
            "exactly. The new scene has no devices yet; he adds those in "
            "the Scenes page. Use this only when he clearly means a new "
            "scene, not a change to an existing one — check list_scenes "
            "first if you're not sure which he means."),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"], "additionalProperties": False},
        handler=_op_create_scene),
    "set_scene_setting": SonicOperation(
        name="set_scene_setting", domain="scene", kind="write",
        summary="Change ONE declared setting on ONE existing scene.",
        instructions=(
            "key must be one of the keys get_scene_settings just showed "
            "you for THIS scene_id — the server re-validates the key and "
            "value against the scene's own declared range and rejects "
            "anything outside them, exactly like set_setting does for room "
            "settings."),
        input_schema={
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "key": {"type": "string", "enum": sorted(SCENE_SETTINGS_REGISTRY)},
                "value": {"description": "New value — type depends on the "
                                         "setting (see get_scene_settings)."},
            },
            "required": ["scene_id", "key", "value"], "additionalProperties": False},
        handler=_op_set_scene_setting),
    "set_flare_kind": SonicOperation(
        name="set_flare_kind", domain="scene", kind="write",
        summary="Create or update one NAMED flare kind on one scene "
                "(matched by name — an existing name is replaced, a new "
                "name is added).",
        instructions=(
            "type is one of: drift_jump (jump='color_set' rolls a new "
            "colour set, jump='dice' re-rolls the scene's binding dice — "
            "no params/gain/hold_ms on this type), momentary (a param/gain "
            "spike that returns to baseline — hold_ms optional, default "
            "250ms), permanent (params/gain land and become the new "
            "baseline — no hold_ms, it never releases). params maps a "
            "param name to either a bare number (an absolute target) or "
            "{mode: 'absolute'|'offset'|'random', value|offset|lo,hi}. "
            "The server re-validates the whole shape and refuses anything "
            "that would make the scene invalid — check get_flare_kind "
            "first if you're editing rather than creating."),
        input_schema={
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "name": {"type": "string"},
                "type": {"type": "string", "enum": ["drift_jump", "momentary", "permanent"]},
                "jump": {"type": "string", "enum": ["color_set", "dice"]},
                "params": {"type": "object", "additionalProperties": True},
                "gain": {"type": "number"},
                "hold_ms": {"type": "integer"},
            },
            "required": ["scene_id", "name", "type"], "additionalProperties": False},
        handler=_op_set_flare_kind),
    "remove_flare_kind": SonicOperation(
        name="remove_flare_kind", domain="scene", kind="write",
        summary="Remove one named flare kind from one scene.",
        instructions=(
            "Refused (nothing changes) if any response band or this "
            "scene's update_kind still references the name — remove or "
            "repoint that reference first, in the Scenes page."),
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}, "name": {"type": "string"}},
            "required": ["scene_id", "name"], "additionalProperties": False},
        handler=_op_remove_flare_kind),
}
