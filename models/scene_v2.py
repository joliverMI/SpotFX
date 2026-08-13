"""SPECTRA SceneV2: a scene is the full device-aware configuration (report §4a).
Coexists with the legacy scene_update path; neither touches the other.
Binding design answers (data/spectra-design-decisions.md):
  1. entries may use different effects — validation never requires one effect type
  2. wheel position: services/color_wheel.py (computed, never stored)
  3. two-way set filter: ColorSetCard.scene_v2_opt_out + accepts_color_set()
Executable spec: scripts/check_scene_v2.py
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SceneColorAssignment(BaseModel):
    # "set": active Color Set owns colors at fire time; "fixed": scene pins them.
    mode:        Literal["set", "fixed"] = "set"
    color_kind:  Optional[Literal["gradient", "solid"]] = None
    color_value: str | None = None   # solid hex or linear-gradient string
    bg_color:    str | None = None
    bg_mode:     Optional[Literal["additive", "overwrite"]] = None


class SceneDeviceConfig(BaseModel):
    # Category targets expand to member virtuals at compile time; a virtual
    # entry overrides its category's claim on that virtual.
    id:          str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_kind: Literal["category", "virtual"] = "category"
    target:      str = ""
    effect_type: str = ""
    params:      dict[str, Any] = Field(default_factory=dict)
    color:       SceneColorAssignment = Field(default_factory=SceneColorAssignment)
    brightness:            float | None = Field(default=None, ge=0.0, le=1.0)  # None = leave alone
    background_brightness: float | None = Field(default=None, ge=0.0, le=1.0)


class FlareBand(BaseModel):
    # Response when a flare fires with intensity in [intensity_min, intensity_max).
    intensity_min: float = Field(default=0.0, ge=0.0, le=1.0)
    intensity_max: float = Field(default=1.0, ge=0.0, le=1.0)
    curve: Literal["linear", "ease_in", "ease_out", "pulse"] = "linear"
    gain:  float = Field(default=1.0, ge=0.0)
    param_patch: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _band_ordered(self) -> "FlareBand":
        if self.intensity_min >= self.intensity_max:
            raise ValueError(
                f"flare band intensity_min ({self.intensity_min}) must be "
                f"< intensity_max ({self.intensity_max})")
        return self


class PhaseChoreography(BaseModel):
    # anchor_frac: crossfade fraction where the payoff lands; engine fires the
    # switch early by anchor_frac × transition_ms (cf. services/transition_phases.py).
    enabled:         bool = False
    transition_ms:   int = Field(default=800, ge=0, le=20000)
    transition_mode: str = "Add"
    anchor_frac:     float = Field(default=0.45, ge=0.0, le=1.0)


class SceneV2(BaseModel):
    id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:   str
    labels: list[str] = Field(default_factory=list)
    devices: list[SceneDeviceConfig] = Field(default_factory=list)
    flare_bands:  list[FlareBand] = Field(default_factory=list)
    choreography: PhaseChoreography = Field(default_factory=PhaseChoreography)
    # accept_all_sets=True: every set not globally opted out is eligible;
    # False narrows to accepted_set_ids.
    accept_all_sets:  bool = True
    accepted_set_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "SceneV2":
        seen: set[tuple[str, str]] = set()
        for dev in self.devices:
            if not dev.target:
                raise ValueError("device entry has an empty target")
            if not dev.effect_type:
                raise ValueError(f"device entry for '{dev.target}' has no effect_type")
            key = (dev.target_kind, dev.target)
            if key in seen:
                raise ValueError(f"duplicate device entry for {dev.target_kind} '{dev.target}'")
            seen.add(key)
        bands = sorted(self.flare_bands, key=lambda b: b.intensity_min)
        for a, b in zip(bands, bands[1:]):
            if b.intensity_min < a.intensity_max:
                raise ValueError(
                    f"flare bands overlap: [{a.intensity_min}, {a.intensity_max}) "
                    f"and [{b.intensity_min}, {b.intensity_max})")
        return self

    def accepts_color_set(self, card) -> bool:
        # Two-way filter (answer 3): the set's global opt-out always wins.
        if getattr(card, "scene_v2_opt_out", False):
            return False
        if self.accept_all_sets:
            return True
        return card.id in self.accepted_set_ids


class ColorWheelPosition(BaseModel):
    # position_deg None: rainbow set (span > 180°) or achromatic (rainbow stays
    # False there). resultant = circular R, confidence signal for rotation UX.
    set_id:       str
    position_deg: float | None = None
    rainbow:      bool = False
    span_deg:     float = 0.0
    resultant:    float = 0.0
