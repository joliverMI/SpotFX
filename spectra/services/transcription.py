"""The settings-console voice seam. Decision (2026-08-14, relayed via
firstmate): voice reaches text by the browser RECORDING audio (MediaRecorder)
and POSTing the clip to SPECTRA's own backend — not the browser's built-in
SpeechRecognition API, which ships the audio straight to a third-party cloud
service and forecloses ever routing it to a local transcriber instead.

THE BROWSER-FACING CONTRACT (spectra/api/settings_console.py, ours to
publish — see its own docstring): POST /api/settings-console/transcribe,
multipart/form-data, one file field named "audio". The browser negotiates
`audio/webm;codecs=opus` explicitly (spectra/web/src/settings/
SettingsConsolePage.tsx). Response: {"text", "vocabulary_honored"}.

THE BRIDGE-FACING CONTRACT (2026-08-15 — published and proven over real
HTTP by the ship building the local-Whisper bridge; SPECTRA CONFORMS to
this, does not renegotiate it): transcribe() below is that conformance —

  POST {SPECTRA_WHISPER_BRIDGE_URL}/transcribe
  Body: the RAW audio bytes (not multipart — that shape is ours-to-the-
        browser only and stops at the API layer above).
  Headers: Content-Type = exactly the mime_type this seam was called
        with (i.e. what the browser actually sent us — forwarded
        unchanged, never renegotiated); X-Vocabulary = vocabulary_hint()'s
        string, percent-encoded (urllib.parse.quote) since it's a header.
  Response (JSON): {"text": str, "vocabulary_applied": bool,
        "content_type_received": str}. Their side has no no-vocabulary
        mode — vocabulary_applied is always meaningful, never N/A.

  ENFORCEMENT, belt and braces at two points on purpose (same invariant,
  re-derived independently rather than trusted once): (1) transcribe()
  itself raises VocabularyNotHonored the moment it sees a non-empty
  vocabulary sent but vocabulary_applied isn't literally True — a
  request whose vocabulary was silently ignored never even becomes a
  successful TranscriptionResult here. (2) settings_console.py's
  post_transcribe independently re-checks the returned
  TranscriptionResult.vocabulary_honored and 502s if it's not True on a
  non-empty-vocabulary request — a backstop against ANY transcribe()
  implementation (this one, a future one, a test stub) that returns
  normally without actually confirming. Neither trusts the other; both
  must agree a vocabulary was honored before a 200 ever reaches the
  browser.

  The bridge's address (spectra.config.whisper_bridge_url()) defaults to
  http://127.0.0.1:8090 — verified 2026-08-15, mirroring the bridge's own
  compose-file STT_BRIDGE_PORT default, not an independently-invented
  number. Still a configured value (SPECTRA_WHISPER_BRIDGE_URL overrides
  it), not a literal buried here. Loopback works ONLY because
  spectra.service runs as a plain host process alongside the bridge — see
  that function's own docstring for the containerisation caveat.

  TWO MORE FACTS THAT PRODUCE A MYSTERY, NOT AN ERROR, IF MISSED (2026-08-15):
  the bridge REJECTS a chunked/streamed body — Content-Length is required.
  transcribe() only accepts `audio: bytes` (never a file-like object or
  iterator) and asserts that type explicitly before sending, because httpx
  silently switches to chunked transfer-encoding the moment it's handed
  anything else — this is not "assume bytes behaves"; it's enforced. Body
  cap is 25MB (BRIDGE_MAX_AUDIO_BYTES) — checked HERE, before the request
  goes out, with a clear TranscriptionUnavailable, rather than letting the
  bridge's own rejection surface as a confusing generic HTTP error.

vocabulary_hint() answers the fed-live-vocabulary question concretely:
SPECTRA already holds every proper noun a voice command would use — scene
names, colour-set names, device/virtual ids — all live-queryable at
request time, so biasing the bridge's transcriber toward the words he's
actually likely to say is a plain string join of data this process
already has in memory.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

import httpx
from pydantic import BaseModel

from spectra import config

logger = logging.getLogger(__name__)

BRIDGE_TIMEOUT_S = 30.0
BRIDGE_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # the bridge's own documented cap


class TranscriptionUnavailable(Exception):
    """No bridge configured, or the bridge is unreachable/erroring/
    returned something unparseable. Maps to a 503 — "nothing to talk
    to" — distinct from VocabularyNotHonored's 502."""


