"""SETS THAT CALL SETS (the Admiral, 2026-10-11: "reference other sets within
sets, so I can, for example, set a bunch of default values for some
settings and call them on several sets that behave similarly").

A `call_set` step (`show_actions.ACTION_KINDS["call_set"]`, param `set` = the
called set's ID) RUNS THE CALLED SET'S STEPS INLINE AT THAT POINT. Four
rules, and every reader of a set goes through this module for them:

  * INLINE MEANS INLINE. A call is expanded, at the moment the set runs,
    into the called set's own steps in its own order, as if they had been
    pasted there — so a pause inside the called set pauses the caller,
    consecutive room-setting steps on either side of the boundary still
    coalesce into one save, and a later step of the caller still wins a
    collision with an earlier one of the callee. Nothing about how a step
    runs knows it arrived through a call; only its record does (`via`).
  * A REFERENCE, NEVER A COPY. The expansion reads the called set as it is
    in his library NOW, so an edit to a shared "defaults" set changes every
    set that calls it. (An ARM or a sequence run fires its set by id, so it
    picks up the edit at fire time too.)
  * NO CYCLES. A set may not call itself, directly or through any chain of
    calls. `find_cycle()` is the one test: `show_store.put_set` refuses a
    save that would close a loop (`SetReferenceCycle`, naming the loop),
    and `expand()` refuses one at run time as well — a cycle that arrived
    some other way (a hand-edited file) fails that one step by name, it
    never recurses.
  * A MISSING SET IS A FAILED STEP, NOT A SILENT SKIP. Deleting a set that
    is called warns first (the API answers 409 with `used_by` unless the
    delete is forced); if it is deleted anyway, every call to it fails by
    name ("calls a set that no longer exists") until he fixes the caller.

`MAX_DEPTH` bounds nesting so a legitimately deep tree can never run away.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from spectra.models.light_show import ActionSet, ShowAction

CALL_KIND = "call_set"
CALL_PARAM = "set"
MAX_DEPTH = 8


class SetReferenceCycle(ValueError):
    """Saving this set would make it call itself."""


def called_id(action: ShowAction) -> Optional[str]:
    """The set a step calls, or None if it is not a call."""
    if action.kind != CALL_KIND:
        return None
    sid = (action.params or {}).get(CALL_PARAM)
    return sid if isinstance(sid, str) and sid else None


def called_ids(actions: Iterable[ShowAction]) -> list[str]:
    """Every set these steps call directly, in step order, without repeats
    (switched-off calls included — a switched-off call is still a
    reference he can switch back on)."""
    out: list[str] = []
    for a in actions:
        sid = called_id(a)
        if sid and sid not in out:
            out.append(sid)
    return out


def _by_id(sets: Iterable[ActionSet]) -> dict[str, ActionSet]:
    return {s.id: s for s in sets}


def find_cycle(set_id: str, actions: list[ShowAction],
               sets: Iterable[ActionSet]) -> Optional[list[str]]:
    """If set `set_id` holding `actions` would call itself (directly or
    through other sets), the loop as a list of set ids starting and ending
    at `set_id`; otherwise None. `sets` is the library the other sets are
    read from — `set_id`'s own stored copy in it is ignored."""
    lib = _by_id(sets)
    seen: set[str] = set()

    def walk(sid: str, path: list[str]) -> Optional[list[str]]:
        steps = actions if sid == set_id and len(path) == 1 else (
            lib[sid].actions if sid in lib else [])
        for nxt in called_ids(steps):
            if nxt == set_id:
                return path + [nxt]
            if nxt in path or nxt in seen:
                continue
            found = walk(nxt, path + [nxt])
            if found:
                return found
        seen.add(sid)
        return None

    return walk(set_id, [set_id])


def cycle_sentence(cycle: list[str], sets: Iterable[ActionSet],
                   names: Optional[dict[str, str]] = None) -> str:
    lib = _by_id(sets)
    names = names or {}

    def nm(sid: str) -> str:
        return names.get(sid) or (lib[sid].name if sid in lib else sid)

    chain = " → ".join(f"“{nm(s)}”" for s in cycle)
    if len(cycle) == 2:
        return f"a set cannot call itself ({chain})"
    return f"that would make “{nm(cycle[0])}” call itself: {chain}"


def callers(set_id: str, sets: Iterable[ActionSet]) -> list[ActionSet]:
    """The sets that call `set_id` directly."""
    return [s for s in sets if s.id != set_id and set_id in called_ids(s.actions)]


@dataclass
class Expanded:
    """One step as it will run. `via` names the sets it was reached through
    (outermost first, the set being fired excluded); `path` is a stable,
    unique id for the step's record (a set called twice yields two records);
    `problem` is set when this step stands in for a call that cannot run."""
    action: ShowAction
    via: list[str] = field(default_factory=list)
    path: str = ""
    problem: Optional[str] = None


def expand(actions: list[ShowAction], sets: Iterable[ActionSet], *,
           root_id: Optional[str] = None) -> list[Expanded]:
    """Flatten every call into the called set's steps, recursively.

    A switched-off call stays as ONE step (it is recorded as skipped, its
    callee's steps are not listed). A call whose set is missing, which would
    loop, or which nests past MAX_DEPTH stays as one step carrying a
    `problem`. Everything else is the called set's own steps, in order."""
    lib = _by_id(sets)
    out: list[Expanded] = []

    def walk(steps: list[ShowAction], via: list[str], ids: list[str], prefix: str) -> None:
        for a in steps:
            path = f"{prefix}{a.id}"
            sid = called_id(a) if a.kind == CALL_KIND else None
            if a.kind != CALL_KIND or not a.enabled:
                out.append(Expanded(a, list(via), path))
                continue
            if sid is None:
                out.append(Expanded(a, list(via), path, "no set chosen to run"))
                continue
            target = lib.get(sid)
            if target is None:
                out.append(Expanded(a, list(via), path,
                                    "calls a set that no longer exists"))
                continue
            if sid in ids:
                loop = " → ".join(f"“{lib[x].name if x in lib else x}”"
                                  for x in ids[ids.index(sid):] + [sid])
                out.append(Expanded(a, list(via), path,
                                    f"would loop forever ({loop}) — not run"))
                continue
            if len(via) >= MAX_DEPTH:
                out.append(Expanded(a, list(via), path,
                                    f"sets nested more than {MAX_DEPTH} deep — not run"))
                continue
            walk(target.actions, via + [target.name], ids + [sid], f"{path}/")

    walk(actions, [], [root_id] if root_id else [], "")
    return out


def references(set_id: str, sets: list[ActionSet], sequences: Optional[list] = None) -> dict:
    """What a set calls and what calls it — the editor's "Calls" and
    "Used by" lines, the delete warning, and Sonic's read."""
    lib = _by_id(sets)
    me = lib.get(set_id)
    calls = []
    for sid in called_ids(me.actions if me else []):
        calls.append({"id": sid, "name": lib[sid].name if sid in lib else None,
                      "missing": sid not in lib})
    used_by = [{"id": s.id, "name": s.name} for s in callers(set_id, sets)]
    used_in = []
    for q in sequences or []:
        if any(getattr(it, "kind", None) == "set" and getattr(it, "set_id", None) == set_id
               for it in q.items):
            used_in.append({"id": q.id, "name": q.name})
    return {"calls": calls, "used_by": used_by, "used_in_sequences": used_in}
