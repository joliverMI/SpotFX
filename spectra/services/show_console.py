"""SONIC'S LIGHT SHOW AUTHORITY (phase 3, the Admiral's own ask: "Sonic
commands for fire / arm / disarm / what's armed / device hold or dim /
create set / move High-Low / end show"; widened 2026-10-08 with his Pulse
reactivity, Pulse brightness floor/ceiling and flares on/off actions —
`set_pulse_reactivity`/`set_pulse_brightness`/`set_flares`/
`end_effect_hold`, each one ad-hoc step through the same
`show_actions.fire()`).

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

SHOW SEQUENCES (2026-10-09, spectra/services/show_sequence.py): reading his
sequences and the running one (`list_show_sequences`,
`show_sequence_status`) and driving a run by name — start (optionally
replacing the running one), pause, resume, stop, Next (skip the current
item unfired), Previous (back one, re-armed) and Fire now (run the current
Set item at once, or end the current Wait). AUTHORING a sequence — adding,
ordering and arming items, building a song list — is the Sequence tab's
Build view, deliberately excluded here for the same reason editing a set's
steps is.

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


def _resolve_sequence(name_or_id: str):
    s = show_store.find_sequence(name_or_id)
    if s is not None:
        return s, None
    names = [x.name for x in show_store.list_sequences()]
    return None, {"status": "rejected",
                  "reason": f"no sequence called {name_or_id!r}",
                  "close_matches": _close(name_or_id, names),
                  "known_sequences": names}


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


UNTIL_CHOICES = ("released", "time", "scene_change")
FLARES_CHOICES = ("off", "on")


async def _fire_one(kind: str, params: dict, name: str) -> dict:
    """One ad-hoc step through show_actions.fire — the SAME path the Build
    view's steps run, never a second write path."""
    reason = show_output.refusal()
    if reason:
        return {"status": "refused", "reason": reason,
                "summary": f"did not run — the show is standing down: {reason}"}
    try:
        show_actions.validate(kind, params)
    except show_actions.ActionError as exc:
        return {"status": "rejected", "reason": str(exc)}
    run = await show_actions.fire([ShowAction(kind=kind, params=params)],
                                  name=name, source="sonic")
    step = run["steps"][0]
    status = "applied" if step.get("status") in ("applied", "skipped") else "rejected"
    out = {"status": status, "run": run, "summary": step.get("detail") or step.get("status")}
    if status == "rejected":
        out["reason"] = step.get("detail")
    return out


def _timing(until: str, duration_s: float) -> dict:
    return {"until": until, "duration_s": duration_s}


async def _op_set_pulse_reactivity(reactivity: float, target_kind: str = "everything",
                                   target_name: Optional[str] = None,
                                   until: str = "released", duration_s: float = 30,
                                   fade_in_ms: int = 1000, fade_out_ms: int = 1000) -> dict:
    target, rejection = _resolve_target(target_kind, target_name)
    if rejection is not None:
        return rejection
    return await _fire_one("pulse_reactivity", {
        "target": target, "reactivity": reactivity, "fade_in_ms": fade_in_ms,
        "fade_out_ms": fade_out_ms, **_timing(until, duration_s)}, "Sonic: Pulse reactivity")


async def _op_set_pulse_brightness(floor: float = 0.0, ceiling: float = 1.0,
                                   target_kind: str = "everything",
                                   target_name: Optional[str] = None,
                                   until: str = "released", duration_s: float = 30,
                                   fade_in_ms: int = 1000, fade_out_ms: int = 1000) -> dict:
    target, rejection = _resolve_target(target_kind, target_name)
    if rejection is not None:
        return rejection
    return await _fire_one("pulse_brightness", {
        "target": target, "floor": floor, "ceiling": ceiling, "fade_in_ms": fade_in_ms,
        "fade_out_ms": fade_out_ms, **_timing(until, duration_s)}, "Sonic: Pulse brightness")


