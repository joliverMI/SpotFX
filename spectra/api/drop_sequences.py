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
                                    beats, song time. Read-only.

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
  POST /member        {uri, key, handle, off}       lull/charge off or back on
  POST /fill          {uri, key, handle}            add a lull or charge by the rules
  POST /review        {uri, key, choice}            "the analysis moved it": keep|take
  POST /add           {uri, drop_ms, lull_ms?, charge_ms?}
                                                    a sequence of his; a missing lull
                                                    and charge are placed by the rules
  POST /confirm-all   {uri}                         every confident detection
  POST /redetect      {uri}                         detect again now
  POST /restore       {uri, edits, expect}          undo/redo
  GET  /edits?uri=                                  his edits and their rev

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

from spectra.services import drop_firing, drop_sequences

router = APIRouter(prefix="/api/drop-sequences", tags=["spectra-drop-sequences"])


@router.get("")
async def get_drop_sequences(uri: str = Query(..., min_length=1)):
    """Off the loop: a detection reads the song's audio shape and beat
    analysis, and the merge reads the trigger store."""
    return await asyncio.to_thread(_view_with_detection, uri)


def _view_with_detection(uri: str) -> dict:
    return drop_firing.annotated_view(uri, drop_sequences.view_with_detection(uri))


def _summary() -> dict:
    data = drop_sequences.all_stored()
    songs = []
    for uri, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            continue
        det = entry.get("detected") or {}
        tiers: dict[str, int] = {}
        for s in det.get("sequences") or []:
            tiers[s.get("tier")] = tiers.get(s.get("tier"), 0) + 1
        overrides = entry.get("overrides") or {}
        songs.append({
            "uri": uri,
            "detected": bool(det),
            "detected_at": det.get("detected_at"),
            "stamp": det.get("stamp"),
            "tiers": tiers,
            "excluded": len(det.get("excluded") or []),
            "overrides": len(overrides),
            "dismissed": sum(1 for o in overrides.values()
                             if isinstance(o, dict) and o.get("state") == "dismissed"),
            "added": len(entry.get("added") or []),
        })
    return {"songs": songs}


@router.get("/summary")
async def get_summary():
    return await asyncio.to_thread(_summary)


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
    handles: dict[Literal["charge", "lull", "drop"], Optional[int]]


class _Member(_Seq):
    handle: Literal["lull", "charge"]
    off: bool


class _Fill(_Seq):
    handle: Literal["lull", "charge"]


class _Review(_Seq):
    choice: Literal["keep", "take"]


class _Add(_Song):
    drop_ms: int
    lull_ms: Optional[int] = None
    charge_ms: Optional[int] = None


class _Restore(_Song):
    edits: dict[str, Any]
    expect: Optional[str] = None


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
    return await _run(body.uri, "handles", key=body.key, handles=dict(body.handles))


@router.post("/member")
async def post_member(body: _Member):
    return await _run(body.uri, "member", key=body.key, handle=body.handle, off=body.off)


@router.post("/fill")
async def post_fill(body: _Fill):
    return await _run(body.uri, "fill", key=body.key, handle=body.handle)


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
    return await _run(body.uri, "restore", edits=body.edits, expect=body.expect)


def _redetect(uri: str) -> dict:
    result = drop_sequences.ensure_detected(uri, force=True)
    body = drop_firing.annotated_view(uri)
    body["detection"] = result
    return body


@router.post("/redetect")
async def post_redetect(body: _Song):
    return await asyncio.to_thread(_redetect, body.uri)
