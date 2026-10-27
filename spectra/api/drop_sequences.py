"""Drop sequences — READ endpoints (drop-detection plan, phase 2; the
Timeline's sequence layer, strip and review list are phase 3, the edits
phase 4). spectra/services/drop_sequences.py is the binding statement.

  GET /api/drop-sequences?uri=      one song: detected sequences merged with
                                    his edits and his own triggers (states,
                                    automatic vs his times, "matches yours",
                                    his own charge/lull/drop grouped the
                                    same way). Read-through: detects first
                                    when the song has no detection yet or
                                    its stamp is stale.
  GET /api/drop-sequences/summary   every song the store holds: what was
                                    detected, by tier, and how many edits
                                    he has made — a store read, never a
                                    detection.
  GET /api/drop-sequences/rails?uri= the snap rails the Timeline draws under
                                    the sequence layer (phase 3): the
                                    detector's own bass spikes and the
                                    beats, and the pre-drop's hits and
                                    entries, song time. Read-only.

EDITS (phase 4) — each a POST with a JSON body naming the song (`uri`)
and, where it applies, the sequence (`key`, as the view gives it). Every
edit answers {"result", "view", "before", "after", "rev_before",
"rev_after"}: the song's merged view after the edit, and HIS EDITS either
side of it — the pair the Timeline's undo/redo puts back through
/restore, which refuses (409) when his edits changed since.

  POST /confirm       {uri, key}                    confirm a detection
  POST /dismiss       {uri, key}                    "not a drop" (removes an added one)
  POST /revert        {uri, key}                    back to detected
  POST /handles       {uri, key, handles}           move handles in one edit;
                                                    {"drop": ms, "lull": null, ...}
                                                    (null = back to automatic)
  POST /member        {uri, key, handle, off}       lull/charge/pre-drop off or back on
  POST /fill          {uri, key, handle}            add a lull, charge or pre-drop by
                                                    the rules
  POST /pre-drop-kind {uri, key, kind}              switch a pre-drop's kind
                                                    (spike | intro)
  POST /review        {uri, key, choice}            "the analysis moved it": keep|take
  POST /add           {uri, drop_ms, lull_ms?, charge_ms?}
                                                    a sequence of his; a missing lull
                                                    and charge are placed by the rules
  POST /confirm-all   {uri}                         every confident detection
  POST /redetect      {uri}                         detect again now
  POST /restore       {uri, edits, expect, profile?} undo/redo (with `profile`,
                                                    his song-profile rows too)
  GET  /edits?uri=                                  his edits and their rev

THE HOME DROPS PANEL (2026-10-26, predrop plan step 1 —
spectra/services/drop_panel.py is the binding statement). Keys are the
view's, plus "his:<drop trigger id>" for one of his own drops (the view's
`yours` rows). Each answers the edit shape above plus `profile` (the song-
profile rows his own drop's write changed, the other half of one undo
step) and `said` (what it did, in words).

  POST /parts         {uri, key, parts}             {part: "on"|"off"}; the
                                                    drop "on" confirms it
  POST /approve       {uri, key}                    the double tick
  POST /remove        {uri, key}                    remove completely
  POST /switch-on     {uri, key}                    one of his drops back on
  GET  /provenance?uri=                             his phase triggers: placed
                                                    by hand or imported (or
                                                    born on SPECTRA's card)

503 when the root process (his song profiles) does not answer — nothing is
changed; the root route's own refusals pass through (404/422/409).

Errors: 404 no such sequence, 422 an edit that would break charge < lull
< drop (or a bad body), 409 a stale undo.

WHAT FIRES (phase 5, spectra/services/drop_firing.py). Every view these
routes answer carries, per sequence, `fires` (whether it fires on this song
under the room's scene-change setting right now) and `fires_reason`, plus
the body's `firing` (the gate for detected and for his sequences) and
`windows` (the protected windows). An edit changes what fires from the next
tick on, and drops the trigger clock's cached analysed plan for the song so
its flares are re-planned around the new windows (drop_sequences._changed).
"""
from __future__ import annotations

import asyncio

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from spectra.services import drop_firing, drop_panel, drop_sequences

router = APIRouter(prefix="/api/drop-sequences", tags=["spectra-drop-sequences"])


@router.get("")
async def get_drop_sequences(uri: str = Query(..., min_length=1)):
    """Off the loop: a detection reads the song's audio shape and beat
    analysis, and the merge reads the trigger store."""
    return await asyncio.to_thread(_view_with_detection, uri)


def _view_with_detection(uri: str) -> dict:
    return drop_firing.annotated_view(uri, drop_sequences.view_with_detection(uri))


@router.get("/summary")
async def get_summary():
    return await asyncio.to_thread(drop_sequences.summary)


@router.get("/rails")
async def get_rails(uri: str = Query(..., min_length=1)):
    """Off the loop: the analysis reads the song's audio shape and beats."""
    return await asyncio.to_thread(drop_sequences.snap_rails, uri)


# ── edits (phase 4) ──────────────────────────────────────────────────────

class _Song(BaseModel):
    uri: str = Field(..., min_length=1)


class _Seq(_Song):
    key: str = Field(..., min_length=1)


class _Handles(_Seq):
    handles: dict[Literal["charge", "lull", "pre_drop", "drop"], Optional[int]]


class _Member(_Seq):
    handle: Literal["lull", "charge", "pre_drop"]
    off: bool


class _Fill(_Seq):
    handle: Literal["lull", "charge", "pre_drop"]


class _PreDropKind(_Seq):
    kind: Literal["spike", "intro"]


class _Review(_Seq):
    choice: Literal["keep", "take"]


