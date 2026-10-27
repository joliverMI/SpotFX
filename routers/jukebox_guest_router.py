"""
SpotFX — the Jukebox's GUEST routes (phase 2.1): the only door the guest
app (jukebox_guest/, its own process on :8020) uses into SpotFX. Every call
must carry the guest app's key (jukebox_guest/key.py) — :8000 is reachable
on the LAN, and these routes name a phone — so a phone never reaches them
directly, and a wrong or missing key is a plain 401.

  POST /api/jukebox/guest/hello   {phone?, token?}       a phone opens the page
  POST /api/jukebox/guest/join    {phone, name?}         "Let's go"
  POST /api/jukebox/guest/name    {phone, name?, shuffle} a new name
  POST /api/jukebox/guest/vote    {phone, vote: up|down|none}
  POST /api/jukebox/guest/search  {phone, q, offset}     his library first, then Spotify
  POST /api/jukebox/guest/add     {phone, uri}           a song into the line (fair order)
  POST /api/jukebox/guest/bump    {phone, entry_id, direction: up|down}  free play's bump
  GET  /api/jukebox/guest/view?phone=                    the screen, again

What each does is services/jukebox/guests.py; every answer carries the
phone's whole view, or a refusal with its sentence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import BASE_DIR
from jukebox_guest import key as guest_key
from services.jukebox import guests

router = APIRouter(prefix="/api/jukebox/guest", tags=["jukebox-guest"])

KEY_FILE = BASE_DIR / "storage" / "jukebox_guest_key"

_key_cache: dict[Path, str] = {}


def _cached_key(path: Path) -> str:
    key = _key_cache.get(path)
    if key is None:
        key = guest_key.load_or_create(path)
        _key_cache[path] = key
    return key


def _check(request: Request) -> None:
    given = request.headers.get(guest_key.HEADER)
    key = _cached_key(KEY_FILE)
    if guest_key.matches(given, key):
        return
    key = guest_key.load_or_create(KEY_FILE)
    _key_cache[KEY_FILE] = key
    if not guest_key.matches(given, key):
        raise HTTPException(status_code=401, detail="guest routes answer the guest app only")


def _answer(result: tuple[int, dict]) -> JSONResponse:
    code, body = result
    return JSONResponse(body, status_code=code)


Phone = Field(default=None, max_length=64)


class HelloBody(BaseModel):
    phone: Optional[str] = Phone
    token: Optional[str] = Field(default=None, max_length=128)


class JoinBody(BaseModel):
    phone: Optional[str] = Phone
    name: Optional[str] = Field(default=None, max_length=64)


class NameBody(BaseModel):
    phone: Optional[str] = Phone
    name: Optional[str] = Field(default=None, max_length=64)
    shuffle: bool = False


class VoteBody(BaseModel):
    phone: Optional[str] = Phone
    vote: str = Field(max_length=8)


class SearchBody(BaseModel):
    phone: Optional[str] = Phone
    q: str = Field(default="", max_length=120)
    offset: int = Field(default=0, ge=0, le=200)


class AddBody(BaseModel):
    phone: Optional[str] = Phone
    uri: str = Field(max_length=200)


class BumpBody(BaseModel):
    phone: Optional[str] = Phone
    entry_id: str = Field(max_length=40)
    direction: str = Field(max_length=8)


@router.post("/hello")
async def post_hello(body: HelloBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.hello(body.phone, body.token))


@router.post("/join")
async def post_join(body: JoinBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.join(body.phone, body.name))


@router.post("/name")
async def post_name(body: NameBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.rename(body.phone, body.name, body.shuffle))


@router.post("/vote")
async def post_vote(body: VoteBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.vote(body.phone, body.vote))


@router.post("/search")
async def post_search(body: SearchBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.search(body.phone, body.q, body.offset))


@router.post("/add")
async def post_add(body: AddBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.add(body.phone, body.uri))


@router.post("/bump")
async def post_bump(body: BumpBody, request: Request) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.bump(body.phone, body.entry_id, body.direction))


@router.get("/view")
async def get_view(request: Request, phone: Optional[str] = None) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.view(phone))
