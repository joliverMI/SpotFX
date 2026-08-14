"""Mechanical mapping of legacy MusicTrigger placements onto SPECTRA
SpectraTrigger objects — THE LEDGER (scoping scout `spectra-trigger-
migration-scoping`, data/spectra-trigger-migration-scoping/report.md
sections 3-6, RULING.md).

The Admiral's binding mapping rule (MAPPING-RULE.md): every legacy trigger
lands in exactly one of five buckets — scene change / flare / lull / charge
/ drop. LEDGER below is the single source of truth for that assignment,
covering all 35 distinct event_id values the real 11,252-trigger corpus
(10,710 base + 542 setlist overrides) references — verified against
`/home/javi/SpotFX/storage/profiles/*.json` and `storage/events.json`
read-only during the scout.

His RULING.md then corrected and split the "scene change" bucket further —
this is NOT a sixth bucket of the five-bucket rule, it's a fourth ACTION
that fixed-update-scene/fixed-reset-scene now route to
(UPDATE_BUCKET, distinct from SCENE_CHANGE_BUCKET, both still categorically
"scene change" per the five-bucket rule):

  "mapped"    — everything: flare/charge/lull/drop (RESPONSE_BUCKETS,
                7,164 of 10,710), scene-change triggers that pick a scene
                (SCENE_CHANGE_BUCKET — his ruling: ALL of them go to the
                room's own chooser, fire_scene with scene_id=None, Option
                B, built, do not re-argue; DROP_SCENE_IDS get intensity
                forced to 1.0, his words: "set the intensity to Max for
                any triggers that have drop scenes"), and now
                fixed-update-scene/fixed-reset-scene (UPDATE_BUCKET — his
                correction: "a major change within the scene, bigger than
                the flare, overriding the drift, going somewhere new on a
                ramp-in transition"; reset IS update, one behaviour, not
                two). UPDATE is now BUILT
                (spectra.services.scene_response.ResponseEngine.on_update,
                spectra.models.trigger.FireSceneUpdateAction) — report.md
                section 5b's finding that it didn't exist is superseded by
                that build; this ledger reflects the shipped state.
  "retired"   — Dinner Party Scenes (id 164df939…) and every trigger that
                fires it: scrapped at his word, out of the migration
                entirely. Not carried, not mapped to the chooser, not
                rebuilt. Never written, in any mode.
"""
from __future__ import annotations

import glob
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from spectra.models.trigger import SpectraTrigger

logger = logging.getLogger(__name__)

Bucket = str  # "flare" | "charge" | "drop" | "lull" | "scene change" | "update"
Status = str  # "mapped" | "retired"
RESPONSE_BUCKETS = {"flare", "charge", "drop", "lull"}
SCENE_CHANGE_BUCKET = "scene change"
UPDATE_BUCKET = "update"
ALL_BUCKETS = RESPONSE_BUCKETS | {SCENE_CHANGE_BUCKET, UPDATE_BUCKET}

# "Drop scenes" (a scene pick themed around a musical drop) — NOT the fixed
# "drop" response class (phase machinery, untouched by this). His ruling
# section 2: these override the trigger's own recorded intensity with MAX.
DROP_SCENE_IDS = frozenset({
    "030ccfab-5f3f-4c8c-8556-80e366309153",  # Drop Group
    "235b76bd-c733-46fa-8868-35fb896a83d7",  # Bass Drop Scenes
    "c5c81de8-8712-423e-b837-3a1a80bf6228",  # Trap Drop Scenes
    "de8b053e-397b-410d-97d0-2f19cacc8ad0",  # Bass Drop Sequence
})
MAX_INTENSITY = 1.0

# Scrapped at his word (RULING.md addition) — out of the migration entirely.
RETIRED_IDS = frozenset({
    "164df939-217e-4081-a2d3-dc523cb5eca3",  # Dinner Party Scenes
})

# RESET IS TREATED AS UPDATE (his correction) — one behaviour, both route to
# UPDATE_BUCKET / map_update.
UPDATE_IDS = frozenset({
    "fixed-update-scene",
    "fixed-reset-scene",
})


@dataclass(frozen=True)
class LedgerEntry:
    event_id: str
    name: str
    bucket: Bucket
    judgment: bool   # False = exact per the Admiral's rule; True = agent's call, recorded
    reason: str

    @property
    def status(self) -> Status:
        """mapped = built and migratable; retired = scrapped at his word,
        never migrated."""
        if self.event_id in RETIRED_IDS:
            return "retired"
        return "mapped"


