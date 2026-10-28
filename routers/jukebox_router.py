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
                                      line, warnings, the log, and how many
                                      phones joined (`guests`) — reads only
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
  GET    /api/jukebox/card            the printable card (N2): the join link
                                      (making the party token if there is none
                                      yet), the unused bonus codes, the bonus
                                      amount and the play mode
  GET    /api/jukebox/report          the post-party report of the latest night
                                      (services/jukebox/night_report.py): what
                                      it played, its line, its credits ledger
                                      when guests used one, and — with a party
                                      size (`?guests=`, else the ledger's
                                      phones) — each measure beside the model's
                                      nights at that size. Reads only
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
  POST   /api/jukebox/line/{id}/move  {to, play_next?} — place among the waiting
                                      songs (the host's Play next may jump the set)
  POST   /api/jukebox/line/{id}/hold  {held} — the host holds a waiting song
                                      (it keeps its place; slots pass it) or
                                      lets it go
  GET    /api/jukebox/guests          tonight's phones (services/jukebox/
                                      guests.py): name, approval, block, name
                                      lock, songs, votes
  POST   /api/jukebox/guests/{phone}  {approved?, blocked?, name_locked?,
                                      name?} — the host's controls over a phone
  POST   /api/jukebox/guests/{phone}/zero   the host's zero: its credits to 0
                                      (credits mode)
  POST   /api/jukebox/guests/{phone}/merge  {retire: phone id} — that phone
                                      joins this one: one guest (§4, §12)
  GET    /api/jukebox/economy         the Live tab's economy panel (services/
                                      jukebox/economy_live.py): credits now,
                                      prices now, recent events — reads only
  GET    /api/jukebox/board           the board (services/jukebox/board.py):
                                      tonight's top songs, every people board
                                      marked shown or not, the song playing
  POST   /api/jukebox/gift            {to: "everyone" | phone id, amount}
                                      the host's gift (credits mode)
  GET    /api/jukebox/bonus-codes     the printed bonus cards' codes
  POST   /api/jukebox/bonus-codes     {count, batch?} — make one-time codes
  DELETE /api/jukebox/bonus-codes/{code}  void an unused code

A refusal is a RECORDED outcome answered with 200 and its reason
(`{"status": "refused", "reason": ..., "detail": ...}`), never a silence —
Absorb's convention.
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from models.jukebox import ProgramConfig
from services.jukebox import (bonus_codes, guest_link, guests, night, night_report, show, simulator,
                              store)
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
    out = night.runner.status(count=max(1, min(int(count), 60)))
    running = (out.get("night") or {}).get("id") if out.get("running") else None
    out["guests"] = guests.book.summary(running)
    return out


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
    play_next: bool = False          # the host's Play next (it may jump the set; a drag never does)


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
    return await night.runner.move(entry_id, body.to, play_next=body.play_next)


class HoldBody(BaseModel):
    held: bool


class SkipLockBody(BaseModel):
    uri: str = Field(max_length=200)
    locked: bool = True


class PhoneBody(BaseModel):
    approved: Optional[bool] = None
    blocked: Optional[bool] = None
    name_locked: Optional[bool] = None
    name: Optional[str] = Field(default=None, max_length=64)
    pardon: bool = False                  # end its time-out now (free play's jail, PR 2.3)


@router.post("/line/{entry_id}/hold")
async def post_hold(entry_id: str, body: HoldBody) -> dict:
    return await night.runner.hold(entry_id, body.held)


@router.post("/skip-lock")
async def post_skip_lock(body: SkipLockBody) -> dict:
    """Keep a song from every skip tonight — the room's vote and a paid
    skip alike (report §12, "Skip griefing") — or let it be skipped again."""
    return await night.runner.set_skip_lock(body.uri, body.locked)


@router.get("/guests")
async def get_guests() -> dict:
    return guests.book.phones()


@router.get("/economy")
async def get_economy() -> dict:
    """The Live tab's economy panel (report §9 3.3, §7): the credits right
    now, the prices a guest sees now, and the night's recent events."""
    return guests.book.economy()


@router.get("/board")
async def get_board() -> dict:
    """The board (services/jukebox/board.py) for his own pages: the Guests
    tab's Board card and the TV page — every people board, each marked with
    whether guests see it, and the song playing with its votes."""
    return guests.book.host_board()


@router.post("/guests/{phone}")
async def post_guest(phone: str, body: PhoneBody) -> JSONResponse:
    code, out = await guests.book.host_set(phone, approved=body.approved, blocked=body.blocked,
                                           name_locked=body.name_locked, name=body.name,
                                           pardon=body.pardon)
    return JSONResponse(out, status_code=code)


@router.post("/guests/{phone}/zero")
async def post_guest_zero(phone: str) -> JSONResponse:
    """The host's zero (report §4, §12): this phone's credits to 0."""
    code, out = await guests.book.zero(phone)
    return JSONResponse(out, status_code=code)


