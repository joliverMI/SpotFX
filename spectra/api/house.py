"""HOUSE LIGHTING — the wire (spectra/services/house.py is the binding
statement for what a mode does; spectra/models/house_mode.py for its shape).

  GET    /api/house/modes          his modes + every Home Assistant alias
  POST   /api/house/modes          create / update one mode
  DELETE /api/house/modes/{id}
  GET    /api/house/mode           which mode, set by whom, what it is doing
                                   (the same payload as engine status's
                                   `lighting` key)
  POST   /api/house/mode           select a mode — THE call Home Assistant
  PUT    /api/house/mode           makes, on Spectra's own port 8010:
                                     {"ha_mode": "Evening", "source": "ha"}
                                   or by name/id: {"mode": "Evening"}
                                   or clear: {"clear": true}
  GET    /api/house/targets        fixtures, categories, Hue areas

PHASE 2 — the rest of the Home Assistant seam (docs/HOUSE_HA_SEAM.md has
every shape with examples; each call is RECORDED whatever the room's state
and ACTED ON only while a mode drives the room):

  GET    /api/house/heartbeat      one-word state for HA's fallback
  PUT    /api/house/fixture/{id}   {"state": "on"|"off"} and/or
  POST                             {"lent_to": "hyperion"|null}
  GET    /api/house/fixtures       every override and what was applied
  PUT    /api/house/tv-music       {"on": true|false} — OFF lends the TV strip
  POST                             to Hyperion, ON takes it back
  PUT    /api/house/media          {"source": "roku", "state": "playing" |
  POST                             "paused" | "idle" | "stopped"} — drives
                                   the TV mode and lends the TV strip
  POST   /api/house/voice          {"state": "listening" | "processing" |
                                   "responding" | "idle"} — never waits
  POST   /api/house/recheck        {"fixtures": [...]} — "the mains are on"
  PUT    /api/house/mains          {"fixtures": [...], "on": false|true} —
  POST                             phase 3: mains off = no stream, no search
  GET    /api/house/settings       the seam's settings (TV strip, voice
  PUT                              fixtures and colours, owned brightness)
                                   and phase 4's CUTOVER SWITCH
                                   {"enabled": true|false} plus the Hue
                                   bulbs a mode leaves alone
                                   {"hue_excluded_lights": [...]}

Selecting a mode is idempotent (the same value again is a no-op, so HA's
5-minute re-assert is a cheap heartbeat) and always 200 with a `status`
word: applied / unchanged / held_manual / unmapped / cleared. An unknown
mode NAME is 404 — that is a typo in a request, not a heartbeat. Nothing
here takes or releases the room: a mode set while the room is not
SPECTRA's is recorded and applies when SPECTRA holds it.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from spectra.models.house_mode import HouseMode
from spectra.services import house, house_store

router = APIRouter(prefix="/api/house", tags=["spectra-house"])


class ModeRequest(BaseModel):
    mode: Optional[str] = None
    ha_mode: Optional[str] = None
    source: str = "spectra"
    glide_s: Optional[float] = None
    clear: bool = False


def validate_mode(mode: HouseMode) -> tuple[list[str], list[str]]:
    """(problems, warnings). A problem refuses the save: a scene, colour
    set or category that does not exist would make the mode silently do
    nothing. A fixture or Hue area the LIVE room does not show is only a
    warning — it may be outside today's take, or the room may be released."""
    from spectra.services import color_sets, scene_store
    problems: list[str] = []
    warnings: list[str] = []
    for p in mode.scenes:
        if scene_store.get_by_id(p.scene_id) is None:
            problems.append(f"no scene {p.scene_id!r}")
    for p in mode.color_sets:
        if color_sets.get_by_id(p.card_id) is None:
            problems.append(f"no colour set or group {p.card_id!r}")
    try:
        from fx import device_model
        cats = {c.get("name") for c in device_model.list_categories()
                if isinstance(c, dict)}
    except Exception:                                    # noqa: BLE001
        cats = None
    from spectra.services import show_output
    host = show_output._host()
    for i, h in enumerate(mode.fixtures, 1):
        if h.target.kind == "category" and cats is not None and h.target.id not in cats:
            problems.append(f"fixture setting {i}: no category {h.target.id!r}")
        if h.target.kind == "fixture" and host is not None and h.target.id not in host.devices:
            warnings.append(f"fixture setting {i}: {h.target.id!r} is not in the live room")
        if (h.level is None and h.motion is None and h.fps is None and not h.off):
            warnings.append(f"fixture setting {i} sets nothing")
    areas = [lk.area for lk in mode.hue]
    if len(areas) != len(set(areas)):
        problems.append("a Hue area appears twice")
    if host is not None:
        hue_ids = {d for d in host.devices
                   if getattr(host.devices.get(d), "type", None) == "hue"}
        for a in areas:
            if a != "*" and a not in hue_ids:
                warnings.append(f"Hue area {a!r} is not in the live room")
    return problems, warnings