# ── Exact (9): the fixed-* response sentinels + "Intensity Scene" (his own example) ──
_EXACT: list[LedgerEntry] = [
    LedgerEntry("fixed-charge", "fixed-charge", "charge", False,
                'exact — legacy fixed charge event is SPECTRA event_class="charge"'),
    LedgerEntry("fixed-lull", "fixed-lull", "lull", False,
                'exact — legacy fixed lull event is SPECTRA event_class="lull"'),
    LedgerEntry("fixed-drop", "fixed-drop", "drop", False,
                'exact — legacy fixed drop event is SPECTRA event_class="drop"'),
    LedgerEntry("fixed-shape-flare", "fixed-shape-flare", "flare", False,
                'exact per rule — "all flares are flare triggers" (shape variant)'),
    LedgerEntry("fixed-combo-flare", "fixed-combo-flare", "flare", False,
                'exact per rule — "all flares are flare triggers" (combo variant)'),
    LedgerEntry("fixed-color-flare", "fixed-color-flare", "flare", False,
                'exact per rule — "all flares are flare triggers" (color variant)'),
    LedgerEntry("37b62a98-3544-4157-a444-ac605b146039", "Intensity Scene", "scene change", False,
                'exact — this is "Intensity Scene", the Admiral\'s own named example'),
]

# ── Judgment calls (21): fixed-update/reset-scene + the 19 long-tail composites, ──
# ── read (event_type + full action tree) individually — report.md section 4     ──
_JUDGMENT: list[LedgerEntry] = [
    LedgerEntry("fixed-update-scene", "fixed-update-scene", "update", True,
                "RULING CORRECTION: originally read as 'keep playing what's up' and "
                "bucketed alongside scene picks. His words: update is a major change "
                "WITHIN the current scene, bigger than a flare, overriding drift, "
                "landing on a ramp-in — not a scene pick. BUILT: routes to "
                "fire_scene_update -> ResponseEngine.on_update (scene_response.py), "
                "which fires the active scene's own update_kind (a type=\"permanent\" "
                "FlareKind), bypassing intensity-band selection entirely"),
    LedgerEntry("fixed-reset-scene", "fixed-reset-scene", "update", True,
                "RULING CORRECTION: RESET IS TREATED AS UPDATE (his words) — same "
                "behaviour and same routing as fixed-update-scene above, not a "
                "separate 'fresh start' reading"),
    LedgerEntry("2b162f23-a5a5-4a29-a4ac-9d4dfa7df200", "3 Beat Color Change", "flare", True,
                "ledfx_effect_param patch over a beat sequence — momentary param change, "
                "no scene pick"),
    LedgerEntry("7af670bb-262a-4ea5-ae4d-9da8185488ac", "Dinner Flare - Shape", "flare", True,
                "named Flare; random_group of five shape-nudge sub-events — momentary "
                "shape nudges, no scene pick"),
    LedgerEntry("b86d3e0c-f3f3-4352-86ed-66869121ece1", "2 Beat Flare", "flare", True,
                "named Flare; ledfx_effect_param over a beat sequence"),
    LedgerEntry("164df939-217e-4081-a2d3-dc523cb5eca3", "Dinner Party Scenes", "scene change", True,
                'random_group -> event_ref -> "Chill Scenes" (itself a pool pick) — a scene '
                'pick. RULING ADDITION: scrapped at his word — that pool and its triggers '
                'are out of the migration entirely. status=retired'),
    LedgerEntry("deba6356-7b7e-49aa-875e-1b46f52a73b2", "Very Dark", "flare", True,
                "morph_step brightness/color patch — momentary look change, not a scene pick"),
    LedgerEntry("936503cc-ed64-4ee1-8617-f64196e14916", "Dinner Party Color Morph", "flare", True,
                "set_color across a parallel_group — momentary color change, matches the "
                "flare colour-jump kind"),
    LedgerEntry("22748c27-282a-45fb-a8ae-756a6cd6fda4", "Half Brightness", "flare", True,
                "morph_step brightness patch"),
    LedgerEntry("ce1d6715-4437-4269-b14c-85cca63c42fa", "Dim Ambient over 5", "flare", True,
                "ledfx_effect_param patch (ambient dim, 5s ramp)"),
    LedgerEntry("3439c312-1b63-43fb-9f2b-a81bf812c4fe", "Dim Ambient over 2", "flare", True,
                "ledfx_effect_param patch (ambient dim, 2s ramp)"),
    LedgerEntry("9e9c8784-4489-4448-b2fd-a33da1863c49", "Contrast 2 Beat Fast", "flare", True,
                "morph_color over a beat sequence — momentary hue rotation"),
    LedgerEntry("aec87bbd-9724-4850-92b7-00bc46f54cde", "Color Blue", "flare", True,
                "ledfx_ambient patch — one-shot color set on the ambient virtual"),
    LedgerEntry("27bdb6b9-d4d7-4194-aa5a-11f8883d3e40", "Ambient Beats", "flare", True,
                "device_settings patch (frequency band) — momentary param change"),
    LedgerEntry("be30fd97-ebd9-4d16-b68b-779bb76573a9", "Ambient Highs", "flare", True,
                "device_settings patch (frequency band)"),
    LedgerEntry("a3d73615-b6b7-42f4-8c06-22bac9cc0098", "Reverse", "flare", True,
                "ledfx_effect_param patch (reverse flag) over a beat sequence"),
    LedgerEntry("af1343e0-1de9-43a4-9a62-e0f376a89e35", "Import: Calm - Rose Gold Lines", "flare", True,
                "scene_override morph_step \"look\" staged via the shared temp-scene "
                "mechanism — a param/color patch, not a library scene pick"),
    LedgerEntry("26d91746-c808-47f6-9438-38b952ca198a", "Full Brightness", "flare", True,
                "morph_step brightness patch"),
    LedgerEntry("030ccfab-5f3f-4c8c-8556-80e366309153", "Drop Group", "scene change", True,
                "named \"Drop\" but mechanically a weighted-random pick among 8 named "
                "scenes (Hype Star/Fireworks/Black Hole/Pacman/Squiggles/Dancers/Orbits/"
                "Eye) — functionally identical to Intensity Scene's pool-pick mechanism; "
                "bucketed as scene change, NOT drop, despite the name. A \"drop scene\" "
                "per his ruling section 2 — intensity forced to MAX, not the recorded "
                "value (DROP_SCENE_IDS)"),
    LedgerEntry("7f6b3c78-85f2-444b-a325-80a3ebe25890", "4 Beat Color Change", "flare", True,
                "ledfx_effect_param patch over a beat sequence"),
    LedgerEntry("1651d7dc-f19c-45b6-bb39-4bd9480ececc", "Ambient Flip and Back - Slow", "flare", True,
                "morph_color over a beat sequence"),
]

