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
  GET  /api/jukebox/guest/view?phone=                    the screen, again

What each does is services/jukebox/guests.py; every answer carries the
phone's whole view, or a refusal with its sentence.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import BASE_DIR
from jukebox_guest import key as guest_key
from services.jukebox import guests

router = APIRouter(prefix="/api/jukebox/guest", tags=["jukebox-guest"])

KEY_FILE = BASE_DIR / "storage" / "jukebox_guest_key"


def _check(request: Request) -> None:
    if not guest_key.matches(request.headers.get(guest_key.HEADER),
                             guest_key.load_or_create(KEY_FILE)):
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


@router.get("/view")
async def get_view(request: Request, phone: Optional[str] = None) -> JSONResponse:
    _check(request)
    return _answer(await guests.book.view(phone))
