"""THE LIGHT SHOW — phase 1 wire (spectra/services/show_actions.py is the
binding statement for what each action does and how it is put back;
show_output.py for the per-fixture holds).

  GET    /api/light-show/catalogue          every action kind + its params
  GET    /api/light-show/ha-scenes          his live Home Assistant scenes
  GET    /api/light-show/targets            fixtures and categories
  GET    /api/light-show/status             holds, levels, settings changed,
                                            running sets, the gate
  GET    /api/light-show/sets               his library
  POST   /api/light-show/sets               create / update one set
  DELETE /api/light-show/sets/{id}        409 + who uses it unless ?force=true
  POST   /api/light-show/sets/{id}/fire     run it NOW
  POST   /api/light-show/sets/{id}/preview  what it would change (writes nothing)
  POST   /api/light-show/fire               run ad-hoc steps NOW
  POST   /api/light-show/release/{device}   let one fixture go
  POST   /api/light-show/levels/{id}/end    end one Level early
  POST   /api/light-show/end                End show: put the room back

Nothing here takes or releases the room. A fire while SPECTRA does not own
it (or while a preview/camera/night run holds it) returns 409 with the
reason and runs nothing.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from spectra.models.light_show import ActionSet, ShowAction
from spectra.services import show_actions, show_output, show_refs, show_store

router = APIRouter(prefix="/api/light-show", tags=["spectra-light-show"])


class SetBody(BaseModel):
    id: Optional[str] = None
    name: str
    actions: list[ShowAction] = Field(default_factory=list)
    notes: str = ""
    #: a brand-new set only — place it right after this id (Duplicate);
    #: ignored when `id` names an existing set.
    after_id: Optional[str] = None


class FireBody(BaseModel):
    actions: list[ShowAction]
    name: str = "Quick action"


async def _broadcast() -> None:
    try:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast({"type": "light_show", **brief()})
    except Exception:                                    # noqa: BLE001
        pass


def brief() -> dict:
    return show_actions.brief()


@router.get("/catalogue")
async def get_catalogue():
    return show_actions.catalogue()


@router.get("/ha-scenes")
async def get_ha_scenes():
    """His live Home Assistant scene.* entities, for the "Activate HA
    scene" step's picker (spectra/services/ha_client.py's list_scenes) —
    a live network call, deliberately kept OUT of `get_catalogue()` above
    so every other catalogue read stays instant and network-free. Never
    a 4xx/5xx: unconfigured or unreachable both answer 200 with an empty
    list and `configured`/`error` naming why, exactly the fail-soft shape
    the Light Show's own HA actions share."""
    from spectra.services import ha_client
    states = await ha_client.list_scenes()
    return {"configured": ha_client.configured(), "scenes": states.scenes,
            "error": None if states.ok else (states.detail or None)}


@router.get("/targets")
async def get_targets():
    return show_output.list_targets()


@router.get("/status")
async def get_status():
    return {**show_actions.status(), **{"output": show_output.status()},
            "brief": brief()}


def _set_payload(s: ActionSet, sets: Optional[list[ActionSet]] = None,
                 sequences: Optional[list] = None) -> dict:
    """A set as the editor reads it: its steps, its problems and conflicts
    (calls checked through), and its references — what it calls and what
    calls it (spectra/services/show_refs.py)."""
    sets = show_store.list_sets() if sets is None else sets
    sequences = show_store.list_sequences() if sequences is None else sequences
    return {**s.model_dump(),
            "problems": show_actions.validate_set(s.actions, set_id=s.id),
            "conflicts": show_actions.conflicts(s.actions, set_id=s.id),
            **show_refs.references(s.id, sets, sequences)}


@router.get("/sets")
async def list_sets():
    sets = show_store.list_sets()
    sequences = show_store.list_sequences()
    return {"sets": [_set_payload(s, sets, sequences) for s in sets]}


@router.post("/sets")
async def upsert_set(body: SetBody):
    data = body.model_dump()
    if not data.get("id"):
        data.pop("id", None)
    after_id = data.pop("after_id", None)
    try:
        s = show_store.put_set(ActionSet(**data), after_id=after_id)
    except show_store.SetNameTaken as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except show_refs.SetReferenceCycle as exc:
        return JSONResponse(status_code=409, content={
            "detail": f"Not saved: {exc}.", "reason": "cycle"})
    # Saved even with problems — a half-built set is his to finish — but the
    # problems travel with it so the editor shows them.
    return _set_payload(s)