# ── setlist_triggers-only judgment calls (7): report.md section 6 flagged     ──
# ── these as needing the same read-the-real-mechanism treatment as the base   ──
# ── corpus before migration is complete; done here rather than left open.     ──
_SETLIST_JUDGMENT: list[LedgerEntry] = [
    LedgerEntry("201e7c4f-88d9-46e4-855e-3bcf93ecefd0", "EDM Charge Scenes", "scene change", True,
                "named \"Charge\" but every event_ref resolves to a scene_update "
                "(Lines/Black Hole/Orbits) — a scene pool pick, same name-vs-mechanism "
                "mismatch as Drop Group; bucketed as scene change, not charge"),
    LedgerEntry("235b76bd-c733-46fa-8868-35fb896a83d7", "Bass Drop Scenes", "scene change", True,
                "single event_ref resolves to scene_update \"Hype Star\" — a direct scene pick"),
    LedgerEntry("7264b514-fe81-4a39-904f-13eef5c93216", "Lull Event - EDM", "flare", True,
                "named \"Lull\" but both event_refs resolve to \"Very Dark\"/\"Very Dark, "
                "Fade\" composites — morph_step brightness patches (the same mechanism "
                "already bucketed flare above), not the fixed lull phase machinery; "
                "bucketed as flare, not lull, despite the name"),
    LedgerEntry("c5c81de8-8712-423e-b837-3a1a80bf6228", "Trap Drop Scenes", "scene change", True,
                "event_type=scene_update with a single ledfx_scene action — a direct scene pick"),
    LedgerEntry("dd0354f5-e4ac-4aa1-a17a-166a46cd0a13", "Mid Charge Scenes", "scene change", True,
                "named \"Charge\" but every event_ref resolves to a scene_update "
                "(Black Hole/Lines) — a scene pool pick, same pattern as EDM Charge "
                "Scenes; bucketed as scene change, not charge"),
    LedgerEntry("de8b053e-397b-410d-97d0-2f19cacc8ad0", "Bass Drop Sequence", "scene change", True,
                "its one event_ref IS \"Drop Group\" (the scene_group already bucketed "
                "scene change above) — a wrapper around the same pool pick"),
    LedgerEntry("e669da41-9781-4788-96a0-84dd2513f40f", "Bass Drop Morph", "flare", True,
                "morph_step + set_color patch, no scene_update/scene_group reference at "
                "any leaf — a momentary look/color change, not a scene pick"),
]

