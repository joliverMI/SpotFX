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

AND A TEST-BED-PROMOTED ROW IS NOT SCORED EITHER — the same circularity
arriving through the authored door. testbed_promote lands a pushed
suggestion source=="authored" (deliberately — see that module's docstring)
at the SUGGESTING ENGINE'S OWN exact time_ms, so every promotion would add
a mark that engine matches by construction and lift its own P/R/F1 on the
next look. The promotion AUDIT LOG is the only thing that can tell such a
row from one he placed by hand (nothing on the trigger itself can), so
`ReferenceMark.promoted` is resolved from `testbed_promote.
promoted_trigger_ids()` / `promoted_ids_by_uri()`.

The exclusion is VISIBLE, not silent: a promoted mark stays in
`SongMarks.transitions`/`.flares` carrying its flag (the page renders it,
labelled), is counted in `SongMarks.n_promoted`, and is dropped only from
the SCORING set — `scoring_marks()`, which is the one definition both
`reference_marks_for_song()` (the /compare route) and the frontend's own
local matcher apply.

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
from spectra.services import testbed_promote, trigger_store

logger = logging.getLogger(__name__)

TRANSITION_KINDS = ("fire_scene", "fire_scene_update")
FLARE_KINDS = ("fire_response", "select_color_set")


@dataclass(frozen=True)
class ReferenceMark:
    id: str
    timestamp_ms: int
    kind: str          # the TriggerAction.kind that produced it
    enabled: bool
    # True = this row reached the corpus through the test bed's own
    # push-to-real button, per the promotion audit log. Shown, never
    # scored — see the module docstring.
    promoted: bool = False


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
    n_promoted: int = 0


@dataclass(frozen=True)
class _SplitMarks:
    transitions: list[ReferenceMark]
    flares: list[ReferenceMark]
    n_generated: int
    n_promoted: int


def _split(triggers: list[SpectraTrigger],
           promoted_ids: set[str]) -> _SplitMarks:
    transitions: list[ReferenceMark] = []
    flares: list[ReferenceMark] = []
    n_generated = 0
    n_promoted = 0
    for t in triggers:
        if t.source != "authored":
            n_generated += 1
            continue
        promoted = t.id in promoted_ids
        mark = ReferenceMark(id=t.id, timestamp_ms=t.timestamp_ms,
                             kind=t.action.kind, enabled=t.enabled,
                             promoted=promoted)
        if t.action.kind in TRANSITION_KINDS:
            transitions.append(mark)
        elif t.action.kind in FLARE_KINDS:
            flares.append(mark)
        else:
            continue
        if promoted:
            n_promoted += 1
    return _SplitMarks(transitions, flares, n_generated, n_promoted)


def scoring_marks(marks: list[ReferenceMark]) -> list[ReferenceMark]:
    """The subset a P/R/F1 comparison may be computed against: his own
    marks, minus every test-bed-promoted one. THE one definition — the
    /compare route calls it and spectra/web/src/testbed/TestbedPage.tsx
    filters on the same `promoted` flag for its local matcher, so the
    page's number and the server's never disagree about what was scored."""
    return [m for m in marks if not m.promoted]


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
                summary: _ProfileSummary, promoted_ids: set[str]) -> SongMarks:
    split = _split(triggers, promoted_ids)
    return SongMarks(uri=uri, transitions=split.transitions, flares=split.flares,
                     provenance=summary.provenance,
                     title=summary.title, artist=summary.artist,
                     n_generated=split.n_generated, n_promoted=split.n_promoted)


def reference_marks_for_song(uri: str) -> tuple[list[ReferenceMark], list[ReferenceMark]]:
    """(transitions, flares) SCORING marks for ONE song from the fired copy
    alone — no profile-directory scan. Test-bed-promoted rows are already
    dropped here (scoring_marks): this is what /compare matches against,
    and matching an engine against its own pushed suggestions is the one
    thing that would make the number a lie. The page's own display list
    (promoted rows included, flagged) is marks_for_song()'s."""
    split = _split(trigger_store.list_for_song(uri),
                   testbed_promote.promoted_trigger_ids(uri))
    return scoring_marks(split.transitions), scoring_marks(split.flares)


def marks_for_song(uri: str) -> SongMarks:
    profile = _find_profile(uri)
    summary = _NO_PROFILE if profile is None else _summarize(profile)
    return _song_marks(uri, trigger_store.list_for_song(uri), summary,
                       testbed_promote.promoted_trigger_ids(uri))


def all_song_marks() -> dict[str, SongMarks]:
    """marks_for_song() for every stored song, from ONE triggers.json read,
    ONE profile-directory pass and ONE promotion-log read — the song list's
    read shape. Keyed by URI in sorted order. A song whose stored triggers
    are ALL generated stays in the listing with empty reference lists and
    its n_generated count, so the page can say so rather than drop it."""
    profiles = _profile_index()
    promoted = testbed_promote.promoted_ids_by_uri()
    out: dict[str, SongMarks] = {}
    for uri, triggers in sorted(trigger_store.list_all().items()):
        out[uri] = _song_marks(uri, triggers, profiles.get(uri, _NO_PROFILE),
                               promoted.get(uri, set()))
    return out
