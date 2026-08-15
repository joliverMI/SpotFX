"""The settings-console voice seam. Decision (2026-08-14, relayed via
firstmate): voice reaches text by the browser RECORDING audio (MediaRecorder)
and POSTing the clip to SPECTRA's own backend — not the browser's built-in
SpeechRecognition API, which ships the audio straight to a third-party cloud
service and forecloses ever routing it to a local transcriber instead. Audio
lands here, at transcribe(), and nowhere else decides how it becomes text —
swap a local Whisper in later without touching the console, the API route,
or the frontend.

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

logger = logging.getLogger(__name__)


class TranscriptionUnavailable(Exception):
    pass


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


async def transcribe(audio: bytes, mime_type: str, vocabulary: str = "") -> str:
    """(audio bytes, its mime type, a vocabulary hint) -> spoken text. The
    ONE seam a concrete transcriber (browser-native today would still call
    through here from a client-side result; a local Whisper later) plugs
    into. Unimplemented — see module docstring."""
    raise TranscriptionUnavailable(
        "no transcriber configured — type your request instead")
