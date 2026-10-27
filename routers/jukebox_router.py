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
  POST   /api/jukebox/set/move        {from_index, to_index} — reorders the
                                      SET PLAYLIST in Spotify; during a night
                                      only songs two or more ahead may move
  POST   /api/jukebox/night/start     {play: true, start_index: 0}
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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from models.jukebox import ProgramConfig
from services.jukebox import night, store
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
                              started_by="press")


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