@router.delete("/sets/{set_id}")
async def remove_set(set_id: str, force: bool = False):
    """A set other sets call (or a sequence uses) is not deleted until the
    delete is FORCED — the 409 names who uses it, so the editor can ask.
    Forced, every call to it then fails by name until its caller is fixed."""
    if show_store.get_set(set_id) is None:
        return JSONResponse(status_code=404, content={"detail": "no such set"})
    refs = show_refs.references(set_id, show_store.list_sets(), show_store.list_sequences())
    users = refs["used_by"] + refs["used_in_sequences"]
    if users and not force:
        names = ", ".join(f"“{u['name']}”" for u in users)
        return JSONResponse(status_code=409, content={
            "detail": f"This set is used by {names}. Deleting it makes those "
                      f"steps fail until they are changed.",
            "reason": "in_use", "used_by": refs["used_by"],
            "used_in_sequences": refs["used_in_sequences"]})
    show_store.delete_set(set_id)
    return {"deleted": set_id, "was_used_by": refs["used_by"],
            "was_used_in_sequences": refs["used_in_sequences"]}


def _gate_or_none() -> Optional[JSONResponse]:
    reason = show_output.refusal()
    if reason:
        return JSONResponse(status_code=409, content={
            "detail": f"The Light Show is standing down: {reason}",
            "reason": reason})
    return None


@router.post("/sets/{set_id}/fire")
async def fire_set(set_id: str):
    s = show_store.find_set(set_id)
    if s is None:
        return JSONResponse(status_code=404, content={"detail": "no such set"})
    if (blocked := _gate_or_none()) is not None:
        return blocked
    try:
        run = await show_actions.fire_set(s.id)
    except show_actions.ActionError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    await _broadcast()
    return run


@router.post("/sets/{set_id}/preview")
async def preview_set(set_id: str):
    s = show_store.find_set(set_id)
    if s is None:
        return JSONResponse(status_code=404, content={"detail": "no such set"})
    return {"set": s.name, "steps": show_actions.preview(s.actions, set_id=s.id),
            "refusal": show_output.refusal()}


@router.post("/fire")
async def fire_actions(body: FireBody):
    if not body.actions:
        return JSONResponse(status_code=400, content={"detail": "no steps"})
    if (blocked := _gate_or_none()) is not None:
        return blocked
    run = await show_actions.fire(body.actions, name=body.name, source="button")
    await _broadcast()
    return run


@router.post("/release/{device_id}")
async def release_device(device_id: str, fade_ms: int = show_output.DEFAULT_RELEASE_FADE_MS):
    result = show_output.release_device(device_id, fade_ms)
    await _broadcast()
    return result


@router.post("/levels/{level_id}/end")
async def end_level(level_id: str):
    if not show_output.end_level(level_id):
        return JSONResponse(status_code=404, content={"detail": "no such level"})
    await _broadcast()
    return {"ended": level_id}


@router.post("/pulse-mods/{mod_id}/end")
async def end_pulse_mod(mod_id: str):
    from spectra.services import show_mods
    if not show_mods.end_pulse_mod(mod_id):
        return JSONResponse(status_code=404, content={"detail": "no such Pulse hold"})
    await _broadcast()
    return {"ended": mod_id}


@router.post("/flare-blocks/{block_id}/end")
async def end_flare_block(block_id: str):
    from spectra.services import show_mods
    if not show_mods.end_flare_block(block_id):
        return JSONResponse(status_code=404, content={"detail": "no such flares-off hold"})
    await _broadcast()
    return {"ended": block_id}


@router.post("/end")
async def end_show(fade_ms: int = show_output.DEFAULT_RELEASE_FADE_MS):
    result = await show_actions.end_show(fade_ms=fade_ms)
    await _broadcast()
    return result


# ── PHASE 2: arms and the High/Low Triggers ────────────────────────────────
# spectra/services/show_arms.py and show_cues.py are the binding statements.
#
#   GET    /api/light-show/arms                the armed board + history +
#                                              this song's High/Low
#   POST   /api/light-show/arms                arm a set (or one action)
#   DELETE /api/light-show/arms/{id}           disarm one
#   POST   /api/light-show/arms/disarm-all
#   GET    /api/light-show/cues?uri=           a song's High and Low
#   PUT    /api/light-show/cues                his dragged position
#   DELETE /api/light-show/cues?uri=&level=    back to automatic

