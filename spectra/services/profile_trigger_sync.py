"""HIS TRIGGER EDITS MUST REACH HIS SHOW — the reconciliation between the
two trigger worlds, and the mechanism that keeps them reconciled.

THE BUG THIS EXISTS FOR (his words, 2026-08-24): "I have updated several
song profiles/triggers and I want those updates reflected in Spectra. The
system still fires on the old triggers, despite me being in My Triggers
Only mode."

There are two copies of every hand-authored trigger:

  EDITOR COPY   storage/profiles/*.json — the legacy SongProfile.
                The Profile Builder timeline (his "Timeline of Spectra",
                /spectra/timeline) reads and writes THIS one, through the
                spot-effects root API (POST /api/profiles).
  FIRED COPY    storage/spectra/triggers.json (spectra/services/
                trigger_store.py) — the ONLY store spectra/services/
                trigger_engine.py ever fires from.

spectra/services/legacy_trigger_migration.py landed the editor copy into the
fired copy ONCE. Nothing kept them together afterwards, so every edit he made
since stayed in the editor copy while the room kept firing the migrated
snapshot. The engine was never wrong; the data never arrived.

WHAT THIS MODULE IS. A pure planner (`plan_song`) over three inputs — the
song's legacy triggers, the song's fired-copy triggers, and the provenance
ledger (spectra/services/profile_sync_ledger.py) — producing a `SyncPlan`
that a caller applies as ONE batched write (`apply_plan`). Both the deploy-
time reconcile (scripts/reconcile_profile_triggers.py) and the on-save hook
(POST /api/triggers/sync-from-profile) run the identical planner, so a
one-off catch-up and a routine save can never disagree about what a song
should contain.

THE FOUR STANDING DECISIONS, stated rather than implied:

  1. THE COPY BEING SAVED WINS, for that song, at that moment. A profile
     trigger that maps is written over whatever the fired copy holds under
     the same id — timestamp, enabled flag and action alike.
  2. AUTHORED MATERIAL ONLY CROSSES. source="generated" triggers (19,023 of
     his) are never read, never written, never deleted by this module. They
     have no counterpart in the profile world by design (they are seeded from
     librosa sections, see spectra/services/midsong_generator.py).
  3. A DELETE IS PROVENANCE-GATED. A fired-copy authored trigger absent from
     the profile is removed ONLY if the ledger has previously seen that id in
     this song's profile. A trigger born on SPECTRA's own card (18 of his,
     and every one authored there in future) is never touched — reported as
     `protected`, not deleted.
  4. AN UNMAPPABLE PROFILE TRIGGER TAKES ITS FIRED COUNTERPART WITH IT.
     Retired ids (Dinner Party Scenes — scrapped at his word), ids outside the
     migration ledger, and negative timestamps are never WRITTEN; and where
     the fired copy still holds a provenance-known row under that same id, that
     row is removed, because decision 1 says the profile wins and the ledger's
     own rule is that a retired event never fires. Every such trigger is
     reported by reason rather than silently dropped — the 5 negative-timestamp
     triggers in his corpus (a -50ms..-1950ms pre-roll, which SpectraTrigger's
     `timestamp_ms >= 0` cannot express) are preserved untouched in his
     profiles and named in the report, never clamped to 0: clamping is an
     authoring-intent guess this code does not make, exactly as
     legacy_trigger_migration.migrate already refuses to make it.

THE REVERSE DIRECTION (`plan_reverse`) is deliberately narrow. The forward
map is many-to-one — 35 legacy event ids collapse into 4 SPECTRA action
shapes — so most SPECTRA-side edits have no faithful legacy expression and
are skipped by name, never guessed at. What IS faithful, for a trigger the
ledger knows the legacy event id of: `timestamp_ms`, `enabled`, and
`intensity` (except on a DROP_SCENE_IDS trigger, whose recorded intensity the
forward map deliberately overrides with MAX — writing the fired value back
there would destroy his authored number). Those three are patched onto the
RAW profile dict in place, leaving every other legacy field byte-identical —
the same raw-dict discipline AGENTS.md already mandates for single-field
scene edits, and for the same reason: a model round-trip rewrites fields the
edit never touched.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from spectra.models.trigger import SpectraTrigger
from spectra.services import legacy_trigger_migration as ltm

logger = logging.getLogger(__name__)

# Why a profile trigger did not cross. Reported, never silent.
SKIP_RETIRED = "retired"                 # scrapped at his word — never migrated
SKIP_UNCLASSIFIED = "unclassified"       # event_id outside the 35-id ledger
SKIP_NEGATIVE_TIMESTAMP = "negative_timestamp"   # pre-roll; SpectraTrigger needs >= 0


@dataclass(frozen=True)
class SkippedTrigger:
    trigger_id: str
    event_id: str
    timestamp_ms: int
    reason: str


@dataclass
class SyncPlan:
    """What ONE song's reconciliation would do. Empty `upserts`+`deletes`
    means the two copies already agree — `apply_plan` then writes nothing at
    all, which is what makes an unchanged save free."""
    uri: str
    upserts: list[SpectraTrigger] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[SkippedTrigger] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)   # card-born, left alone
    generated_untouched: int = 0
    # {trigger_id: legacy event_id} — this song's provenance AFTER the plan
    # lands. Written to the ledger by apply_plan.
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def changes(self) -> int:
        return len(self.upserts) + len(self.deletes)

    def summary(self) -> dict:
        by_reason: dict[str, int] = {}
        for s in self.skipped:
            by_reason[s.reason] = by_reason.get(s.reason, 0) + 1
        return {
            "uri": self.uri,
            "written": len(self.upserts),
            "deleted": len(self.deletes),
            "unchanged": self.unchanged,
            "skipped": by_reason,
            "protected_spectra_authored": len(self.protected),
            "generated_untouched": self.generated_untouched,
        }


def _same(existing: SpectraTrigger, incoming: SpectraTrigger) -> bool:
    """Would writing `incoming` change anything on disk? Compared through the
    MODEL's own serialization, not the raw dicts: a stored row predating a
    later-added field (fire_scene's `scene_pool`, `trigger_offset_ms`) is
    materially identical to a freshly built one, and a raw-dict compare would
    report every such row as a change and rewrite 10,689 triggers for nothing.

    trigger_offset_ms is carried over from the existing row rather than
    compared: it is a SPECTRA-only field (his drag-the-marker offset, see
    docs/SPECTRA_TIMING_CONVENTIONS.md) that the legacy MusicTrigger has no
    equivalent for, so a profile save must not reset it — see `_carry_forward`.
    """
    return existing.model_dump_json() == incoming.model_dump_json()


def _carry_forward(existing: Optional[SpectraTrigger],
                   incoming: SpectraTrigger) -> SpectraTrigger:
    """Preserve SPECTRA-only state the profile world cannot express, so a
    profile save never silently resets it. Today that is exactly
    `trigger_offset_ms` — every other SpectraTrigger field is either derived
    from the legacy trigger (id / timestamp / enabled / action) or fixed by
    the migration (source="authored", generator_key=None)."""
    if existing is None or existing.trigger_offset_ms == incoming.trigger_offset_ms:
        return incoming
    return incoming.model_copy(update={"trigger_offset_ms": existing.trigger_offset_ms})


def plan_song(uri: str,
              profile_triggers: list[dict],
              fired_triggers: list[dict],
              known_profile_ids: dict[str, str]) -> SyncPlan:
    """Pure — no I/O, no clock, no storage. `profile_triggers` are RAW legacy
    MusicTrigger dicts; `fired_triggers` are RAW rows out of triggers.json;
    `known_profile_ids` is this song's provenance ledger view
    ({trigger_id: legacy event_id}).

    Provenance grows here as well as being read: any fired-copy authored row
    whose id is present in the profile RIGHT NOW is proven profile-origin, so
    a song never reconciled before is seeded correctly by its first sync."""
    plan = SyncPlan(uri=uri)

    fired_authored: dict[str, dict] = {}
    for row in fired_triggers:
        if row.get("source", "authored") == "generated":
            plan.generated_untouched += 1
            continue
        tid = row.get("id")
        if tid:
            fired_authored[tid] = row

    seen_profile_ids: set[str] = set()
    for raw in profile_triggers:
        tid = raw.get("id")
        if not tid:
            continue
        seen_profile_ids.add(tid)
        event_id = raw.get("event_id", "")
        entry = ltm.classify(event_id)
        if entry is None:
            reason = SKIP_UNCLASSIFIED
        elif entry.status == "retired":
            reason = SKIP_RETIRED
        elif raw.get("timestamp_ms", 0) < 0:
            reason = SKIP_NEGATIVE_TIMESTAMP
        else:
            reason = ""
        if reason:
            plan.skipped.append(SkippedTrigger(
                trigger_id=tid, event_id=event_id,
                timestamp_ms=int(raw.get("timestamp_ms", 0)), reason=reason))
            # Decision 4: the profile wins — a fired row we planted earlier
            # under this id must not keep firing a retired/unmappable event.
            if tid in fired_authored and tid in known_profile_ids:
                plan.deletes.append(tid)
            continue

        mapped = ltm.map_trigger(raw)
        if mapped is None:      # classify() said mapped; map_trigger disagreed
            plan.skipped.append(SkippedTrigger(
                trigger_id=tid, event_id=event_id,
                timestamp_ms=int(raw.get("timestamp_ms", 0)),
                reason=SKIP_UNCLASSIFIED))
            continue

        incoming = SpectraTrigger.model_validate(mapped)
        existing_raw = fired_authored.get(tid)
        existing = None
        if existing_raw is not None:
            try:
                existing = SpectraTrigger.model_validate(existing_raw)
            except Exception as exc:   # a corrupt stored row — replace it
                logger.warning("fired trigger %s (%s) unreadable, replacing: %s",
                               tid, uri, exc)
        incoming = _carry_forward(existing, incoming)
        plan.provenance[tid] = event_id
        if existing is not None and _same(existing, incoming):
            plan.unchanged += 1
        else:
            plan.upserts.append(incoming)

    # Fired-copy authored rows the profile no longer carries.
    for tid in fired_authored:
        if tid in seen_profile_ids:
            continue
        if tid in known_profile_ids:
            plan.deletes.append(tid)            # decision 3: provably his profile's
        else:
            plan.protected.append(tid)          # card-born (or unproven) — untouched

    return plan


def apply_plan(plan: SyncPlan) -> dict:
    """Land a plan: ONE batched triggers.json write, then the ledger. Writes
    nothing at all when the plan has no changes — but still refreshes this
    song's provenance, which is how a never-before-reconciled song becomes
    delete-safe without touching a single trigger."""
    from spectra.services import profile_sync_ledger, trigger_store

    if plan.changes:
        trigger_store.apply_batch(plan.uri, plan.upserts, plan.deletes)

    ledger = profile_sync_ledger.load()
    before = profile_sync_ledger.for_song(ledger, plan.uri)
    after = dict(plan.provenance)
    # Keep provenance for ids we deliberately did not touch this pass
    # (protected/card-born ids were never in the ledger by definition; a
    # deleted id drops out).
    if after != before:
        profile_sync_ledger.set_song(ledger, plan.uri, after)
        profile_sync_ledger.save(ledger)
    return plan.summary()


# ── Reverse: SPECTRA card -> profile, faithful fields only ────────────────────

REVERSE_FIELDS = ("timestamp_ms", "enabled", "intensity")


@dataclass(frozen=True)
class ReverseEdit:
    trigger_id: str
    event_id: str
    changes: dict          # {field: (old, new)}


@dataclass
class ReversePlan:
    uri: str
    edits: list[ReverseEdit] = field(default_factory=list)
    # ids present in the fired copy with no faithful legacy expression
    skipped_lossy: list[str] = field(default_factory=list)
    # ids the ledger cannot tie back to a legacy event — card-born
    skipped_unknown_origin: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"uri": self.uri, "edits": len(self.edits),
                "skipped_lossy": len(self.skipped_lossy),
                "skipped_unknown_origin": len(self.skipped_unknown_origin)}


def _reverse_intensity(action: dict, event_id: str) -> Optional[float]:
    """The fired action's intensity, when it is faithfully HIS number.

    None means "do not write it back": either the action kind carries no
    intensity, or the forward map overrode his recorded value with MAX
    (DROP_SCENE_IDS — his own ruling, "set the intensity to Max for any
    triggers that have drop scenes"), in which case the fired value says
    nothing about what he authored."""
    if event_id in ltm.DROP_SCENE_IDS:
        return None
    value = action.get("intensity")
    return float(value) if isinstance(value, (int, float)) else None


def plan_reverse(uri: str,
                 profile_triggers: list[dict],
                 fired_triggers: list[dict],
                 known_profile_ids: dict[str, str]) -> ReversePlan:
    """Pure. What a SPECTRA-side edit would faithfully write back into this
    song's profile — only the fields REVERSE_FIELDS names, only for triggers
    the ledger ties to a known legacy event id, and only where the fired copy
    genuinely disagrees with the profile."""
    plan = ReversePlan(uri=uri)
    by_id = {t.get("id"): t for t in profile_triggers if t.get("id")}

    for row in fired_triggers:
        if row.get("source", "authored") == "generated":
            continue
        tid = row.get("id")
        if not tid:
            continue
        event_id = known_profile_ids.get(tid)
        if event_id is None or tid not in by_id:
            # Card-born (or provenance never established): there is no legacy
            # event to write back TO. Named, never invented.
            plan.skipped_unknown_origin.append(tid)
            continue
        legacy = by_id[tid]
        action = row.get("action") or {}

        # Did he change the ACTION on the SPECTRA card? The forward map is
        # many-to-one, so a changed kind cannot be expressed as a legacy
        # event_id without picking one of many candidates — lossy by
        # construction, skipped by name.
        forward = ltm.map_trigger(legacy)
        if forward is None or forward["action"].get("kind") != action.get("kind"):
            plan.skipped_lossy.append(tid)
            continue

        changes: dict = {}
        ts = row.get("timestamp_ms")
        if isinstance(ts, int) and ts != legacy.get("timestamp_ms"):
            changes["timestamp_ms"] = (legacy.get("timestamp_ms"), ts)

        enabled = bool(row.get("enabled", True))
        if enabled != bool(legacy.get("enabled", True)):
            changes["enabled"] = (legacy.get("enabled", True), enabled)

        intensity = _reverse_intensity(action, event_id)
        if intensity is not None:
            old = float(legacy.get("intensity", 0.5))
            if abs(intensity - old) > 1e-9:
                changes["intensity"] = (old, intensity)

        if changes:
            plan.edits.append(ReverseEdit(trigger_id=tid, event_id=event_id,
                                          changes=changes))
    return plan


def apply_reverse(plan: ReversePlan, profile_raw: dict) -> int:
    """Patch a RAW profile dict in place — mutating only the three fields
    REVERSE_FIELDS names on the specific triggers the plan chose. Everything
    else in his profile (labels, override_blend, colour-group/display-mode
    overrides, and every profile-level field) is left byte-identical, which
    a model round-trip would not guarantee. Returns the number of triggers
    touched; the CALLER writes the file."""
    edits = {e.trigger_id: e for e in plan.edits}
    touched = 0
    for raw in profile_raw.get("triggers", []):
        edit = edits.get(raw.get("id"))
        if edit is None:
            continue
        for key, (_old, new) in edit.changes.items():
            raw[key] = new
        touched += 1
    return touched


def diff_json(before: object, after: object) -> list[str]:
    """Line-level diff of two JSON-serializable objects — the proof surface
    a --apply run prints so only the intended rows can move. Kept here rather
    than in the script so tests can assert on it."""
    import difflib
    a = json.dumps(before, indent=2, sort_keys=True).splitlines()
    b = json.dumps(after, indent=2, sort_keys=True).splitlines()
    return list(difflib.unified_diff(a, b, "before", "after", lineterm="", n=1))
