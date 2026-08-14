"""SPECTRA mid-song trigger generation — front 3 of THE KEYSTONE
(decision-mid-song-model.md, binding): "song analysis GENERATES seeded
scene-change triggers that are ORDINARY AND EDITABLE" — the SAME
SpectraTrigger objects a human places by hand, through the same
trigger_store.upsert the authoring API uses. No separate schema, no
distinct execution path (spectra/models/trigger.py's own binding decision).

Analysis source: analysis_reader.sections_for_uri (the S2 bridge's own
read-only librosa reader — no spot-effects import, per the process-split
import discipline). LibrosaSection boundaries ARE "the analyzed transitions"
the legacy world already computes: each section's start_ms past the song's
own opening is one candidate mid-song scene-change moment. Sections are
already spaced by librosa_service's own min-distance floor
(min_dist_beats), so no extra spacing filter is applied here.

Intensity: each section's own energy_rms, per-song min-max renormalized
with a floor — the same minmax+floor convention
scripts/backfill_trigger_intensity.py established for the legacy world
(CLAUDE.md: raw energy_rms is max-normalized only, no floor subtraction,
so the quietest section of every song lands near 0.33, never near 0).

Scene choice: EVERY generated trigger's fire_scene action carries
scene_id=None — the pick is left to spectra.services.trigger_engine's
kernel routing AT FIRE TIME (curve × genre × affinity, the same selection
kernel the sequencer's own rolls use), not baked in here. Chosen because
LibrosaSection carries no scene reference today — only a structural label
(intro/verse/chorus/bridge/drop/outro) inferred from energy/density rank,
not an authored cue naming a SPECTRA scene. Should a future analysis stage
attach an explicit scene cue to a section, this generator is where it would
be threaded through as a baked scene_id instead — the fire_scene action
already supports both (spectra/models/trigger.py's own docstring).

Idempotent + edit-preserving: every generated trigger carries
source="generated" and generator_key=f"section:{start_ms}", stable across
regenerations of the SAME analysis. generate_for_song:
  - upserts a fresh generated trigger for every current section boundary
    with no matching still-generated trigger in storage,
  - updates a still-generated trigger's timestamp/intensity in place when
    the analysis moved it (re-running librosa can shift boundaries),
  - deletes a still-generated trigger whose generator_key no longer matches
    any current boundary (the analysis changed underneath it),
  - never touches a trigger whose source is "authored" — including a
    formerly-generated trigger a human edited: spectra/api/triggers.py's
    upsert_trigger stamps source="authored" on every write that arrives
    through the editing API, so an edited generated trigger has already
    left this function's reach by the time it runs again.

Whether a generated trigger fires at all is the room-level
midsong_triggers_enabled switch (spectra/services/room_controls.py),
checked by trigger_engine at fire time — generation and storage happen
regardless, so seeded triggers are always visible/editable on the timeline
even with the switch off.
"""
from __future__ import annotations

from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import analysis_reader, trigger_store

INTENSITY_FLOOR = 0.05


def _normalized_intensities(sections: list[dict]) -> list[float]:
    """Per-song min-max stretch of energy_rms with a floor — mirrors
    scripts/backfill_trigger_intensity.py's default `minmax` curve."""
    raw: list[float] = []
    for sec in sections:
        try:
            raw.append(max(0.0, min(1.0, float(sec.get("energy_rms", 0.0)))))
        except (TypeError, ValueError):
            raw.append(0.0)
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    span = hi - lo
    if span <= 1e-9:
        return [0.5 for _ in raw]
    return [round(INTENSITY_FLOOR + ((v - lo) / span) * (1.0 - INTENSITY_FLOOR), 3)
            for v in raw]


def candidate_moments(uri: str) -> list[tuple[int, float, str]]:
    """(timestamp_ms, intensity, generator_key) for every section boundary
    past the song's own start. Empty when no analysis is available yet —
    generation is a no-op, not an error, for an unanalyzed song."""
    sections = analysis_reader.sections_for_uri(uri)
    if not sections:
        return []
    ordered = sorted(sections, key=lambda s: int(s.get("start_ms", 0)))
    intensities = _normalized_intensities(ordered)
    out: list[tuple[int, float, str]] = []
    for sec, intensity in zip(ordered, intensities):
        ms = int(sec.get("start_ms", 0))
        if ms <= 0:
            continue  # the song's own start, not a mid-song moment
        out.append((ms, intensity, f"section:{ms}"))
    return out


def generate_for_song(uri: str) -> dict:
    """Deterministic, idempotent regeneration for one song. No RNG, no
    scene pick — see the module docstring. Returns a summary dict."""
    moments = candidate_moments(uri)
    existing = trigger_store.list_for_song(uri)
    by_key = {t.generator_key: t for t in existing
              if t.source == "generated" and t.generator_key}
    seen_keys: set[str] = set()

    added = updated = 0
    for ms, intensity, key in moments:
        seen_keys.add(key)
        current = by_key.get(key)
        if current is None:
            trigger_store.upsert(uri, SpectraTrigger(
                timestamp_ms=ms, source="generated", generator_key=key,
                action=FireSceneAction(scene_id=None, intensity=intensity)))
            added += 1
        elif (current.timestamp_ms != ms
              or current.action.kind != "fire_scene"
              or current.action.scene_id is not None
              or current.action.intensity != intensity):
            trigger_store.upsert(uri, current.model_copy(update={
                "timestamp_ms": ms,
                "action": FireSceneAction(
                    scene_id=None, intensity=intensity,
                    color_set_id=getattr(current.action, "color_set_id", None)),
            }))
            updated += 1

    deleted = 0
    for key, stale in by_key.items():
        if key not in seen_keys:
            trigger_store.delete(uri, stale.id)
            deleted += 1

    skipped_authored = sum(1 for t in existing if t.source == "authored")
    return {
        "moments": len(moments),
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "skipped_authored": skipped_authored,
    }
