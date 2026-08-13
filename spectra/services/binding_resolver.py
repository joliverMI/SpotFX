"""Binding resolution for SPECTRA scenes — pure functions plus FireContext,
the per-fire memo that makes dice correlation real.

Ported semantics from spot-effects services/signal_resolver.apply_binding
(map / steps / fallback / random_sign-before-clamp), re-targeted at the
scene compiler: coercion kinds come from the shared param registry
(fx/device_model) instead of the aspect-kind table.

One FireContext per fire. Every 🎲 binding with the same dice letter reads
ONE roll from it (memoized), so correlated variants land as authored pairs;
dice=None rolls fresh per field (today's behavior). Signals:

  trigger_intensity / section_energy → ctx.intensity — the fire's intensity
      axis (editor test-fire slider now; trigger fires and section energy
      arrive identically through the S2 bridge).
  random → ctx.roll(dice)
  rms_total / rms_bass / onset_score → None until the S2 bridge supplies
      beat context (the binding's fallback applies — stated degradation).

Resolution returning None means "leave the field unset" — the compiler
drops the key so the fire doesn't touch that param.
"""
from __future__ import annotations

from random import Random
from typing import Optional

from spectra.models.binding import ValueBinding

# Coercion kinds (subset of spot-effects' FieldKind vocabulary that scene
# params need; ranges come from the registry meta).
KIND_NUMERIC = "numeric"
KIND_INTEGER = "integer"
KIND_TOGGLE = "toggle"
KIND_STRING = "string"


class FireContext:
    """Everything one fire resolves against. intensity None = no axis
    available (bindings fall back); rng injectable for deterministic specs."""

    def __init__(self, intensity: Optional[float], *,
                 rng: Random | None = None) -> None:
        self.intensity = intensity
        self.rng = rng or Random()
        self._dice: dict[str, float] = {}
        # Observability: what each resolved binding produced (the editor's
        # test-fire panel shows this next to the compiled writes).
        self.resolved: list[dict] = []

    def roll(self, dice: str | None) -> float:
        if dice is None:
            return self.rng.random()
        if dice not in self._dice:
            self._dice[dice] = self.rng.random()
        return self._dice[dice]

    def dice_rolls(self) -> dict[str, float]:
        return dict(self._dice)


def signal_value(binding: ValueBinding, ctx: FireContext) -> Optional[float]:
    if binding.signal == "random":
        return ctx.roll(binding.dice)
    if binding.signal in ("trigger_intensity", "section_energy"):
        return ctx.intensity
    return None   # beat-window signals need the S2 bridge


def _maybe_flip_sign(binding: ValueBinding, value, rng: Random):
    """With random_sign, negate a numeric value 50% of the time (fresh roll
    per field — sign flips are deliberately never dice-correlated). Bools /
    strings pass through. Runs BEFORE kind clamping."""
    if (binding.random_sign and isinstance(value, (int, float))
            and not isinstance(value, bool) and rng.random() < 0.5):
        return -value
    return value


def coerce(value, kind: str, lo: float | None = None, hi: float | None = None):
    """Coerce a resolved value into the param's value space; None = no-op."""
    if value is None:
        return None
    if kind == KIND_TOGGLE:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("on", "true", "1", "toggle")
        return bool(value)
    if kind == KIND_STRING:
        return str(value)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    if kind == KIND_INTEGER:
        return int(round(v))
    return round(v, 4)


def apply_binding(binding: ValueBinding, ctx: FireContext, kind: str,
                  lo: float | None = None, hi: float | None = None):
    """Resolve one binding to a scalar in the field's value space (or None =
    leave unset). map mode on toggle/string fields is invalid → fallback."""
    rng = ctx.rng
    sig = signal_value(binding, ctx)

    if binding.mode == "map" and kind in (KIND_TOGGLE, KIND_STRING):
        return coerce(binding.fallback, kind, lo, hi)

    if binding.mode == "steps":
        if sig is None:
            return coerce(_maybe_flip_sign(binding, binding.fallback, rng), kind, lo, hi)
        chosen = None
        for step in binding.steps:   # validator keeps these ascending
            if sig >= step.threshold:
                chosen = step.value
        if chosen is None:
            return coerce(_maybe_flip_sign(binding, binding.fallback, rng), kind, lo, hi)
        return coerce(_maybe_flip_sign(binding, chosen, rng), kind, lo, hi)

    # map mode
    if sig is None:
        if binding.fallback is not None:
            return coerce(_maybe_flip_sign(binding, binding.fallback, rng), kind, lo, hi)
        sig = 0.5   # neutral — the standing eff_intensity convention
    span = binding.in_max - binding.in_min
    if span == 0:
        t = 1.0 if sig >= binding.in_min else 0.0
    else:
        t = max(0.0, min(1.0, (sig - binding.in_min) / span))
    out = binding.out_min + t * (binding.out_max - binding.out_min)
    return coerce(_maybe_flip_sign(binding, out, rng), kind, lo, hi)


def kind_for_meta(meta: dict | None) -> tuple[str, float | None, float | None]:
    """(kind, lo, hi) for a registry param meta. Unknown params resolve as
    free numerics — the registry is curated, but an agent-authored binding on
    an unlisted param must still produce a number, not crash the compile."""
    if meta is None:
        return KIND_NUMERIC, None, None
    ptype = meta.get("type")
    if ptype == "toggle":
        return KIND_TOGGLE, None, None
    if ptype in ("string", "enum"):
        return KIND_STRING, None, None
    if ptype == "integer":
        return KIND_INTEGER, meta.get("min"), meta.get("max")
    return KIND_NUMERIC, meta.get("min"), meta.get("max")
