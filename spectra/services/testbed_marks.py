"""His real marks, for the music-analysis test bed
(data/spotfx-music-analysis-plan/report.md, Part 3) — read-only, and read
from the FIRED copy (storage/spectra/triggers.json via trigger_store), the
same choice the report itself makes ("what actually reaches the room" —
Part 3's own "What it reads" section), not the legacy editor copy. docs/agents/scenes-and-flares.md's
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
(docs/agents/testbed-and-drops.md's own count), so admitting them would grade librosa against
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

all_song_marks() (the whole-corpus SONG LIST) is the one exception to
"ONLY source=='authored' rows are reference marks" above: a song with
cached analyzed triggers (services/analyzed_trigger_store.py) is listed
from THOSE instead, and a song with only his old authored rows and no
analyzed cache is listed with NO reference marks at all (not just no
generated ones) — see that function's own docstring for why. marks_for_song()
and reference_marks_for_song() keep the rule above exactly as stated for
every song that has no analyzed cache.

Provenance (ai_generated / verified) comes from the legacy editor-copy
SongProfile (storage/profiles/*.json, read-only, same file docs/agents/scenes-and-flares.md's own
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

# services/analyzed_trigger_store.py's cache (storage/analyzed_triggers/
# <track_id>.json, read-only here per config.ANALYZED_TRIGGERS_DIR's own
# docstring — plain dict reads only, never services.training_profile_manager
# or services.analyzed_trigger_store themselves: the S3 import-discipline
# rule above forbids spectra/ importing spot-effects runtime internals).
# A song whose only triggers are his own hand-placed ones has nothing in
# this store, so it falls through to the old split below.
#
# The Admiral, 2026-11: "i am done adding my own triggers. the analyzed
# triggers are better. we should only focus on the analyzed triggers."
# The song list surfaces every song that has analyzed triggers (the ones
# he now cares about), scored against THOSE triggers rather than his old
# hand-placed ones — see all_song_marks()'s own docstring for the split.
#
# Role split (scene change vs flare) mirrors routers/ai_triggers_router.py's
# own `role_attrs` exactly (the same training-profile event-id attrs,
# categorized the same way) so an analyzed song's transitions/flares split
# agrees with what actually fires it at play time.
_ANALYZED_ROLE_ATTRS = {
    "song_start_event_id": "scene", "beat_start_event_id": "scene",
    "song_end_event_id": "scene", "drop_event_id": "scene",
    "lull_event_id": "scene", "charge_event_id": "scene",
    "quiet_event_id": "scene", "scene_fill_event_id": "scene",
    "flare_event_id": "flare", "flare_low_event_id": "flare",
    "flare_mid_event_id": "flare", "flare_high_event_id": "flare",
    "flare_scene_event_id": "flare",
}


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
    # fire_response's own event_class (flare / charge / lull / drop) — the
    # Drops lane's reference sets (drops / lulls / charges) are the flares
    # filtered by it. None for every other action kind.
    event_class: Optional[str] = None


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
    # Phase 2 beat-snap provenance (spectra/services/beat_snap.py) over
    # this song's GENERATED triggers — never its scored reference marks
    # (those are always source=="authored"; see the module docstring's
    # exclusion rule). Which grid each snapped cue used, and how many of
    # the song's generated cues went unsnapped (no usable grid, or past
    # the one-beat cap) — so the test bed can show why generation landed
    # where it did without exposing generated cues as scoreable marks.
    n_snapped: int = 0
    n_unsnapped_generated: int = 0
    snap_grid_counts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _SplitMarks:
    transitions: list[ReferenceMark]
    flares: list[ReferenceMark]
    n_generated: int
    n_promoted: int
    n_snapped: int
    n_unsnapped_generated: int
    snap_grid_counts: dict


def _split(triggers: list[SpectraTrigger],
           promoted_ids: set[str]) -> _SplitMarks:
    transitions: list[ReferenceMark] = []
    flares: list[ReferenceMark] = []
    n_generated = 0
    n_promoted = 0
    n_snapped = 0
    n_unsnapped_generated = 0
    snap_grid_counts: dict = {}
    for t in triggers:
        if t.source != "authored":
            n_generated += 1
            if t.snap_grid is not None:
                n_snapped += 1
                snap_grid_counts[t.snap_grid] = snap_grid_counts.get(t.snap_grid, 0) + 1
            else:
                n_unsnapped_generated += 1
            continue
        promoted = t.id in promoted_ids
        mark = ReferenceMark(id=t.id, timestamp_ms=t.timestamp_ms,
                             kind=t.action.kind, enabled=t.enabled,
                             promoted=promoted,
                             event_class=getattr(t.action, "event_class", None))
        if t.action.kind in TRANSITION_KINDS:
            transitions.append(mark)
        elif t.action.kind in FLARE_KINDS:
            flares.append(mark)
        else:
            continue
        if promoted:
            n_promoted += 1
    return _SplitMarks(transitions, flares, n_generated, n_promoted,
                       n_snapped, n_unsnapped_generated, snap_grid_counts)


PHASE_REFERENCES = {"drops": "drop", "lulls": "lull", "charges": "charge"}
"""The Drops lane's reference sets: his own flares of one event_class."""


