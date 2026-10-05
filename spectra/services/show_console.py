"""SONIC'S LIGHT SHOW AUTHORITY (phase 3, the Admiral's own ask: "Sonic
commands for fire / arm / disarm / what's armed / device hold or dim /
create set / move High-Low / end show").

WHAT IS IN SCOPE, and it is exactly that list: firing an already-saved set
now, arming/disarming a set (or disarming everything), reading the armed
board, holding or dimming a fixture/category/everything (the same
`device_state`/`level` action kinds the Build view already offers — this
module builds a one-step ad-hoc run through `show_actions.fire()` rather
than inventing a second write path), creating a brand-new empty set
(fresh id, and a name clash is rejected rather than silently overwritten —
`scene_console.create_scene`'s "fresh id" precedent, adapted to this
store's own unique-name rule, `show_store.put_set`'s `SetNameTaken`),
moving this song's High or Low Trigger, and ending the show.

WHAT IS DELIBERATELY EXCLUDED: editing an EXISTING set's own steps (that is
a drag-and-drop authoring act on the Build view, not a settable field —
the same line `room_effect_console.py` draws around starting/stopping an
effect), and starting/stopping a room effect directly (already Sonic's via
`room_effect_console.py`'s own boundary reasoning — a show action that
fires a room effect is a Light Show set, armed and fired like any other;
nothing here duplicates that authority).

NAMES ARE NEVER GUESSED. Every operation that takes a set, an arm, a
fixture or a category by name resolves it through `_resolve()`: an exact
id or case-insensitive name match succeeds; anything else returns
`{"status": "rejected", ...}` naming the closest spellings
(`difflib.get_close_matches`) rather than picking one — the same "refuse
unsure, never guess" rule the Admiral gave for this build. Every write
handler's reply also carries a `summary` sentence saying plainly what ran,
so "every reply says what ran" doesn't depend on the model's own prose.

ROOM-EFFECT COMPATIBILITY. A set containing a `room_effect` step arms and
fires through the exact same `fire_show_set`/`arm_show_set` operations as
any other set — nothing here special-cases that action kind. Arming one is
no different from arming a lighting set: `show_arms.arm()` only ever reads
a set's `actions` list, never its kinds."""
from __future__ import annotations

import difflib
from typing import Any, Optional

from spectra.models.light_show import ShowAction
from spectra.services import show_actions, show_arms, show_cues, show_output, show_store
from spectra.services.sonic_ops import SonicOperation

TRIGGER_CHOICES = ("scene_change", "high", "low")
TARGET_KIND_CHOICES = ("everything", "category", "fixture")
STATE_CHOICES = ("show", "steady", "freeze", "dark")
CUE_LEVEL_CHOICES = ("high", "low")


def _close(name: str, candidates: list[str]) -> list[str]:
    return difflib.get_close_matches(name, candidates, n=3, cutoff=0.4)


def _resolve_set(name_or_id: str):
    s = show_store.find_set(name_or_id)
    if s is not None:
        return s, None
    names = [x.name for x in show_store.list_sets()]
    return None, {"status": "rejected",
                  "reason": f"no set called {name_or_id!r}",
                  "close_matches": _close(name_or_id, names),
                  "known_sets": names}


def _resolve_arm(arm_id_or_label: str):
    arms = show_arms.active_arms()
    hit = next((a for a in arms if a.id == arm_id_or_label), None)
    if hit is None:
        low = arm_id_or_label.strip().lower()
        hit = next((a for a in arms if (a.label or "").strip().lower() == low), None)
    if hit is not None:
        return hit, None
    labels = [a.label or a.id for a in arms]
    return None, {"status": "rejected",
                  "reason": f"nothing armed called {arm_id_or_label!r}",
                  "close_matches": _close(arm_id_or_label, labels),
                  "currently_armed": labels}


