"""SPECTRA sequencer data model — the UNAMBIGUOUS CORE of the sequencing
design (data/spectra-sequencing-design/report.md, Part 4). Data shapes only;
no engine consumes these yet.

Five product-owner decisions are OPEN (captain holds: weighting-structure,
selection-algorithm, colorset-flare-mechanism, curve-ownership,
change-trigger-mode). What is pinned here is capture-verbatim and
decision-neutral:
  - CurvePoint / CurveProfile: points on a line, linear between, sorted-x.
    Duplicate x = a step discontinuity (evaluation: later point wins at
    exactly that x — services/selection_kernel.curve_eval). One flat point
    ≡ a scalar weight.
  - dwell_weight: relative float > 0, default 1.0, dimensionless — weight 2
    holds twice as long as weight 1, whatever the base pace is.
  - AffinityEdge: explicit from/to/mult, directional by construction.
    Self-pairs are rejected: the diagonal IS dwell_weight (report Part 3).

TODO(decision selection-algorithm): composition + fallback ladder semantics.
TODO(decision colorset-flare-mechanism): colour-set / flare selector
    instances; SequencerConfig below is the SCENE selector's shape only.
TODO(decision curve-ownership): whether curve_ref (named profile) or
    inline_points is the primary form; both are stored, neither is wired.
TODO(decision change-trigger-mode): change_mode is stored, consumed by
    nothing until the engine lands.

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
    # the agent, never by a settings form.
    genre_mult:   dict[str, float] = Field(default_factory=dict)
    # Relative dwell: weight 2 holds twice as long as weight 1. Dimensionless;
    # no absolute per-scene seconds anywhere.
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
    # Directional: from→to is a different edge from to→from.
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
    """Scene-selector configuration as the agent-adjustment endpoints need it.
    Stored dark: nothing consumes it until the open decisions land."""
    change_mode: Literal["both", "transition", "timed"] = "both"
    base_dwell_s: float = Field(default=180.0, gt=0.0)
    entries:  dict[str, SelectorEntry] = Field(default_factory=dict)  # scene id → entry
    affinity: list[AffinityEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_edges(self) -> "SequencerConfig":
        seen: set[tuple[str, str]] = set()
        for edge in self.affinity:
            key = (edge.from_id, edge.to_id)
            if key in seen:
                raise ValueError(f"duplicate affinity edge {edge.from_id} → {edge.to_id}")
            seen.add(key)
        return self
