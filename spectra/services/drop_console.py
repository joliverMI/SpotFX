"""THE DROPS DOMAIN — Sonic's operations over the playing song's drop
sequences (drop-detection plan, phase 4; report section 10's "talk to it":
"confirm every drop on this song", "move the second drop one beat
earlier", "no drops on this song").

Every write goes through spectra/services/drop_sequences.py's own
`apply_edit` — the same edits the Timeline's buttons make, never a second
write path — so the "How edits are kept" rules hold here exactly as there.
What fires is spectra/services/drop_firing.py's rule (phase 5): a
sequence confirmed, edited or added here counts as his.

NUMBERING. A sequence is named by its number in song order among the
song's sequences that are not dismissed (#1 is the earliest), the same
order the Timeline's review list shows — never by a key he cannot see. A
number that names nothing is REJECTED with the list, never guessed. A
sequence that stands down on his own triggers ("matches yours") is listed
but not edited here: his triggers are edited on the SPECTRA triggers strip.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

from spectra.services import drop_firing, drop_sequences as ds
from spectra.services.sonic_ops import SonicOperation

HANDLE_CHOICES = ("charge", "lull", "drop")


def _current_uri() -> Optional[str]:
    from spectra.services import show_arms
    return show_arms.current_uri()


def _song(uri: Optional[str]) -> tuple[Optional[str], Optional[dict]]:
    """(uri, rejection)."""
    if uri is not None:
        if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
            return None, {"status": "rejected", "reason": "uri must be a spotify:track: URI"}
        return uri, None
    cur = _current_uri()
    if not cur:
        return None, {"status": "rejected", "reason": "nothing is playing right now — "
                      "name the song (its spotify:track: URI)"}
    return cur, None


def _secs(ms: Optional[int]) -> Optional[float]:
    return None if ms is None else round(ms / 1000.0, 2)


def _numbered(view: dict) -> list[dict]:
    seqs = [s for s in view.get("sequences") or [] if s.get("state") != ds.STATE_DISMISSED]
    return sorted(seqs, key=lambda s: s["drop_ms"])


def _describe(n: int, s: dict) -> dict:
    out = {
        "number": n, "state": s["state"],
        "drop_s": _secs(s["drop_ms"]), "lull_s": _secs(s.get("lull_ms")),
        "charge_s": _secs(s.get("charge_ms")),
        # the Timeline draws a switched-off lull/charge differently from one
        # that was never placed — nothing before this surfaced that
        # difference here, so "turn the lull back on" had no way to know
        # whether there was ever a lull to turn on (build item B5).
        "lull_off": bool(s.get("lull_off")), "charge_off": bool(s.get("charge_off")),
        "editable": s["state"] != ds.STATE_MATCHES_YOURS,
        "needs_review": bool(s.get("needs_review")),
    }
    # whether this sequence fires under the room's scene-change setting right
    # now (drop_firing.annotate, phase 5) — only present when `s` came from
    # annotated_view (_op_list); a sequence resolved off the plain, un-
    # annotated view (e.g. _pick's rejection payload) never had this checked,
    # so it must never be reported as a "does not fire" verdict here.
    if "fires" in s:
        out["fires"] = bool(s.get("fires"))
        out["fires_reason"] = s.get("fires_reason")
    return out


def _pick(view: dict, number: Any) -> tuple[Optional[dict], Optional[dict]]:
    seqs = _numbered(view)
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= len(seqs):
        return None, {"status": "rejected",
                      "reason": f"there is no drop sequence #{number} on this song "
                                f"(it has {len(seqs)})",
                      "sequences": [_describe(i + 1, s) for i, s in enumerate(seqs)]}
    s = seqs[number - 1]
    if s["state"] == ds.STATE_MATCHES_YOURS:
        return None, {"status": "rejected",
                      "reason": f"#{number} sits on your own charge/lull/drop triggers, so the "
                                "detection stands down — edit your triggers on the SPECTRA "
                                "triggers strip instead"}
    return s, None


#: One song's most recent SONIC-made edit — {"before": edits-before-it,
#: "rev_after": the rev it left}. In-memory only, same posture as
#: settings_agent._SESSIONS (a chat transcript / a one-step undo handle,
#: not a setting — a process restart clearing it is fine). This is what
#: lets undo_drop_edit put back exactly what SONIC itself last changed,
#: refusing (rather than clobbering) if the Timeline edited the song in
#: between — the same `expect` conflict guard /restore already enforces.
_LAST_SONIC_EDIT: dict[str, dict] = {}


def _edit(uri: str, op: str, **kw) -> dict:
    try:
        res = ds.apply_edit(uri, op, **kw)
    except (ds.SequenceNotFound, ds.InvalidEdit, ds.EditConflict) as exc:
        return {"status": "rejected", "reason": str(exc)}
    _LAST_SONIC_EDIT[uri] = {"before": res.before, "rev_after": ds.edits_rev(res.after)}
    return {"status": "applied", "result": res.result}


async def _op_list(uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    # annotated_view (not the plain ds.view) so `fires`/`fires_reason` — the
    # room's own phase-5 verdict — rides every sequence this returns; the
    # other handlers below still resolve a sequence off the plain view via
    # _pick, which only ever needs the key/times/state fields, not firing.
    view = await asyncio.to_thread(drop_firing.annotated_view, uri)
    seqs = _numbered(view)
    return {"status": "ok", "uri": uri, "detection": view.get("status"),
            "beat_s": _secs((view.get("song") or {}).get("beat_ms")),
            "sequences": [_describe(i + 1, s) for i, s in enumerate(seqs)],
            "summary": f"{len(seqs)} drop sequence{'s' if len(seqs) != 1 else ''} on this song"}


async def _op_confirm(sequence: Any, uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    if sequence == "all":
        out = await asyncio.to_thread(_edit, uri, "confirm_all")
        if out["status"] == "applied":
            n = len(out["result"] or [])
            out["summary"] = (f"confirmed {n} confident drop sequence{'s' if n != 1 else ''}"
                              if n else "no confident drop sequence was left to confirm")
        return out
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    out = await asyncio.to_thread(_edit, uri, "confirm", key=s["key"])
    if out["status"] == "applied":
        out["summary"] = f"confirmed drop sequence #{sequence} (drop at {_secs(s['drop_ms'])} s)"
    return out


async def _op_dismiss(sequence: Any, uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    out = await asyncio.to_thread(_edit, uri, "dismiss", key=s["key"])
    if out["status"] == "applied":
        what = "removed" if s["origin"] == "added" else "dismissed (not a drop)"
        out["summary"] = f"{what} drop sequence #{sequence} at {_secs(s['drop_ms'])} s"
    return out


async def _op_move(sequence: Any, handle: Literal["charge", "lull", "drop"],
                   by_beats: Optional[float] = None, to_seconds: Optional[float] = None,
                   uri: Optional[str] = None) -> dict:
    if handle not in HANDLE_CHOICES:
        return {"status": "rejected", "reason": "handle must be charge, lull or drop"}
    if (by_beats is None) == (to_seconds is None):
        return {"status": "rejected", "reason": "give exactly one of by_beats or to_seconds"}
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    at = s.get(f"{handle}_ms")
    if at is None:
        return {"status": "rejected", "reason": f"#{sequence} has no {handle} to move"}
    beat = float((view.get("song") or {}).get("beat_ms") or 500.0)
    try:
        target = (int(round(at + float(by_beats) * beat)) if by_beats is not None
                  else int(round(float(to_seconds) * 1000)))
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": "by_beats / to_seconds must be numbers"}
    out = await asyncio.to_thread(_edit, uri, "handles", key=s["key"], handles={handle: target})
    if out["status"] == "applied":
        out["summary"] = (f"moved the {handle} of drop sequence #{sequence} from "
                          f"{_secs(at)} s to {_secs(target)} s")
    return out


async def _op_add(drop_seconds: float, lull_seconds: Optional[float] = None,
                  charge_seconds: Optional[float] = None, uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    try:
        drop_ms = int(round(float(drop_seconds) * 1000))
        lull_ms = None if lull_seconds is None else int(round(float(lull_seconds) * 1000))
        charge_ms = None if charge_seconds is None else int(round(float(charge_seconds) * 1000))
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": "drop_seconds / lull_seconds / charge_seconds "
                                                "must be numbers"}
    out = await asyncio.to_thread(_edit, uri, "add", drop_ms=drop_ms,
                                  lull_ms=lull_ms, charge_ms=charge_ms)
    if out["status"] == "applied":
        out["summary"] = f"added a drop sequence at {_secs(drop_ms)} s"
    return out


async def _op_set_member(sequence: Any, handle: Literal["lull", "charge"], on: bool,
                         uri: Optional[str] = None) -> dict:
    if handle not in ("lull", "charge"):
        return {"status": "rejected", "reason": "handle must be lull or charge"}
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    currently_off = bool(s.get(f"{handle}_off"))
    currently_present = s.get(f"{handle}_ms") is not None
    if on:
        if currently_present and not currently_off:
            return {"status": "rejected", "reason": f"#{sequence} already has a {handle}"}
        if currently_off:
            out = await asyncio.to_thread(_edit, uri, "member", key=s["key"],
                                          handle=handle, off=False)
        else:
            # never there at all — place it by the detector's own rules
            # (the "＋ Lull / ＋ Charge" button's op), not a bare on/off flip.
            out = await asyncio.to_thread(_edit, uri, "fill", key=s["key"], handle=handle)
        if out["status"] == "applied":
            out["summary"] = f"added a {handle} to drop sequence #{sequence}"
        return out
    if currently_off or not currently_present:
        return {"status": "rejected", "reason": f"#{sequence} has no {handle} to switch off"}
    out = await asyncio.to_thread(_edit, uri, "member", key=s["key"], handle=handle, off=True)
    if out["status"] == "applied":
        out["summary"] = f"switched the {handle} off on drop sequence #{sequence}"
    return out


async def _op_revert(sequence: Any, uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    out = await asyncio.to_thread(_edit, uri, "revert", key=s["key"])
    if out["status"] == "applied":
        out["summary"] = f"drop sequence #{sequence} is back to detected"
    return out


async def _op_review(sequence: Any, choice: Literal["keep", "take"],
                     uri: Optional[str] = None) -> dict:
    if choice not in ("keep", "take"):
        return {"status": "rejected", "reason": "choice must be keep or take"}
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    out = await asyncio.to_thread(_edit, uri, "review", key=s["key"], choice=choice)
    if out["status"] == "applied":
        out["summary"] = (f"kept your place for drop sequence #{sequence}" if choice == "keep"
                          else f"moved drop sequence #{sequence} to where the analysis now finds it")
    return out


async def _op_undo(uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    tracked = _LAST_SONIC_EDIT.get(uri)
    if tracked is None:
        return {"status": "rejected",
                "reason": "nothing to undo for this song — Sonic hasn't edited its "
                         "drop sequences yet"}
    try:
        res = await asyncio.to_thread(
            ds.apply_edit, uri, "restore", edits=tracked["before"], expect=tracked["rev_after"])
    except (ds.SequenceNotFound, ds.InvalidEdit, ds.EditConflict) as exc:
        return {"status": "rejected", "reason": str(exc)}
    _LAST_SONIC_EDIT.pop(uri, None)
    return {"status": "applied", "result": res.result,
            "summary": "undid the last drop-sequence edit Sonic made to this song"}


async def _op_redetect(uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    result = await asyncio.to_thread(ds.ensure_detected, uri, force=True)
    if result.get("status") == "unavailable":
        return {"status": "rejected", "reason": result.get("reason") or "could not re-detect"}
    n = result.get("sequences")
    return {"status": "applied", "result": result,
            "summary": (f"re-detected drops on this song — {n} sequence"
                        f"{'s' if n != 1 else ''}" if n is not None
                        else "this song's drop detection is already current")}


async def _op_summary() -> dict:
    data = await asyncio.to_thread(ds.summary)
    songs = data.get("songs") or []
    return {"status": "ok", "songs": songs,
            "summary": f"{len(songs)} song{'s' if len(songs) != 1 else ''} with drop data"}


async def _op_explain_switch(sequence: Any = None, uri: Optional[str] = None) -> dict:
    """THE DROP-LED SCENE SWITCH, read only (spectra/services/drop_switch.py):
    why a drop sequence did — or did not — change the scene this play. The
    decision is made by the trigger clock when it reaches the sequence, so
    a sequence the song has not reached yet says so rather than guessing."""
    from spectra.services import drop_switch
    from spectra.services.room_controls import load_room_controls
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    numbered = _numbered(view)
    number_of = {s["key"]: i + 1 for i, s in enumerate(numbered)}
    settings = drop_switch.SwitchSettings.from_room(load_room_controls())

    def row(p) -> dict:
        d = p.as_dict()
        return {"number": number_of.get(p.key), "drop_s": _secs(p.drop_ms),
                "switched": bool(p.switch), "why": p.sentence,
                "from_scene": p.from_scene_name, "to_scene": p.to_scene_name,
                "moment": p.moment, "handoff": p.handoff,
                "stale_by": d["stale_by"], "cut_s": _secs(d["cut_ms"]),
                # the fireworks melds' late cut: what releases it
                "release_by": p.release_by,
                "outcome": p.outcome}

    plans = drop_switch.plans_for(uri)
    out = {"status": "ok", "settings": {
        "enabled": settings.enabled,
        "after_previous_drop": settings.after_previous_drop,
        "stale_margin_s": settings.stale_margin_s,
        "drops_in_a_row": settings.drops_in_a_row,
        "swallow_delay_s": settings.swallow_delay_s,
        "hit_threshold": settings.hit_threshold}}
    if sequence is not None:
        if (not isinstance(sequence, int) or isinstance(sequence, bool)
                or not 1 <= sequence <= len(numbered)):
            return {"status": "rejected",
                    "reason": f"there is no drop sequence #{sequence} on this song "
                              f"(it has {len(numbered)})",
                    "sequences": [_describe(i + 1, x) for i, x in enumerate(numbered)]}
        key = numbered[sequence - 1]["key"]
        hit = next((p for p in plans if p.key == key), None)
        out["decision"] = None if hit is None else row(hit)
        out["summary"] = (hit.sentence if hit is not None else
                          f"#{sequence} has not been reached this play yet — the switch "
                          "is decided when the song gets to its charge.")
        return out
    out["decisions"] = [row(p) for p in plans]
    n = sum(1 for p in plans if p.switch)
    out["summary"] = (f"{len(plans)} drop sequence{'s' if len(plans) != 1 else ''} decided "
                      f"this play, {n} changed the scene" if plans
                      else "no drop sequence has been reached on this song this play")
    return out


_URI = {"type": "string", "description": "A spotify:track: URI; omit for the song playing now."}
_SEQ = {"type": "integer", "minimum": 1,
        "description": "The sequence's number in song order (#1 is the earliest), as "
                       "list_drop_sequences gives it."}

OPERATIONS: dict[str, SonicOperation] = {
    "list_drop_sequences": SonicOperation(
        name="list_drop_sequences", domain="drops", kind="read",
        summary="List the drop sequences (charge → lull → drop) on the playing song, numbered "
                "in song order, with their state, times, and whether each fires right now.",
        instructions=(
            "Call first whenever he talks about the drops on a song, so you can name them by "
            "number. States: confident / suggested (detected), confirmed / edited / added "
            "(his), matches_yours (sits on his own triggers — not editable here). "
            "lull_off/charge_off say whether an existing lull/charge is switched off (vs. "
            "never placed at all) — check these before set_drop_member. fires/fires_reason "
            "say whether this sequence actually fires under the room's current scene-change "
            "setting (e.g. dismissed, waits_for_confirm, matches_yours, transitions_only, "
            "analysed_show_off, his, analysed_show) — a sequence can be confirmed/edited here "
            "and still not fire if the room's tier doesn't reach it."),
        input_schema={"type": "object", "properties": {"uri": _URI}, "additionalProperties": False},
        handler=_op_list),
    "confirm_drop_sequence": SonicOperation(
        name="confirm_drop_sequence", domain="drops", kind="write",
        summary="Confirm a drop sequence by its number, or every confident one on the song "
                "(sequence=\"all\").",
        instructions=(
            "Use when he says a drop is right, or 'confirm every drop on this song' "
            "(sequence=\"all\" confirms the confident ones only — suggestions need him to name "
            "them). A confirm survives re-analysis. He can undo it on the Timeline with "
            "'Back to detected'."),
        input_schema={"type": "object", "properties": {
            "sequence": {"oneOf": [_SEQ, {"type": "string", "enum": ["all"]}]}, "uri": _URI},
            "required": ["sequence"], "additionalProperties": False},
        handler=_op_confirm),
    "dismiss_drop_sequence": SonicOperation(
        name="dismiss_drop_sequence", domain="drops", kind="write",
        summary="'Not a drop' — dismiss a drop sequence by its number (removes one he added).",
        instructions=(
            "Use when he says a detected drop is not a drop. It is hidden and never offered "
            "again within two beats of there. One at a time; read the list first."),
        input_schema={"type": "object", "properties": {"sequence": _SEQ, "uri": _URI},
                      "required": ["sequence"], "additionalProperties": False},
        handler=_op_dismiss),
    "move_drop_handle": SonicOperation(
        name="move_drop_handle", domain="drops", kind="write",
        summary="Move the charge, lull or drop of a drop sequence by a number of beats "
                "(negative = earlier) or to a time in seconds.",
        instructions=(
            "'Move the second drop one beat earlier' = sequence=2, handle='drop', "
            "by_beats=-1. Give exactly one of by_beats or to_seconds. His time always wins "
            "over the analysis afterwards; order is kept (charge before lull before drop, "
            "200 ms apart) and a move that breaks it is refused with the reason."),
        input_schema={"type": "object", "properties": {
            "sequence": _SEQ,
            "handle": {"type": "string", "enum": list(HANDLE_CHOICES)},
            "by_beats": {"type": "number"},
            "to_seconds": {"type": "number", "minimum": 0},
            "uri": _URI},
            "required": ["sequence", "handle"], "additionalProperties": False},
        handler=_op_move),
    "add_drop_sequence": SonicOperation(
        name="add_drop_sequence", domain="drops", kind="write",
        summary="Add a drop sequence of his own at a time in seconds — a "
                "missing lull/charge is placed by the detector's own "
                "rules where there's room for one.",
        instructions=(
            "drop_seconds is where the drop itself lands. Give "
            "lull_seconds/charge_seconds only to pin them yourself; "
            "otherwise the detector places them (and leaves one out "
            "rather than overlap the drop before it)."),
        input_schema={"type": "object", "properties": {
            "drop_seconds": {"type": "number", "minimum": 0},
            "lull_seconds": {"type": "number", "minimum": 0},
            "charge_seconds": {"type": "number", "minimum": 0},
            "uri": _URI},
            "required": ["drop_seconds"], "additionalProperties": False},
        handler=_op_add),
    "set_drop_member": SonicOperation(
        name="set_drop_member", domain="drops", kind="write",
        summary="Switch a drop sequence's lull or charge off, back on, or "
                "add one that was never there (on=true when it has none "
                "at all places it by the detector's own rules).",
        instructions=(
            "Call list_drop_sequences first — lull_off/charge_off there "
            "say which handles are currently switched off, so you don't "
            "have to ask. on=false needs a handle that currently exists "
            "and isn't already off; on=true either turns a switched-off "
            "one back on or, if there was never one at all, adds it "
            "(the same placement move_drop_handle and add_drop_sequence "
            "use — refused if there's no room before the drop/lull)."),
        input_schema={"type": "object", "properties": {
            "sequence": _SEQ,
            "handle": {"type": "string", "enum": ["lull", "charge"]},
            "on": {"type": "boolean"},
            "uri": _URI},
            "required": ["sequence", "handle", "on"], "additionalProperties": False},
        handler=_op_set_member),
    "revert_drop_sequence": SonicOperation(
        name="revert_drop_sequence", domain="drops", kind="write",
        summary="'Back to detected' — forget every edit made to one drop "
                "sequence's detection (a confirm, a move, a switched-off "
                "member).",
        instructions="Does not remove a sequence HE added — that's "
                    "dismiss_drop_sequence. Only clears edits to a DETECTED one.",
        input_schema={"type": "object", "properties": {"sequence": _SEQ, "uri": _URI},
                      "required": ["sequence"], "additionalProperties": False},
        handler=_op_revert),
    "resolve_drop_review": SonicOperation(
        name="resolve_drop_review", domain="drops", kind="write",
        summary="Answer a sequence's 'needs review' flag after a "
                "re-detection moved it: keep his place, or take the "
                "analysis's new one.",
        instructions=(
            "list_drop_sequences' needs_review flag says which sequences "
            "are asking. choice='keep' pins his times as they were; "
            "'take' moves his sequence to where the analysis puts it now "
            "(his confirm and any switched-off member survive either way)."),
        input_schema={"type": "object", "properties": {
            "sequence": _SEQ, "choice": {"type": "string", "enum": ["keep", "take"]},
            "uri": _URI},
            "required": ["sequence", "choice"], "additionalProperties": False},
        handler=_op_review),
    "undo_drop_edit": SonicOperation(
        name="undo_drop_edit", domain="drops", kind="write",
        summary="Undo the single most recent drop-sequence edit SONIC "
                "made on this song.",
        instructions=(
            "Only ever undoes an edit Sonic itself just made on this "
            "song in this process — if he's since edited the same song "
            "on the Timeline, this is refused (nothing is undone) rather "
            "than overwriting his own later change."),
        input_schema={"type": "object", "properties": {"uri": _URI},
                      "additionalProperties": False},
        handler=_op_undo),
    "redetect_drop_sequences": SonicOperation(
        name="redetect_drop_sequences", domain="drops", kind="write",
        summary="Re-run drop detection on this song right now.",
        instructions="His edits (confirms, moves, added/dismissed "
                    "sequences) are never touched by a re-detection.",
        input_schema={"type": "object", "properties": {"uri": _URI},
                      "additionalProperties": False},
        handler=_op_redetect),
    "explain_drop_switch": SonicOperation(
        name="explain_drop_switch", domain="drops", kind="read",
        summary="Why a drop sequence did — or did not — change the scene this play (the "
                "drop-led scene switch), or every decision on the song so far.",
        instructions=(
            "Read only. Use for 'why did the scene change on that drop', 'why did it stay "
            "on Fish', 'when does a drop switch'. Give sequence (its number from "
            "list_drop_sequences) for one, omit it for every decision this play. A drop "
            "switches with a hard cut ON the drop when the scene showing is stale (it "
            "played the previous drop, carried drops_in_a_row drops, or overstayed its "
            "dwell by stale_margin_s); early, at the charge or on a flare inside it, only "
            "when there is no good drop hand-off or it has overstayed. Leaving Fireworks, "
            "Fireworks plays its own drop first: into the Black Hole the cut lands "
            "swallow_delay_s later; into Fish/Orbits/Squiggles/STAR on the next analysed "
            "flare at least hit_threshold strong (release_by 'hit'), else at a deadline. "
            "Into Fireworks from Fish/Orbits, three keepers burst where they stand. The "
            "thresholds are ordinary settings (drop_switch_*) — change them with "
            "set_setting, not here."),
        input_schema={"type": "object", "properties": {"sequence": _SEQ, "uri": _URI},
                      "additionalProperties": False},
        handler=_op_explain_switch),
    "drop_detection_summary": SonicOperation(
        name="drop_detection_summary", domain="drops", kind="read",
        summary="How many songs have drop detection, and how many of his "
                "edits each one carries — a library-wide count, not one song.",
        instructions="Use for 'how many songs have drops detected' — for "
                    "one song's own sequences, call list_drop_sequences instead.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_summary),
}
