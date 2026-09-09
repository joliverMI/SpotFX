"""Music-analysis test-bed API (data/spotfx-music-analysis-plan/report.md,
Part 3): a READ-ONLY comparison surface over his real marks + every
candidate engine's precomputed output, with ONE write exception — the
reviewed push-to-real button.

  GET    /api/testbed/songs                          candidate song list
  GET    /api/testbed/marks?uri=                      his real marks (split)
  GET    /api/testbed/waveform?uri=                    waveform/energy lane
  GET    /api/testbed/engines?uri=                    per-engine availability
  GET    /api/testbed/engine-marks?uri=&engine=&mark_kind=
                                                       one engine's marks, nothing else
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
    (~9.5MB on his real corpus), the profile directory once, the promotion
    log once, the audio-shape index once, the pin registry once — then a
    per-song walk over what's already in memory. The per-song helpers this
    composes (marks_for_song / availability_for / status) each re-read
    their store on every call; looping them over ~850 songs is a full
    parse per song.

    `count_marks=False` is the same discipline one layer down: a listing
    needs each engine's availability BIT, and parsing every song's
    .librosa.json to produce a mark count it then discards is 965 files
    and 417MB of his real storage per request (and this listing is
    re-fetched on every pin, unpin and promotion)."""
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
            "n_generated": marks.n_generated,
            "n_promoted": marks.n_promoted,
            "provenance": marks.provenance.__dict__,
            "audio": testbed_audio.status(uri, stem_index=stems, registry=pinned),
            "engines": testbed_engines.availability_for(
                uri, stem_index=stems, count_marks=False),
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
    """One song's marks + provenance: a full triggers.json parse plus the
    profile-directory scan its caveat needs, so it runs off the loop."""
    def _read() -> dict:
        marks = testbed_marks.marks_for_song(uri)
        return {
            "uri": uri,
            "title": marks.title,
            "artist": marks.artist,
            "transitions": [m.__dict__ for m in marks.transitions],
            "flares": [m.__dict__ for m in marks.flares],
            "n_generated": marks.n_generated,
            "n_promoted": marks.n_promoted,
            "provenance": marks.provenance.__dict__,
        }
    return await asyncio.to_thread(_read)


def _waveform(uri: str) -> dict:
    peaks = testbed_audio.load_peaks(uri)
    if peaks is not None:
        # The pinned WAV's sample 0 is NOT song-time 0 — a capture starts
        # mid-song. Resolved at READ time (not baked into the stored peaks)
        # so a pin taken before this existed carries it too, and so a later
        # re-analysis of the sidecar is picked up without re-pinning. None =
        # genuinely unknown, which the page renders as such rather than
        # drawing the lane at a position it cannot justify.
        return {"uri": uri, "source": "wav_peaks",
                "capture_offset_ms": testbed_audio.capture_offset_ms(uri),
                **peaks}
    shape = testbed_audio.load_npz_shape(uri)
    if shape is not None:
        return {"uri": uri, "source": "npz_rms_fallback", **shape}
    return {"uri": uri, "source": "none", "note": "no waveform or coarse "
            "shape data available for this song"}


@router.get("/waveform")
async def get_waveform(uri: str = Query(...)):
    """Off the loop like every other per-song read here: the npz fallback
    resolves the song's stem, and a miss (the common case — most stored
    songs have no captured audio) rebuilds the whole sidecar index."""
    return await asyncio.to_thread(_waveform, uri)


@router.get("/engines")
async def get_engines(uri: str = Query(...)):
    engines = await asyncio.to_thread(testbed_engines.availability_for, uri)
    return {"uri": uri, "engines": engines}


def _estimate_for(engine: str, uri: str, mark_kind: str):
    """One engine's marks of one kind, or None when the engine has nothing
    for this song — the ONLY read the page's per-lane fetch needs. Never
    touches triggers.json or the profile directory."""
    engine_marks = testbed_engines.marks_for(engine, uri)
    if engine_marks is None:
        return None
    return [m for m in engine_marks if m.kind == mark_kind]


