"""THE DROPS DOMAIN — Sonic's operations over the playing song's drop
sequences (drop-detection plan, phase 4; report section 10's "talk to it":
"confirm every drop on this song", "move the second drop one beat
earlier", "no drops on this song").

Every write goes through spectra/services/drop_sequences.py's own
`apply_edit` — the same edits the Timeline's buttons make, never a second
write path — so the "How edits are kept" rules hold here exactly as there.
Nothing here fires anything (phase 5).

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

from spectra.services import drop_sequences as ds
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
    return {
        "number": n, "state": s["state"],
        "drop_s": _secs(s["drop_ms"]), "lull_s": _secs(s.get("lull_ms")),
        "charge_s": _secs(s.get("charge_ms")),
        "editable": s["state"] != ds.STATE_MATCHES_YOURS,
        "needs_review": bool(s.get("needs_review")),
    }


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


def _edit(uri: str, op: str, **kw) -> dict:
    try:
        res = ds.apply_edit(uri, op, **kw)
    except (ds.SequenceNotFound, ds.InvalidEdit, ds.EditConflict) as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied", "result": res.result}


async def _op_list(uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
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


_URI = {"type": "string", "description": "A spotify:track: URI; omit for the song playing now."}
_SEQ = {"type": "integer", "minimum": 1,
        "description": "The sequence's number in song order (#1 is the earliest), as "
                       "list_drop_sequences gives it."}

OPERATIONS: dict[str, SonicOperation] = {
    "list_drop_sequences": SonicOperation(
        name="list_drop_sequences", domain="drops", kind="read",
        summary="List the drop sequences (charge → lull → drop) on the playing song, numbered "
                "in song order, with their state and times.",
        instructions=(
            "Call first whenever he talks about the drops on a song, so you can name them by "
            "number. States: confident / suggested (detected), confirmed / edited / added "
            "(his), matches_yours (sits on his own triggers — not editable here). Nothing "
            "detected fires yet."),
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
}