def _resolve_target(target_kind: str, target_name: Optional[str]) -> tuple[Optional[dict], Optional[dict]]:
    if target_kind == "everything":
        return {"kind": "everything", "id": None}, None
    if not target_name:
        return None, {"status": "rejected",
                      "reason": f"target_kind={target_kind!r} needs a target_name"}
    targets = show_output.list_targets()
    if target_kind == "category":
        names = [c["name"] for c in targets["categories"]]
        hit = next((n for n in names if n.strip().lower() == target_name.strip().lower()), None)
        if hit is not None:
            return {"kind": "category", "id": hit}, None
        return None, {"status": "rejected",
                      "reason": f"no category called {target_name!r}",
                      "close_matches": _close(target_name, names),
                      "known_categories": names}
    # fixture
    byname = {f["name"]: f["id"] for f in targets["fixtures"]}
    hit = next((n for n in byname if n.strip().lower() == target_name.strip().lower()), None)
    if hit is not None:
        return {"kind": "fixture", "id": byname[hit]}, None
    return None, {"status": "rejected",
                  "reason": f"no fixture called {target_name!r}",
                  "close_matches": _close(target_name, list(byname)),
                  "known_fixtures": list(byname)}


# ── handlers ───────────────────────────────────────────────────────────────

def _op_show_status() -> dict:
    return {**show_actions.status(), "output": show_output.status(),
            "arms": show_arms.status(), "brief": show_actions.brief()}


def _op_list_show_sets() -> dict:
    out = []
    for s in show_store.list_sets():
        out.append({"id": s.id, "name": s.name, "steps": len(s.actions),
                    "kinds": [a.kind for a in s.actions],
                    "problems": show_actions.validate_set(s.actions)})
    return {"sets": out}


def _op_create_show_set(name: str) -> dict:
    from spectra.models.light_show import ActionSet
    try:
        s = show_store.put_set(ActionSet(name=name))
    except show_store.SetNameTaken as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied", "set": {"id": s.id, "name": s.name},
            "summary": f"created the empty set '{s.name}' — add steps on the "
                      f"Light Show page's Build view"}


async def _op_fire_show_set(set_name: str) -> dict:
    s, rejection = _resolve_set(set_name)
    if rejection is not None:
        return rejection
    reason = show_output.refusal()
    if reason:
        return {"status": "refused", "reason": reason,
                "summary": f"'{s.name}' did not fire — the show is standing down: {reason}"}
    try:
        run = await show_actions.fire_set(s.id, source="sonic")
    except show_actions.ActionError as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied", "run": run,
            "summary": f"fired '{s.name}'"}


async def _op_arm_show_set(set_name: str, on: str = "scene_change", repeat: bool = False,
                           this_song_only: bool = False, finish_on_mark: bool = True) -> dict:
    s, rejection = _resolve_set(set_name)
    if rejection is not None:
        return rejection
    try:
        arm = show_arms.arm(set_id=s.id, on=on, repeat=repeat,
                            this_song_only=this_song_only,
                            finish_on_mark=finish_on_mark, source="sonic")
    except show_arms.ArmError as exc:
        return {"status": "rejected", "reason": str(exc)}
    trigger_word = {"scene_change": "the next scene change",
                    "high": "this song's High Trigger", "low": "this song's Low Trigger"}[on]
    return {"status": "applied", "arm": arm.model_dump(),
            "summary": f"armed '{s.name}' for {trigger_word}"
                      + (" (repeating)" if repeat else "")}


def _op_disarm_show(arm: str) -> dict:
    a, rejection = _resolve_arm(arm)
    if rejection is not None:
        return rejection
    show_arms.disarm(a.id)
    return {"status": "applied", "disarmed": a.id,
            "summary": f"disarmed '{a.label or a.id}'"}


def _op_disarm_all_show() -> dict:
    ids = show_arms.disarm_all(reason="disarmed by Sonic")
    return {"status": "applied", "disarmed": ids,
            "summary": f"disarmed {len(ids)} arm(s)" if ids else "nothing was armed"}


async def _op_hold_device(state: str, target_kind: str = "everything",
                          target_name: Optional[str] = None, color: Optional[str] = None,
                          fade_ms: int = 0) -> dict:
    if state not in STATE_CHOICES:
        return {"status": "rejected", "reason": f"state must be one of {STATE_CHOICES}"}
    target, rejection = _resolve_target(target_kind, target_name)
    if rejection is not None:
        return rejection
    reason = show_output.refusal()
    if reason:
        return {"status": "refused", "reason": reason,
                "summary": f"did not hold — the show is standing down: {reason}"}
    params: dict[str, Any] = {"target": target, "state": state, "fade_ms": fade_ms}
    if color:
        params["color"] = color
    action = ShowAction(kind="device_state", params=params)
    run = await show_actions.fire([action], name="Sonic: hold", source="sonic")
    who = target_name or "everything"
    return {"status": "applied", "run": run,
            "summary": f"set {who} to {state}"}