async def _op_set_flares(flares: str, target_kind: str = "everything",
                         target_name: Optional[str] = None, until: str = "released",
                         duration_s: float = 30) -> dict:
    if flares not in FLARES_CHOICES:
        return {"status": "rejected", "reason": "flares must be 'off' or 'on'"}
    target, rejection = _resolve_target(target_kind, target_name)
    if rejection is not None:
        return rejection
    return await _fire_one("flares", {"target": target, "flares": flares,
                                      **_timing(until, duration_s)}, "Sonic: flares")


def _op_end_effect_hold(hold_id: str) -> dict:
    from spectra.services import show_mods
    if show_mods.end_pulse_mod(hold_id):
        return {"status": "applied", "ended": hold_id, "summary": "ended that Pulse hold"}
    if show_mods.end_flare_block(hold_id):
        return {"status": "applied", "ended": hold_id, "summary": "flares back on there"}
    held = show_mods.status()
    return {"status": "rejected",
            "reason": f"no Pulse hold or flares-off called {hold_id!r}",
            "pulse_holds": [m["id"] for m in held["pulse_mods"]],
            "flares_off": [b["id"] for b in held["flare_blocks"]]}


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


def _op_list_show_sequences() -> dict:
    from spectra.services import show_sequence
    out = []
    for s in show_store.list_sequences():
        out.append({"id": s.id, "name": s.name, "loop": s.loop,
                    "items": [show_sequence.item_title(it) for it in s.items],
                    "problems": show_sequence.problems(s)})
    return {"sequences": out}


def _op_show_sequence_status() -> dict:
    from spectra.services import show_sequence
    st = show_sequence.status()
    r = st["run"]
    if r is None:
        return {"run": None, "summary": "no sequence has run yet"}
    brief = {k: r[k] for k in ("name", "state", "index", "waiting_for", "loops_done",
                               "paused_reason", "end_reason")}
    brief["current"] = (r["items"][r["index"]]["title"]
                        if 0 <= r["index"] < len(r["items"]) else None)
    brief["upcoming"] = [it["title"] for it in r["items"][r["index"] + 1:]]
    brief["recent_log"] = r["log"][:8]
    return {"run": brief, "refusal": st["refusal"]}


def _sequence_control(fn, done: str):
    from spectra.services import show_sequence
    try:
        r = fn()
    except show_sequence.SequenceError as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied", "summary": done.format(name=r.name),
            "now": show_sequence.waiting_for(r) or r.state, "index": r.index}


def _op_start_show_sequence(sequence_name: str, replace: bool = False) -> dict:
    from spectra.services import show_sequence
    s, err = _resolve_sequence(sequence_name)
    if err:
        return err
    return _sequence_control(
        lambda: show_sequence.start(s.id, replace=replace, source="sonic"),
        "started the sequence '{name}'")


def _op_stop_show_sequence() -> dict:
    from spectra.services import show_sequence
    return _sequence_control(lambda: show_sequence.stop("stopped by Sonic"),
                             "stopped the sequence '{name}'")


def _op_pause_show_sequence() -> dict:
    from spectra.services import show_sequence
    return _sequence_control(lambda: show_sequence.pause("paused by Sonic"),
                             "paused the sequence '{name}'")


def _op_resume_show_sequence() -> dict:
    from spectra.services import show_sequence
    return _sequence_control(show_sequence.resume, "resumed the sequence '{name}'")


def _op_next_show_sequence_step() -> dict:
    from spectra.services import show_sequence
    return _sequence_control(show_sequence.next_item,
                             "skipped to the next item of '{name}'")


def _op_previous_show_sequence_step() -> dict:
    from spectra.services import show_sequence
    return _sequence_control(show_sequence.previous_item,
                             "stepped '{name}' back one item")


async def _op_fire_show_sequence_step() -> dict:
    from spectra.services import show_sequence
    try:
        r = await show_sequence.fire_now()
    except show_sequence.SequenceError as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied",
            "summary": f"ran the current item of '{r.name}' now and moved on",
            "now": show_sequence.waiting_for(r) or r.state, "index": r.index}


_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

