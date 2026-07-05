"""
SpotFX — Value Bindings: signal-driven parameter values.

A ValueBinding lets a morph/effect parameter (float, int, or toggle) be
computed at fire time from a music signal instead of being a fixed scalar —
the DAW modulation-matrix pattern (source + range map / threshold steps).

Signals (all 0–1, from the precomputed librosa analysis):
  rms_total / rms_bass / onset_score — per-beat values; window_beats=0 reads
      the nearest beat (classic "intensity"), N>0 takes a rolling mean over N
      beats in window_dir (past / future / centered — future is legal because
      beats are precomputed, letting a binding anticipate a build or drop).
  section_energy — mean RMS of the librosa section containing the fire
      position (window_* ignored).
  trigger_intensity — the firing MusicTrigger's user-set intensity (0-1,
      drawn on the builder timeline; window_* ignored). Manual event fires
      have no trigger → resolves None → the binding's fallback applies.

Mapping modes:
  map   — linear range map: signal in [in_min, in_max] → [out_min, out_max]
          (inverted output ranges allowed, e.g. slow ramps at low energy).
  steps — ordered thresholds: the last step whose threshold <= signal wins.
          The only mode for toggle-ish fields; step values may be numbers,
          bools, or the strings "on"/"off"/"toggle".

`fallback` applies when the signal is unavailable (no beat data) or, in
steps mode, when the signal is below the first threshold. The `bind`
discriminator reserves a future bind="expr" mode with zero migration.

Resolution happens in services/signal_resolver.py at the executor seams;
models here are pure data. The existing nudge system (NumericNudge,
intensity_scale) is separate and untouched — nudges are relative beat
modulation, bindings compute absolute values.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

SignalName = Literal["rms_total", "rms_bass", "onset_score", "section_energy", "trigger_intensity"]

# Values a binding may produce: numbers, bools, or toggle-ish strings.
BindingValue = float | bool | str


class BindingStep(BaseModel):
    threshold: float                      # applies when signal >= threshold
    value: BindingValue


class ValueBinding(BaseModel):
    bind: Literal["signal"] = "signal"    # discriminator (future: "expr")
    signal: SignalName = "rms_total"
    window_beats: int = Field(default=0, ge=0)
    window_dir: Literal["past", "future", "centered"] = "past"
    mode: Literal["map", "steps"] = "map"
    in_min: float = 0.0
    in_max: float = 1.0
    out_min: float = 0.0
    out_max: float = 1.0
    steps: list[BindingStep] = Field(default_factory=list)
    fallback: Optional[BindingValue] = None

    @model_validator(mode="after")
    def _sort_steps(self) -> "ValueBinding":
        # Canonical storage form: ascending thresholds (clean round-trips even
        # when the JSON escape hatch authors them out of order).
        if self.steps:
            self.steps.sort(key=lambda s: s.threshold)
        return self