LEDGER: dict[str, LedgerEntry] = {e.event_id: e for e in (*_EXACT, *_JUDGMENT, *_SETLIST_JUDGMENT)}
assert len(LEDGER) == 35, f"expected all 35 known event_ids (28 base-corpus + 7 setlist-only), got {len(LEDGER)}"
assert all(e.bucket in ALL_BUCKETS for e in LEDGER.values())


def classify(event_id: str) -> Optional[LedgerEntry]:
    """None means: not one of the 28 ids seen in the real corpus during the
    scout. Callers must not guess a bucket for an unknown id — count it as
    unclassified and surface it, the same discipline the ledger itself was
    built with."""
    return LEDGER.get(event_id)


def map_unambiguous(music_trigger: dict) -> Optional[dict]:
    """Legacy MusicTrigger dict -> SpectraTrigger-shaped dict, ONLY for the
    four response buckets (flare/charge/lull/drop). Returns None for
    anything else — kept as its own function (rather than folded into
    map_trigger) because its shape (fire_response) and invariants are
    simpler and independently tested."""
    entry = classify(music_trigger["event_id"])
    if entry is None or entry.bucket not in RESPONSE_BUCKETS:
        return None
    return {
        "id": music_trigger["id"],
        "timestamp_ms": music_trigger["timestamp_ms"],
        "enabled": music_trigger.get("enabled", True),
        "source": "authored",
        "generator_key": None,
        "action": {
            "kind": "fire_response",
            "event_class": entry.bucket,
            "intensity": music_trigger.get("intensity", 0.5),
        },
    }


def map_scene_change(music_trigger: dict) -> Optional[dict]:
    """Legacy MusicTrigger dict -> SpectraTrigger-shaped dict for the
    scene-change bucket, per his ruling: ALL scene-change triggers fire
    through the room's own chooser — Option B, scene_id=None, no per-trigger
    pool restriction (built, not re-argued). A "drop scene" (DROP_SCENE_IDS
    — a scene pick themed around a musical drop, distinct from the fixed
    "drop" response class) gets intensity forced to MAX instead of its
    recorded value: the drop scene overrides the trigger's own energy, his
    words exactly.

    Returns None for a retired id (Dinner Party Scenes — scrapped, never
    migrated), a blocked id (update/reset — the behaviour doesn't exist yet,
    never silently mapped here), a non-scene-change bucket, or an unknown
    id."""
    entry = classify(music_trigger["event_id"])
    if entry is None or entry.bucket != SCENE_CHANGE_BUCKET or entry.status != "mapped":
        return None
    intensity = MAX_INTENSITY if entry.event_id in DROP_SCENE_IDS else music_trigger.get("intensity", 0.5)
    return {
        "id": music_trigger["id"],
        "timestamp_ms": music_trigger["timestamp_ms"],
        "enabled": music_trigger.get("enabled", True),
        "source": "authored",
        "generator_key": None,
        "action": {
            "kind": "fire_scene",
            "scene_id": None,
            "intensity": intensity,
            "color_set_id": None,
        },
    }


def map_update(music_trigger: dict) -> Optional[dict]:
    """Legacy MusicTrigger dict -> SpectraTrigger-shaped dict for
    UPDATE_BUCKET (fixed-update-scene / fixed-reset-scene, one behaviour
    per his correction). Maps to fire_scene_update with the trigger's own
    recorded intensity — no scene_id, no event_class, just the one field
    on_update needs to compute its ramp and scale (spectra.services.
    scene_response.ResponseEngine.on_update / update_ramp_ms).

    Returns None for a non-update bucket, a retired id, or an unknown id."""
    entry = classify(music_trigger["event_id"])
    if entry is None or entry.bucket != UPDATE_BUCKET or entry.status != "mapped":
        return None
    return {
        "id": music_trigger["id"],
        "timestamp_ms": music_trigger["timestamp_ms"],
        "enabled": music_trigger.get("enabled", True),
        "source": "authored",
        "generator_key": None,
        "action": {
            "kind": "fire_scene_update",
            "intensity": music_trigger.get("intensity", 0.5),
        },
    }