class MergeBody(BaseModel):
    retire: str = Field(max_length=60)          # the phone that joins this one


@router.post("/guests/{phone}/merge")
async def post_guest_merge(phone: str, body: MergeBody) -> JSONResponse:
    """The host's merge (report §4, §12): `retire` and this phone are one
    guest — everything of `retire` joins this phone."""
    code, out = await guests.book.merge(body.retire, phone)
    return JSONResponse(out, status_code=code)


class GiftBody(BaseModel):
    to: str = Field(max_length=60)              # "everyone", or a phone's id
    amount: int = 2


@router.post("/gift")
async def post_gift(body: GiftBody) -> JSONResponse:
    """The host's gift (report §4: "Everyone +2", "Give…"), credits mode only."""
    code, out = await guests.book.gift(body.to, body.amount)
    return JSONResponse(out, status_code=code)


class MintBody(BaseModel):
    count: int = Field(ge=1, le=bonus_codes.MINT_MAX)
    batch: str = Field("", max_length=40)


def _bonus_read() -> dict:
    try:
        return bonus_codes.summary()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/bonus-codes")
async def get_bonus_codes() -> dict:
    """Every printed bonus card's code, unused first (report §9's N2)."""
    return await asyncio.to_thread(_bonus_read)


@router.post("/bonus-codes")
async def post_bonus_codes(body: MintBody) -> dict:
    """Make a batch of one-time codes for the printed cards."""
    try:
        made = await asyncio.to_thread(bonus_codes.mint, body.count, body.batch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"made": [bonus_codes.pretty(c) for c in made], **await asyncio.to_thread(_bonus_read)}


@router.delete("/bonus-codes/{code}")
async def delete_bonus_code(code: str) -> dict:
    """Void an UNUSED code (a lost card). A used one is kept, as a record."""
    try:
        gone = await asyncio.to_thread(bonus_codes.void, code)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not gone:
        raise HTTPException(status_code=404, detail="No unused code like that.")
    return await asyncio.to_thread(_bonus_read)


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
    old = store.load_show()
    try:
        new = show.apply_patch(old, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not dry_run:
        store.save_show(new)
        if new.play_mode != old.play_mode:
            await night.runner.convert_jail_mode(new.play_mode == "credits", new.free_jail_songs)
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


# ── the printed card (N2): the join link, the unused bonus codes ─────────────

def _card_read() -> dict:
    st = guest_link.controller.status()
    try:
        codes = bonus_codes.summary()
        err = None
    except ValueError as exc:
        codes, err = {"codes": []}, str(exc)
    show_cfg = store.load_show()
    return {"link": st["link"], "host": st["host"], "state": st["state"],
            "public_port": st["config"]["public_port"], "token_created_ms": st["token_created_ms"],
            "unused": [c["code"] for c in codes["codes"] if not c["used"]], "codes_error": err,
            "qr_bonus": show_cfg.economy.qr_bonus, "play_mode": show_cfg.play_mode}


@router.get("/card")
async def get_card() -> dict:
    """What the printable card (report §9's N2) needs: the join link with the
    party token — made now if there is none yet, since the cards carry it —
    the unused bonus codes and the QR bonus. The Wi-Fi name and password are
    typed on the card page and never reach SpotFX. The mint is serialized
    with every other guest-link mutator (edit/rotate/on_night_start) before
    the rest of the read runs off the loop, so a card read racing a night
    start can't each mint and save a different token."""
    await guest_link.controller.ensure_token_async()
    return await asyncio.to_thread(_card_read)


# ── the post-party report (PR 3.3's report: every model row, the model's way) ──

def build_report(guests: Optional[int], nights: int, now_ms: int) -> dict:
    runner = night.runner
    runner._ensure_loaded()
    n = runner.night
    show_cfg = store.load_show()
    program_cfg = store.load_config()
    entries, verify = night_report.load_entries(n.id if n else "", show_cfg.economy)
    book = night_report.load_book(n.id if n else "")
    out = night_report.build(n, entries, show_cfg.economy, now_ms=now_ms, guests=guests,
                             mode=program_cfg.mode, every=program_cfg.every,
                             run=program_cfg.run, nights=nights, verify=verify, book=book)
    return {"program_from": "your saved program and credits settings", **out}


@router.get("/report")
async def get_report(guests: Optional[int] = None, nights: int = 20) -> dict:
    if guests is not None and not simulator.GUESTS_MIN <= guests <= simulator.GUESTS_MAX:
        raise HTTPException(status_code=422, detail=f"guests must be "
                            f"{simulator.GUESTS_MIN}-{simulator.GUESTS_MAX}")
    nights = max(simulator.NIGHTS_MIN, min(int(nights), simulator.NIGHTS_MAX))
    if _simulating.locked():
        raise HTTPException(status_code=409, detail="a simulation is already running")
    import time as _time
    async with _simulating:
        return await asyncio.to_thread(build_report, guests, nights, int(_time.time() * 1000))
