"""The Sung words lane's matches (lyrics plan step 3): what Claude guessed a
song's words are about, and his own corrections. Nothing here reaches the
lights. spectra/services/lyric_matches.py is the binding statement.

  GET  /api/testbed/lyric-matches?uri=          the matches and how fresh they are
  POST /api/testbed/lyric-matches/read?uri=     Claude reads this song, now
  POST /api/testbed/lyric-matches/add           he matches words himself
  POST /api/testbed/lyric-matches/delete        he takes a match off
  POST /api/testbed/lyric-matches/restore-deleted?uri=  brings his deleted ones back
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from spectra.models.lyric_labels import TargetRef
from spectra.services import claude_text, lyric_matches, lyric_reading, sung_labels

router = APIRouter(prefix="/api/testbed/lyric-matches", tags=["spectra-lyric-matches"])


@router.get("")
async def get_matches(uri: str = Query(...)):
    try:
        data = await asyncio.to_thread(lyric_matches.payload, uri)
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    return {**data, "claude": claude_text.availability()}


@router.post("/read")
async def read_now(uri: str = Query(...)):
    """His press. Replaces Claude's previous reading of this song; his own
    edits are kept apart from it."""
    try:
        data = await lyric_reading.read_song(uri)
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    except (lyric_reading.NoUsableWords, lyric_reading.NoLabels) as exc:
        raise HTTPException(409, str(exc)) from exc
    except claude_text.ClaudeUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except claude_text.ClaudeReplyInvalid as exc:
        raise HTTPException(502, str(exc)) from exc
    return {**data, "claude": claude_text.availability()}


class AddBody(BaseModel):
    uri: str = Field(min_length=1)
    first_word: int = Field(ge=0)
    last_word: int = Field(ge=0)
    target: TargetRef


@router.post("/add")
async def add_match(body: AddBody):
    try:
        data = await asyncio.to_thread(lyric_matches.add, body.uri, body.first_word,
                                       body.last_word, body.target)
    except lyric_matches.MatchRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    return {**data, "claude": claude_text.availability()}


class DeleteBody(BaseModel):
    uri: str = Field(min_length=1)
    id: str = Field(min_length=1)


@router.post("/delete")
async def delete_match(body: DeleteBody):
    try:
        data = await asyncio.to_thread(lyric_matches.delete, body.uri, body.id)
    except lyric_matches.MatchRefused as exc:
        raise HTTPException(404, str(exc)) from exc
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    return {**data, "claude": claude_text.availability()}


@router.post("/restore-deleted")
async def restore_deleted(uri: str = Query(...)):
    try:
        data = await asyncio.to_thread(lyric_matches.restore_deleted, uri)
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    return {**data, "claude": claude_text.availability()}
