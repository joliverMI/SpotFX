"""His real marks, for the music-analysis test bed
(data/spotfx-music-analysis-plan/report.md, Part 3) — read-only, and read
from the FIRED copy (storage/spectra/triggers.json via trigger_store), the
same choice the report itself makes ("what actually reaches the room" —
Part 3's own "What it reads" section), not the legacy editor copy. AGENTS.md's
"TWO trigger copies" section is why this is a deliberate pick, not an
oversight: the two stores can genuinely disagree (Part 3's Methodology
note), and a full dual-store picker is future work (report §Part 2.5 gap
#5 / the open decision list) — this module surfaces the editor copy's own
trigger COUNT alongside the fired-copy split as a visible caveat, not a
second definition of "his marks" to switch between.

Split, per the report's own Part 1/Part 3 convention:
  transitions — fire_scene / fire_scene_update actions ("where the scene
                changes")
  flares      — fire_response / select_color_set actions ("where something
                sparks" — a much denser, beat-anchored set)

Provenance (ai_generated / verified) comes from the legacy editor-copy
SongProfile (storage/profiles/*.json, read-only, same file AGENTS.md's own
"A scene's stored data is not proof he authored it" caution applies to) —
surfaced so the test bed can show the caveat on the page itself (the
report's own Methodology section insists on this), not bury it in a report
he read once.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from spectra import config
from spectra.services import trigger_store

logger = logging.getLogger(__name__)

TRANSITION_KINDS = ("fire_scene", "fire_scene_update")
FLARE_KINDS = ("fire_response", "select_color_set")


@dataclass(frozen=True)
class ReferenceMark:
    id: str
    timestamp_ms: int
    kind: str          # the TriggerAction.kind that produced it
    enabled: bool


@dataclass(frozen=True)
class Provenance:
    found: bool = False
    ai_generated: bool = False
    verified: bool = False
    editor_trigger_count: int = 0


@dataclass(frozen=True)
class SongMarks:
    uri: str
    transitions: list[ReferenceMark] = field(default_factory=list)
    flares: list[ReferenceMark] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)


def _split(uri: str) -> tuple[list[ReferenceMark], list[ReferenceMark]]:
    transitions: list[ReferenceMark] = []
    flares: list[ReferenceMark] = []
    for t in trigger_store.list_for_song(uri):
        mark = ReferenceMark(id=t.id, timestamp_ms=t.timestamp_ms,
                             kind=t.action.kind, enabled=t.enabled)
        if t.action.kind in TRANSITION_KINDS:
            transitions.append(mark)
        elif t.action.kind in FLARE_KINDS:
            flares.append(mark)
    return transitions, flares


def _find_profile(uri: str) -> Optional[dict]:
    """Read-only scan of storage/profiles/*.json for the matching
    spotify_uri — same read-only spot-effects storage AGENTS.md's own
    "TWO trigger copies" section names, never imported as a model (the S3
    import-discipline rule: nothing under spectra/ imports spot-effects
    runtime internals) — a plain dict read is enough for the two provenance
    flags and a trigger count."""
    profiles_dir = config.PROFILES_DIR
    if not profiles_dir.exists():
        return None
    for path in profiles_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("spotify_uri") == uri:
            return data
    return None


def provenance_for(uri: str) -> Provenance:
    profile = _find_profile(uri)
    if profile is None:
        return Provenance()
    return Provenance(
        found=True,
        ai_generated=bool(profile.get("ai_generated", False)),
        verified=bool(profile.get("verified", False)),
        editor_trigger_count=len(profile.get("triggers") or []),
    )


def marks_for_song(uri: str) -> SongMarks:
    transitions, flares = _split(uri)
    return SongMarks(uri=uri, transitions=transitions, flares=flares,
                     provenance=provenance_for(uri))


def known_uris() -> list[str]:
    """Every URI with at least one fired-copy trigger — the candidate song
    list's base set (spectra/api/testbed.py adds pin/audio-availability
    state on top)."""
    raw = trigger_store._load_raw()
    return sorted(uri for uri, rows in raw.items() if rows)
