"""SPECTRA-native per-song trigger — THE KEYSTONE (decision-mid-song-model.md,
binding, 2026-08-13): "scene changes are driven by triggers." A trigger is
placed at ONE song moment (timestamp_ms into a spotify_uri) and fires exactly
one SPECTRA-native action:

  fire_scene        scene_id + intensity (+ optional explicit colour set) —
                     through spectra.services.scene_sequencer.fire_scene_by_id,
                     the SAME fire choke point the sequencer's own picks use.
  fire_response      event_class (flare/charge/lull/drop) + intensity —
                     through the S2 response engine, the same path the
                     bridge's classified trigger_fired events already drive.
  select_color_set   set_id — the room's supported manual-apply surface
                     (drift_conductor.apply_set_directly), the same one
                     POST /api/room-color/apply uses.
  fire_scene_update  intensity only — through
                     spectra.services.scene_response.ResponseEngine.
                     on_update, the UPDATE behaviour (data/spectra-trigger-
                     migration-scoping RULING.md, 2026-08-14): "a major
                     change within the scene, bigger than a flare,
                     overriding the drift, going somewhere new on a
                     ramp-in transition." Fires the ACTIVE scene's own
                     SceneV2.update_kind by name, bypassing intensity-band
                     selection entirely (unlike fire_response) — no
                     update_kind authored on the active scene is a silent
                     no-op, same convention as an empty response band.
                     Reset is the SAME action (his correction: "reset is
                     treated as update" — one behaviour, not two).

ONE mechanism, not two (the binding decision): the seeded transitions-only
default and heavily hand-tuned mid-song shows are the same trigger list at
different densities. This model is deliberately generation-friendly — a
later mid-song-generation stage constructs these SAME SpectraTrigger objects
programmatically and calls the same trigger_store.upsert; no separate
"generated" schema, no distinct execution path.

Dropped from the legacy vocabulary per decision-legacy-retirement-picks.md:
label filtering, per-trigger display-mode/colour-group/drop-group overrides,
Override Blend (all owner-retired or routed elsewhere) — a SPECTRA trigger
carries only what it needs to name a moment and an action.

Front 3 (mid-song generation, decision-mid-song-model.md binding): a
generated trigger's fire_scene action carries scene_id=None — "name a
moment, not a scene" — so spectra.services.trigger_engine routes the pick
through the sequencer selection kernel (curve × genre × affinity) AT FIRE
TIME, the same kernel the sequencer's own rolls use
(spectra.services.midsong_generator). scene_id is only ever baked in at
generation time when the analysis carries an explicit scene cue (none does
today — see midsong_generator's module docstring) or when a human picks one
by hand.

Provenance (front 3): source distinguishes a hand-placed trigger from one
midsong_generator seeded, and generator_key ties a generated trigger back to
the analysis moment that produced it — both are how regeneration stays
idempotent and edit-preserving. spectra.api.triggers.upsert_trigger stamps
every write that arrives through the human editing API back to
source="authored" (generator_key cleared) — the ownership-transfer rule: a
touched generated trigger becomes the owner's, so regeneration never
overwrites it.

Executable spec: scripts/check_triggers.py
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from spectra.models.scene import ResponseClass

TriggerActionKind = Literal["fire_scene", "fire_response", "select_color_set",
                            "fire_scene_update"]
TriggerSource = Literal["authored", "generated"]


class FireSceneAction(BaseModel):
    kind: Literal["fire_scene"] = "fire_scene"
    # None = pick at fire time through the sequencer selection kernel (the
    # generation-friendly default for a generated trigger — see the module
    # docstring); a hand-picked or explicit-cue scene names it directly.
    scene_id: Optional[str] = None
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    # None = the scene fires wearing the room's active colour set (the
    # ordinary case — scene_compiler.fire_scene's own default).
    color_set_id: Optional[str] = None

    @field_validator("scene_id")
    @classmethod
    def _scene_id_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("scene_id must be non-empty when given")
        return v


class FireResponseAction(BaseModel):
    kind: Literal["fire_response"] = "fire_response"
    event_class: ResponseClass
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


class SelectColorSetAction(BaseModel):
    kind: Literal["select_color_set"] = "select_color_set"
    set_id: str = Field(min_length=1)


class FireSceneUpdateAction(BaseModel):
    kind: Literal["fire_scene_update"] = "fire_scene_update"
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


TriggerAction = Annotated[
    Union[FireSceneAction, FireResponseAction, SelectColorSetAction,
         FireSceneUpdateAction],
    Field(discriminator="kind"),
]


class SpectraTrigger(BaseModel):
    """One hand-placed or generated moment in one song. enabled lets an
    owner disarm a trigger without losing its placement/action — the
    authoring surface's "delete" is a real removal; this flag is for a
    future mute gesture, mirrored from the legacy trigger's own field.

    source/generator_key: provenance for front 3's mid-song generation —
    see the module docstring and spectra.services.midsong_generator. An
    "authored" trigger (the default, and every pre-front-3 trigger already
    on disk) is never touched by regeneration."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int = Field(ge=0)
    enabled: bool = True
    source: TriggerSource = "authored"
    generator_key: Optional[str] = None
    action: TriggerAction