def map_trigger(music_trigger: dict) -> Optional[dict]:
    """The one entry point a migration writer should call: dispatches to
    map_unambiguous / map_scene_change / map_update by bucket, or returns
    None for a retired/unknown id — the same None either way, so a caller
    cannot accidentally treat "not migrated" differently by bucket."""
    entry = classify(music_trigger["event_id"])
    if entry is None:
        return None
    if entry.bucket in RESPONSE_BUCKETS:
        return map_unambiguous(music_trigger)
    if entry.bucket == SCENE_CHANGE_BUCKET:
        return map_scene_change(music_trigger)
    if entry.bucket == UPDATE_BUCKET:
        return map_update(music_trigger)
    return None


@dataclass
class MigrationSummary:
    mapped: int = 0
    by_class: dict = field(default_factory=dict)   # response event_class, "scene change", or "update"
    retired: int = 0     # Dinner Party Scenes — scrapped at his word
    unclassified: int = 0
    unclassified_ids: set = field(default_factory=set)
    invalid_timestamp: int = 0     # timestamp_ms < 0 in the real source data — see migrate()
    invalid_timestamp_examples: list = field(default_factory=list)
    written: int = 0
    drop_scene_max_intensity: int = 0   # of `mapped`, how many got the MAX-intensity override

    @property
    def total(self) -> int:
        return (self.mapped + self.retired
                + self.unclassified + self.invalid_timestamp)


def iter_legacy_triggers(profiles_glob: str,
                          include_setlist: bool = False) -> Iterator[tuple[str, dict]]:
    """Yields (spotify_uri, MusicTrigger dict) read-only from legacy profile
    files. include_setlist also walks setlist_triggers overrides (report.md
    section 6) — off by default since the base `triggers` list is the
    10,710 the Admiral and the brief both mean by that number."""
    for path in sorted(glob.glob(profiles_glob)):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        uri = data["spotify_uri"]
        for t in data.get("triggers", []):
            yield uri, t
        if include_setlist:
            for trigs in data.get("setlist_triggers", {}).values():
                for t in trigs:
                    yield uri, t


def migrate(profiles_glob: str, *, apply: bool = False,
            include_setlist: bool = False) -> MigrationSummary:
    """Dry-run by default (apply=False): classifies and validates every
    trigger, writes nothing. apply=True writes every MAPPED trigger —
    response-bucket, scene-change-bucket (Option B), AND update-bucket (now
    built, per his ruling) — through spectra.services.trigger_store.upsert,
    the same per-trigger, atomic, idempotent write path the live authoring
    API uses.

    Retired (Dinner Party Scenes — scrapped at his word) and unclassified
    triggers are NEVER written, in either mode — this function enforces
    that, it doesn't just document it.

    A small real-data finding from running this against the live corpus:
    5 "Intensity Scene" triggers carry a negative timestamp_ms (a small
    pre-roll before the song's own position 0, -50ms to -1950ms —
    SpectraTrigger requires timestamp_ms >= 0). Not silently clamped to 0
    here — that's an authoring-intent guess this function doesn't make;
    counted as `invalid_timestamp` and never written, same discipline as
    an unclassified id."""
    summary = MigrationSummary()
    trigger_store = None
    if apply:
        from spectra.services import trigger_store as _trigger_store
        trigger_store = _trigger_store

    for uri, t in iter_legacy_triggers(profiles_glob, include_setlist=include_setlist):
        entry = classify(t["event_id"])
        if entry is None:
            summary.unclassified += 1
            summary.unclassified_ids.add(t["event_id"])
            continue
        if entry.status == "retired":
            summary.retired += 1
            continue
        if t["timestamp_ms"] < 0:
            summary.invalid_timestamp += 1
            if len(summary.invalid_timestamp_examples) < 10:
                summary.invalid_timestamp_examples.append(
                    {"uri": uri, "id": t["id"], "timestamp_ms": t["timestamp_ms"]})
            continue

        out = map_trigger(t)
        assert out is not None  # status == "mapped", guaranteed by classify() above
        validated = SpectraTrigger.model_validate(out)  # raises if the ledger ever drifts from the model
        summary.mapped += 1
        summary.by_class[entry.bucket] = summary.by_class.get(entry.bucket, 0) + 1
        if entry.event_id in DROP_SCENE_IDS:
            summary.drop_scene_max_intensity += 1

        if apply:
            trigger_store.upsert(uri, validated)
            summary.written += 1

    return summary
