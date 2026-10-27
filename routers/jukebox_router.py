"""
SpotFX — the Jukebox API, the master side (services/jukebox/night.py is the
engine). On :8000, the LAN-only master; the guest page is a separate
process on its own port (phase 2) and never reaches these routes.

  GET    /api/jukebox/config          his program settings
  PUT    /api/jukebox/config          a PARTIAL update — only the keys sent
                                      change; an unknown key or an
                                      out-of-range value is a 422 naming it.
                                      `?dry_run=true` validates the same way
                                      and writes nothing. The set playlist
                                      can't change under a running night (409)
  GET    /api/jukebox/status          the night: what is playing, the next
                                      program items with start times, the
                                      line, warnings, the log — reads only
  GET    /api/jukebox/preview         what the set-list editor draws for the
                                      saved settings: the whole set, one pass
                                      with its slots, the next items, the
                                      Auto pattern as Manual slots, the
                                      playhead — reads the set (cached 60 s;
                                      `?refresh=true` reads again)
  GET    /api/jukebox/show            the show settings (every economy setting,
                                      the approval switch, the last preset), the
                                      field table the page draws (ranges read off
                                      the model) and the presets
  PUT    /api/jukebox/show            a PARTIAL edit — {"economy": {...},
                                      "approve_new_phones": bool}; a bad key or
                                      value is a 422 naming it; `?dry_run=true`
  POST   /api/jukebox/show/preset     {preset: small|medium|large} — sets the
                                      program (and approval, for Large)
  GET    /api/jukebox/price-check     the current rules on real examples,
                                      `?guests=` the room size
  GET    /api/jukebox/guest-link      the guests' public link (N1): off/armed/
                                      live/error, the link with tonight's party
                                      token, what it would publish, the last
                                      step and self-test
  PUT    /api/jukebox/guest-link      a PARTIAL edit {enabled, public_host,
                                      public_port, guest_port}; `?dry_run=true`.
                                      enabled SHIPS FALSE; switching it off
                                      while live closes the link at once
  POST   /api/jukebox/guest-link/rotate     a fresh party token (refused
                                      while a night runs: tonight's cards)
  POST   /api/jukebox/guest-link/self-test  the plan alone while closed (no
                                      Tailscale call); Funnel's own status and
                                      the public address while live
  POST   /api/jukebox/simulate        {guests, nights, seed, program:
                                      "saved"|"preset"} — the party simulator:
                                      one model night under the SAVED economy,
                                      recorded for playback, and the average
                                      of `nights` nights beside the tuned
                                      defaults (services/jukebox/simulator.py).
                                      Reads only; runs off the event loop, one
                                      at a time (a second is a 409)
  POST   /api/jukebox/set/move        {from_index, to_index} — reorders the
                                      SET PLAYLIST in Spotify; during a night
                                      only songs two or more ahead may move
  POST   /api/jukebox/night/start     {play: true, start_index: 0,
                                      started_by: "press"|"sonic"}
  POST   /api/jukebox/night/stop      {pause: false}
  POST   /api/jukebox/line            {uri} — a song link, URI or id
  DELETE /api/jukebox/line/{id}       a waiting song leaves; a committed one
                                      is skipped as it starts; a playing one
                                      is skipped now
  POST   /api/jukebox/line/{id}/move  {to} — place among the waiting songs

A refusal is a RECORDED outcome answered with 200 and its reason
(`{"status": "refused", "reason": ..., "detail": ...}`), never a silence —
Absorb's convention.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from models.jukebox import ProgramConfig
from services.jukebox import guest_link, night, show, simulator, store
from services.jukebox.night import sentence

router = APIRouter(prefix="/api/jukebox", tags=["jukebox"])

CONFIG_KEYS = frozenset(ProgramConfig.model_fields)


def apply_config_patch(patch: dict) -> ProgramConfig:
    """THE validator for a program-settings edit: the stored settings with
    the patch on top, validated whole. Raises ValueError naming the key."""
    if not isinstance(patch, dict):
        raise ValueError("expected a JSON object")
    unknown = sorted(set(patch) - CONFIG_KEYS)
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}")
    merged = {**store.load_config().model_dump(mode="json"), **patch}
    try:
        cfg = ProgramConfig.model_validate(merged)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "settings"
        raise ValueError(f"{where}: {first.get('msg')}") from None
    return cfg


@router.get("/config")
async def get_config() -> dict:
    return store.load_config().model_dump(mode="json")


@router.put("/config")
async def put_config(request: Request, dry_run: bool = False) -> dict:
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="expected a JSON object")
    try:
        cfg = apply_config_patch(patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if dry_run:
        return {"dry_run": True, "config": cfg.model_dump(mode="json")}
    refusal = night.runner.apply_config(cfg)
    if refusal is not None:
        raise HTTPException(status_code=409, detail=refusal[1])
    store.save_config(cfg)
    return {"dry_run": False, "config": cfg.model_dump(mode="json")}


@router.get("/status")
async def get_status(count: int = 20) -> dict:
    return night.runner.status(count=max(1, min(int(count), 60)))


@router.get("/preview")
async def get_preview(count: int = 20, refresh: bool = False) -> dict:
    cfg = store.load_config()
    if not cfg.playlist.strip():
        return {"status": "refused", "reason": "no_playlist", "detail": sentence("no_playlist")}
    try:
        return await night.runner.preview(cfg, count=max(1, min(int(count), 60)),
                                          refresh=refresh)
    except Exception as exc:
        return {"status": "refused", "reason": "spotify_error",
                "detail": sentence("spotify_error", f"{type(exc).__name__}")}


class StartBody(BaseModel):
    play: bool = True
    start_index: int = 0
    started_by: Literal["press", "sonic"] = "press"   # Sonic's own start says so in the log


class StopBody(BaseModel):
    pause: bool = False


class AddBody(BaseModel):
    uri: str


class MoveBody(BaseModel):
    to: int


class SetMoveBody(BaseModel):
    from_index: int
    to_index: int


@router.post("/night/start")
async def post_start(body: StartBody = StartBody()) -> dict:
    return await night.runner.start(play=body.play, start_index=body.start_index,
                                    started_by=body.started_by)


@router.post("/night/stop")
async def post_stop(body: StopBody = StopBody()) -> dict:
    return await night.runner.stop(pause=body.pause)


@router.post("/line")
async def post_line(body: AddBody) -> dict:
    return await night.runner.add(body.uri, added_by="host")


@router.delete("/line/{entry_id}")
async def delete_line(entry_id: str) -> dict:
    return await night.runner.remove(entry_id)


@router.post("/line/{entry_id}/move")
async def post_move(entry_id: str, body: MoveBody) -> dict:
    return await night.runner.move(entry_id, body.to)


@router.post("/set/move")
async def post_set_move(body: SetMoveBody) -> dict:
    return await night.runner.move_set_song(body.from_index, body.to_index)


@router.get("/show")
async def get_show() -> dict:
    return show.read()


@router.put("/show")
async def put_show(request: Request, dry_run: bool = False) -> dict:
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="expected a JSON object")
    try:
        new = show.apply_patch(store.load_show(), patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not dry_run:
        store.save_show(new)
    return {"dry_run": dry_run, **show.read(new)}


class PresetBody(BaseModel):
    preset: str


@router.post("/show/preset")
async def post_preset(body: PresetBody) -> dict:
    try:
        new_show, new_program = show.apply_preset(body.preset, store.load_show(), store.load_config())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    refusal = night.runner.apply_config(new_program)
    if refusal is not None:
        raise HTTPException(status_code=409, detail=refusal[1])
    store.save_config(new_program)
    store.save_show(new_show)
    return {"config": new_program.model_dump(mode="json"), **show.read(new_show)}


@router.get("/price-check")
async def get_price_check(guests: int = 15) -> dict:
    return show.price_check(store.load_show().economy, max(1, min(int(guests), 100)))


class SimulateBody(BaseModel):
    guests: int = Field(20, ge=simulator.GUESTS_MIN, le=simulator.GUESTS_MAX)
    nights: int = Field(20, ge=simulator.NIGHTS_MIN, le=simulator.NIGHTS_MAX)
    seed: int = Field(1, ge=1, le=1_000_000)
    program: Literal["saved", "preset"] = "saved"


_simulating = asyncio.Lock()


def run_simulation(body: SimulateBody) -> dict:
    """The simulation itself, synchronous (the route runs it in a thread):
    the SAVED economy, and the saved program or the plan's preset for the
    party size."""
    cfg = store.load_config()
    if body.program == "preset":
        mix = simulator.program(body.guests)
        mode = "auto" if mix["set_per_slot"] else "jukebox_first"
        every, run = max(1, mix["set_per_slot"]), mix["juke_per_slot"]
    else:
        mode, every, run = cfg.mode, cfg.every, cfg.run
    out = simulator.simulate(body.guests, store.load_show().economy, mode=mode, every=every,
                             run=run, seed=body.seed, nights=body.nights)
    return {"program_source": body.program, **out}


@router.post("/simulate")
async def post_simulate(body: SimulateBody = SimulateBody()) -> dict:
    if _simulating.locked():
        raise HTTPException(status_code=409, detail="a simulation is already running")
    async with _simulating:
        return await asyncio.to_thread(run_simulation, body)


# ── the guest link (N1; services/jukebox/guest_link.py) ─────────────────────

@router.get("/guest-link")
async def get_guest_link() -> dict:
    return guest_link.controller.status()


@router.put("/guest-link")
async def put_guest_link(request: Request, dry_run: bool = False) -> dict:
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="expected a JSON object")
    try:
        return await guest_link.controller.edit(patch, dry_run=dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/guest-link/rotate")
async def post_guest_link_rotate() -> dict:
    return await guest_link.controller.rotate()


@router.post("/guest-link/self-test")
async def post_guest_link_self_test() -> dict:
    return await guest_link.controller.self_test()
