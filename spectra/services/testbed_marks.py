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

ONLY source=="authored" rows are reference marks. midsong_generator seeds a
source=="generated" fire_scene at every librosa section boundary — the
exact times testbed_engines emits as the librosa engine's own
section_boundary marks — and 63% of his stored songs hold nothing else
(AGENTS.md's own count), so admitting them would grade librosa against
itself and every other engine against librosa. The excluded rows are
COUNTED (`SongMarks.n_generated`) so a song with no authored marks reads
as "nothing to compare against yet", never as an empty comparison.

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
from spectra.models.trigger import SpectraTrigger
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
    # From the same editor-copy profile the provenance is read off — the
    # song list carries these so the page can label ~850 songs from ONE
    # listing instead of one /api/profiles/by-uri round-trip per song.
    title: Optional[str] = None
    artist: Optional[str] = None
    n_generated: int = 0


@dataclass(frozen=True)
class _SplitMarks:
    transitions: list[ReferenceMark]
    flares: list[ReferenceMark]
    n_generated: int


def _split(triggers: list[SpectraTrigger]) -> _SplitMarks:
    transitions: list[ReferenceMark] = []
    flares: list[ReferenceMark] = []
    n_generated = 0
    for t in triggers:
        if t.source != "authored":
            n_generated += 1
            continue
        mark = ReferenceMark(id=t.id, timestamp_ms=t.timestamp_ms,
                             kind=t.action.kind, enabled=t.enabled)
        if t.action.kind in TRANSITION_KINDS:
            transitions.append(mark)
        elif t.action.kind in FLARE_KINDS:
            flares.append(mark)
    return _SplitMarks(transitions, flares, n_generated)


@dataclass(frozen=True)
class _ProfileSummary:
    provenance: Provenance
    title: Optional[str]
    artist: Optional[str]


_NO_PROFILE = _ProfileSummary(Provenance(), None, None)


def _summarize(profile: dict) -> _ProfileSummary:
    return _ProfileSummary(
        provenance=Provenance(
            found=True,
            ai_generated=bool(profile.get("ai_generated", False)),
            verified=bool(profile.get("verified", False)),
            editor_trigger_count=len(profile.get("triggers") or []),
        ),
        title=(profile.get("title") or None),
        artist=(profile.get("artist") or None),
    )


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
        if isinstance(data, dict) and data.get("spotify_uri") == uri:
            return data
    return None


def _profile_index() -> dict[str, _ProfileSummary]:
    """ONE pass over storage/profiles/*.json -> {spotify_uri: summary}, for
    the whole-corpus song list. _find_profile() stops at the first match
    and is the right shape for one song; called once per stored URI it
    re-parses the profile directory per song (O(songs x profiles))."""
    profiles_dir = config.PROFILES_DIR
    out: dict[str, _ProfileSummary] = {}
    if not profiles_dir.exists():
        return out
    for path in profiles_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri = data.get("spotify_uri") if isinstance(data, dict) else None
        if uri and uri not in out:
            out[uri] = _summarize(data)
    return out


def _song_marks(uri: str, triggers: list[SpectraTrigger],
                summary: _ProfileSummary) -> SongMarks:
    split = _split(triggers)
    return SongMarks(uri=uri, transitions=split.transitions, flares=split.flares,
                     provenance=summary.provenance,
                     title=summary.title, artist=summary.artist,
                     n_generated=split.n_generated)


def reference_marks_for_song(uri: str) -> tuple[list[ReferenceMark], list[ReferenceMark]]:
    """(transitions, flares) for ONE song from the fired copy alone — no
    profile-directory scan. The comparison endpoint needs only the marks
    to match against; provenance is the page's caveat display and is
    served by marks_for_song()."""
    split = _split(trigger_store.list_for_song(uri))
    return split.transitions, split.flares


def marks_for_song(uri: str) -> SongMarks:
    profile = _find_profile(uri)
    summary = _NO_PROFILE if profile is None else _summarize(profile)
    return _song_marks(uri, trigger_store.list_for_song(uri), summary)


def all_song_marks() -> dict[str, SongMarks]:
    """marks_for_song() for every stored song, from ONE triggers.json read
    and ONE profile-directory pass — the song list's read shape. Keyed by
    URI in sorted order. A song whose stored triggers are ALL generated
    stays in the listing with empty reference lists and its n_generated
    count, so the page can say so rather than drop it."""
    profiles = _profile_index()
    out: dict[str, SongMarks] = {}
    for uri, triggers in sorted(trigger_store.list_all().items()):
        out[uri] = _song_marks(uri, triggers, profiles.get(uri, _NO_PROFILE))
    return out
