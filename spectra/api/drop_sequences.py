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

Nothing here fires anything (phase 5).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from spectra.services import drop_sequences

router = APIRouter(prefix="/api/drop-sequences", tags=["spectra-drop-sequences"])


@router.get("")
async def get_drop_sequences(uri: str = Query(..., min_length=1)):
    """Off the loop: a detection reads the song's audio shape and beat
    analysis, and the merge reads the trigger store."""
    return await asyncio.to_thread(drop_sequences.view_with_detection, uri)


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
