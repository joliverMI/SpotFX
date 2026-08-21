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
                     migration-scoping RULING.md, 2026-08-14, originally:
                     "a major change within the scene, bigger than a
                     flare, overriding the drift, going somewhere new on a
                     ramp-in transition," firing the ACTIVE scene's own
                     SceneV2.update_kind by name). That original mechanism
                     is RETIRED (2026-08-20, his ask: "make update scene
                     act like a double intensity flare until we build it
                     out specifically") — on_update now fires the active
                     scene's own ordinary "flare" ResponseClass at 2x
                     intensity instead (see on_update's own docstring); no
                     "flare" response/bands declared at all is a silent
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

SCENE POOLS (2026-08-17, his own ask: "triggers should be able to carry
some meta data that can say choose from only these scenes and includes
weights"): a fire_scene action with scene_id=None may additionally carry
scene_pool, a narrow-and-bias override on top of the sequencer's free
choice — "only these scenes, weighted like this" rather than "pick from
everything I've configured." Absent (the default, and every one of his
20,958 existing fire_scene triggers as of this field's introduction — the
migration to storage/spectra/triggers.json carried scene_id=None but not
his legacy hand-built scene_group pools, which this field is the recovery
path for) means unconstrained: identical behaviour to today,
_default_select_scene's own curve x genre x affinity draw over every
configured entry. When present, selection instead runs a PURE weighted
draw over the pool's own weights only (spectra.services.selection_kernel.
select_from_scene_pool) — deliberately not curve/genre/affinity-composed,
mirroring legacy's scene_group_mode="weighted" (storage/events.json,
"weight" occurs 898 times there) and the already-shipped
color_set_groups.py weighted branch, not the scene selector's ladder. A
pool member's scene_id is dropped at fire time if that scene no longer
exists; an empty-after-filtering or all-non-positive-weight pool picks
nothing (same "nothing fires this crossing" convention the kernel's own
terminal rung uses), never silently falls back to the unconstrained draw —
"only these scenes" stays "only these scenes, if any remain valid."

Executable spec: scripts/check_triggers.py, scripts/check_trigger_scene_pools.py
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from spectra.models.scene import ResponseClass

TriggerActionKind = Literal["fire_scene", "fire_response", "select_color_set",
                            "fire_scene_update"]
TriggerSource = Literal["authored", "generated"]


class ScenePoolMember(BaseModel):
    """One scene in a trigger's scene_pool, with its own selection weight
    (weighted-draw only — see FireSceneAction.scene_pool). weight=0 is a
    deliberate veto within the pool (keep the scene named, stop it firing),
    mirroring the kernel's own zero-veto convention elsewhere."""
    scene_id: str = Field(min_length=1)
    weight: float = Field(default=1.0, ge=0.0)


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
    # None (the default — see the module docstring's SCENE POOLS section) =
    # the sequencer chooses freely among every configured entry. Only
    # consulted when scene_id is None; a trigger that names scene_id
    # directly never reads this field.
    scene_pool: Optional[list[ScenePoolMember]] = None

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
