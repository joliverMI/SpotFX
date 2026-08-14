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

Executable spec: scripts/check_triggers.py
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from spectra.models.scene import ResponseClass

TriggerActionKind = Literal["fire_scene", "fire_response", "select_color_set"]


class FireSceneAction(BaseModel):
    kind: Literal["fire_scene"] = "fire_scene"
    scene_id: str = Field(min_length=1)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    # None = the scene fires wearing the room's active colour set (the
    # ordinary case — scene_compiler.fire_scene's own default).
    color_set_id: Optional[str] = None


class FireResponseAction(BaseModel):
    kind: Literal["fire_response"] = "fire_response"
    event_class: ResponseClass
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


class SelectColorSetAction(BaseModel):
    kind: Literal["select_color_set"] = "select_color_set"
    set_id: str = Field(min_length=1)


TriggerAction = Annotated[
    Union[FireSceneAction, FireResponseAction, SelectColorSetAction],
    Field(discriminator="kind"),
]


class SpectraTrigger(BaseModel):
    """One hand-placed (or later, generated) moment in one song. enabled
    lets an owner disarm a trigger without losing its placement/action —
    the authoring surface's "delete" is a real removal; this flag is for a
    future mute gesture, mirrored from the legacy trigger's own field."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int = Field(ge=0)
    enabled: bool = True
    action: TriggerAction