@router.get("/modes")
async def get_modes() -> dict:
    modes = house_store.list_modes()
    aliases = {a: m.name for m in modes for a in m.ha_aliases}
    return {"modes": [m.model_dump() for m in modes], "aliases": aliases,
            "current_mode_id": house_store.state().mode_id}


@router.post("/modes")
async def post_mode(body: dict):
    try:
        mode = HouseMode(**body)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                                for e in exc.errors())})
    problems, warnings = validate_mode(mode)
    if problems:
        return JSONResponse(status_code=422, content={"detail": "; ".join(problems),
                                                      "problems": problems})
    try:
        saved = house_store.put_mode(mode)
    except house_store.ModeConflict as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    live_mode = house.current_mode()
    if saved.id in (house_store.state().mode_id,
                    live_mode.id if live_mode is not None else None):
        await house.tick()       # an edit to the live mode lands now
    return {"mode": saved.model_dump(), "warnings": warnings}


@router.delete("/modes/{mode_id}")
async def delete_mode(mode_id: str):
    was_current = house_store.state().mode_id == mode_id
    if not house_store.delete_mode(mode_id):
        return JSONResponse(status_code=404, content={"detail": "no such mode"})
    out: dict = {"deleted": mode_id}
    if was_current:
        res = await house.set_mode(clear=True, source="spectra")
        out["cleared"] = True
        out["lighting"] = res["lighting"]
    return out


@router.get("/mode")
async def get_mode() -> dict:
    return house.status()


async def _select(body: ModeRequest):
    res = await house.set_mode(mode=body.mode, ha_mode=body.ha_mode,
                               source=body.source, glide_s=body.glide_s,
                               clear=body.clear)
    if res.get("status") == "unknown_mode":
        return JSONResponse(status_code=404, content={"detail": res["reason"], **res})
    return res


@router.post("/mode")
async def post_select(body: ModeRequest):
    return await _select(body)


@router.put("/mode")
async def put_select(body: ModeRequest):
    return await _select(body)


# ── phase 2: the rest of the Home Assistant seam ──────────────────────────

class FixtureRequest(BaseModel):
    state: Optional[str] = None
    lent_to: Optional[str] = None
    source: str = "ha"


class TvMusicRequest(BaseModel):
    on: bool
    source: str = "ha"


class MediaRequest(BaseModel):
    source: Optional[str] = None
    state: str
    origin: str = "ha"


class VoiceRequest(BaseModel):
    state: str
    source: str = "ha"


class RecheckRequest(BaseModel):
    fixtures: list[str]


@router.get("/heartbeat")
async def get_heartbeat() -> dict:
    return house.heartbeat()


@router.get("/fixtures")
async def get_fixtures() -> dict:
    from spectra.services import house_fixtures
    return house_fixtures.status()


async def _fixture(fixture_id: str, body: FixtureRequest):
    from spectra.services import house_fixtures
    sent = body.model_fields_set
    kw: dict = {"source": body.source}
    if "state" in sent:
        kw["power"] = body.state
    if "lent_to" in sent:
        kw["lent_to"] = body.lent_to
    if "power" not in kw and "lent_to" not in kw:
        return JSONResponse(status_code=422, content={
            "detail": "send \"state\" (\"on\"/\"off\") and/or \"lent_to\""})
    res = house_fixtures.set_fixture(fixture_id, **kw)
    if res["status"] == "unknown_fixture":
        return JSONResponse(status_code=404, content={"detail": res["reason"], **res})
    if res["status"] == "invalid":
        return JSONResponse(status_code=422, content={"detail": res["reason"], **res})
    res["acting"] = house.layer_active()
    if not res["acting"]:
        res["note"] = (f"recorded — not acted on: {house.inactive_reason()}")
    return res


@router.put("/fixture/{fixture_id}")
async def put_fixture(fixture_id: str, body: FixtureRequest):
    return await _fixture(fixture_id, body)


@router.post("/fixture/{fixture_id}")
async def post_fixture(fixture_id: str, body: FixtureRequest):
    return await _fixture(fixture_id, body)


async def _tv_music(body: TvMusicRequest):
    from spectra.services import house_fixtures
    return house_fixtures.set_tv_music(body.on, source=body.source)


@router.put("/tv-music")
async def put_tv_music(body: TvMusicRequest):
    return await _tv_music(body)


