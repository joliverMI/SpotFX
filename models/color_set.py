"""
SpotFX — Color Set data models.

A `ColorSetCard` is either:
  - kind="set":   a reusable bundle of FG/BG color entries, each scoped to a
                  device/category. Applied to many devices at once by a
                  Set Color step.
  - kind="group": an ordered list of references to Color Sets, picked one at a
                  time (sequential cycle or weighted random) when fired. A
                  group may also carry its own `entries` — a field-level
                  override layer merged per virtual on top of the picked Set
                  at fire time (see trigger_engine._execute_set_color).

A Color Set entry is essentially a restricted Morph Step target (color +
bg_color), so it reuses `MorphScope` from models.music_event and is compiled
through the same `morph_compiler` path at fire time.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid

from models.music_event import MorphScope


class ColorSetEntry(BaseModel):
    """One scoped FG/BG color definition within a Color Set. Both colors are
    optional — leave one unset to only change the other. `bg_mode` maps to the
    LedFX `background_mode` param (additive/overwrite); None = don't touch it.
    `ramp_ms` overrides the Set Color step’s ramp only when assigned."""
    scope:       MorphScope = Field(default_factory=MorphScope)
    color_kind:  Optional[Literal["gradient", "solid"]] = None
    color_value: str | None = None
    bg_color:    str | None = None
    bg_mode:     Optional[Literal["additive", "overwrite"]] = None
    # Optional numeric / accent params (None = leave the device's value alone).
    brightness:            float | None = None  # effect brightness 0..1
    background_brightness: float | None = None  # bg brightness 0..1
    accent_color:          str | None = None    # "third color" (sparks/peak), hex
    ramp_ms:     int | None = None


class GroupMember(BaseModel):
    """One reference to a Color Set within a Group, with a selection weight."""
    color_set_id: str
    weight:       float = 1.0


class ModeVariant(BaseModel):
    """One Dark/Light "mode lane" of a Group card (dark_variant /
    light_variant). Active while the display mode resolved from the levels
    ABOVE the member set (global → trigger → scene group → scene → set_color
    action → this group card) is the matching dark/light; a resolution of
    "default" always uses the base group as authored.

    `entries`: extra per-device overrides layered ON TOP of the group's own
    override entries (variant fields win) — author only what differs.
    `members`: non-empty = replaces the base member pool for the pick, with
    its own selection cursor (base cycling position is untouched)."""
    entries: list[ColorSetEntry] = Field(default_factory=list)
    members: list[GroupMember] = Field(default_factory=list)


class ColorSetCard(BaseModel):
    """A card on the Color Sets page — a Color Set or a Group of Color Sets."""
    id:    str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:  str
    color: str = "#FFD700"     # swatch shown in the card list
    kind:  Literal["set", "group"] = "set"
    labels: list[str] = Field(default_factory=list)
    # Dark/Light display mode carried by this card — the LAST two levels of the
    # display-mode cascade (group card outranks the picked member set). Only
    # consulted when every level above (TopBar, trigger, scene group, scene,
    # set_color action) left the mode at "default".
    display_mode: Literal["default", "dark", "light"] = "default"

    # SPECTRA per-item mode AVAILABILITY (distinct from display_mode above,
    # which is the legacy dark/light "variant lane" — this is a plain
    # on/off eligibility gate, owner ask 2026-08-17): "light" is available
    # while the room's global display_mode is light or default/hybrid,
    # skipped while dark; "dark" is available while dark or default/hybrid,
    # skipped while light; "default" is always available. Consulted only
    # by SPECTRA's own automatic selection paths (spectra/services/
    # mode_availability.py) — a manual apply/preview/test-fire always goes
    # through regardless, same "explicit human action bypasses automatic
    # gating" convention as Force Scene.
    display_availability: Literal["default", "dark", "light"] = "default"

    # kind == "set": the palette itself.
    # kind == "group": optional overrides — any field set here replaces the
    # picked member Set's value for the virtuals the entry's scope resolves to.
    entries: list[ColorSetEntry] = Field(default_factory=list)

    # kind == "group"
    members:        list[GroupMember] = Field(default_factory=list)
    mode:           Literal["cycle", "weighted"] = "cycle"
    cycle_behavior: Literal["wrap", "bounce"] = "wrap"
    exclude_current: bool = True
    # Dark/Light "mode lanes" (kind == "group"): optional per-mode variants —
    # see ModeVariant. None = this group looks the same in every mode.
    dark_variant:  Optional[ModeVariant] = None
    light_variant: Optional[ModeVariant] = None
    # Palette Sync: synced groups share one room-wide "current palette hue".
    # A synced group starts its pick from the member nearest that hue (instead
    # of its own private cursor), then publishes the pick's hue back — so
    # switching between synced groups keeps the room on one color family.
    palette_sync:   bool = False

    # SceneV2 global opt-out (design answer 3): True removes this set from
    # every SceneV2's pool, overriding any scene's own accept list. The legacy
    # scene/set-color path ignores this flag.
    scene_v2_opt_out: bool = False
