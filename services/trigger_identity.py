"""STABLE IDENTITY for machine-produced triggers, and the one merge that
decides what a RE-import does to what is already in his profile.

THE BUG THIS EXISTS FOR (2026-08-25). `MusicTrigger.id` defaults to a fresh
`uuid4`, and every import path built its triggers by constructing fresh
`MusicTrigger`s for the whole song. So re-importing a song produced a list
in which not one id matched the previous import's — nothing in the system
could tell "the same analyzed mark, computed again" from "a brand new mark
next to a deleted one". Downstream that made the fired-store sync churn a
song's entire authored corpus on every import: every previously-synced row
read as absent-from-the-profile and was deleted, then re-inserted under new
ids. The row count came out right, which is exactly why it went unnoticed.

THE FIX: derive the id from what the mark IS — its event and its position —
so the same analyzed mark computed twice is the same trigger twice, by
identity, with no state kept anywhere. `analyzed_{event_id}_{timestamp_ms}`
is not a new convention: routers/ai_triggers_router.py's analyzed-trigger
CACHE has always keyed rows this exact way, so the id an import writes into
his profile is now the same string that cache already used for it.

WHAT A STABLE ID DOES AND DOES NOT PROVE. It makes a re-run of the SAME
analysis idempotent, which is the whole point. It does NOT survive him
MOVING a mark on the timeline: the timeline edits a trigger in place, so a
moved trigger keeps the id derived from where it originally sat, and the id
no longer matches its own content. That is a feature here rather than a
flaw — under the "protect" policy it is precisely what lets a re-import find
his moved trigger already present and leave it alone.

THE OPEN TRADE, PARAMETERISED RATHER THAN DECIDED. Whether a re-import
should overwrite triggers he has hand-edited since the last one is his call,
not this module's. `settings.trigger_import_policy` switches both behaviours
with no rewrite; the default PROTECTS his edits, consistent with the show
side already refusing to touch a trigger authored on SPECTRA's own card.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from models.song_profile import MusicTrigger

logger = logging.getLogger(__name__)

PROTECT = "protect"
REPLACE = "replace"
POLICIES = (PROTECT, REPLACE)


def stable_trigger_id(event_id: str, timestamp_ms: int) -> str:
    """The id an analyzed mark gets, every time it is computed.

    Same shape routers/ai_triggers_router.py's analyzed-trigger cache already
    keys its rows with, deliberately — an imported trigger and its cache row
    now carry the same id rather than two unrelated ones.
    """
    return f"analyzed_{event_id}_{int(timestamp_ms)}"


def import_policy() -> str:
    """The configured policy, falling back to the protective one rather than
    raising on a typo in .env — a mistyped setting must never be the reason
    his hand edits get overwritten."""
    policy = str(getattr(settings, "trigger_import_policy", PROTECT) or "").strip().lower()
    if policy not in POLICIES:
        logger.warning("trigger_import_policy=%r is not one of %s — using %r",
                       policy, POLICIES, PROTECT)
        return PROTECT
    return policy


def build_imported_triggers(suggestions: list[dict]) -> list[MusicTrigger]:
    """Analyzed-engine output -> MusicTriggers carrying stable ids.

    The ONE place an import turns suggestions into triggers, so no writer can
    reintroduce a fresh uuid per mark.
    """
    from models.song_profile import MusicTrigger

    built: list[MusicTrigger] = []
    for s in suggestions:
        event_id = s["event_id"]
        timestamp_ms = int(s["timestamp_ms"])
        kwargs = {
            "id": stable_trigger_id(event_id, timestamp_ms),
            "timestamp_ms": timestamp_ms,
            "event_id": event_id,
        }
        # The analyzed pipeline carries an intensity for some marks and not
        # others; an absent one keeps MusicTrigger's own 0.5 default rather
        # than being written as None.
        if s.get("intensity") is not None:
            kwargs["intensity"] = float(s["intensity"])
        built.append(MusicTrigger(**kwargs))
    return built


def merge_imported_triggers(
    existing: list[MusicTrigger],
    imported: list[MusicTrigger],
    policy: str | None = None,
) -> tuple[list[MusicTrigger], dict[str, int]]:
    """Fold a fresh import into what the song's profile already holds.

    Returns (merged, counts) where counts reports what actually happened —
    `added` / `kept` / `overwritten` / `dropped` — so a caller can tell him
    rather than presenting an import as an opaque success.

    Ordering is by timestamp, which is how the timeline reads them anyway.
    """
    policy = policy or import_policy()
    by_id = {t.id: t for t in existing}
    counts = {"added": 0, "kept": 0, "overwritten": 0, "dropped": 0}

    if policy == REPLACE:
        # The analysis wins outright: whatever it produces IS the list. A mark
        # the new analysis no longer produces leaves the profile — that is the
        # point of this policy, and it is why it is not the default.
        imported_ids = {t.id for t in imported}
        for t in imported:
            if t.id in by_id:
                counts["overwritten"] += 1
            else:
                counts["added"] += 1
        counts["dropped"] = sum(1 for tid in by_id if tid not in imported_ids)
        merged = list(imported)
    else:
        # PROTECT: an id already in the profile is his — untouched, whether he
        # edited it or it simply came from the last import unchanged. Only
        # marks the profile has never seen are added.
        merged = list(existing)
        for t in imported:
            if t.id in by_id:
                counts["kept"] += 1
            else:
                merged.append(t)
                counts["added"] += 1

    merged.sort(key=lambda t: t.timestamp_ms)
    return merged, counts