async def _op_dim_device(level: float, target_kind: str = "everything",
                         target_name: Optional[str] = None, duration_s: float = 10,
                         fade_in_ms: int = 500, fade_out_ms: int = 1000,
                         until: str = "time") -> dict:
    target, rejection = _resolve_target(target_kind, target_name)
    if rejection is not None:
        return rejection
    reason = show_output.refusal()
    if reason:
        return {"status": "refused", "reason": reason,
                "summary": f"did not dim — the show is standing down: {reason}"}
    action = ShowAction(kind="level", params={
        "target": target, "level": level, "duration_s": duration_s,
        "fade_in_ms": fade_in_ms, "fade_out_ms": fade_out_ms, "until": until})
    run = await show_actions.fire([action], name="Sonic: level", source="sonic")
    who = target_name or "everything"
    return {"status": "applied", "run": run,
            "summary": f"set {who} to {level:.0f}% for {duration_s:.0f}s"}


async def _op_move_high_low(level: str, seconds_into_song: float) -> dict:
    if level not in CUE_LEVEL_CHOICES:
        return {"status": "rejected", "reason": "level must be 'high' or 'low'"}
    uri = show_arms.current_uri()
    if not uri:
        return {"status": "rejected", "reason": "nothing is playing right now, "
                "so there is no song to move this song's High/Low on"}
    ts_ms = int(round(seconds_into_song * 1000))
    try:
        import asyncio
        saved = await asyncio.to_thread(show_cues.set_override, uri, level, ts_ms)
    except ValueError as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied", "cue": saved,
            "summary": f"moved this song's {level.title()} Trigger to {seconds_into_song:.1f}s"}


async def _op_end_show() -> dict:
    report = await show_actions.end_show()
    return {"status": "applied", "report": report,
            "summary": "ended the show — put back every setting and released every fixture"}


