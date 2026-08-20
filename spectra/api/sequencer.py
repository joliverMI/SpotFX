"""SPECTRA sequencer API — the spot-effects agent-adjustment surface, ported
onto SPECTRA's stores. The interface split is unchanged: curves are
graphical (the UI writes ONLY the profile library and each entry's curve
attachment); relationships (genre_mult, affinity, enabled) are adjusted by
telling the agent through PUT /config. Minimum dwell (the retired
dwell_weight's successor) is NOT here at all — it's a per-scene SceneV2
field (spectra/models/scene.py's dwell_curve), round-tripped through
POST /scenes like any other scene field; see spectra/services/dwell.py.

  GET/PUT /api/sequencer/config     GET/PUT /api/sequencer/curves
  GET     /api/sequencer/status     POST    /api/sequencer/simulate
  GET     /api/sequencer/intensity-histogram
"""
from __future__ import annotations

import json
import logging
from random import Random
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra import config as spectra_config
from spectra.models.sequencer import CurvePoint, CurveProfile, SequencerConfig
from spectra.services import selection_kernel as kernel
from spectra.services import sequencer_store
from spectra.services.scene_sequencer import scene_sequencer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sequencer", tags=["spectra-sequencer"])

HISTOGRAM_BINS = 20

# Census cache: (file count, newest mtime_ns) → intensities. The census reads
# spot-effects' storage/profiles READ-ONLY (bridge contract).
_census_cache: tuple[tuple[int, int], list[float]] | None = None


def _intensity_census() -> list[float]:
    global _census_cache
    profiles_dir = spectra_config.PROFILES_DIR
    files = sorted(profiles_dir.glob("*.json")) if profiles_dir.exists() else []
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
    all_entries = (list(config.entries.values())
                   + list(config.flare_entries.values())
                   + list(config.color_set_entries.values()))
    dangling = sorted({e.curve_ref for e in all_entries
                       if e.curve_ref is not None and e.curve_ref not in known})
    if config.wheel_travel_curve is not None and \
            config.wheel_travel_curve not in known:
        dangling.append(config.wheel_travel_curve)
    if dangling:
        raise HTTPException(422, f"unknown curve profile id(s): {', '.join(dangling)}")
    sequencer_store.save_config(config)
    return {"status": "saved", "entries": len(config.entries),
            "flare_entries": len(config.flare_entries),
            "color_set_entries": len(config.color_set_entries),
            "affinity_edges": len(config.affinity),
            "enabled": config.enabled}


@router.get("/curves")
async def get_curves():
    return {pid: p.model_dump() for pid, p in sequencer_store.load_curves().items()}


@router.put("/curves")
async def put_curves(curves: dict[str, CurveProfile]):
    mismatched = sorted(pid for pid, p in curves.items() if pid != p.id)
    if mismatched:
        raise HTTPException(422, f"key does not match profile id: {', '.join(mismatched)}")
    config = sequencer_store.load_config()
    referenced = {e.curve_ref
                  for e in (list(config.entries.values())
                            + list(config.flare_entries.values())
                            + list(config.color_set_entries.values()))
                  if e.curve_ref is not None}
    if config.wheel_travel_curve is not None:
        referenced.add(config.wheel_travel_curve)
    orphaned = sorted(referenced - set(curves))
    if orphaned:
        raise HTTPException(
            422, f"config entries still reference profile id(s): {', '.join(orphaned)}")
    sequencer_store.save_curves(curves)
    return {"status": "saved", "profiles": len(curves)}


@router.get("/status")
async def get_status():
    return scene_sequencer.status()


class SimulateRequest(BaseModel):
    intensity: float = Field(ge=0.0, le=1.0)
    n: int = Field(default=1000, ge=1, le=100_000)
    kind: Literal["scene", "flare", "color_set"] = "scene"
    current_id: Optional[str] = None
    genre_bucket: Optional[str] = None
    room_position_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    seed: Optional[int] = None


def _color_set_positions() -> dict[str, Optional[float]]:
    from spectra.services import color_sets, color_wheel
    return {sid: p.position_deg
            for sid, p in color_wheel.wheel_positions(
                color_sets.list_all()).items()}


@router.post("/simulate")
async def simulate(req: SimulateRequest):
    config = sequencer_store.load_config()
    curves = sequencer_store.load_curves()
    rng = Random(req.seed)
    if req.kind == "flare":
        candidates = kernel.build_flare_candidates(
            config.flare_entries, curves, genre_bucket=req.genre_bucket)
    elif req.kind == "color_set":
        wheel_profile = (curves.get(config.wheel_travel_curve)
                         if config.wheel_travel_curve else None)
        from spectra.services import color_set_groups
        candidates = kernel.build_color_set_candidates(
            config.color_set_entries, curves,
            genre_bucket=req.genre_bucket, room_deg=req.room_position_deg,
            set_positions=_color_set_positions(),
            wheel_points=(wheel_profile.points if wheel_profile
                          else [CurvePoint(x=0.0, y=1.0)]),
            group_ids_by_set=color_set_groups.group_ids_by_set())
    else:
        candidates = kernel.build_scene_candidates(
            config.entries, curves, config.affinity,
            genre_bucket=req.genre_bucket, prev_id=req.current_id)
    picks: dict[str, int] = {}
    rungs: dict[str, int] = {}
    factors: dict = {}
    for _ in range(req.n):
        if req.kind == "flare":
            pick = kernel.select_flare(candidates, intensity=req.intensity, rng=rng)
        elif req.kind == "color_set":
            pick = kernel.select_color_set(candidates, intensity=req.intensity,
                                           rng=rng, current_id=req.current_id)
        else:
            pick = kernel.select(candidates, intensity=req.intensity, rng=rng,
                                 current_id=req.current_id,
                                 terminal=kernel.TERMINAL_STAY)
        key = pick.picked_id if pick.picked_id is not None else f"<{pick.rung}>"
        picks[key] = picks.get(key, 0) + 1
        rungs[pick.rung] = rungs.get(pick.rung, 0) + 1
        factors = pick.factors
    return {"n": req.n, "intensity": req.intensity, "kind": req.kind,
            "shares": {k: v / req.n for k, v in sorted(picks.items())},
            "rungs": rungs, "factors": factors}


@router.get("/intensity-histogram")
async def get_intensity_histogram():
    intensities = _intensity_census()
    counts = [0] * HISTOGRAM_BINS
    for v in intensities:
        counts[min(int(v * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1
    return {"bins": HISTOGRAM_BINS, "counts": counts, "total": len(intensities)}
