"""Music-analysis test-bed API (data/spotfx-music-analysis-plan/report.md,
Part 3): a READ-ONLY comparison surface over his real marks + every
candidate engine's precomputed output, with ONE write exception — the
reviewed push-to-real button.

  GET    /api/testbed/songs                          candidate song list
  GET    /api/testbed/marks?uri=                      his real marks (split)
  GET    /api/testbed/waveform?uri=                    waveform/energy lane
  GET    /api/testbed/engines?uri=                    per-engine availability
  GET    /api/testbed/compare?uri=&engine=&mark_kind=&reference=&tolerance_ms=
                                                       one engine's marks + P/R/F1
  GET    /api/testbed/audio/status?uri=                pin/WAV status
  POST   /api/testbed/audio/pin?uri=                    pin (copy + peaks)
  DELETE /api/testbed/audio/pin?uri=                    unpin
  POST   /api/testbed/promote                          THE reviewed write
  GET    /api/testbed/promotions?uri=                   audit trail

Every read here degrades honestly (empty lists / {"available": false}) —
never a 500 for "nothing computed yet," which is the ordinary state for a
song this build hasn't been pinned/precomputed for.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from spectra.models.trigger import TriggerAction
from spectra.services import (analysis_reader, testbed_audio, testbed_engines,
                              testbed_marks, testbed_metrics, testbed_promote,
                              trigger_store)

router = APIRouter(prefix="/api/testbed", tags=["spectra-testbed"])


def _song_list() -> list[dict]:
    """ONE read of each store for the whole corpus — triggers.json once
    (~9.5MB on his real corpus), the profile directory once, the
    audio-shape index once, the pin registry once — then a per-song walk
    over what's already in memory. The per-song helpers this composes
    (marks_for_song / availability_for / status) each re-read their store
    on every call; looping them over ~850 songs is a full parse per song."""
    stems = analysis_reader.stem_index()
    pinned = testbed_audio.list_pinned()
    out = []
    for uri, marks in testbed_marks.all_song_marks().items():
        out.append({
            "uri": uri,
            "title": marks.title,
            "artist": marks.artist,
            "n_transitions": len(marks.transitions),
            "n_flares": len(marks.flares),
            "provenance": marks.provenance.__dict__,
            "audio": testbed_audio.status(uri, stem_index=stems, registry=pinned),
            "engines": testbed_engines.availability_for(uri, stem_index=stems),
        })
    return out


@router.get("/songs")
async def list_songs():
    """Runs off the event loop (asyncio.to_thread, the sync-from-profile
    precedent in spectra/api/triggers.py): even as one read per store this
    is synchronous file I/O over the whole corpus, and this process's
    bridge polls / trigger ticks / WS broadcasts must not stall behind a
    page mount."""
    return await asyncio.to_thread(_song_list)


@router.get("/marks")
async def get_marks(uri: str = Query(...)):
    marks = testbed_marks.marks_for_song(uri)
    return {
        "uri": uri,
        "title": marks.title,
        "artist": marks.artist,
        "transitions": [m.__dict__ for m in marks.transitions],
        "flares": [m.__dict__ for m in marks.flares],
        "provenance": marks.provenance.__dict__,
    }


@router.get("/waveform")
async def get_waveform(uri: str = Query(...)):
    peaks = testbed_audio.load_peaks(uri)
    if peaks is not None:
        return {"uri": uri, "source": "wav_peaks", **peaks}
    shape = testbed_audio.load_npz_shape(uri)
    if shape is not None:
        return {"uri": uri, "source": "npz_rms_fallback", **shape}
    return {"uri": uri, "source": "none", "note": "no waveform or coarse "
            "shape data available for this song"}


@router.get("/engines")
async def get_engines(uri: str = Query(...)):
    return {"uri": uri, "engines": testbed_engines.availability_for(uri)}


@router.get("/compare")
async def compare(
    uri: str = Query(...),
    engine: str = Query(...),
    mark_kind: str = Query(...),
    reference: str = Query("transitions", pattern="^(transitions|flares)$"),
    tolerance_ms: float = Query(500.0, gt=0),
):
    if engine not in testbed_engines.ENGINES:
        raise HTTPException(404, f"unknown engine '{engine}'")
    engine_marks = testbed_engines.marks_for(engine, uri)
    if engine_marks is None:
        return {"uri": uri, "engine": engine, "mark_kind": mark_kind,
                "reference": reference, "tolerance_ms": tolerance_ms,
                "available": False, "estimate": [], "reference_marks": [],
                "metrics": None}

    estimate = [m for m in engine_marks if m.kind == mark_kind]
    song_marks = testbed_marks.marks_for_song(uri)
    ref_marks = (song_marks.transitions if reference == "transitions"
                else song_marks.flares)

    result = testbed_metrics.match_marks(
        [m.timestamp_ms for m in ref_marks],
        [m.time_ms for m in estimate],
        tolerance_ms,
    )
    return {
        "uri": uri, "engine": engine, "mark_kind": mark_kind,
        "reference": reference, "tolerance_ms": tolerance_ms,
        "available": True,
        "estimate": [{"time_ms": m.time_ms, "label": m.label, "score": m.score}
                     for m in estimate],
        "reference_marks": [{"id": m.id, "timestamp_ms": m.timestamp_ms,
                             "kind": m.kind} for m in ref_marks],
        "metrics": testbed_metrics.match_result_dict(result),
    }


@router.get("/audio/status")
async def audio_status(uri: str = Query(...)):
    return {"uri": uri, **testbed_audio.status(uri)}


@router.post("/audio/pin")
async def audio_pin(uri: str = Query(...)):
    """Off the event loop: a pin copies a full-length WAV (tens of MB for
    a four-minute capture) and decodes it again for the peaks — seconds of
    blocking I/O the trigger engine and bridge must not wait behind."""
    result = await asyncio.to_thread(testbed_audio.pin, uri)
    if result.get("status") in ("unknown_song", "no_source_wav"):
        raise HTTPException(409, result["status"])
    return result


@router.delete("/audio/pin")
async def audio_unpin(uri: str = Query(...)):
    if not testbed_audio.unpin(uri):
        raise HTTPException(404, "not pinned")
    return {"status": "unpinned"}


class PromoteRequest(BaseModel):
    uri: str = Field(min_length=1)
    timestamp_ms: int = Field(ge=0)
    action: TriggerAction
    source_engine: str = Field(min_length=1)
    source_mark_kind: str = Field(min_length=1)
    trigger_offset_ms: int = Field(default=0, ge=-60_000, le=60_000)
    # No default — an omitted field is a 422, not a silent False. The
    # frontend's review dialog is the only caller that ever sets this True;
    # see testbed_promote.py's module docstring for the full gate.
    confirmed: bool


@router.post("/promote")
async def promote(body: PromoteRequest):
    try:
        return testbed_promote.promote(
            uri=body.uri, timestamp_ms=body.timestamp_ms, action=body.action,
            source_engine=body.source_engine, source_mark_kind=body.source_mark_kind,
            confirmed=body.confirmed, trigger_offset_ms=body.trigger_offset_ms,
        )
    except testbed_promote.PromotionNotConfirmed as exc:
        raise HTTPException(422, str(exc)) from exc
    except trigger_store.InvalidTriggerAction as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/promotions")
async def promotions(uri: str | None = Query(None)):
    return testbed_promote.log_for_song(uri)
