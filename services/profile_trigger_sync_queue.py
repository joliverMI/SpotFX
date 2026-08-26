"""SYNC AS A PROPERTY OF WRITING HIS TRIGGERS, not a call each route
remembers to make.

HIS BAR (2026-08-25): "so if i import triggers for a new song and edit them,
do we need to manually sync them or do they automatically work in spectra?
let's make sure they do" — he must never again have to ask whether his own
work reached his show.

THE SHAPE OF THE PROBLEM. The fired copy lives in the OTHER process (the S3
split: this interpreter may not import anything under spectra/), so landing
a profile write there is an async HTTP call. But `profile_manager.
save_profile` is an ordinary synchronous function called from routes, from
worker threads, and from offline scripts alike — it cannot make that call
itself, and rewriting every caller to remember to is exactly the per-route
bolt-on that produced the import gap in the first place.

SO THE WRITE MARKS, AND A SUPERVISED TASK LANDS. `save_profile` calls
`mark_dirty()` — a cheap, side-effect-free set insertion that cannot fail,
cannot block, and needs no event loop. `run_supervised()` (wired into
main.py's lifespan) drains the marks on its own clock. A route that wants to
report the outcome in its own response still syncs inline and calls
`clear()`; anything that does not — a worker thread, a code path written
next year that nobody thought about — is landed by the drain regardless.
That is what makes this structural: a NEW writer of his triggers is synced
because it wrote, not because its author remembered.

ALWAYS UPSERT-ONLY. The drain cannot know whether a write was his deliberate
deletion or a background job carrying a partial list, so it never deletes —
`spectra_trigger_sync_client.sync_profile_upsert_only`. Deletions land only
through an explicit Timeline save, which syncs inline with whole-song
semantics before the drain ever sees the mark.

WHAT THIS DOES NOT COVER, named rather than implied. An OFFLINE script that
writes a profile with the app down marks nothing that anyone will drain (and
could not HTTP-sync anyway, with no SPECTRA to reach).
scripts/reconcile_profile_triggers.py remains the repair path for exactly
that case — it is not weakened or replaced by any of this.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

DRAIN_INTERVAL_S = 20.0

_dirty: set[str] = set()

# Songs whose last drain attempt failed (SPECTRA down/erroring). Kept only so
# status can say so out loud; a failed song stays dirty and is simply retried.
_last_failures: dict[str, str] = {}


def mark_dirty(spotify_uri: str) -> None:
    """Called by profile_manager.save_profile on EVERY profile write. Must
    stay trivial: no I/O, no loop, no exception — a bookkeeping failure here
    would take his save down with it."""
    if spotify_uri:
        _dirty.add(spotify_uri)


def clear(spotify_uri: str) -> None:
    """A caller that already synced this song inline (and reported the
    outcome itself) retires the mark so the drain does not repeat it."""
    _dirty.discard(spotify_uri)
    _last_failures.pop(spotify_uri, None)


def pending() -> set[str]:
    return set(_dirty)


def status() -> dict:
    return {"pending": sorted(_dirty), "last_failures": dict(_last_failures)}


async def drain_once() -> dict:
    """Land every marked song in the fired copy. Returns what happened, for
    tests and for a status surface — never raises."""
    from services import spectra_trigger_sync_client
    from services.profile_manager import load_profile_by_uri

    result = {"synced": [], "failed": [], "missing": []}
    for uri in sorted(pending()):
        try:
            profile = load_profile_by_uri(uri)
        except Exception as exc:
            logger.warning("trigger sync drain: cannot load %s: %s", uri, exc)
            _last_failures[uri] = str(exc)
            result["failed"].append(uri)
            continue
        if profile is None:
            # Written then deleted, or an unreadable file. Nothing to land;
            # dropping the mark stops an unresolvable song spinning forever.
            _dirty.discard(uri)
            result["missing"].append(uri)
            continue
        summary = await spectra_trigger_sync_client.sync_profile_upsert_only(profile)
        if summary.get("status") == "ok":
            clear(uri)
            result["synced"].append(uri)
        else:
            # Stays dirty on purpose — SPECTRA restarting must cost a retry,
            # not his edit.
            _last_failures[uri] = str(summary.get("status"))
            result["failed"].append(uri)
    return result


async def run_supervised() -> None:
    """Own task, started from main.py's lifespan alongside the other
    reconcilers. Never exits on a per-drain failure."""
    logger.info("profile trigger sync drain started (every %.0fs)", DRAIN_INTERVAL_S)
    while True:
        try:
            await asyncio.sleep(DRAIN_INTERVAL_S)
            if _dirty:
                outcome = await drain_once()
                if outcome["synced"] or outcome["failed"]:
                    logger.info("trigger sync drain: %d synced, %d failed",
                                len(outcome["synced"]), len(outcome["failed"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("trigger sync drain tick failed", exc_info=True)
