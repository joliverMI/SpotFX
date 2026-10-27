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
but not edited by the older operations: his triggers are edited on the
SPECTRA triggers strip.

THE HOME DROPS PANEL'S OWN REACH (2026-10-26, predrop plan step 1 —
spectra/services/drop_panel.py is the binding statement): "approve drop
2" (approve_drop_sequence, the double tick), "turn off the lull on drop 3"
(set_drop_part, a part's toggle — the drop itself included), "remove drop
1" (remove_drop_sequence), and "turn drop testing on" (the ordinary
`drop_testing` setting, set_setting). His OWN drops are reached either
through the detection that stands in for one (its number) or by the time
of his drop (`your_drop_s`, the listing's `yours`). Because those writes
can DELETE triggers he placed by hand (the Admiral's answer 6: placed by
hand → deleted, imported → switched off), every one that could ASKS FIRST:
the first call writes nothing and answers `needs_confirmation`, what would
happen in words and a single-use `confirm_id` (absorb_console.py's two-call
protocol); only a second call with that id, made after he says yes, acts.
The id is bound to the operation, its arguments and the row's triggers as
they were when he was asked, so a yes never covers a request that changed.
"""
from __future__ import annotations

import asyncio
import json as _json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from spectra.services import drop_firing, drop_panel, drop_sequences as ds
from spectra.services.sonic_ops import SonicOperation

HANDLE_CHOICES = ("charge", "lull", "drop")
PART_CHOICES = ("charge", "lull", "pre_drop", "drop")
PRE_DROP_PLACES = ("detected", "rules", "off", "on")
PRE_DROP_KINDS = ("spike", "intro")


def _pre_drop_brief(pre: Optional[dict]) -> Optional[dict]:
    """A pre-drop as the listing names it: its time, kind, state and the
    detector's confidence (drop_sequences.py's PRE-DROPS)."""
    if not pre:
        return None
    at = pre.get("ms") if not pre.get("off") else pre.get("was")
    out = {"at_s": _secs(at), "kind": pre.get("kind"), "off": bool(pre.get("off")),
           "placed_by_you": bool(pre.get("moved"))}
    if pre.get("tier"):
        out["tier"] = pre["tier"]
    if pre.get("part"):
        out["part"] = pre["part"]
    return out


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
    # the Drops panel's per-part states (drop_sequences.py's PARTS):
    # on / waiting / off / absent for charge, lull, pre_drop and drop
    if s.get("parts"):
        out["parts"] = dict(s["parts"])
    pre = _pre_drop_brief({"ms": s.get("pre_drop_ms"), "was": s.get("pre_drop_was"),
                           "kind": s.get("pre_drop_kind"), "off": s.get("pre_drop_off"),
                           "moved": (s.get("moved") or {}).get("pre_drop"),
                           "tier": s.get("pre_drop_tier")}
                          if s.get("pre_drop_kind") else None)
    if pre:
        out["pre_drop"] = pre
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
    _LAST_SONIC_EDIT[uri] = {"before": res.before, "rev_after": ds.edits_rev(res.after),
                             "profile": []}
    return {"status": "applied", "result": res.result}


async def _panel(uri: str, write) -> dict:
    """One drop_panel write, remembered for undo_drop_edit (its profile rows
    too)."""
    try:
        res = await write
    except (ds.SequenceNotFound, ds.InvalidEdit, ds.EditConflict) as exc:
        return {"status": "rejected", "reason": str(exc)}
    except drop_panel.ProfileRefused as exc:
        return {"status": "rejected", "reason": exc.detail}
    except drop_panel.ProfileUnavailable as exc:
        return {"status": "rejected", "reason": str(exc)}
    _LAST_SONIC_EDIT[uri] = {"before": res.before, "rev_after": ds.edits_rev(res.after),
                             "profile": list(res.profile)}
    return {"status": "applied", "result": res.result, "said": res.said}


async def _op_list(uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    # annotated_view (not the plain ds.view) so `fires`/`fires_reason` — the
    # room's own phase-5 verdict — rides every sequence this returns; the
    # other handlers below still resolve a sequence off the plain view via
    # _pick, which only ever needs the key/times/state fields, not firing.
    def read() -> dict:
        # off the loop, so his own drops' pre-drops are worked out too
        from spectra.services import trigger_store
        triggers = trigger_store.list_for_song(uri)
        return drop_firing.annotated_view(
            uri, view=ds.view(uri, triggers=triggers, compute_pre_drops=True),
            triggers=triggers)
    view = await asyncio.to_thread(read)
    seqs = _numbered(view)
    number_of = {s["key"]: i + 1 for i, s in enumerate(seqs)}
    yours = [{"drop_s": _secs(r["drop"]["timestamp_ms"]),
              "lull_s": _secs((r.get("lull") or {}).get("timestamp_ms")),
              "charge_s": _secs((r.get("charge") or {}).get("timestamp_ms")),
              "enabled": bool(r.get("enabled")),
              "switched_off": [h for h in HANDLE_CHOICES
                               if r.get(h) and not r[h].get("enabled")],
              "stands_for": [number_of[k] for k in r.get("detections") or []
                             if k in number_of],
              "pre_drop": _pre_drop_brief(r.get("pre_drop"))}
             for r in view.get("yours") or []]
    return {"status": "ok", "uri": uri, "detection": view.get("status"),
            "beat_s": _secs((view.get("song") or {}).get("beat_ms")),
            "testing": bool((view.get("firing") or {}).get("testing")),
            "sequences": [_describe(i + 1, s) for i, s in enumerate(seqs)],
            "yours": yours,
            "summary": f"{len(seqs)} drop sequence{'s' if len(seqs) != 1 else ''} on this song"
                       + (f", {len(yours)} drop{'s' if len(yours) != 1 else ''} of yours"
                          if yours else "")}


# ── the Home Drops panel's reach (module docstring) ─────────────────────────

CONFIRM_TTL_S = 300.0
_PENDING_MAX = 50


@dataclass
class _Ask:
    op: str
    fingerprint: str
    expires: float


_PENDING: dict[str, _Ask] = {}
#: injectable for tests
_clock: Callable[[], float] = time.monotonic


def _ask(op: str, fingerprint: str, question: str, **extra: Any) -> dict:
    now = _clock()
    for k in [k for k, a in _PENDING.items() if a.expires <= now]:
        del _PENDING[k]
    while len(_PENDING) >= _PENDING_MAX:
        del _PENDING[next(iter(_PENDING))]
    cid = uuid.uuid4().hex[:12]
    _PENDING[cid] = _Ask(op, fingerprint, now + CONFIRM_TTL_S)
    return {"status": "needs_confirmation", "op": op, "confirm_id": cid,
            "question": question,
            "reason": f"Not done yet — this needs his yes first. {question}",
            "expires_in_s": int(CONFIRM_TTL_S), **extra}


def _redeem(op: str, fingerprint: str, confirm_id: Any) -> Optional[dict]:
    """None when `confirm_id` is the live answer to exactly this question;
    otherwise the rejection. Used up either way."""
    a = _PENDING.pop(confirm_id, None) if isinstance(confirm_id, str) else None
    if a is None or a.op != op:
        return {"status": "rejected",
                "reason": "that confirm_id is not one this operation handed out, or it was "
                          "already used — call it again without one and ask him"}
    if a.expires <= _clock():
        return {"status": "rejected",
                "reason": "that confirmation expired — call it again without a confirm_id "
                          "and ask him again"}
    if a.fingerprint != fingerprint:
        return {"status": "rejected",
                "reason": "something changed since he was asked (the request, or his "
                          "triggers on this drop), so his yes no longer covers it — ask him "
                          "again"}
    return None


def _pick_any(view: dict, number: Any) -> tuple[Optional[dict], Optional[dict]]:
    """`_pick`, but a sequence standing in for one of his drops is allowed:
    the caller reaches his drop through it."""
    seqs = _numbered(view)
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= len(seqs):
        return None, {"status": "rejected",
                      "reason": f"there is no drop sequence #{number} on this song "
                                f"(it has {len(seqs)})",
                      "sequences": [_describe(i + 1, s) for i, s in enumerate(seqs)]}
    return seqs[number - 1], None


def _target(view: dict, sequence: Any, your_drop_s: Any
            ) -> tuple[Optional[str], Optional[dict], Optional[dict], Optional[dict]]:
    """(key, sequence view or None, his row or None, rejection)."""
    rows = view.get("yours") or []
    if your_drop_s is not None:
        try:
            at = float(your_drop_s) * 1000.0
        except (TypeError, ValueError):
            return None, None, None, {"status": "rejected",
                                      "reason": "your_drop_s must be a number of seconds"}
        near = sorted((abs(r["drop"]["timestamp_ms"] - at), i) for i, r in enumerate(rows))
        if not near or near[0][0] > 1000:
            return None, None, None, {
                "status": "rejected",
                "reason": f"none of your own drops is within a second of {your_drop_s} s",
                "yours": [_secs(r["drop"]["timestamp_ms"]) for r in rows]}
        row = rows[near[0][1]]
        return row["key"], None, row, None
    if sequence is None:
        return None, None, None, {"status": "rejected",
                                  "reason": "name the drop: its sequence number from "
                                            "list_drop_sequences, or your_drop_s for one "
                                            "of your own drops"}
    s, rej = _pick_any(view, sequence)
    if rej:
        return None, None, None, rej
    if s["state"] == ds.STATE_MATCHES_YOURS:
        row = next((r for r in rows if s["key"] in (r.get("detections") or [])), None)
        if row is None:
            return None, None, None, {
                "status": "rejected",
                "reason": f"#{sequence} sits on your own triggers, but they are not "
                          "grouped into a drop of yours — edit them on the SPECTRA "
                          "triggers strip"}
        return row["key"], s, row, None
    return s["key"], s, None, None


def _row_fp(op: str, args: dict, row: dict) -> str:
    members = {h: (row.get(h) or {}).get("id") and
               [row[h]["id"], bool(row[h].get("enabled"))] for h in HANDLE_CHOICES}
    return _json.dumps({"op": op, "args": args, "row": members}, sort_keys=True, default=str)


def _what_happens(row: dict, prov: dict, parts: tuple[str, ...]) -> list[str]:
    by_id = {t.get("id"): t for t in prov.get("triggers") or []}
    words = []
    for h in parts:
        m = row.get(h)
        if not m or not m.get("enabled"):
            continue
        t = by_id.get(m["id"]) or {}
        at = _secs(m["timestamp_ms"])
        if t.get("remove_would") == "delete":
            words.append(f"delete your {h} at {at} s (you placed it by hand)")
        elif t.get("remove_would") == "disable":
            words.append(f"switch off your {h} at {at} s (imported, so it stays in "
                         "your song, off)")
        else:                              # not named: never guessed either way
            words.append(f"take out your {h} at {at} s (deleted if you placed it by "
                         "hand, switched off if it was imported)")
    return words


async def _provenance(uri: str) -> tuple[Optional[dict], Optional[dict]]:
    """(the merged provenance, None) or (None, a rejection): Sonic asks
    first, so a question it cannot answer truthfully is refused."""
    try:
        prov = await drop_panel.panel_provenance(uri)
    except drop_panel.ProfileRefused as exc:
        return None, {"status": "rejected", "reason": f"cannot say what would happen: {exc}"}
    if prov.get("status") == "unknown":
        return None, {"status": "rejected",
                      "reason": f"cannot say what would happen: {prov.get('reason')}"}
    return prov, None


async def _op_approve(sequence: Any, uri: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    s, rej = _pick(view, sequence)
    if rej:
        return rej
    out = await _panel(uri, drop_panel.approve(uri, s["key"]))
    if out["status"] == "applied":
        out["summary"] = (f"approved drop sequence #{sequence} (drop at "
                          f"{_secs(s['drop_ms'])} s): every part that is not off now plays")
    return out


async def _op_set_part(part: Literal["charge", "lull", "pre_drop", "drop"], on: bool,
                       sequence: Any = None, your_drop_s: Any = None,
                       uri: Optional[str] = None, confirm_id: Optional[str] = None) -> dict:
    if part not in PART_CHOICES:
        return {"status": "rejected", "reason": "part must be charge, lull, pre_drop or drop"}
    if not isinstance(on, bool):
        return {"status": "rejected", "reason": "on must be true or false"}
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    key, s, row, rej = _target(view, sequence, your_drop_s)
    if rej:
        return rej
    value = ds.PART_ON if on else ds.PART_OFF
    if row is not None and not on and part != ds.PRE_DROP:
        # (his pre-drop is not one of his triggers: switching it off changes
        # nothing in his song profile, so it needs no question)
        member = row.get(part)
        if not member or not member.get("enabled"):
            return {"status": "rejected", "reason": f"that drop of yours has no {part} "
                                                    "switched on"}
        prov, rej = await _provenance(uri)
        if rej:
            return rej
        fp = _row_fp("set_drop_part", {"key": key, "part": part, "on": on}, row)
        if confirm_id is None:
            words = _what_happens(row, prov, (part,))
            return _ask("set_drop_part", fp,
                        f"This would {words[0] if words else 'change your ' + part}"
                        + (" and stop the detection standing in for it from playing"
                           if row.get("detections") else "") + ". Go ahead?")
        refusal = _redeem("set_drop_part", fp, confirm_id)
        if refusal:
            return refusal
    out = await _panel(uri, drop_panel.set_parts(uri, key, {part: value}))
    if out["status"] == "applied":
        where = (f"your drop at {_secs(row['drop']['timestamp_ms'])} s" if row is not None
                 else f"drop sequence #{sequence}")
        out["summary"] = (f"{part.replace('_', '-')} {'approved' if on else 'switched off'} "
                          f"on {where}"
                          + (f" — {out['said']}" if out.get("said") else ""))
    return out


async def _pre_drop_target(view: dict, sequence: Any, your_drop_s: Any
                           ) -> tuple[Optional[str], Optional[int], str, Optional[dict]]:
    """(key, the moment its drop fires, how to name it, rejection)."""
    key, s, row, rej = _target(view, sequence, your_drop_s)
    if rej:
        return None, None, "", rej
    if row is not None:
        drop_ms = int(row["drop"]["timestamp_ms"])
        return key, drop_ms, f"your drop at {_secs(drop_ms)} s", None
    return key, int(s["drop_ms"]), f"drop sequence #{sequence}", None


async def _op_set_pre_drop(sequence: Any = None, your_drop_s: Any = None,
                           at_seconds: Any = None, before_drop_ms: Any = None,
                           place: Optional[str] = None, uri: Optional[str] = None) -> dict:
    given = [x for x in (at_seconds, before_drop_ms, place) if x is not None]
    if len(given) != 1:
        return {"status": "rejected",
                "reason": "give exactly one of at_seconds, before_drop_ms or place"}
    if place is not None and place not in PRE_DROP_PLACES:
        return {"status": "rejected", "reason": f"place must be one of {PRE_DROP_PLACES}"}
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    key, drop_ms, where, rej = await _pre_drop_target(view, sequence, your_drop_s)
    if rej:
        return rej
    if place == "detected":
        write = drop_panel.move_handles(uri, key, {ds.PRE_DROP: None})
        words = f"the pre-drop of {where} is back where the detector puts it"
    elif place == "rules":
        write = drop_panel.pre_drop_fill(uri, key)
        words = f"added a pre-drop to {where}, where the rules put it"
    elif place in ("off", "on"):
        write = drop_panel.pre_drop_member(uri, key, place == "off")
        words = f"switched the pre-drop of {where} {place}"
    else:
        try:
            ms = (int(round(float(at_seconds) * 1000)) if at_seconds is not None
                  else int(drop_ms) - int(round(float(before_drop_ms))))
        except (TypeError, ValueError):
            return {"status": "rejected",
                    "reason": "at_seconds / before_drop_ms must be numbers"}
        write = drop_panel.move_handles(uri, key, {ds.PRE_DROP: ms})
        words = (f"moved the pre-drop of {where} to {_secs(ms)} s "
                 f"({_secs(int(drop_ms) - ms)} s before its drop)")
    out = await _panel(uri, write)
    if out["status"] == "applied":
        out["summary"] = words
    return out


async def _op_switch_pre_drop(kind: str, sequence: Any = None, your_drop_s: Any = None,
                              uri: Optional[str] = None) -> dict:
    if kind not in PRE_DROP_KINDS:
        return {"status": "rejected", "reason": "kind must be spike or intro"}
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    key, _drop_ms, where, rej = await _pre_drop_target(view, sequence, your_drop_s)
    if rej:
        return rej
    out = await _panel(uri, drop_panel.pre_drop_kind(uri, key, kind))
    if out["status"] == "applied":
        out["summary"] = (f"the pre-drop of {where} is now "
                          f"{'a spike' if kind == 'spike' else 'a vocal intro'}")
    return out


async def _op_remove(sequence: Any = None, your_drop_s: Any = None,
                     uri: Optional[str] = None, confirm_id: Optional[str] = None) -> dict:
    uri, rej = _song(uri)
    if rej:
        return rej
    view = await asyncio.to_thread(ds.view, uri)
    key, s, row, rej = _target(view, sequence, your_drop_s)
    if rej:
        return rej
    if row is not None:
        prov, rej = await _provenance(uri)
        if rej:
            return rej
        words = _what_happens(row, prov, HANDLE_CHOICES)
        if row.get("detections"):
            words.append(f"dismiss the detection{'s' if len(row['detections']) != 1 else ''} "
                         "standing in for it")
        fp = _row_fp("remove_drop_sequence", {"key": key}, row)
        question = ("Removing your drop at "
                    f"{_secs(row['drop']['timestamp_ms'])} s would "
                    + ("; ".join(words) if words else "change nothing") + ". Go ahead?")
    else:
        what = ("delete the drop you added" if s["origin"] == "added"
                else "dismiss it as not a drop (it is never offered again there)")
        fp = _json.dumps({"op": "remove_drop_sequence", "key": key,
                          "state": s["state"]}, sort_keys=True)
        question = (f"Removing drop sequence #{sequence} at {_secs(s['drop_ms'])} s would "
                    f"{what}. Go ahead?")
    if confirm_id is None:
        return _ask("remove_drop_sequence", fp, question)
    refusal = _redeem("remove_drop_sequence", fp, confirm_id)
    if refusal:
        return refusal
    out = await _panel(uri, drop_panel.remove(uri, key))
    if out["status"] == "applied":
        out["summary"] = f"removed it — {out.get('said') or 'done'}"
    return out


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
        if tracked.get("profile"):
            # one of his own drops: its song-profile rows go back too, in
            # the same step (drop_panel.py's ONE UNDO STEP)
            res = await drop_panel.restore(uri, tracked["before"], tracked["rev_after"],
                                           drop_panel._reverse(tracked["profile"]))
        else:
            res = await asyncio.to_thread(
                ds.apply_edit, uri, "restore", edits=tracked["before"],
                expect=tracked["rev_after"])
    except (ds.SequenceNotFound, ds.InvalidEdit, ds.EditConflict) as exc:
        return {"status": "rejected", "reason": str(exc)}
    except drop_panel.ProfileRefused as exc:
        return {"status": "rejected", "reason": exc.detail}
    except drop_panel.ProfileUnavailable as exc:
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
            "analysed_show_off, his, analysed_show, switched_off, testing) — a sequence can "
            "be confirmed/edited here and still not fire if the room's tier doesn't reach it. "
            "parts gives each part's state (on / waiting / off / absent); `yours` lists his "
            "OWN drops (by time, with the numbers of any detection standing in for each); "
            "testing says whether drop testing is on (every detected drop plays, approved "
            "or not — the setting drop_testing)."),
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
    "approve_drop_sequence": SonicOperation(
        name="approve_drop_sequence", domain="drops", kind="write",
        summary="Approve a drop sequence by its number — the Drops panel's double tick: "
                "its charge, lull, pre-drop and drop all approved (every part not off).",
        instructions=(
            "'Approve drop 2' = sequence=2. A part he switched off stays off (tap it with "
            "set_drop_part to bring it back). A drop of his own needs no approval. "
            "undo_drop_edit puts it back."),
        input_schema={"type": "object", "properties": {"sequence": _SEQ, "uri": _URI},
                      "required": ["sequence"], "additionalProperties": False},
        handler=_op_approve),
    "set_drop_part": SonicOperation(
        name="set_drop_part", domain="drops", kind="write",
        summary="Approve or switch off one part of a drop — its charge, its lull, its "
                "pre-drop or the drop itself (the Drops panel's toggles).",
        instructions=(
            "on=true approves the part (it plays, with its drop); on=false switches it off "
            "(never plays, not even with drop testing on). Switching the DROP off keeps "
            "the sequence listed but silent — that is not removing it. Name a detection by "
            "its number (list_drop_sequences), or one of HIS OWN drops by your_drop_s (its "
            "time, from the listing's `yours`) or by the number of the detection standing "
            "in for it. On his own drop, on=false DELETES a trigger he placed by hand and "
            "switches off an imported one, so it asks first: tell him the question it "
            "answers, and only after he says yes call it again with the same arguments "
            "plus confirm_id (a pre-drop never asks: it is not one of his triggers). To "
            "add a lull or charge that was never there, use set_drop_member; a pre-drop, "
            "set_pre_drop with place='rules'. Nothing plays from a pre-drop yet."),
        input_schema={"type": "object", "properties": {
            "part": {"type": "string", "enum": list(PART_CHOICES)},
            "on": {"type": "boolean"},
            "sequence": _SEQ,
            "your_drop_s": {"type": "number", "minimum": 0,
                            "description": "the time of one of his own drops, in seconds"},
            "uri": _URI,
            "confirm_id": {"type": "string"}},
            "required": ["part", "on"], "additionalProperties": False},
        handler=_op_set_part),
    "set_pre_drop": SonicOperation(
        name="set_pre_drop", domain="drops", kind="write",
        summary="Place, move, switch off or on, or add a drop's pre-drop (the hit or vocal "
                "entry just before the drop).",
        instructions=(
            "Exactly one of: at_seconds (a song time), before_drop_ms (how far before its "
            "drop, e.g. 800), or place: 'detected' (back where the detector puts it), "
            "'rules' (add one where the rules put it, when it has none), 'off', 'on'. A "
            "spike sits 250-3000 ms before its drop, a vocal intro 350-4500 ms; at least "
            "200 ms before it either way. Name the drop as set_drop_part does (sequence, "
            "or your_drop_s for one of his own drops — his pre-drop edits never touch his "
            "triggers). list_drop_sequences shows each drop's pre_drop. Nothing plays "
            "from a pre-drop yet. undo_drop_edit puts it back."),
        input_schema={"type": "object", "properties": {
            "sequence": _SEQ,
            "your_drop_s": {"type": "number", "minimum": 0,
                            "description": "the time of one of his own drops, in seconds"},
            "at_seconds": {"type": "number", "minimum": 0},
            "before_drop_ms": {"type": "integer", "minimum": 200, "maximum": 4500},
            "place": {"type": "string", "enum": list(PRE_DROP_PLACES)},
            "uri": _URI},
            "additionalProperties": False},
        handler=_op_set_pre_drop),
    "switch_pre_drop": SonicOperation(
        name="switch_pre_drop", domain="drops", kind="write",
        summary="Switch a drop's pre-drop between a spike (one loud hit) and a vocal intro "
                "(a voice entering out of a hush).",
        instructions=(
            "kind='spike' or 'intro'. Refused when its lead does not fit the kind (a spike "
            "250-3000 ms before its drop, a vocal intro 350-4500 ms): move it first with "
            "set_pre_drop. Name the drop as set_drop_part does. undo_drop_edit puts it "
            "back."),
        input_schema={"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(PRE_DROP_KINDS)},
            "sequence": _SEQ,
            "your_drop_s": {"type": "number", "minimum": 0,
                            "description": "the time of one of his own drops, in seconds"},
            "uri": _URI},
            "required": ["kind"], "additionalProperties": False},
        handler=_op_switch_pre_drop),
    "remove_drop_sequence": SonicOperation(
        name="remove_drop_sequence", domain="drops", kind="write",
        summary="Remove a drop completely (the Drops panel's Remove) — always asks first.",
        instructions=(
            "A detection is dismissed (never offered there again), a drop he added is "
            "deleted, and one of HIS OWN drops (your_drop_s, or the number of the detection "
            "standing in for it) has its charge/lull/drop triggers DELETED when he placed "
            "them by hand and switched off when they were imported, and the detection "
            "standing in for it dismissed. The first call changes nothing and answers "
            "needs_confirmation with the question: put it to him, and only after he says "
            "yes call again with the same arguments plus confirm_id. undo_drop_edit puts "
            "everything back, his song-profile triggers included."),
        input_schema={"type": "object", "properties": {
            "sequence": _SEQ,
            "your_drop_s": {"type": "number", "minimum": 0,
                            "description": "the time of one of his own drops, in seconds"},
            "uri": _URI,
            "confirm_id": {"type": "string"}},
            "additionalProperties": False},
        handler=_op_remove),
    "drop_detection_summary": SonicOperation(
        name="drop_detection_summary", domain="drops", kind="read",
        summary="How many songs have drop detection, and how many of his "
                "edits each one carries — a library-wide count, not one song.",
        instructions="Use for 'how many songs have drops detected' — for "
                    "one song's own sequences, call list_drop_sequences instead.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_summary),
}
