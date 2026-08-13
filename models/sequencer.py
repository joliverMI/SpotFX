"""SPECTRA sequencer data model — decision-complete per the five answered
holds (data/spectra-sequencing-design/decision-five-answers.md; blueprint in
data/spectra-sequencing-design/report.md Parts 2–4).

  - CurvePoint / CurveProfile: points on a line, linear between, sorted-x.
    Duplicate x = a step discontinuity (evaluation: later point wins at
    exactly that x — services/selection_kernel.curve_eval). One flat point
    ≡ a scalar weight.
  - Curve ownership (decision 4): NAMED profiles referenced by entries via
    curve_ref, with inline_points as the one-off escape hatch.
  - dwell_weight: relative float > 0, default 1.0, dimensionless — weight 2
    holds twice as long as weight 1, whatever the base pace is. In the
    shipped transition-only mode the unit is SONGS (decision 5).
  - AffinityEdge: explicit from/to/mult, directional by construction.
    Self-pairs are rejected: the diagonal IS dwell_weight (report Part 3).
  - change_mode (decision 5): shipped default is "transition" — song
    transitions are the only change moments; NO timer runs. "timed"/"both"
    are stored for a later owner-approved clock but the engine refuses to
    tick them (services/scene_sequencer.py holds the pluggable seam).
  - enabled: the sequencer's own dark switch, default OFF. Nothing fires
    until the agent flips it via PUT /api/sequencer/config.
  - flare_entries: the flare selector's entries (decision 3) — curve × genre
    only; dwell_weight is carried by the shared entry shape but flares have
    no dwell and the selector never reads it.
  - color_set_entries + wheel_travel_curve: the colour-set selector — the
    kernel's third flavour, wired LAST (decision 3). score = curve(intensity)
    × genre × wheel-travel, where wheel travel is itself a named curve
    profile over angular distance (0–180° → x 0–1). No dwell: colours change
    with scenes, not on their own clock, and the selector never reads
    dwell_weight. Rainbow-tagged sets (services/color_wheel.py) take a
    neutral ×1.0 wheel factor and never move the room's wheel position.

Executable spec: scripts/check_sequencer.py
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class CurvePoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)   # intensity axis
    y: float = Field(ge=0.0)           # relative likelihood, not a percentage


def _validate_sorted_x(points: list[CurvePoint], label: str) -> None:
    if not points:
        raise ValueError(f"{label} needs at least one point")
    for a, b in zip(points, points[1:]):
        if b.x < a.x:
            raise ValueError(
                f"{label} points must be sorted by x ({b.x} after {a.x}); "
                "equal x is allowed and means a step")


class CurveProfile(BaseModel):
    id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:   str
    points: list[CurvePoint]

    @model_validator(mode="after")
    def _validate(self) -> "CurveProfile":
        _validate_sorted_x(self.points, f"curve profile '{self.name}'")
        return self


class SelectorEntry(BaseModel):
    # Exactly one of curve_ref (named CurveProfile id) / inline_points (one-off
    # escape hatch) may be set; both None = flat 1.0 (pure scalar weight 1).
    curve_ref:     Optional[str] = None
    inline_points: Optional[list[CurvePoint]] = None
    # Genre bucket (training-profile name) → multiplier; adjusted by telling
    # the agent, never by a settings form. 0 is a hard veto for that genre.
    genre_mult:   dict[str, float] = Field(default_factory=dict)
    # Relative dwell: weight 2 holds twice as long as weight 1. Dimensionless;
    # no absolute per-scene seconds anywhere. Songs in transition mode;
    # fractional weights resolve probabilistically at adoption time
    # (selection_kernel.resolve_dwell_songs). Unread for flare entries.
    dwell_weight: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def _validate(self) -> "SelectorEntry":
        if self.curve_ref is not None and self.inline_points is not None:
            raise ValueError("entry may set curve_ref or inline_points, not both")
        if self.inline_points is not None:
            _validate_sorted_x(self.inline_points, "inline curve")
        for bucket, mult in self.genre_mult.items():
            if mult < 0:
                raise ValueError(f"genre_mult['{bucket}'] must be >= 0, got {mult}")
        return self


class AffinityEdge(BaseModel):
    # Directional: from→to is a different edge from to→from. 0 is a hard veto
    # of that succession (the fallback ladder can still relax it).
    from_id: str
    to_id:   str
    mult:    float = Field(default=1.0, ge=0.0)

    @model_validator(mode="after")
    def _no_self_pair(self) -> "AffinityEdge":
        if self.from_id == self.to_id:
            raise ValueError(
                "self-affinity is not stored — the diagonal IS dwell_weight")
        return self


class SequencerConfig(BaseModel):
    """The whole sequencer configuration (storage/sequencer.json "config").
    Curves are edited graphically; everything else here is adjusted by telling
    the agent (PUT /api/sequencer/config) — no settings forms."""
    # Dark switch. Default OFF: the engine consumes nothing and fires nothing
    # until the agent enables it (exclusive-switchover doctrine — the legacy
    # chooser path keeps running either way and is never coupled to this).
    enabled: bool = False
    # Decision 5: transitions only. "timed"/"both" are accepted for storage so
    # a later owner-approved timer needs no schema change, but no timer ships —
    # the engine ticks only on song transitions regardless (and logs when a
    # stored mode asks for more).
    change_mode: Literal["transition", "timed", "both"] = "transition"
    # Base pace for the future timed clock only; meaningless in transition
    # mode, where the base is one song.
    base_dwell_s: float = Field(default=180.0, gt=0.0)
    entries:  dict[str, SelectorEntry] = Field(default_factory=dict)  # SceneV2 id → entry
    affinity: list[AffinityEdge] = Field(default_factory=list)
    # Flare selector (decision 3): shares the kernel with curve × genre only —
    # no third factor, no dwell; its terminal ladder rung fires NOTHING.
    flare_entries: dict[str, SelectorEntry] = Field(default_factory=dict)
    # Colour-set selector (decision 3, wired last): ColorSetCard id → entry.
    # curve × genre × wheel-travel; no dwell (dwell_weight is never read);
    # terminal ladder rung KEEPS the current colours — never forced to churn.
    color_set_entries: dict[str, SelectorEntry] = Field(default_factory=dict)
    # The wheel-travel likelihood curve: a named CurveProfile id evaluated
    # over angular distance (x = travel/180°). None = neutral ×1.0 everywhere.
    # Seeded downhill ("prefer small steps") by seed_sequencer_from_legacy so
    # the migrated room approximates today's deterministic palette walk.
    wheel_travel_curve: Optional[str] = None

    @model_validator(mode="after")
    def _no_duplicate_edges(self) -> "SequencerConfig":
        seen: set[tuple[str, str]] = set()
        for edge in self.affinity:
            key = (edge.from_id, edge.to_id)
            if key in seen:
                raise ValueError(f"duplicate affinity edge {edge.from_id} → {edge.to_id}")
            seen.add(key)
        return self