import asyncio as _asyncio

from fastapi import Query as _Query

from spectra.services import show_arms, show_cues


class ArmBody(BaseModel):
    set_id: Optional[str] = None
    action: Optional[ShowAction] = None
    on: str = "scene_change"
    repeat: bool = False
    this_song_only: bool = False
    finish_on_mark: bool = True


class CueBody(BaseModel):
    uri: str
    level: str
    timestamp_ms: int


@router.get("/arms")
async def get_arms():
    return show_arms.status()


@router.post("/arms")
async def post_arm(body: ArmBody):
    try:
        arm = show_arms.arm(set_id=body.set_id, action=body.action, on=body.on,
                            repeat=body.repeat, this_song_only=body.this_song_only,
                            finish_on_mark=body.finish_on_mark, source="button")
    except show_arms.ArmError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    await _broadcast()
    # Armed even while the room is not SPECTRA's — the arm waits, and says so.
    return {**arm.model_dump(), "lead_ms": show_arms.lead_ms(arm),
            "refusal": show_output.refusal()}


@router.delete("/arms/{arm_id}")
async def delete_arm(arm_id: str):
    if not show_arms.disarm(arm_id):
        return JSONResponse(status_code=404, content={"detail": "no such armed set"})
    await _broadcast()
    return {"disarmed": arm_id}


@router.post("/arms/disarm-all")
async def disarm_all():
    ids = show_arms.disarm_all()
    await _broadcast()
    return {"disarmed": ids}


@router.get("/cues")
async def get_cues(uri: str = _Query(..., min_length=1)):
    cues = await _asyncio.to_thread(show_cues.cues_for_song, uri)
    return cues.as_dict()


@router.put("/cues")
async def put_cue(body: CueBody):
    try:
        saved = await _asyncio.to_thread(show_cues.set_override, body.uri,
                                         body.level, body.timestamp_ms)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    await _broadcast()
    return {"uri": body.uri, "level": body.level, **saved}


@router.delete("/cues")
async def delete_cue(uri: str = _Query(..., min_length=1),
                     level: str = _Query(...)):
    if level not in show_cues.LEVELS:
        return JSONResponse(status_code=400, content={"detail": "level must be high or low"})
    cleared = await _asyncio.to_thread(show_cues.clear_override, uri, level)
    await _broadcast()
    return {"uri": uri, "level": level, "reverted": cleared}


# ── SHOW SEQUENCES — ordered, pre-armed sets and Waits ─────────────────────
# spectra/services/show_sequence.py is the binding statement.
#
#   GET    /api/light-show/sequences                 his sequences (+ problems)
#   POST   /api/light-show/sequences                 create / update one
#   DELETE /api/light-show/sequences/{id}
#   POST   /api/light-show/sequences/{id}/duplicate  "<name> copy", right after it
#   GET    /api/light-show/sequence-run              the run: current item, what
#                                                    it waits for, the log
#   POST   /api/light-show/sequence-run/start        {sequence_id, replace}
#   POST   /api/light-show/sequence-run/{pause|resume|stop|next|previous|fire-now}
#   GET    /api/light-show/songs?q=&limit=           songs SPECTRA knows (a
#                                                    song-list Wait's picker)

from spectra.models.light_show import SequenceItem, ShowSequence
from spectra.services import show_sequence, song_library


class SequenceBody(BaseModel):
    id: Optional[str] = None
    name: str
    items: list[SequenceItem] = Field(default_factory=list)
    loop: bool = False
    notes: str = ""


class StartBody(BaseModel):
    sequence_id: str
    replace: bool = False


def _sequence_row(s: ShowSequence) -> dict:
    return {**s.model_dump(),
            "items": [{**it.model_dump(), "title": show_sequence.item_title(it),
                       "problems": show_sequence.item_problems(it)} for it in s.items],
            "problems": show_sequence.problems(s)}


async def _broadcast_sequence() -> None:
    try:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast({"type": "light_show_sequence",
                                    "run": show_sequence.status()["run"]})
    except Exception:                                    # noqa: BLE001
        pass


