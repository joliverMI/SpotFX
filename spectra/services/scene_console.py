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

THE STRUCTURAL SAFETY PROPERTY THAT PROTECTS HIS AUTHORED SCENES,
UNCHANGED IN KIND, WIDER IN SCOPE (2026-08-15, his own follow-up ask: "I
want Sonic to be able to edit scenes and overwrite them just back them up
ahead of time and make an easy to undo last agent change button"):
create_scene only ever calls `SceneV2(name=...)` — id is
`Field(default_factory=lambda: str(uuid.uuid4()))` on the model itself, so
a created scene can structurally never collide with, and therefore never
overwrite, an existing scene id; there is still no delete-by-id operation
anywhere in the enumerated set. What CHANGED: overwrite_scene now exists —
a genuinely destructive operation that can replace a scene's name/labels/
settings/flare_kinds wholesale (never `devices` — that boundary is
unchanged, he didn't ask to reverse it). Four things make that safe, ALL
STRUCTURAL, none of them the agent's to skip:

  1. BACKUP BEFORE ANY EDIT, TAKEN BY THE MECHANISM, VERIFIED NOT MERELY
     ATTEMPTED. _write_and_verify_backup() runs before EVERY write that
     touches an EXISTING scene (set_scene_setting, set_flare_kind,
     remove_flare_kind, overwrite_scene, restore_scene_backup) — it
     writes the pre-edit snapshot into the scene's backup ring, then
     RE-READS THE FILE FROM DISK and compares against what was intended;
     a successful os.replace() alone is never trusted. If the reread
     doesn't match, it raises SceneOpError and the edit is refused before
     scene_store.save() is ever called — this is not a try/except around
     the write, it is a read-back-and-compare, because "the write didn't
     raise" and "the write actually landed" are different claims and only
     the second one is a backup.
  2. RETENTION, both deliberate, both his own follow-up call (stated
     plainly per his instruction): the last SCENE_BACKUP_RING_SIZE (10)
     edits per scene, oldest evicted first — so an undo of an undo works
     (see below) and a second bad edit can't overwrite the one good
     backup with a broken one — PLUS a permanent, NEVER-PRUNED genesis
     snapshot per scene, captured once on that scene's first-ever edit
     (or, for a scene Sonic itself created, at creation) and never
     touched again regardless of how many edits or ring evictions follow.
     His 9 authored scenes are irreplaceable; the genesis snapshot is the
     anchor that survives any chain of bad edits, not just the last 10.
  3. UNDO — undo_last_scene_change() is ONE action, no scene_id needed:
     it finds the most recent not-yet-undone log entry that carries a
     `backup_id` (every edit above stamps one; create_scene doesn't, so
     it is naturally never a candidate — there's nothing to restore FROM)
     and restores that backup. Restoring is ITSELF an edit that goes
     through the same backup-before-write gate (rule 1), which is what
     makes "undo of an undo" work for free: undoing edit B backs up
     (and can later restore) the post-B state before landing pre-B.
  4. PREVIEW — every edit above returns a `preview` field, and
     get_scene_preview(scene_id) can be called any time after: BOTH are
     computed by _diff_scenes() comparing two REAL stored snapshots (the
     backup just taken vs. the scene as saved) — never generated from the
     model's own account of what it did. A confident "here's what I
     changed" in the reply text is exactly the fabrication this project
     caught on the real model tonight; the preview is a read of the file.

restore_scene_backup(scene_id, backup_id) is the deliberate, pick-a-point
counterpart to undo (which only ever steps back one edit): backup_id may
name any entry in the ring OR the literal string "genesis" for the
permanent pre-Sonic snapshot — "just restore the backup for that scene if
we cannot work it out," his words, and genesis is the guaranteed-available
last resort.

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
deliberate, not an oversight). Backup ring: storage/spectra/
scene_backups.json, `{scene_id: [entry, ...]}`, newest last, capped at
SCENE_BACKUP_RING_SIZE. Genesis: storage/spectra/scene_genesis.json,
`{scene_id: entry}`, written once, never pruned. Both atomic tmp+replace,
same discipline as the log."""
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
    entry.setdefault("undone", False)
    log = _load_log()
    log.append(entry)
    while len(log) > SCENE_LOG_MAX_ENTRIES:
        log.pop(0)
    _atomic_write_json(config.SCENE_AGENT_LOG_FILE, log)


def load_log(limit: int = 50) -> list[dict]:
    return list(reversed(_load_log()))[:limit]


# ═══ backup-before-any-edit — see module docstring's numbered list ═══════

SCENE_BACKUP_RING_SIZE = 10


def _load_backups() -> dict[str, list[dict]]:
    path = config.SCENE_BACKUPS_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_genesis() -> dict[str, dict]:
    path = config.SCENE_GENESIS_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _snapshot(scene_id: str, scene: SceneV2, op: str) -> dict:
    return {"id": str(uuid.uuid4()), "scene_id": scene_id,
            "ts_ms": int(time.time() * 1000), "op": op,
            "scene": scene.model_dump(mode="json")}


def _write_and_verify_backup(scene_id: str, pre_edit_scene: SceneV2, op: str) -> dict:
    """THE required step before any write that touches an EXISTING scene
    (never called by create_scene — nothing to back up yet). Snapshots
    `pre_edit_scene` (the scene AS IT STOOD before this edit) into the
    bounded ring, and — only on this scene's first-ever backup — into the
    permanent genesis store, then RE-READS BOTH FILES FROM DISK and
    confirms the just-written entry is actually there. Raises SceneOpError
    (refusing the whole edit — the caller must not call scene_store.save()
    after this raises) if either re-read doesn't match what was written; a
    successful write call alone is never treated as proof."""
    entry = _snapshot(scene_id, pre_edit_scene, op)

    ring = _load_backups()
    ring.setdefault(scene_id, []).append(entry)
    while len(ring[scene_id]) > SCENE_BACKUP_RING_SIZE:
        ring[scene_id].pop(0)
    _atomic_write_json(config.SCENE_BACKUPS_FILE, ring)
    reread_ring = _load_backups().get(scene_id) or []
    if not reread_ring or reread_ring[-1]["id"] != entry["id"] \
            or reread_ring[-1]["scene"] != entry["scene"]:
        raise SceneOpError(
            f"backup could not be verified for scene {scene_id!r} — refusing the edit "
            f"(nothing was written to the scene)")

    genesis = _load_genesis()
    if scene_id not in genesis:
        genesis[scene_id] = entry
        _atomic_write_json(config.SCENE_GENESIS_FILE, genesis)
        reread_genesis = _load_genesis().get(scene_id)
        if reread_genesis is None or reread_genesis["scene"] != entry["scene"]:
            raise SceneOpError(
                f"genesis snapshot could not be verified for scene {scene_id!r} — "
                f"refusing the edit (nothing was written to the scene)")

    return entry


def _find_backup_entry(scene_id: str, backup_id: str) -> Optional[dict]:
    genesis = _load_genesis().get(scene_id)
    if backup_id == "genesis" or (genesis and genesis["id"] == backup_id):
        return genesis
    for entry in _load_backups().get(scene_id, []):
        if entry["id"] == backup_id:
            return entry
    return None


def list_scene_backups(scene_id: str) -> dict:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    genesis = _load_genesis().get(scene_id)
    ring = _load_backups().get(scene_id, [])
    backups = [{"id": e["id"], "ts_ms": e["ts_ms"], "op": e["op"], "is_genesis": False}
              for e in reversed(ring)]
    if genesis is not None:
        backups.append({"id": genesis["id"], "ts_ms": genesis["ts_ms"],
                        "op": genesis["op"], "is_genesis": True})
    return {"scene_id": scene.id, "name": scene.name, "backups": backups}


def _diff_scenes(before: SceneV2, after: SceneV2) -> dict:
    """A field-level diff between two REAL SceneV2 snapshots — this is
    what a preview/check-in renders from, never a narration. Top-level
    fields only: if a nested structure (flare_kinds, responses, ...)
    changed at all, before/after show the whole field rather than a
    nested sub-diff — simple, and always accurate because it's a literal
    comparison of stored data, not an interpretation of it."""
    b, a = before.model_dump(mode="json"), after.model_dump(mode="json")
    return {k: {"before": b.get(k), "after": a.get(k)} for k in a if a.get(k) != b.get(k)}


def get_scene_preview(scene_id: str) -> dict:
    """What actually changed since the last backup was taken for this
    scene — callable any time, not just right after an edit, so "what did
    you just change" always gets an answer read from disk rather than
    recalled from the conversation."""
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    ring = _load_backups().get(scene_id, [])
    if not ring:
        return {"scene_id": scene.id, "name": scene.name, "has_backup": False,
                "preview": {}}
    last = ring[-1]
    before = SceneV2.model_validate(last["scene"])
    return {"scene_id": scene.id, "name": scene.name, "has_backup": True,
            "backup_id": last["id"], "backup_ts_ms": last["ts_ms"],
            "preview": _diff_scenes(before, scene)}


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
    backup = _write_and_verify_backup(scene_id, previous, op="set_scene_setting")
    scene_store.save(candidate)
    getter, _ = _ACCESSORS[key]
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "set_scene_setting", "scene_id": scene_id, "scene_name": candidate.name,
             "key": key, "old_value": getter(previous), "new_value": getter(candidate),
             "backup_id": backup["id"], "preview": _diff_scenes(previous, candidate),
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
    backup = _write_and_verify_backup(scene_id, scene, op=f"flare_kind_{op}")
    scene_store.save(candidate)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": f"flare_kind_{op}", "scene_id": scene_id, "scene_name": candidate.name,
             "flare_kind": name, "backup_id": backup["id"],
             "preview": _diff_scenes(scene, candidate), "source": source}
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
    backup = _write_and_verify_backup(scene_id, scene, op="flare_kind_removed")
    scene_store.save(candidate)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "flare_kind_removed", "scene_id": scene_id, "scene_name": candidate.name,
             "flare_kind": name, "backup_id": backup["id"],
             "preview": _diff_scenes(scene, candidate), "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ overwrite_scene — wholesale replace of name/labels/settings/flare_kinds
# (never `devices` — that boundary is unchanged, not reversed by this ask) ═

def _validate_overwrite_scene(scene_id: str, name: Optional[str], labels: Optional[list[str]],
                              settings: Optional[dict[str, Any]],
                              flare_kinds: Optional[list[dict]]) -> tuple[SceneV2, SceneV2]:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    candidate = scene.model_copy(deep=True)

    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise SceneOpError("a scene name cannot be blanked out")
        candidate.name = stripped
    if labels is not None:
        candidate.labels = list(labels)
    if settings is not None:
        unknown = sorted(k for k in settings if k not in SCENE_SETTINGS_REGISTRY)
        if unknown:
            raise SceneOpError(f"not a scene setting: {unknown}",
                               allowed_keys=sorted(SCENE_SETTINGS_REGISTRY))
        for key, value in settings.items():
            _, setter = _ACCESSORS[key]
            setter(candidate, value)
    if flare_kinds is not None:
        try:
            candidate.flare_kinds = [FlareKind.model_validate(k) for k in flare_kinds]
        except ValidationError as exc:
            raise SceneOpError(f"not a legal flare kind: {_errs(exc)}",
                               pydantic_errors=_errs(exc)) from exc

    try:
        candidate = SceneV2.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        raise SceneOpError(
            f"this overwrite would make scene {scene.name!r} invalid: {_errs(exc)}",
            pydantic_errors=_errs(exc)) from exc
    return scene, candidate


async def apply_overwrite_scene(scene_id: str, name: Optional[str] = None,
                                labels: Optional[list[str]] = None,
                                settings: Optional[dict[str, Any]] = None,
                                flare_kinds: Optional[list[dict]] = None,
                                source: str = "agent") -> dict:
    scene, candidate = _validate_overwrite_scene(scene_id, name, labels, settings, flare_kinds)
    backup = _write_and_verify_backup(scene_id, scene, op="overwrite_scene")
    scene_store.save(candidate)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "overwrite_scene", "scene_id": scene_id, "scene_name": candidate.name,
             "backup_id": backup["id"], "preview": _diff_scenes(scene, candidate),
             "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ restore_scene_backup — pick-a-point restore; itself an edit, itself
# backed up (this is what makes "undo of an undo" work — see docstring) ═══

def _validate_restore(scene_id: str, backup_id: str) -> tuple[SceneV2, SceneV2, dict]:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise SceneOpError(f"no scene with id {scene_id!r}")
    target = _find_backup_entry(scene_id, backup_id)
    if target is None:
        raise SceneOpError(
            f"no backup {backup_id!r} for scene {scene_id!r} — call list_scene_backups "
            f"to see what's available ('genesis' always works if any backup exists)")
    try:
        restored = SceneV2.model_validate(target["scene"])
    except ValidationError as exc:
        raise SceneOpError(
            f"backup {backup_id!r} no longer validates as a legal scene: {_errs(exc)}",
            pydantic_errors=_errs(exc)) from exc
    return scene, restored, target


async def apply_restore_scene_backup(scene_id: str, backup_id: str,
                                     source: str = "agent") -> dict:
    current, restored, target = _validate_restore(scene_id, backup_id)
    backup = _write_and_verify_backup(scene_id, current, op="restore_scene_backup")
    scene_store.save(restored)
    entry = {"id": str(uuid.uuid4()), "ts_ms": int(time.time() * 1000),
             "op": "restore_scene_backup", "scene_id": scene_id, "scene_name": restored.name,
             "restored_from": backup_id, "backup_id": backup["id"],
             "preview": _diff_scenes(current, restored), "source": source}
    _append_log(entry)
    return {"status": "applied", **entry}


# ═══ undo_last_scene_change — ONE action, no scene_id needed ════════════

async def apply_undo_last_scene_change(source: str = "undo") -> dict:
    log = _load_log()
    target = None
    for entry in reversed(log):
        if not entry.get("undone") and entry.get("backup_id"):
            target = entry
            break
    if target is None:
        raise SceneOpError("nothing to undo")

    result = await apply_restore_scene_backup(
        target["scene_id"], target["backup_id"], source=source)

    log = _load_log()
    for entry in log:
        if entry["id"] == target["id"]:
            entry["undone"] = True
            break
    _atomic_write_json(config.SCENE_AGENT_LOG_FILE, log)

    return result


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


async def _op_overwrite_scene(scene_id: str, name: Optional[str] = None,
                              labels: Optional[list[str]] = None,
                              settings: Optional[dict] = None,
                              flare_kinds: Optional[list[dict]] = None) -> dict:
    try:
        return await apply_overwrite_scene(
            scene_id, name=name, labels=labels, settings=settings, flare_kinds=flare_kinds)
    except SceneOpError as exc:
        return exc.payload()


def _op_list_scene_backups(scene_id: str) -> dict:
    try:
        return list_scene_backups(scene_id)
    except SceneOpError as exc:
        return exc.payload()


def _op_get_scene_preview(scene_id: str) -> dict:
    try:
        return get_scene_preview(scene_id)
    except SceneOpError as exc:
        return exc.payload()


async def _op_restore_scene_backup(scene_id: str, backup_id: str) -> dict:
    try:
        return await apply_restore_scene_backup(scene_id, backup_id)
    except SceneOpError as exc:
        return exc.payload()


async def _op_undo_last_scene_change() -> dict:
    try:
        return await apply_undo_last_scene_change()
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
    "overwrite_scene": SonicOperation(
        name="overwrite_scene", domain="scene", kind="write",
        summary="Wholesale-replace an EXISTING scene's name/labels/"
                "settings/flare_kinds in one shot. His first genuinely "
                "destructive scene operation — always backed up first.",
        instructions=(
            "Only fields you pass are touched — omit a field to leave it "
            "unchanged. `settings` is a dict of get_scene_settings keys -> "
            "values, applied all at once. `flare_kinds`, if passed, "
            "REPLACES THE WHOLE LIST — kinds you don't include are "
            "removed, so pass the full set you want, not just the ones "
            "changing (call list_flare_kinds first to see what's there). "
            "Never touches devices/effects — that stays the Scenes page's "
            "own visual editor. A verified backup of the scene's PRE-edit "
            "state is taken automatically before anything is written; if "
            "the backup can't be verified the whole overwrite is refused "
            "and nothing changes. After this succeeds, relay the "
            "`preview` field back to him verbatim (it's read from the "
            "saved file, not your own account) and check it's what he "
            "wanted — if not, call restore_scene_backup or "
            "undo_last_scene_change."),
        input_schema={
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "name": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "settings": {"type": "object", "additionalProperties": True},
                "flare_kinds": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["scene_id"], "additionalProperties": False},
        handler=_op_overwrite_scene),
    "list_scene_backups": SonicOperation(
        name="list_scene_backups", domain="scene", kind="read",
        summary="List one scene's available restore points: the last 10 "
                "edits plus the permanent pre-Sonic genesis snapshot.",
        instructions=(
            "scene_id from list_scenes. Use an entry's `id` (or the "
            "literal string \"genesis\" for the permanent snapshot, "
            "always shown with is_genesis=true) as restore_scene_backup's "
            "backup_id."),
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"], "additionalProperties": False},
        handler=_op_list_scene_backups),
    "get_scene_preview": SonicOperation(
        name="get_scene_preview", domain="scene", kind="read",
        summary="What actually changed on one scene since its last "
                "backup — read from the stored scene and its stored "
                "backup, never from what you remember doing.",
        instructions=(
            "Call this whenever he asks what changed, rather than "
            "answering from the conversation — the answer here is "
            "generated from the real files, so it can never be wrong "
            "about what actually landed."),
        input_schema={
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"], "additionalProperties": False},
        handler=_op_get_scene_preview),
    "restore_scene_backup": SonicOperation(
        name="restore_scene_backup", domain="scene", kind="write",
        summary="Restore one scene to a specific earlier point — any "
                "entry from list_scene_backups, or \"genesis\" for the "
                "permanent pre-Sonic snapshot.",
        instructions=(
            "Use when he wants to go back further than one step, or "
            "wants the guaranteed-safe original back ('if we can't work "
            "it out, just restore it' — his words: pass "
            "backup_id=\"genesis\"). This is itself an edit — it's backed "
            "up before it runs too, so restoring is never a dead end."),
        input_schema={
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "backup_id": {"type": "string"},
            },
            "required": ["scene_id", "backup_id"], "additionalProperties": False},
        handler=_op_restore_scene_backup),
    "undo_last_scene_change": SonicOperation(
        name="undo_last_scene_change", domain="scene", kind="write",
        summary="Undo the single most recent scene edit Sonic made, "
                "across any scene — one action, no scene_id needed.",
        instructions=(
            "The easy 'undo last agent change' button, his words. Steps "
            "back exactly one edit; call it again to step back another. "
            "Only ever touches edits Sonic itself applied (create_scene "
            "can't be undone this way — nothing existed before it to "
            "restore)."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_undo_last_scene_change),
}