@router.post("/tv-music")
async def post_tv_music(body: TvMusicRequest):
    return await _tv_music(body)


async def _media(body: MediaRequest):
    res = await house.set_media(source=body.source, state=body.state,
                                source_from=body.origin)
    if res.get("status") == "invalid":
        return JSONResponse(status_code=422, content={"detail": res["reason"], **res})
    return res


@router.put("/media")
async def put_media(body: MediaRequest):
    return await _media(body)


@router.post("/media")
async def post_media(body: MediaRequest):
    return await _media(body)


@router.post("/voice")
async def post_voice(body: VoiceRequest):
    """Never waits: the voice pipeline calls this and moves on."""
    from spectra.services import house_voice
    res = house_voice.set_voice(body.state, source=body.source)
    if res.get("status") == "invalid":
        return JSONResponse(status_code=422, content={"detail": res["reason"], **res})
    return res


@router.post("/recheck")
async def post_recheck(body: RecheckRequest):
    from spectra.services import house_fixtures
    res = house_fixtures.recheck(body.fixtures)
    if res.get("status") == "invalid":
        return JSONResponse(status_code=422, content={"detail": res["reason"], **res})
    return res


class MainsRequest(BaseModel):
    fixtures: list[str] = []
    on: bool
    source: str = "ha"


@router.put("/mains")
async def put_mains(body: MainsRequest):
    """Home Assistant reports a fixture's MAINS supply switched (the kitchen
    sconces on light.dimmer_kitchen_sconce). OFF: no stream and no search
    while a mode drives the room. ON: cleared, and the fixtures are re-found
    at once (the recheck). Spectra never switches the mains itself."""
    from spectra.services import house_fixtures
    res = house_fixtures.set_mains(body.fixtures, body.on, source=body.source)
    if res.get("status") == "invalid":
        code = 404 if res.get("unknown") else 422
        return JSONResponse(status_code=code, content={"detail": res.get("reason"), **res})
    if not res["acting"]:
        res["note"] = f"recorded — not acted on: {house.inactive_reason()}"
    return res


@router.post("/mains")
async def post_mains(body: MainsRequest):
    return await put_mains(body)


@router.get("/settings")
async def get_settings() -> dict:
    return {"settings": house_store.load_library().settings.model_dump()}


@router.put("/settings")
async def put_settings(body: dict):
    from spectra.models.house_mode import HouseSettings
    current = house_store.load_library().settings.model_dump()
    body = dict(body or {})
    if isinstance(body.get("voice_looks"), dict):
        # A partial edit of one voice state keeps every other state as HE
        # set it, not as the defaults.
        looks = {k: dict(v) for k, v in current["voice_looks"].items()}
        for state, look in body["voice_looks"].items():
            looks[state] = {**looks.get(state, {}),
                            **(look if isinstance(look, dict) else {})}
        body["voice_looks"] = looks
    if isinstance(body.get("energy"), dict):
        # A partial edit of the energy block (one keep-alive, one cap)
        # keeps everything else in it as he set it.
        energy = dict(current.get("energy") or {})
        patch = dict(body["energy"])
        if isinstance(patch.get("resting_fps"), dict):
            fps = dict(energy.get("resting_fps") or {})
            for k, v in patch["resting_fps"].items():
                if v is None:
                    fps.pop(k, None)
                else:
                    fps[k] = v
            patch["resting_fps"] = fps
        body["energy"] = {**energy, **patch}
    try:
        merged = HouseSettings(**{**current, **body})
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                                for e in exc.errors())})
    saved = house_store.put_settings(merged)
    from spectra.services import house_fixtures
    house_fixtures.kick()
    if "energy" in body:
        # Resting caps are part of the mode's plan: re-enter so a changed
        # default lands now, not at the next mode change.
        await house.reapply()
    out: dict = {"settings": saved.model_dump()}
    if (current.get("enabled") != saved.enabled
            or current.get("hue_excluded_lights") != saved.hue_excluded_lights):
        # THE CUTOVER SWITCH (or the bulbs it leaves alone) moved: apply it
        # now rather than on the supervisor's next pass, and say what the
        # room is doing as a result.
        house._record("switched", {"enabled": saved.enabled,
                                   "hue_excluded_lights": saved.hue_excluded_lights})
        await house.tick()
        out["lighting"] = house.status_dict()
    return out


@router.get("/targets")
async def get_targets() -> dict:
    from spectra.services import ambient, show_output
    out = show_output.list_targets()
    try:
        out["hue_areas"] = await ambient.list_groups()
    except Exception:                                    # noqa: BLE001
        out["hue_areas"] = []
    return out