@router.get("/sequences")
async def list_sequences():
    return {"sequences": [_sequence_row(s) for s in show_store.list_sequences()]}


@router.post("/sequences")
async def upsert_sequence(body: SequenceBody):
    data = body.model_dump()
    if not data.get("id"):
        data.pop("id", None)
    try:
        s = show_store.put_sequence(ShowSequence(**data))
    except show_store.SequenceNameTaken as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    return _sequence_row(s)


@router.delete("/sequences/{seq_id}")
async def remove_sequence(seq_id: str):
    r = show_sequence.run()
    if r is not None and r.sequence_id == seq_id and r.state in show_sequence.ACTIVE_STATES:
        return JSONResponse(status_code=409, content={
            "detail": f"{r.name!r} is running — stop it before deleting it"})
    if not show_store.delete_sequence(seq_id):
        return JSONResponse(status_code=404, content={"detail": "no such sequence"})
    return {"deleted": seq_id}


@router.post("/sequences/{seq_id}/duplicate")
async def duplicate_sequence(seq_id: str):
    s = show_store.duplicate_sequence(seq_id)
    if s is None:
        return JSONResponse(status_code=404, content={"detail": "no such sequence"})
    return _sequence_row(s)


@router.get("/sequence-run")
async def get_sequence_run():
    return show_sequence.status()


