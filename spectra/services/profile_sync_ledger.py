"""PROVENANCE for the two trigger worlds — which fired-copy triggers came
from the predecessor's profile store, and which legacy event each one came
from.

WHY A SIDECAR AND NOT A MODEL FIELD. `storage/spectra/triggers.json` (the
ONLY store spectra/services/trigger_engine.py fires from) holds three
populations of trigger that must be told apart before anything is deleted:

  * PROFILE-ORIGIN — landed by spectra/services/legacy_trigger_migration.py
    (or by this feature's on-save sync) out of a `storage/profiles/*.json`
    SongProfile. The migration preserves the legacy `MusicTrigger.id` as the
    SpectraTrigger id, so "same id" IS the provenance link — while the
    profile still carries that id.
  * CARD-BORN — authored on SPECTRA's own trigger card (spectra/api/
    triggers.py), a fresh uuid4 that never existed in any profile. 18 of
    these in his live corpus at build time. Must NEVER be deleted by a
    profile save.
  * GENERATED — source="generated", 19,023 of his. Never crosses either way.

The id link alone cannot survive a DELETION: once he removes a trigger from
the profile, its id is gone from the profile too, and a card-born trigger and
a profile-deleted trigger become indistinguishable. Rather than add a field to
SpectraTrigger (which would have to default to one of the two answers and so
would mis-label ~10.7k already-stored rows either way), provenance is recorded
here, beside the fired copy, as ids this feature has itself observed on both
sides — the conservative reading: a fired-copy trigger this ledger has never
seen in a profile is treated as card-born and left alone.

`event_id` is kept alongside because it is the ONLY thing that makes a
faithful reverse write possible (profile_trigger_sync.plan_reverse) — the
forward map is many-to-one (35 legacy event ids collapse into 4 SPECTRA
action shapes), so without the original event id a write back into his
profiles would be a guess.

Same atomic tmp+os.replace discipline as trigger_store.py / scene_store.py.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from spectra import config

logger = logging.getLogger(__name__)

# {spotify_uri: {trigger_id: legacy_event_id}}
Ledger = dict[str, dict[str, str]]


def load() -> Ledger:
    path = config.PROFILE_SYNC_LEDGER_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {u: dict(v) for u, v in data.items() if isinstance(v, dict)}
        except Exception as exc:
            logger.warning("profile sync ledger parse failed: %s", exc)
    return {}


def save(ledger: Ledger) -> None:
    path = config.PROFILE_SYNC_LEDGER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({u: v for u, v in sorted(ledger.items()) if v}, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def for_song(ledger: Ledger, uri: str) -> dict[str, str]:
    """{trigger_id: legacy event_id} known to have come from this song's
    profile. Read-only view — mutate through set_song/apply_song."""
    return dict(ledger.get(uri, {}))


def set_song(ledger: Ledger, uri: str, known: dict[str, str]) -> Ledger:
    """Replace one song's provenance record. Returns the same ledger object
    (mutated) so callers can chain a load -> set_song -> save."""
    if known:
        ledger[uri] = dict(known)
    else:
        ledger.pop(uri, None)
    return ledger
