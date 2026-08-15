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
                                        Routes to services/settings_agent.py
                                        (default, ANTHROPIC_API_KEY) or
                                        services/settings_agent_cli.py
                                        (config.settings_agent_backend()
                                        == "cli", a subscription-
                                        authenticated `claude -p`
                                        subprocess -- see that module's
                                        docstring; default OFF, the
                                        captain's ruling) -- either way,
                                        503 when that backend has no
                                        model to talk to, never a silent
                                        no-op.
  POST /api/settings-console/transcribe multipart audio upload (field
                                        "audio") -> {text, vocabulary_honored}.
                                        503 (via TranscriptionUnavailable)
                                        until a real transcriber is wired
                                        into services/transcription.py —
                                        the mic button is real, its
                                        current failure is stated, not
                                        hidden. 502 when a transcriber IS
                                        wired but doesn't confirm it used
                                        the vocabulary hint it was given —
                                        see the hard-fail block below.

The write authority itself is NOT in this file — see services/
settings_console.py's module docstring for why the boundary lives in the
mechanism, not the API layer or the model prompt.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from spectra import config
from spectra.services import settings_agent, settings_agent_cli, settings_console, transcription
from spectra.services.settings_agent import SettingsAgentUnavailable
from spectra.services.settings_console import SettingChangeError
from spectra.services.transcription import TranscriptionUnavailable, VocabularyNotHonored

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
    # config.settings_agent_backend() defaults to "api" -- see that
    # function's docstring and settings_agent_cli.py's module docstring
    # for the captain's ruling this switch exists to honour: a
    # subscription-authenticated CLI backend may be built ready to
    # enable, but never enables itself.
    agent = settings_agent_cli if config.settings_agent_backend() == "cli" else settings_agent
    try:
        return await agent.run_turn(body.session_id, body.text)
    except SettingsAgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/transcribe")
async def post_transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    vocabulary = transcription.vocabulary_hint()
    try:
        result = await transcription.transcribe(
            data, audio.content_type or "application/octet-stream",
            vocabulary=vocabulary)
    except TranscriptionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except VocabularyNotHonored as exc:
        # The seam's own bridge call already caught this at the source —
        # see below for the independent backstop check on whatever a
        # different transcribe() implementation might return instead.
        raise HTTPException(502, str(exc)) from exc

    # Backstop, deliberately re-checking the SAME invariant transcribe()
    # itself may already enforce (spectra/services/transcription.py's
    # wire-contract docstring) — the vocabulary is the entire reason this
    # seam exists instead of a plain generic transcriber, so ANY
    # implementation that doesn't confirm using it is treated as broken,
    # never as a degraded-but-fine 200. `is not True` (not `is False`) so
    # a forgetful implementation that just omits the field (leaves it
    # None) fails closed too.
    if vocabulary and result.vocabulary_honored is not True:
        raise HTTPException(
            502,
            "transcriber did not confirm using the vocabulary hint — "
            "refusing a silently generic transcription")

    return result.model_dump()