def phase_marks(flares: list[ReferenceMark], reference: str) -> list[ReferenceMark]:
    """His drops / lulls / charges — the flares whose event_class the
    reference set names. The /compare route and the song list's counts
    both use this; spectra/web/src/testbed/TestbedPage.tsx mirrors it
    (the same event_class filter) for its local matcher."""
    cls = PHASE_REFERENCES[reference]
    return [m for m in flares if m.event_class == cls]


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
    spotify_uri — same read-only spot-effects storage docs/agents/scenes-and-flares.md's own
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
                     n_generated=split.n_generated, n_promoted=split.n_promoted,
                     n_snapped=split.n_snapped,
                     n_unsnapped_generated=split.n_unsnapped_generated,
                     snap_grid_counts=split.snap_grid_counts)


def _track_id(uri: str) -> str:
    return uri.split(":")[-1]


def _load_analyzed(uri: str) -> Optional[dict]:
    """Plain-dict read of storage/analyzed_triggers/<track_id>.json
    (services/analyzed_trigger_store.py's cache) for ONE song — read-only,
    never through that module's own pydantic models (the S3 import-
    discipline rule: nothing under spectra/ imports spot-effects runtime
    internals — the same reason _find_profile reads storage/profiles/ as a
    plain dict). None when the song has no cached analyzed triggers."""
    path = config.ANALYZED_TRIGGERS_DIR / f"{_track_id(uri)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _analyzed_index() -> dict[str, dict]:
    """ONE pass over storage/analyzed_triggers/*.json -> {track_id: cached
    dict} — the whole-corpus read shape all_song_marks() needs, same
    reasoning as _profile_index()."""
    analyzed_dir = config.ANALYZED_TRIGGERS_DIR
    out: dict[str, dict] = {}
    if not analyzed_dir.exists():
        return out
    for path in analyzed_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        track_id = data.get("track_id") if isinstance(data, dict) else None
        if track_id:
            out[track_id] = data
    return out


def _training_profiles_raw() -> dict:
    """Plain-dict read of storage/training_profiles.json (id -> profile),
    for classifying an analyzed trigger's event_id as a scene change or a
    flare — never services.training_profile_manager.TrainingProfile
    itself (same import-discipline reason as _load_analyzed)."""
    path = config.TRAINING_PROFILES_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _event_role_map(profile_id: str, training_profiles: dict) -> dict[str, str]:
    """{event_id: "scene"|"flare"} for one training profile — the same
    categorization routers/ai_triggers_router.py's own `role_attrs` applies
    when it imports analyzed triggers for playback, so an analyzed song's
    transitions/flares split here agrees with what actually fires it."""
    profile = training_profiles.get(profile_id)
    if not isinstance(profile, dict):
        return {}
    out: dict[str, str] = {}
    for attr, role in _ANALYZED_ROLE_ATTRS.items():
        eid = profile.get(attr) or ""
        if eid:
            out[eid] = role
    return out


def _split_analyzed(cached: dict, training_profiles: dict) -> _SplitMarks:
    """transitions/flares for one song's cached analyzed triggers — the
    role split above. An event_id the owning training profile no longer
    names (profile edited/deleted since the cache was written) falls back
    to a flare rather than vanishing silently."""
    role_map = _event_role_map(cached.get("training_profile_id", ""), training_profiles)
    transitions: list[ReferenceMark] = []
    flares: list[ReferenceMark] = []
    for t in cached.get("triggers") or []:
        if not isinstance(t, dict):
            continue
        mark = ReferenceMark(id=str(t.get("id", "")),
                             timestamp_ms=int(t.get("timestamp_ms", 0) or 0),
                             kind="analyzed", enabled=True)
        if role_map.get(t.get("event_id", "")) == "scene":
            transitions.append(mark)
        else:
            flares.append(mark)
    return _SplitMarks(transitions, flares, n_generated=0, n_promoted=0,
                       n_snapped=0, n_unsnapped_generated=0, snap_grid_counts={})


