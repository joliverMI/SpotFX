"""The sung labels page's routes (lyrics plan step 3). Nothing here reaches
the lights. spectra/services/sung_labels.py is the binding statement.

  GET  /api/sung-labels            every colour set's and effect's labels
  POST /api/sung-labels/edit       one word added or taken out
  POST /api/sung-labels/draft      Claude drafts meanings for a small batch of
                                    cards (color_meanings.DRAFT_BATCH_SIZE)
  PUT  /api/sung-labels/settings   a true partial update: automatic reading
                                    on or off (off by default), and the
                                    weak-match threshold a reading uses
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.services import claude_text, color_meanings, sung_labels

router = APIRouter(prefix="/api/sung-labels", tags=["spectra-sung-labels"])


def _page() -> dict:
    return {**sung_labels.page(), "claude": claude_text.availability(),
            "draft_batch_size": color_meanings.DRAFT_BATCH_SIZE}


@router.get("")
async def get_page():
    try:
        return await asyncio.to_thread(_page)
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc


class EditBody(BaseModel):
    kind: Literal["color_set", "effect"]
    id: str = Field(min_length=1)
    list: Literal["labels", "things", "moods", "places"]
    op: Literal["add", "remove"]
    text: str = Field(min_length=1, max_length=200)


@router.post("/edit")
async def post_edit(body: EditBody):
    def _run() -> dict:
        sung_labels.edit(body.kind, body.id, body.list, body.op, body.text)
        return _page()
    try:
        return await asyncio.to_thread(_run)
    except sung_labels.EditRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc


class DraftBody(BaseModel):
    ids: list[str] = Field(min_length=1)


@router.post("/draft")
async def post_draft(body: DraftBody):
    """Asks Claude once, for up to DRAFT_BATCH_SIZE cards. Only the drafts change: his
    edits are kept apart from them."""
    try:
        return await color_meanings.draft(body.ids)
    except color_meanings.DraftRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except claude_text.ClaudeUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except claude_text.ClaudeReplyInvalid as exc:
        raise HTTPException(500, str(exc)) from exc
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc


class SettingsBody(BaseModel):
    # A true partial update: an omitted field is left exactly as it was,
    # the same contract room_controls' own PUT holds (AGENTS.md).
    auto_read: Optional[bool] = None


@router.put("/settings")
async def put_settings(body: SettingsBody):
    def _run() -> dict:
        if body.auto_read is not None:
            sung_labels.set_auto_read(body.auto_read)
        return _page()
    try:
        return await asyncio.to_thread(_run)
    except sung_labels.EditRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except sung_labels.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