OPERATIONS: dict[str, SonicOperation] = {
    "show_status": SonicOperation(
        name="show_status", domain="show", kind="read",
        summary="What the Light Show is doing right now: held fixtures, "
                "levels, a running room effect, settings it has changed, "
                "running sets, and the full armed board.",
        instructions="Call this first for anything Light-Show-related. "
                    "`arms.armed` is the waiting board; `arms.song` carries "
                    "this song's High/Low for a countdown.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_show_status),
    "list_show_sets": SonicOperation(
        name="list_show_sets", domain="show", kind="read",
        summary="His named Light Show sets, with their step count and kinds.",
        instructions="Use this to find the exact name/id to pass to "
                    "fire_show_set/arm_show_set — never guess a name a "
                    "user approximated; if it doesn't exactly match one "
                    "here, those operations will refuse with close matches.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_list_show_sets),
    "create_show_set": SonicOperation(
        name="create_show_set", domain="show", kind="write",
        summary="Create a brand-new, empty Light Show set by name.",
        instructions="Always a NEW set with a fresh id. Set names are "
                    "unique: a name that already exists is REJECTED, "
                    "never silently overwritten. Adding steps to it is a "
                    "Build-view act, not something you can do — tell him "
                    "to open the Light Show page.",
        input_schema={"type": "object",
                     "properties": {"name": {"type": "string"}},
                     "required": ["name"], "additionalProperties": False},
        handler=_op_create_show_set),
    "fire_show_set": SonicOperation(
        name="fire_show_set", domain="show", kind="write",
        summary="Fire an already-saved Light Show set right now.",
        instructions="set_name may be the set's id or its exact name "
                    "(case-insensitive). A set holding a room-effect step "
                    "fires it exactly like any other step.",
        input_schema={"type": "object",
                     "properties": {"set_name": {"type": "string"}},
                     "required": ["set_name"], "additionalProperties": False},
        handler=_op_fire_show_set),
    "arm_show_set": SonicOperation(
        name="arm_show_set", domain="show", kind="write",
        summary="Arm a saved set to fire on the next scene change, or on "
                "this song's High or Low Trigger.",
        instructions="on is 'scene_change' | 'high' | 'low'. repeat keeps "
                    "it armed after firing; this_song_only scopes it to "
                    "whatever song is playing now; finish_on_mark (default "
                    "true) starts the set's fades early so they land on "
                    "the trigger mark.",
        input_schema={
            "type": "object",
            "properties": {
                "set_name": {"type": "string"},
                "on": {"type": "string", "enum": list(TRIGGER_CHOICES)},
                "repeat": {"type": "boolean"},
                "this_song_only": {"type": "boolean"},
                "finish_on_mark": {"type": "boolean"}},
            "required": ["set_name"], "additionalProperties": False},
        handler=_op_arm_show_set),
    "disarm_show": SonicOperation(
        name="disarm_show", domain="show", kind="write",
        summary="Disarm one waiting set by its label or arm id.",
        instructions="Call show_status first if unsure of the exact label "
                    "on the armed board.",
        input_schema={"type": "object",
                     "properties": {"arm": {"type": "string"}},
                     "required": ["arm"], "additionalProperties": False},
        handler=_op_disarm_show),
    "disarm_all_show": SonicOperation(
        name="disarm_all_show", domain="show", kind="write",
        summary="Disarm every waiting set at once.",
        instructions="No arguments.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_disarm_all_show),
    "hold_device": SonicOperation(
        name="hold_device", domain="show", kind="write",
        summary="Hold a fixture, a category, or everything at Steady/"
                "Frozen/Dark, or return it to Show.",
        instructions="state is 'show' | 'steady' | 'freeze' | 'dark'. "
                    "target_kind defaults to 'everything'; set it to "
                    "'category' or 'fixture' with target_name to narrow. "
                    "color (hex) only matters for 'steady' — empty uses "
                    "his Ambient colour. The show keeps running "
                    "underneath, so 'show' returns it to step.",
        input_schema={
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": list(STATE_CHOICES)},
                "target_kind": {"type": "string", "enum": list(TARGET_KIND_CHOICES)},
                "target_name": {"type": "string"},
                "color": {"type": "string"},
                "fade_ms": {"type": "number"}},
            "required": ["state"], "additionalProperties": False},
        handler=_op_hold_device),
    "dim_device": SonicOperation(
        name="dim_device", domain="show", kind="write",
        summary="Temporarily dim or brighten a fixture, a category, or "
                "everything.",
        instructions="level is a percent, 100 = unchanged, above 100 "
                    "brightens (clipped at full). duration_s is how long "
                    "it lasts before its fade-out (until='time', the "
                    "default); until may also be 'scene_change' or "
                    "'released'.",
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "number", "minimum": 0, "maximum": 200},
                "target_kind": {"type": "string", "enum": list(TARGET_KIND_CHOICES)},
                "target_name": {"type": "string"},
                "duration_s": {"type": "number", "minimum": 0, "maximum": 3600},
                "fade_in_ms": {"type": "number"},
                "fade_out_ms": {"type": "number"},
                "until": {"type": "string",
                         "enum": ["time", "scene_change", "released"]}},
            "required": ["level"], "additionalProperties": False},
        handler=_op_dim_device),
    "move_high_low": SonicOperation(
        name="move_high_low", domain="show", kind="write",
        summary="Move this song's High or Low Trigger to a specific "
                "moment, like dragging it on the Light Show page.",
        instructions="Needs a song actually playing right now — there is "
                    "no song to move a cue on otherwise. seconds_into_song "
                    "is from the start of the song.",
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": list(CUE_LEVEL_CHOICES)},
                "seconds_into_song": {"type": "number", "minimum": 0}},
            "required": ["level", "seconds_into_song"], "additionalProperties": False},
        handler=_op_move_high_low),
    "end_show": SonicOperation(
        name="end_show", domain="show", kind="write",
        summary="End the Light Show: cancel running sets, stop its room "
                "effect, release every held fixture, and put back every "
                "setting it changed (unless he changed it since, which is "
                "left alone and named).",
        instructions="No arguments. Safe to call even if nothing is "
                    "active — it reports 'nothing to put back'.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_end_show),
}