class VocabularyNotHonored(Exception):
    """The bridge responded, but didn't confirm using a non-empty
    vocabulary hint. Maps to a 502 — the bridge IS there and DID answer,
    it just didn't hold up its half of the contract."""


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
    """Space-joined scene / colour-set / device names, for the bridge's
    vocabulary-biasing input. Best-effort: any one source failing (e.g. an
    empty/corrupt store) just contributes nothing, same posture as
    feedback.capture_moment's bridge-down degrade."""
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


def _client() -> httpx.AsyncClient:
    """A seam of its own so tests can swap in an httpx.MockTransport
    without a real socket (same DI pattern as conftest.py's
    fresh_ledfx_client)."""
    return httpx.AsyncClient(timeout=BRIDGE_TIMEOUT_S)


async def transcribe(audio: bytes, mime_type: str, vocabulary: str = "") -> TranscriptionResult:
    """Conforms to the local-Whisper bridge's published contract — see the
    module docstring. Raises TranscriptionUnavailable (bridge unconfigured/
    unreachable/malformed -> 503) or VocabularyNotHonored (bridge answered
    but ignored a non-empty vocabulary hint -> 502)."""
    base_url = config.whisper_bridge_url()
    if not base_url:
        raise TranscriptionUnavailable(
            "no local-Whisper bridge configured (SPECTRA_WHISPER_BRIDGE_URL "
            "unset) — type your request instead")

    # The bridge requires a fixed Content-Length body and rejects chunked
    # transfer-encoding. httpx only emits a fixed-length request when
    # `content` is bytes/bytearray — a file-like object or iterator would
    # silently switch it to chunked. Asserting the type here, rather than
    # trusting the caller, is what actually turns streaming off: nothing
    # downstream can hand this function something that triggers it.
    if not isinstance(audio, (bytes, bytearray)):
        raise TranscriptionUnavailable(
            "audio must be raw bytes — the bridge requires a fixed "
            "Content-Length body and rejects chunked transfer-encoding")
    if len(audio) > BRIDGE_MAX_AUDIO_BYTES:
        raise TranscriptionUnavailable(
            f"audio clip is {len(audio)} bytes, over the bridge's "
            f"{BRIDGE_MAX_AUDIO_BYTES}-byte cap — record a shorter clip")

    headers = {
        "Content-Type": mime_type,
        "X-Vocabulary": urllib.parse.quote(vocabulary),
    }
    try:
        async with _client() as client:
            # content=<bytes> — not a file/iterator — is what gives this a
            # real Content-Length instead of chunked encoding; see the
            # type check above for why that's guaranteed, not assumed.
            resp = await client.post(
                f"{base_url.rstrip('/')}/transcribe", content=audio, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Connection-refused (nothing listening on the bridge port) lands
        # here too, by design — an honest "unavailable," never chased with
        # a retry, a scan, or an attempt to start anything.
        raise TranscriptionUnavailable(
            f"local-Whisper bridge unreachable or malformed: {exc}") from exc

    text = data.get("text")
    if not isinstance(text, str):
        raise TranscriptionUnavailable(
            f"local-Whisper bridge response missing 'text': {data!r}")

    raw_applied = data.get("vocabulary_applied")
    vocabulary_applied = raw_applied if isinstance(raw_applied, bool) else None
    if vocabulary and vocabulary_applied is not True:
        raise VocabularyNotHonored(
            "local-Whisper bridge did not confirm using the vocabulary hint "
            f"(vocabulary_applied={raw_applied!r}) — refusing a silently "
            "generic transcription")

    return TranscriptionResult(text=text, vocabulary_honored=vocabulary_applied)
