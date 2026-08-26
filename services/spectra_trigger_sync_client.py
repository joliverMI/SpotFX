"""Spot-effects -> SPECTRA notifier: every song-profile save also lands that
song's authored triggers in the copy SPECTRA actually fires from.

WHY THIS IS AN HTTP CALL AND NOT AN IMPORT. His edits are made in the
Profile Builder timeline, which saves through THIS process (POST
/api/profiles -> services/profile_manager.save_profile) into
storage/profiles/*.json. The store SPECTRA fires from
(storage/spectra/triggers.json) is owned by the OTHER process, and the S3
process split forbids this interpreter from loading anything under spectra/
— asserted, not merely documented, by scripts/check_process_split.py
section 1. So the sync itself lives in SPECTRA (spectra/services/
profile_trigger_sync.py, reached at POST /api/triggers/sync-from-profile)
and this module is a thin, direct httpx client to it — the same shape
services/spectra_liveness_reconciler.py already uses to read her liveness,
aimed at settings.spectra_port directly rather than through
services/spectra_proxy.py (a proxied call shares this process's own event
loop).

ONE call per save, carrying the whole song — never one call per trigger. The
receiving end collapses the song into a single batched read+write; a
per-trigger loop over the live endpoint would cost ~126ms EACH against his
real corpus.

BEST-EFFORT BY DESIGN. A SPECTRA that is down, restarting, or slow must
never fail or delay his save — the profile is already safely on disk by the
time this runs. A failure is logged and reported back in the save response's
`spectra_sync` field (so the outcome is visible rather than assumed), and
the deploy-time catch-up (scripts/reconcile_profile_triggers.py) is the
backstop that repairs anything a missed call left behind.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10.0     # a batched triggers.json rewrite is ~126ms; this is slack


def _url() -> str:
    return (f"http://127.0.0.1:{settings.spectra_port}"
            f"/spectra/api/triggers/sync-from-profile")


async def sync_song(spotify_uri: str, triggers: list[dict],
                    delete_missing: bool = True) -> dict[str, Any]:
    """POST one song's legacy triggers to SPECTRA. Returns the sync summary
    on success, or {"status": "unreachable"|"error", ...} — never raises, and
    never blocks the caller for longer than REQUEST_TIMEOUT_S.

    `delete_missing=False` is UPSERT-ONLY — see sync_profile_upsert_only."""
    if not spotify_uri:
        return {"status": "skipped", "reason": "profile has no spotify_uri"}
    payload = {"spotify_uri": spotify_uri, "triggers": triggers,
               "delete_missing": delete_missing}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            resp = await client.post(_url(), json=payload)
        if resp.status_code >= 400:
            logger.warning("SPECTRA trigger sync for %s returned HTTP %d: %s",
                           spotify_uri, resp.status_code, resp.text[:200])
            return {"status": "error", "http_status": resp.status_code}
        summary = resp.json()
        logger.info("SPECTRA trigger sync for %s: %s", spotify_uri, summary)
        return {"status": "ok", **summary}
    except Exception as exc:
        # SPECTRA down / restarting / unreachable — his save already landed;
        # scripts/reconcile_profile_triggers.py repairs the gap later.
        logger.warning("SPECTRA trigger sync for %s unreachable: %s",
                       spotify_uri, exc)
        return {"status": "unreachable", "detail": str(exc)}


def _payload(profile: Any) -> list[dict]:
    """ONE place that knows how a SongProfile becomes the sync payload, so no
    writer can serialize it differently from the Timeline save."""
    return [t.model_dump(mode="json") for t in profile.triggers]


async def sync_profile(profile: Any) -> dict[str, Any]:
    """WHOLE-SONG sync — for an EXPLICIT save only (POST /api/profiles, his
    Timeline pressing Save). The profile wins outright for that song at that
    moment, including his deliberate deletions: a fired row he removed in the
    editor is removed from the show. That is only safe because he did it on
    purpose, with the result in front of him.

    Every AUTOMATIC writer must call sync_profile_upsert_only instead."""
    return await sync_song(profile.spotify_uri, _payload(profile), delete_missing=True)


async def sync_profile_upsert_only(profile: Any) -> dict[str, Any]:
    """UPSERT-ONLY sync — for every AUTOMATIC writer: the analyzed-trigger
    import, the post-capture generation, the post-recapture realign.

    Adds and updates by trigger identity; never deletes. An unattended write
    can carry a partial or freshly-derived list, so letting it remove rows
    would mean a background job silently deleting his authored work — worse
    than the missed sync this whole seam exists to fix.
    scripts/reconcile_profile_triggers.py stays the repair path for anything
    a no-delete sync leaves stale."""
    return await sync_song(profile.spotify_uri, _payload(profile), delete_missing=False)
