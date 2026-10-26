"""THE NARROW PROFILE TRIGGER EDIT — the one way anything other than his
Timeline save changes his charge, lull and drop triggers in a song profile
(2026-10-26, predrop plan step 1: the Home Drops panel; the Admiral's
answer 6, "it can remove ones i manually added and disables imported
ones").

WHY THE PROFILE, NOT THE FIRED COPY. Every one of his triggers lives in his
song profile (storage/profiles/*.json, the Timeline's editor copy) as well
as in the copy SPECTRA fires from, and an explicit profile save wins
(AGENTS.md, "TWO trigger copies"). A deletion made only in the fired copy
would come back with his next Timeline save. So the panel's Remove writes
HERE, and the route runs the whole-song sync so the fired copy follows.

WHAT IT MAY TOUCH. Only `triggers` entries whose `event_id` is one of the
three fixed phase events (PHASE_EVENT_IDS) — every one of his 586 charge/
lull/drop triggers uses them (the plan's count, 2026-10-25) — so it can
never change anything else in a song. An id the profile does not hold is
refused by name (`TriggerNotFound`), and so is any other trigger
(`EditRefused`); a refused request writes nothing.

PLACED BY HAND OR IMPORTED (`imported_reason`). Nothing records who placed
a trigger, so it is a rule, read off what is stored: a stable analysed-
import id (`analyzed_<event>_<ms>`, services/trigger_identity.py), or any
trigger in a profile an import or the AI generator wrote (`embedded_
generated` / `ai_generated`), counts as imported; every other one as placed
by hand. `remove` DELETES a hand-placed trigger and SWITCHES OFF an
imported one (`enabled = false`): a switched-off imported trigger stays in
his profile, so a re-import under the default "protect" policy finds it by
its id and leaves it off. The rule's honest limit: a drop he hand-placed
inside an import-written profile counts as imported, so it is switched off
rather than deleted — the safe direction.

THE RAW-DICT DISCIPLINE. The profile is patched as the dict it is on disk
(profile_trigger_sync's reverse direction precedent): no model round-trip,
so no other field is rewritten; the file keeps its own escaping (pydantic
writes raw UTF-8, the repair scripts write \\uXXXX — `write_profile_raw`).

UNDO. Every change comes back as {id, before, after, index}: the row as it
was, as it is now, and where it sat. `restore` takes such records the other
way round ({id, from, to, index}): each row must still be exactly `from`
(else `RestoreConflict`, nothing written), then it becomes `to` — None
deletes it, a row that is gone is put back at its old index.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

PHASE_EVENT_IDS = ("fixed-charge", "fixed-lull", "fixed-drop")
ANALYSED_ID_PREFIX = "analyzed_"

REASON_ANALYSED_ID = "analysed_import_id"
REASON_EMBEDDED = "embedded_import"
REASON_AI = "ai_generated"


class EditRefused(ValueError):
    """The request names a trigger this route may not touch, or is malformed."""


class TriggerNotFound(LookupError):
    """The profile holds no trigger with that id."""


class RestoreConflict(RuntimeError):
    """A row changed since the record being restored was taken."""


def imported_reason(trigger: dict, profile: dict) -> Optional[str]:
    """Why `trigger` counts as imported, or None when it was placed by hand."""
    if str(trigger.get("id") or "").startswith(ANALYSED_ID_PREFIX):
        return REASON_ANALYSED_ID
    if profile.get("embedded_generated"):
        return REASON_EMBEDDED
    if profile.get("ai_generated"):
        return REASON_AI
    return None


def is_phase(trigger: dict) -> bool:
    return trigger.get("event_id") in PHASE_EVENT_IDS


def provenance(profile: dict) -> dict:
    """Every phase trigger in the profile, with whether it is imported and
    what Remove would do to it."""
    rows = []
    for t in profile.get("triggers") or []:
        if not isinstance(t, dict) or not is_phase(t):
            continue
        why = imported_reason(t, profile)
        rows.append({"id": t.get("id"), "event_id": t.get("event_id"),
                     "timestamp_ms": t.get("timestamp_ms"),
                     "enabled": bool(t.get("enabled", True)),
                     "imported": why is not None, "why": why or "by_hand",
                     "remove_would": "disable" if why is not None else "delete"})
    return {"uri": profile.get("spotify_uri"),
            "imported_profile": bool(profile.get("embedded_generated")
                                     or profile.get("ai_generated")),
            "triggers": rows}


@dataclass
class Edit:
    remove: list = field(default_factory=list)
    delete: list = field(default_factory=list)
    disable: list = field(default_factory=list)
    enable: list = field(default_factory=list)
    move: list = field(default_factory=list)        # [{"id", "timestamp_ms"}]
    restore: list = field(default_factory=list)     # [{"id", "from", "to", "index"}]


def _index_of(triggers: list, tid: str) -> Optional[int]:
    for i, t in enumerate(triggers):
        if isinstance(t, dict) and str(t.get("id")) == tid:
            return i
    return None


def _check_target(triggers: list, tid: str) -> int:
    i = _index_of(triggers, tid)
    if i is None:
        raise TriggerNotFound(f"this song's profile holds no trigger {tid!r}")
    if not is_phase(triggers[i]):
        raise EditRefused(
            f"trigger {tid!r} is a {triggers[i].get('event_id')!r} trigger: only "
            f"charge, lull and drop triggers ({', '.join(PHASE_EVENT_IDS)}) can be "
            "changed here")
    return i


def apply(profile: dict, edit: Edit) -> list[dict]:
    """Apply `edit` to the RAW profile dict in place and return what
    changed (module docstring's UNDO). Validates everything first, so a
    refusal leaves `profile` untouched."""
    triggers = profile.get("triggers")
    if not isinstance(triggers, list):
        raise EditRefused("this profile has no trigger list")
    if edit.restore:
        if edit.remove or edit.delete or edit.disable or edit.enable or edit.move:
            raise EditRefused("restore is its own request")
        return _restore(triggers, edit.restore)

    named: dict[str, str] = {}
    for op, ids in (("remove", edit.remove), ("delete", edit.delete),
                    ("disable", edit.disable), ("enable", edit.enable),
                    ("move", [m.get("id") for m in edit.move])):
        for tid in ids:
            tid = str(tid)
            if tid in named:
                raise EditRefused(f"trigger {tid!r} is named twice ({named[tid]} and {op})")
            named[tid] = op
            _check_target(triggers, tid)
    if not named:
        raise EditRefused("name at least one trigger")
    moves = {}
    for m in edit.move:
        try:
            ms = int(m.get("timestamp_ms"))
        except (TypeError, ValueError):
            raise EditRefused(f"move of {m.get('id')!r} needs a timestamp_ms") from None
        if ms < 0:
            raise EditRefused("a trigger cannot sit before the song starts")
        moves[str(m.get("id"))] = ms

    changes: list[dict] = []
    deletes: list[int] = []
    for tid, op in named.items():
        i = _index_of(triggers, tid)
        before = copy.deepcopy(triggers[i])
        if op == "remove":
            op = "disable" if imported_reason(before, profile) else "delete"
        if op == "delete":
            deletes.append(i)
            changes.append({"id": tid, "before": before, "after": None, "index": i,
                            "did": "deleted"})
            continue
        row = triggers[i]
        if op == "disable":
            if row.get("enabled", True) is False:
                continue
            row["enabled"] = False
            did = "switched_off"
        elif op == "enable":
            if row.get("enabled", True) is True:
                continue
            row["enabled"] = True
            did = "switched_on"
        else:
            if int(row.get("timestamp_ms") or 0) == moves[tid]:
                continue
            row["timestamp_ms"] = moves[tid]
            did = "moved"
        changes.append({"id": tid, "before": before, "after": copy.deepcopy(row),
                        "index": i, "did": did})
    for i in sorted(deletes, reverse=True):
        triggers.pop(i)
    return changes


def _restore(triggers: list, records: list) -> list[dict]:
    plan = []
    for rec in records:
        tid = str(rec.get("id") or "")
        if not tid:
            raise EditRefused("every restore record names its trigger id")
        frm, to = rec.get("from"), rec.get("to")
        for row in (frm, to):
            if row is not None and (not isinstance(row, dict) or not is_phase(row)
                                    or str(row.get("id")) != tid):
                raise EditRefused(f"restore of {tid!r} names a row that is not that "
                                  "charge, lull or drop trigger")
        i = _index_of(triggers, tid)
        current = triggers[i] if i is not None else None
        if current != frm:
            raise RestoreConflict(f"trigger {tid!r} changed since — nothing was undone; "
                                  "reload and try again")
        plan.append((tid, frm, to, rec.get("index")))
    changes = []
    # Rows that exist are replaced or deleted (found by id, so order does
    # not matter); rows that are gone go back last, lowest old index first,
    # so each lands where it sat before the edit that removed it.
    inserts = sorted((p for p in plan if p[1] is None and p[2] is not None),
                     key=lambda p: p[3] if isinstance(p[3], int) else len(triggers))
    for tid, frm, to, _index in plan:
        if frm is None:
            continue
        i = _index_of(triggers, tid)
        if to is None:
            triggers.pop(i)
            changes.append({"id": tid, "before": frm, "after": None, "index": i,
                            "did": "deleted"})
        else:
            triggers[i] = copy.deepcopy(to)
            changes.append({"id": tid, "before": frm, "after": copy.deepcopy(to),
                            "index": i, "did": "restored"})
    for tid, _frm, to, index in inserts:
        at = index if isinstance(index, int) and 0 <= index <= len(triggers) else len(triggers)
        triggers.insert(at, copy.deepcopy(to))
        changes.append({"id": tid, "before": None, "after": copy.deepcopy(to),
                        "index": at, "did": "restored"})
    return changes


def file_is_ascii(raw: bytes) -> bool:
    """True when the profile file holds no raw non-ASCII bytes — written with
    \\uXXXX escapes — so a rewrite keeps the same convention."""
    return not any(b > 127 for b in raw)