async def _control(fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
        if _asyncio.iscoroutine(res):
            await res
    except show_sequence.SequenceError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    await _broadcast_sequence()
    await _broadcast()
    return show_sequence.status()


@router.post("/sequence-run/start")
async def start_sequence(body: StartBody):
    return await _control(show_sequence.start, body.sequence_id, replace=body.replace)


@router.post("/sequence-run/pause")
async def pause_sequence():
    return await _control(show_sequence.pause)


@router.post("/sequence-run/resume")
async def resume_sequence():
    return await _control(show_sequence.resume)


@router.post("/sequence-run/stop")
async def stop_sequence():
    return await _control(show_sequence.stop)


@router.post("/sequence-run/next")
async def next_sequence_item():
    return await _control(show_sequence.next_item)


@router.post("/sequence-run/previous")
async def previous_sequence_item():
    return await _control(show_sequence.previous_item)


@router.post("/sequence-run/fire-now")
async def fire_sequence_item_now():
    return await _control(show_sequence.fire_now)


@router.get("/songs")
async def search_songs(q: str = "", limit: int = _Query(song_library.DEFAULT_LIMIT, ge=1, le=200)):
    found = await _asyncio.to_thread(song_library.search, q, limit)
    playing = show_sequence.status()["playing_uri"]
    now = None
    if playing:
        hit = await _asyncio.to_thread(song_library.lookup, playing)
        now = (hit.as_dict() if hit else {"uri": playing, "title": playing, "artist": ""})
    return {"songs": [s.as_dict() for s in found], "playing": now}


# ── SHOW PLAYLISTS — programs keyed to the Spotify playlists he plays ──────
# spectra/services/show_playlists.py is the binding statement. Spectra
# FOLLOWS playback; nothing here starts, queues or skips a song.
#
#   GET    /api/light-show/playlists                 his programs (+ problems)
#   POST   /api/light-show/playlists                 create / update one
#   DELETE /api/light-show/playlists/{id}            409 while it is following
#   POST   /api/light-show/playlists/{id}/duplicate  "<name> copy", no context
#   PUT    /api/light-show/playlists/follow          {enabled} the global switch
#   GET    /api/light-show/playlist-run              the run, its song, up next
#   POST   /api/light-show/playlist-run/start        {playlist_id | name, replace}
#   POST   /api/light-show/playlist-run/{stop|resume|skip-song}
#   POST   /api/light-show/playlist-run/fire-step    {step_id}
#   GET    /api/light-show/context-name?uri=         a Spotify context's name

from spectra.models.light_show import ShowPlaylist
from spectra.services import show_playlists


class PlaylistBody(ShowPlaylist):
    id: Optional[str] = None
    #: a brand-new program only — place it right after this id
    after_id: Optional[str] = None


class PlaylistStartBody(BaseModel):
    playlist_id: Optional[str] = None
    name: Optional[str] = None
    replace: bool = False


class FollowBody(BaseModel):
    enabled: bool


class FireStepBody(BaseModel):
    step_id: str


def _playlist_row(p: ShowPlaylist) -> dict:
    def steps(items):
        return [{**st.model_dump(), "title": show_playlists.step_title(st),
                 "problems": show_playlists.step_problems(st)} for st in items]
    d = p.model_dump()
    d["on_start"]["steps"] = steps(p.on_start.steps)
    d["on_end"]["steps"] = steps(p.on_end.steps)
    if p.default_song is not None:
        d["default_song"]["steps"] = steps(p.default_song.steps)
    d["songs"] = [{**e.model_dump(), "steps": steps(e.steps),
                   "summary": show_playlists.entry_summary(e)} for e in p.songs]
    d["problems"] = show_playlists.problems(p)
    return d


async def _broadcast_playlist() -> None:
    try:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast({"type": "light_show_playlist",
                                    "run": show_playlists.status()["run"]})
    except Exception:                                    # noqa: BLE001
        pass


@router.get("/playlists")
async def list_playlists():
    lib = show_store.load_playlists()
    return {"playlists": [_playlist_row(p) for p in lib.playlists],
            "follow_enabled": lib.follow_enabled}


@router.post("/playlists")
async def upsert_playlist(body: PlaylistBody):
    data = body.model_dump()
    if not data.get("id"):
        data.pop("id", None)
    after_id = data.pop("after_id", None)
    try:
        p = show_store.put_playlist(ShowPlaylist(**data), after_id=after_id)
    except show_store.PlaylistConflict as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    # Saved even with problems (a half-built program is his to finish); the
    # problems travel with it.
    return _playlist_row(p)


@router.put("/playlists/follow")
async def put_follow(body: FollowBody):
    on = show_playlists.set_follow(body.enabled)
    return {"follow_enabled": on}


@router.delete("/playlists/{pl_id}")
async def remove_playlist(pl_id: str):
    r = show_playlists.run()
    if r is not None and r.playlist_id == pl_id and r.state in show_playlists.ACTIVE_STATES:
        return JSONResponse(status_code=409, content={
            "detail": f"{r.name!r} is following — stop it before deleting it"})
    if not show_store.delete_playlist(pl_id):
        return JSONResponse(status_code=404, content={"detail": "no such playlist program"})
    return {"deleted": pl_id}


@router.post("/playlists/{pl_id}/duplicate")
async def duplicate_playlist(pl_id: str):
    p = show_store.duplicate_playlist(pl_id)
    if p is None:
        return JSONResponse(status_code=404, content={"detail": "no such playlist program"})
    return _playlist_row(p)


@router.get("/playlist-run")
async def get_playlist_run():
    return show_playlists.status()


async def _playlist_control(fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
        if _asyncio.iscoroutine(res):
            await res
    except show_playlists.PlaylistError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    await _broadcast_playlist()
    await _broadcast()
    return show_playlists.status()


@router.post("/playlist-run/start")
async def start_playlist(body: PlaylistStartBody):
    """Follow a program now (a button, Sonic, Home Assistant) — whatever is
    playing. Open like sequence-run/start."""
    key = body.playlist_id or body.name
    if not key:
        return JSONResponse(status_code=400, content={"detail": "name a playlist program"})
    return await _playlist_control(show_playlists.start, key, replace=body.replace,
                                   source="button")


@router.post("/playlist-run/stop")
async def stop_playlist():
    return await _playlist_control(show_playlists.stop)


@router.post("/playlist-run/resume")
async def resume_playlist():
    return await _playlist_control(show_playlists.resume)


@router.post("/playlist-run/skip-song")
async def skip_playlist_song():
    return await _playlist_control(show_playlists.skip_song)


@router.post("/playlist-run/fire-step")
async def fire_playlist_step(body: FireStepBody):
    return await _playlist_control(show_playlists.fire_step, body.step_id)


@router.get("/context-name")
async def get_context_name(uri: str = _Query(..., min_length=1)):
    """A Spotify context's friendly name: the bridge's when it is the one
    playing, else asked of SpotFX (read-only). "" when unknown."""
    from spectra.services import spotify_context
    name = await _asyncio.to_thread(spotify_context.name_for, uri)
    return {"uri": uri, "name": name}