def _song_marks_for_analyzed(uri: str, cached: dict, summary: _ProfileSummary,
                             training_profiles: dict) -> SongMarks:
    split = _split_analyzed(cached, training_profiles)
    return SongMarks(uri=uri, transitions=split.transitions, flares=split.flares,
                     provenance=summary.provenance,
                     title=summary.title, artist=summary.artist)


def reference_marks_for_song(uri: str) -> tuple[list[ReferenceMark], list[ReferenceMark]]:
    """(transitions, flares) SCORING marks for ONE song — from its cached
    analyzed triggers when it has any (the Admiral: only the analysed
    triggers are "what the Test Bed shows and scores against" now), else
    from the fired copy alone, exactly as before. Test-bed-promoted rows
    are already dropped here (scoring_marks): this is what /compare
    matches against, and matching an engine against its own pushed
    suggestion would make the number a lie. The page's own display list
    (promoted rows included, flagged) is marks_for_song()'s."""
    cached = _load_analyzed(uri)
    if cached is not None:
        split = _split_analyzed(cached, _training_profiles_raw())
        return scoring_marks(split.transitions), scoring_marks(split.flares)
    split = _split(trigger_store.list_for_song(uri),
                   testbed_promote.promoted_trigger_ids(uri))
    return scoring_marks(split.transitions), scoring_marks(split.flares)


def marks_for_song(uri: str) -> SongMarks:
    profile = _find_profile(uri)
    summary = _NO_PROFILE if profile is None else _summarize(profile)
    cached = _load_analyzed(uri)
    if cached is not None:
        return _song_marks_for_analyzed(uri, cached, summary, _training_profiles_raw())
    return _song_marks(uri, trigger_store.list_for_song(uri), summary,
                       testbed_promote.promoted_trigger_ids(uri))


def all_song_marks() -> dict[str, SongMarks]:
    """marks_for_song() for every stored song, merged with every song that
    has cached analyzed triggers (services/analyzed_trigger_store.py,
    storage/analyzed_triggers/*.json) — the gap that otherwise leaves a
    song unlisted whenever its only SPECTRA trigger_store row is the
    analyzed cache's own track_id with no matching triggers.json entry at
    all (his 131 songs, 2026-11).

    The Admiral, verbatim: "i am done adding my own triggers. the analyzed
    triggers are better. we should only focus on the analyzed triggers...
    we don't need to remove the old triggers yet, but they shouldn't be
    part of any future work." Applied to the LIST specifically:
      - a song with analyzed triggers is listed FROM THOSE — never from
        trigger_store, even when it also carries old rows there; the
        analyzed set always wins for this song.
      - a song with only trigger_store rows and at least one source==
        "authored" row (his own old hand placements) and NO analyzed cache
        stays listed (its audio/pin/engine status is still useful) but
        reads as having NOTHING to review: the same empty-reference-marks
        treatment a source=="generated"-only song already got (this
        module's own long-standing exclusion rule, above), now extended to
        his own old rows too, since they are no longer "work" either.
        marks_for_song()/reference_marks_for_song() (the per-song detail
        and /compare routes) are UNCHANGED for this case — deliberately:
        this split is scoped to the LIST's "does this song have work to
        review" read, not to the single-song page, which would need a
        broader, separately-decided change to stop scoring his old marks
        there too.
      - a source=="generated"-only song (no authored row, no analyzed
        cache) is UNCHANGED — still listed with n_generated and empty
        reference marks exactly as before
        (test_a_generated_only_song_stays_listed_with_nothing_to_compare_
        against): there is no old authored row to clear out of that case."""
    profiles = _profile_index()
    promoted = testbed_promote.promoted_ids_by_uri()
    training_profiles = _training_profiles_raw()
    out: dict[str, SongMarks] = {}
    for track_id, cached in _analyzed_index().items():
        uri = f"spotify:track:{track_id}"
        out[uri] = _song_marks_for_analyzed(uri, cached, profiles.get(uri, _NO_PROFILE),
                                            training_profiles)
    for uri, triggers in trigger_store.list_all().items():
        if uri in out:
            continue  # analysed triggers already own this song's marks
        summary = profiles.get(uri, _NO_PROFILE)
        if any(t.source == "authored" for t in triggers):
            split = _split(triggers, promoted.get(uri, set()))
            out[uri] = SongMarks(uri=uri, provenance=summary.provenance,
                                 title=summary.title, artist=summary.artist,
                                 n_generated=split.n_generated,
                                 n_snapped=split.n_snapped,
                                 n_unsnapped_generated=split.n_unsnapped_generated,
                                 snap_grid_counts=split.snap_grid_counts)
        else:
            out[uri] = _song_marks(uri, triggers, summary, promoted.get(uri, set()))
    return dict(sorted(out.items()))