def _estimate_payload(estimate) -> list[dict]:
    return [{"time_ms": m.time_ms, "label": m.label, "score": m.score}
            for m in estimate]


@router.get("/engine-marks")
async def engine_marks(
    uri: str = Query(...),
    engine: str = Query(...),
    mark_kind: str = Query(...),
):
    """The page's per-lane fetch: it recomputes P/R/F1 locally against the
    marks it already holds (spectra/web/src/testbed/metrics.ts), so the
    server-side match and the reference marks /compare carries would be
    computed and discarded — and the trigger-store parse + profile scan
    they cost is what this route exists to skip."""
    if engine not in testbed_engines.ENGINES:
        raise HTTPException(404, f"unknown engine '{engine}'")
    estimate = await asyncio.to_thread(_estimate_for, engine, uri, mark_kind)
    return {
        "uri": uri, "engine": engine, "mark_kind": mark_kind,
        "available": estimate is not None,
        "estimate": _estimate_payload(estimate or []),
    }


@router.get("/compare")
async def compare(
    uri: str = Query(...),
    engine: str = Query(...),
    mark_kind: str = Query(...),
    reference: str = Query("transitions", pattern="^(transitions|flares)$"),
    tolerance_ms: float = Query(500.0, gt=0),
):
    """Server-computed P/R/F1 at a fixed tolerance — for any caller that
    wants the number from the reference matcher itself rather than the
    page's local port. Reads the fired copy for the reference marks (one
    triggers.json parse, off the loop) and never the profile directory:
    provenance is /marks' business."""
    if engine not in testbed_engines.ENGINES:
        raise HTTPException(404, f"unknown engine '{engine}'")

    def _read() -> dict:
        estimate = _estimate_for(engine, uri, mark_kind)
        if estimate is None:
            return {"uri": uri, "engine": engine, "mark_kind": mark_kind,
                    "reference": reference, "tolerance_ms": tolerance_ms,
                    "available": False, "estimate": [], "reference_marks": [],
                    "metrics": None}

        # SCORING marks only — reference_marks_for_song has already
        # dropped every test-bed-promoted row (see testbed_marks.py's
        # docstring: an engine must not be graded against its own pushed
        # suggestions).
        transitions, flares = testbed_marks.reference_marks_for_song(uri)
        ref_marks = transitions if reference == "transitions" else flares
        result = testbed_metrics.match_marks(
            [m.timestamp_ms for m in ref_marks],
            [m.time_ms for m in estimate],
            tolerance_ms,
        )
        return {
            "uri": uri, "engine": engine, "mark_kind": mark_kind,
            "reference": reference, "tolerance_ms": tolerance_ms,
            "available": True,
            "estimate": _estimate_payload(estimate),
            "reference_marks": [{"id": m.id, "timestamp_ms": m.timestamp_ms,
                                 "kind": m.kind} for m in ref_marks],
            "metrics": testbed_metrics.match_result_dict(result),
        }
    return await asyncio.to_thread(_read)


@router.get("/audio/status")
async def audio_status(uri: str = Query(...)):
    status = await asyncio.to_thread(testbed_audio.status, uri)
    return {"uri": uri, **status}


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
    """Off the loop: the duplicate check and the upsert are each a full
    triggers.json parse (the upsert a rewrite too)."""
    def _run() -> dict:
        return testbed_promote.promote(
            uri=body.uri, timestamp_ms=body.timestamp_ms, action=body.action,
            source_engine=body.source_engine, source_mark_kind=body.source_mark_kind,
            confirmed=body.confirmed, trigger_offset_ms=body.trigger_offset_ms,
        )
    try:
        return await asyncio.to_thread(_run)
    except testbed_promote.PromotionNotConfirmed as exc:
        raise HTTPException(422, str(exc)) from exc
    except testbed_promote.PromotionDuplicate as exc:
        raise HTTPException(409, str(exc)) from exc
    except trigger_store.InvalidTriggerAction as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/promotions")
async def promotions(uri: str | None = Query(None)):
    return testbed_promote.log_for_song(uri)
