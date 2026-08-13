"""Sequencer agent-adjustment API (report Part 4). The interface split pins
this channel: relationships and durations are adjusted by telling the agent —
the agent hits these PUT endpoints; there is no settings form.

  GET /api/sequencer/config               — SequencerConfig
  PUT /api/sequencer/config               — replace whole config
  GET /api/sequencer/curves               — {profile_id: CurveProfile}
  PUT /api/sequencer/curves               — replace whole profile library
  GET /api/sequencer/intensity-histogram  — trigger-intensity census over
      storage/profiles (the CurveEditor's honesty underlay)

Storage stays dark: nothing consumes sequencer.json until the open decisions
land (models/sequencer.py header). POST /simulate awaits the selection
algorithm decision.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from config import PROFILES_DIR
from models.sequencer import CurveProfile, SequencerConfig
from services import sequencer_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sequencer", tags=["sequencer"])

HISTOGRAM_BINS = 20

# Census cache: (file count, newest mtime_ns) → intensities. Profiles change
# rarely relative to editor opens; a stale hit only lags the underlay.
_census_cache: tuple[tuple[int, int], list[float]] | None = None


def _intensity_census() -> list[float]:
    global _census_cache
    files = sorted(PROFILES_DIR.glob("*.json")) if PROFILES_DIR.exists() else []
    signature = (len(files), max((f.stat().st_mtime_ns for f in files), default=0))
    if _census_cache is not None and _census_cache[0] == signature:
        return _census_cache[1]
    intensities: list[float] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for trigger in data.get("triggers") or []:
            value = trigger.get("intensity", 0.5)
            if isinstance(value, (int, float)) and 0.0 <= value <= 1.0:
                intensities.append(float(value))
    _census_cache = (signature, intensities)
    return intensities


@router.get("/config")
async def get_config():
    return sequencer_store.load_config().model_dump()


@router.put("/config")
async def put_config(config: SequencerConfig):
    known = set(sequencer_store.load_curves())
    dangling = sorted({e.curve_ref for e in config.entries.values()
                       if e.curve_ref is not None and e.curve_ref not in known})
    if dangling:
        raise HTTPException(422, f"unknown curve profile id(s): {', '.join(dangling)}")
    sequencer_store.save_config(config)
    return {"status": "saved", "entries": len(config.entries),
            "affinity_edges": len(config.affinity)}


@router.get("/curves")
async def get_curves():
    return {pid: p.model_dump() for pid, p in sequencer_store.load_curves().items()}


@router.put("/curves")
async def put_curves(curves: dict[str, CurveProfile]):
    mismatched = sorted(pid for pid, p in curves.items() if pid != p.id)
    if mismatched:
        raise HTTPException(422, f"key does not match profile id: {', '.join(mismatched)}")
    referenced = {e.curve_ref for e in sequencer_store.load_config().entries.values()
                  if e.curve_ref is not None}
    orphaned = sorted(referenced - set(curves))
    if orphaned:
        raise HTTPException(
            422, f"config entries still reference profile id(s): {', '.join(orphaned)}")
    sequencer_store.save_curves(curves)
    return {"status": "saved", "profiles": len(curves)}


@router.get("/intensity-histogram")
async def get_intensity_histogram():
    intensities = _intensity_census()
    counts = [0] * HISTOGRAM_BINS
    for v in intensities:
        counts[min(int(v * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1
    return {"bins": HISTOGRAM_BINS, "counts": counts, "total": len(intensities)}