SEQUENCE_OPERATIONS: dict[str, SonicOperation] = {
    "list_show_sequences": SonicOperation(
        name="list_show_sequences", domain="show", kind="read",
        summary="His Show Sequences: ordered lists of sets (each armed "
                "instant / next scene change / next High / next Low) and Waits.",
        instructions="Use it to find the exact name to pass to "
                    "start_show_sequence. Building or editing a sequence is "
                    "the Light Show page's Sequence tab — not something you can do.",
        input_schema=_NO_ARGS, handler=_op_list_show_sequences),
    "show_sequence_status": SonicOperation(
        name="show_sequence_status", domain="show", kind="read",
        summary="The running (or last) Show Sequence: its state, the current "
                "item and what it is waiting for, what comes next, and the "
                "recent log.",
        instructions="No arguments. `waiting_for` is the plain sentence to "
                    "repeat to him ('waiting for 2 more High Triggers').",
        input_schema=_NO_ARGS, handler=_op_show_sequence_status),
    "start_show_sequence": SonicOperation(
        name="start_show_sequence", domain="show", kind="write",
        summary="Start a Show Sequence by name. It runs its items strictly "
                "in order, never skipping ahead.",
        instructions="Only one sequence runs at a time: if one is running "
                    "this is refused unless replace=true, which stops it "
                    "first. Say which was replaced.",
        input_schema={"type": "object",
                      "properties": {"sequence_name": {"type": "string"},
                                     "replace": {"type": "boolean"}},
                      "required": ["sequence_name"], "additionalProperties": False},
        handler=_op_start_show_sequence),
    "stop_show_sequence": SonicOperation(
        name="stop_show_sequence", domain="show", kind="write",
        summary="Stop the running Show Sequence (its waiting arm is disarmed; "
                "nothing it already did is undone — that is end_show).",
        instructions="No arguments.", input_schema=_NO_ARGS,
        handler=_op_stop_show_sequence),
    "pause_show_sequence": SonicOperation(
        name="pause_show_sequence", domain="show", kind="write",
        summary="Pause the running Show Sequence: its arm is disarmed, a "
                "timed Wait's clock stops, and triggers are not counted.",
        instructions="No arguments. resume_show_sequence picks up where it was.",
        input_schema=_NO_ARGS, handler=_op_pause_show_sequence),
    "resume_show_sequence": SonicOperation(
        name="resume_show_sequence", domain="show", kind="write",
        summary="Resume a paused Show Sequence at its current item.",
        instructions="No arguments.", input_schema=_NO_ARGS,
        handler=_op_resume_show_sequence),
    "next_show_sequence_step": SonicOperation(
        name="next_show_sequence_step", domain="show", kind="write",
        summary="Skip the current item of the running Show Sequence WITHOUT "
                "running it, and move to the next.",
        instructions="If he wants the current set to RUN and then move on, "
                    "use fire_show_sequence_step instead.",
        input_schema=_NO_ARGS, handler=_op_next_show_sequence_step),
    "previous_show_sequence_step": SonicOperation(
        name="previous_show_sequence_step", domain="show", kind="write",
        summary="Step the running Show Sequence back one item and re-arm it "
                "(nothing that item already did is undone).",
        instructions="An instant item stepped back onto does not fire by "
                    "itself; it waits for fire_show_sequence_step or Next.",
        input_schema=_NO_ARGS, handler=_op_previous_show_sequence_step),
    "fire_show_sequence_step": SonicOperation(
        name="fire_show_sequence_step", domain="show", kind="write",
        summary="Run the current Set item of the running Show Sequence now "
                "(whatever its arming) and move on; on a Wait, end the Wait.",
        instructions="No arguments. Refused while the Light Show is standing "
                    "down — say why.",
        input_schema=_NO_ARGS, handler=_op_fire_show_sequence_step),
}


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
    "set_pulse_reactivity": SonicOperation(
        name="set_pulse_reactivity", domain="show", kind="write",
        summary="Turn how strongly the Pulse effect reacts to the music "
                "(0 = no reaction to hits, 1 = full) on a fixture, a "
                "category or everything, as a Light Show hold.",
        instructions="reactivity 0..1. Scales Pulse's live-audio hit pulses "
                    "and its rainbow hit-steps only — not flares (use "
                    "set_flares) nor charge/lull/drop. A hold on a "
                    "different target stacks (multiplies); the exact same "
                    "target restarts it instead of adding a duplicate. "
                    "until: 'released' (default — ends with "
                    "end_effect_hold or end_show) | 'time' (duration_s) | "
                    "'scene_change'. A target not running Pulse is "
                    "unaffected until it does.",
        input_schema={
            "type": "object",
            "properties": {
                "reactivity": {"type": "number", "minimum": 0, "maximum": 1},
                "target_kind": {"type": "string", "enum": list(TARGET_KIND_CHOICES)},
                "target_name": {"type": "string"},
                "until": {"type": "string", "enum": list(UNTIL_CHOICES)},
                "duration_s": {"type": "number", "minimum": 0, "maximum": 3600},
                "fade_in_ms": {"type": "number"},
                "fade_out_ms": {"type": "number"}},
            "required": ["reactivity"], "additionalProperties": False},
        handler=_op_set_pulse_reactivity),
    "set_pulse_brightness": SonicOperation(
        name="set_pulse_brightness", domain="show", kind="write",
        summary="Keep the Pulse effect between a brightness floor and "
                "ceiling (0..1) on a fixture, a category or everything, as "
                "a Light Show hold.",
        instructions="floor/ceiling are 0..1 on Pulse's own (perceived) "
                    "brightness scale; floor 0 = none, ceiling 1 = none, and "
                    "at least one must be set; floor may not exceed "
                    "ceiling. Clamps hits, drops, lulls and flares alike. "
                    "until as for set_pulse_reactivity.",
        input_schema={
            "type": "object",
            "properties": {
                "floor": {"type": "number", "minimum": 0, "maximum": 1},
                "ceiling": {"type": "number", "minimum": 0, "maximum": 1},
                "target_kind": {"type": "string", "enum": list(TARGET_KIND_CHOICES)},
                "target_name": {"type": "string"},
                "until": {"type": "string", "enum": list(UNTIL_CHOICES)},
                "duration_s": {"type": "number", "minimum": 0, "maximum": 3600},
                "fade_in_ms": {"type": "number"},
                "fade_out_ms": {"type": "number"}},
            "additionalProperties": False},
        handler=_op_set_pulse_brightness),
    "set_flares": SonicOperation(
        name="set_flares", domain="show", kind="write",
        summary="Switch flares off (or back on) for a fixture, a category "
                "or everything — off also takes them out of charge/lull/drop.",
        instructions="flares 'off' | 'on'. It works per virtual: one Hue "
                    "fixture takes every Hue bulb with it (the reply names "
                    "who came along). 'on' lifts every flares-off on those "
                    "lights. until as for set_pulse_reactivity (default "
                    "'released'). show_status lists what is off "
                    "(output.flare_blocks).",
        input_schema={
            "type": "object",
            "properties": {
                "flares": {"type": "string", "enum": list(FLARES_CHOICES)},
                "target_kind": {"type": "string", "enum": list(TARGET_KIND_CHOICES)},
                "target_name": {"type": "string"},
                "until": {"type": "string", "enum": list(UNTIL_CHOICES)},
                "duration_s": {"type": "number", "minimum": 0, "maximum": 3600}},
            "required": ["flares"], "additionalProperties": False},
        handler=_op_set_flares),
    "end_effect_hold": SonicOperation(
        name="end_effect_hold", domain="show", kind="write",
        summary="End one Pulse hold or flares-off switch by its id.",
        instructions="Ids are in show_status's output.pulse_mods / "
                    "output.flare_blocks. end_show ends all of them.",
        input_schema={"type": "object",
                     "properties": {"hold_id": {"type": "string"}},
                     "required": ["hold_id"], "additionalProperties": False},
        handler=_op_end_effect_hold),
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

OPERATIONS.update(SEQUENCE_OPERATIONS)
