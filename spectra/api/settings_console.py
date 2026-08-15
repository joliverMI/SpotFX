"""The settings-console API — standing order 5. Five endpoints:

  GET  /api/settings-console/registry   every declared setting + its live
                                        value/range — the read-only summary
                                        strip; never a form to submit.
  GET  /api/settings-console/log?limit= recent change-log entries, newest
                                        first — the visible "what changed"
                                        record.
  POST /api/settings-console/undo       revert the most recent not-yet-
                                        undone change. 409 when there's
                                        nothing to undo.
  POST /api/settings-console/message    one chat turn: {session_id?, text}
                                        -> {session_id, reply, changes}.
                                        503 when no ANTHROPIC_API_KEY is
                                        configured (the console has no
                                        model to talk to, not a silent
                                        no-op).
  POST /api/settings-console/transcribe multipart audio upload -> {text}.
                                        503 (via TranscriptionUnavailable)
                                        until a real transcriber is wired
                                        into services/transcription.py —
                                        the mic button is real, its
                                        current failure is stated, not
                                        hidden.

The write authority itself is NOT in this file — see services/
settings_console.py's module docstring for why the boundary lives in the
mechanism, not the API layer or the model prompt.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from spectra.services import settings_agent, settings_console, transcription
from spectra.services.settings_agent import SettingsAgentUnavailable
from spectra.services.settings_console import SettingChangeError
from spectra.services.transcription import TranscriptionUnavailable

router = APIRouter(prefix="/api/settings-console", tags=["spectra-settings-console"])

LOG_QUERY_MAX = 200


class MessageIn(BaseModel):
    text: str
    session_id: Optional[str] = None


@router.get("/registry")
async def get_registry():
    return settings_console.describe_current()


@router.get("/log")
async def get_log(limit: int = Query(50, ge=1, le=LOG_QUERY_MAX)):
    return settings_console.load_log(limit=limit)


@router.post("/undo")
async def post_undo():
    try:
        return await settings_console.undo_last_change()
    except SettingChangeError as exc:
        raise HTTPException(409, exc.message) from exc


@router.post("/message")
async def post_message(body: MessageIn):
    try:
        return await settings_agent.run_turn(body.session_id, body.text)
    except SettingsAgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/transcribe")
async def post_transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    try:
        text = await transcription.transcribe(
            data, audio.content_type or "application/octet-stream",
            vocabulary=transcription.vocabulary_hint())
    except TranscriptionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"text": text}
