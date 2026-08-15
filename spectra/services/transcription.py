"""The settings-console voice seam. Decision (2026-08-14, relayed via
firstmate): voice reaches text by the browser RECORDING audio (MediaRecorder)
and POSTing the clip to SPECTRA's own backend — not the browser's built-in
SpeechRecognition API, which ships the audio straight to a third-party cloud
service and forecloses ever routing it to a local transcriber instead. Audio
lands here, at transcribe(), and nowhere else decides how it becomes text —
swap a local Whisper in later without touching the console, the API route,
or the frontend.

THE WIRE CONTRACT (fixed 2026-08-14 — a second ship is building the local
Whisper bridge against this; both halves must agree without guessing):
  POST /api/settings-console/transcribe (spectra/api/settings_console.py),
  multipart/form-data, ONE file field named "audio". The browser client
  (spectra/web/src/settings/SettingsConsolePage.tsx) negotiates
  `MediaRecorder.isTypeSupported('audio/webm;codecs=opus')` explicitly and
  uses `recorder.mimeType` (the type actually negotiated, not a hardcoded
  guess) as the Blob's — and therefore the multipart part's — Content-Type.
  Production traffic today is WEBM/OPUS. A WAV producer is legitimate
  against this same seam (transcribe() takes raw bytes + a mime_type
  string, no format is hardcoded below the API layer) but nothing in this
  codebase emits it — MediaRecorder doesn't natively produce WAV. Whoever
  ends up implementing transcribe() must accept audio/webm (opus) at
  minimum; treat WAV as a bonus, not an assumption.

  Vocabulary travels as a plain space-joined string (vocabulary_hint()),
  computed SERVER-SIDE per request from live scene/colour-set/device
  names — it is NOT a client-supplied field, so a caller can't spoof or
  omit it; the browser has no vocabulary of its own to send.

  Response: {"text": str, "vocabulary_honored": bool | None}.
  vocabulary_honored is None only when the request carried no vocabulary
  hint to honor (nothing to confirm). Otherwise a concrete implementation
  MUST set it — True only when the vocabulary hint was actually handed to
  the underlying engine (e.g. Whisper's initial_prompt), never defaulted
  True. THE API LAYER ENFORCES THIS: post_transcribe() hard-fails (502)
  when a non-empty vocabulary hint was sent but the result doesn't confirm
  vocabulary_honored is True — a request whose vocabulary was silently
  ignored is a bug, not a degraded-but-OK transcription, because the
  vocabulary is the entire reason this seam exists instead of a plain
  generic transcriber. This is enforced structurally in the caller (spectra/
  api/settings_console.py), not left to convention — an implementation that
  forgets to report vocabulary_honored fails closed (None/missing is
  treated as "not honored" whenever a vocabulary was sent), never silently
  passed through as a normal 200.

transcribe() is intentionally UNIMPLEMENTED tonight (explicit instruction:
don't build the Whisper integration yet). It raises TranscriptionUnavailable
so the API layer can return a clear, honest 503 rather than a silent no-op —
the mic button is real (records, POSTs) but its failure is stated, not
hidden; typed text is the working floor until a transcriber is wired here.

vocabulary_hint() answers the fed-live-vocabulary question concretely
rather than by assertion: SPECTRA already holds every proper noun a voice
command would use — scene names, colour-set names, device/virtual ids — all
live-queryable at request time, so biasing a future transcriber (Whisper's
`initial_prompt` / vocabulary-biasing param) toward the words he's actually
likely to say is a plain string join of data this process already has in
memory. No new store, no new stage — just pass this string down alongside
the audio when a real transcriber lands here.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TranscriptionUnavailable(Exception):
    pass


class TranscriptionResult(BaseModel):
    text: str
    # None = the request carried no vocabulary hint, nothing to honor.
    # True = the underlying engine was actually given the vocabulary hint.
    # False = a vocabulary hint existed but the engine didn't use it.
    # A caller (spectra/api/settings_console.py) treats anything other
    # than True — including a missing/None value on a non-empty-vocabulary
    # request — as a hard failure, never a silent generic pass-through.
    vocabulary_honored: Optional[bool] = None


def vocabulary_hint(limit: int = 200) -> str:
    """Space-joined scene / colour-set / device names, for a future
    transcriber's vocabulary-biasing input. Best-effort: any one source
    failing (e.g. an empty/corrupt store) just contributes nothing, same
    posture as feedback.capture_moment's bridge-down degrade."""
    words: list[str] = []

    try:
        from spectra.services import scene_store
        words += [s.name for s in scene_store.list_all()]
    except Exception:
        logger.exception("vocabulary_hint: scene_store read failed")

    try:
        from spectra.services import color_sets
        words += [c.name for c in color_sets.list_all()]
    except Exception:
        logger.exception("vocabulary_hint: color_sets read failed")

    try:
        from fx import device_model
        words += device_model.get_all_virtual_ids()
    except Exception:
        logger.exception("vocabulary_hint: device_model read failed")

    return " ".join(words[:limit])


async def transcribe(audio: bytes, mime_type: str, vocabulary: str = "") -> TranscriptionResult:
    """(audio bytes, its mime type, a vocabulary hint) -> TranscriptionResult.
    The ONE seam a concrete transcriber (a local Whisper bridge) plugs
    into — see the module docstring for the full wire contract this
    signature is part of, including the vocabulary_honored requirement.
    Unimplemented tonight; raises TranscriptionUnavailable."""
    raise TranscriptionUnavailable(
        "no transcriber configured — type your request instead")
