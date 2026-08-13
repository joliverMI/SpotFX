"""SPECTRA value bindings — ported from spot-effects models/value_binding.py
(same semantics, proven on the events page) plus ONE growth: `dice`.

A binding computes a parameter's value at fire time from a signal instead of
a fixed scalar. Two modes:
  map   — linear range map: signal in [in_min, in_max] → [out_min, out_max]
          (inverted output ranges allowed).
  steps — ordered thresholds: the last step whose threshold <= signal wins.
          The only mode for toggles / enums; step values may be numbers,
          bools, or strings (enum options like a dance style).

Signals SPECTRA resolves in S1: `trigger_intensity` / `section_energy` (both
read the fire's intensity — the editor's chosen-intensity slider, a trigger
fire's intensity via the S2 bridge, or section energy for sequencer fires)
and `random` (a fresh uniform roll per fire). The beat-window signals
(rms_total / rms_bass / onset_score) stay legal in the model and resolve to
the fallback until the S2 bridge supplies beat context — the ⚡ menu on the
editor page offers only intensity + random (owner's words); the wider set
stays agent-authorable with zero migration.

`dice` (the growth): 🎲 bindings sharing a dice letter share ONE uniform
roll per fire — Mid Star's three authored shape variants land as authored
pairs with their exact 2:2:1 weights, never scrambled halves. dice=None (the
default) keeps today's fresh-per-field roll, so nothing existing changes.
Resolution memoizes per letter in services/binding_resolver.FireContext.

`fallback` applies when the signal is unavailable or, in steps mode, below
the first threshold. Migrated scenes carry their rebuild's static value here
(decision: v2-randomness-scope — "static fallbacks become the bindings'
fallbacks").
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

SignalName = Literal["rms_total", "rms_bass", "onset_score", "section_energy",
                     "trigger_intensity", "random"]

BindingValue = float | bool | str


class BindingStep(BaseModel):
    threshold: float                      # applies when signal >= threshold
    value: BindingValue


class ValueBinding(BaseModel):
    bind: Literal["signal"] = "signal"    # discriminator (future: "expr")
    signal: SignalName = "trigger_intensity"
    window_beats: int = Field(default=0, ge=0)
    window_dir: Literal["past", "future", "centered"] = "past"
    mode: Literal["map", "steps"] = "map"
    in_min: float = 0.0
    in_max: float = 1.0
    out_min: float = 0.0
    out_max: float = 1.0
    steps: list[BindingStep] = Field(default_factory=list)
    fallback: Optional[BindingValue] = None
    # Numeric results (map output, steps values, fallback) get their sign
    # flipped with 50% probability per fire. Ignored for bools / strings.
    random_sign: bool = False
    # Correlated randomness: 🎲 bindings sharing a letter share one roll per
    # fire. Only meaningful with signal="random"; None = independent roll.
    dice: Optional[str] = None

    @model_validator(mode="after")
    def _sort_steps(self) -> "ValueBinding":
        # Canonical storage form: ascending thresholds.
        if self.steps:
            self.steps.sort(key=lambda s: s.threshold)
        return self


def is_binding(value: object) -> bool:
    return isinstance(value, ValueBinding) or (
        isinstance(value, dict) and value.get("bind") == "signal")