class _Add(_Song):
    drop_ms: int
    lull_ms: Optional[int] = None
    charge_ms: Optional[int] = None


class _Restore(_Song):
    edits: dict[str, Any]
    expect: Optional[str] = None
    # the profile half of a panel write's undo: restore records
    # {id, from, to, index}, oriented by the caller (drop_panel.restore)
    profile: list[dict[str, Any]] = Field(default_factory=list)


class _Parts(_Seq):
    parts: dict[Literal["charge", "lull", "pre_drop", "drop"], Literal["on", "off"]]


def _edit(uri: str, op: str, **kw) -> dict:
    try:
        res = drop_sequences.apply_edit(uri, op, **kw)
    except drop_sequences.SequenceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except drop_sequences.InvalidEdit as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except drop_sequences.EditConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "result": res.result,
        "view": drop_firing.annotated_view(uri),
        "before": res.before,
        "after": res.after,
        "rev_before": drop_sequences.edits_rev(res.before),
        "rev_after": drop_sequences.edits_rev(res.after),
    }


async def _run(uri: str, op: str, **kw) -> dict:
    """Off the loop: an edit rewrites the store, and the view reads the
    trigger store."""
    return await asyncio.to_thread(_edit, uri, op, **kw)


@router.get("/edits")
async def get_edits(uri: str = Query(..., min_length=1)):
    return await asyncio.to_thread(drop_sequences.edits, uri)


@router.post("/confirm")
async def post_confirm(body: _Seq):
    return await _run(body.uri, "confirm", key=body.key)


@router.post("/dismiss")
async def post_dismiss(body: _Seq):
    return await _run(body.uri, "dismiss", key=body.key)


@router.post("/revert")
async def post_revert(body: _Seq):
    return await _run(body.uri, "revert", key=body.key)


@router.post("/handles")
async def post_handles(body: _Handles):
    if drop_panel.is_his(body.key):
        # one of his own drops: its trigger moves in his song profile
        return await _panel(body.uri, drop_panel.move_handles(body.uri, body.key,
                                                              dict(body.handles)))
    return await _run(body.uri, "handles", key=body.key, handles=dict(body.handles))


@router.post("/member")
async def post_member(body: _Member):
    if body.handle == "pre_drop":
        # any drop's pre-drop, his own included (stored in the drop store)
        return await _panel(body.uri, drop_panel.pre_drop_member(body.uri, body.key, body.off))
    return await _run(body.uri, "member", key=body.key, handle=body.handle, off=body.off)


@router.post("/fill")
async def post_fill(body: _Fill):
    if body.handle == "pre_drop":
        return await _panel(body.uri, drop_panel.pre_drop_fill(body.uri, body.key))
    return await _run(body.uri, "fill", key=body.key, handle=body.handle)


@router.post("/pre-drop-kind")
async def post_pre_drop_kind(body: _PreDropKind):
    return await _panel(body.uri, drop_panel.pre_drop_kind(body.uri, body.key, body.kind))


@router.post("/review")
async def post_review(body: _Review):
    return await _run(body.uri, "review", key=body.key, choice=body.choice)


@router.post("/add")
async def post_add(body: _Add):
    return await _run(body.uri, "add", drop_ms=body.drop_ms, lull_ms=body.lull_ms,
                      charge_ms=body.charge_ms)


@router.post("/confirm-all")
async def post_confirm_all(body: _Song):
    return await _run(body.uri, "confirm_all")


@router.post("/restore")
async def post_restore(body: _Restore):
    if body.profile:
        return await _panel(body.uri, drop_panel.restore(body.uri, body.edits, body.expect,
                                                         list(body.profile)))
    return await _run(body.uri, "restore", edits=body.edits, expect=body.expect)


# ── the Home Drops panel (spectra/services/drop_panel.py) ─────────────────

async def _panel(uri: str, write) -> dict:
    try:
        res = await write
    except drop_sequences.SequenceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except drop_sequences.InvalidEdit as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except drop_sequences.EditConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except drop_panel.ProfileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    except drop_panel.ProfileUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "result": res.result,
        "view": await asyncio.to_thread(drop_firing.annotated_view, uri),
        "before": res.before,
        "after": res.after,
        "rev_before": drop_sequences.edits_rev(res.before),
        "rev_after": drop_sequences.edits_rev(res.after),
        "profile": res.profile,
        "said": res.said,
    }


@router.post("/parts")
async def post_parts(body: _Parts):
    return await _panel(body.uri, drop_panel.set_parts(body.uri, body.key, dict(body.parts)))


@router.post("/approve")
async def post_approve(body: _Seq):
    return await _panel(body.uri, drop_panel.approve(body.uri, body.key))


@router.post("/remove")
async def post_remove(body: _Seq):
    return await _panel(body.uri, drop_panel.remove(body.uri, body.key))


@router.post("/switch-on")
async def post_switch_on(body: _Seq):
    return await _panel(body.uri, drop_panel.switch_on(body.uri, body.key))


@router.get("/provenance")
async def get_provenance(uri: str = Query(..., min_length=1)):
    """His charge/lull/drop triggers: each one placed by hand or imported,
    read from his song profile by the root process, plus any born on
    SPECTRA's own trigger card (placed by hand; drop_panel.card_born_rows).
    A root that does not answer is a stated "unknown", never a guess."""
    try:
        return await drop_panel.panel_provenance(uri)
    except drop_panel.ProfileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


def _redetect(uri: str) -> dict:
    result = drop_sequences.ensure_detected(uri, force=True)
    body = drop_firing.annotated_view(uri)
    body["detection"] = result
    return body


@router.post("/redetect")
async def post_redetect(body: _Song):
    return await asyncio.to_thread(_redetect, body.uri)
