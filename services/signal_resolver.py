"""
SpotFX — Value-binding resolution (pure functions).

Resolves ValueBinding objects (models/value_binding.py) into concrete
scalars at fire time. Kept free of engine/state imports so everything is
offline-testable with fabricated beats/sections — same philosophy as the
`intensity_resolver` callable that morph_scene threads around.

The engine applies `resolve_action_bindings` at the executor seams
(_execute_morph_step / _execute_morph_color / effect_param leaf /
_build_scene_payload) so every dispatch path — bus, scene-override
prestage, beat timelines — sees plain scalars. The morph compiler itself
never learns about bindings.
"""
from __future__ import annotations

import logging
from bisect import bisect_left
from typing import Callable, Optional

from models.value_binding import ValueBinding

logger = logging.getLogger(__name__)

# Signature the engine provides: binding -> current signal value (0-1) or None.
SignalFn = Callable[[ValueBinding], Optional[float]]

# Field kinds drive coercion of the resolved value.
#   float01     — clamp [0, 1]                  (number, star)
#   float_pm1   — clamp [−1, 1]                 (x_offset, y_offset)
#   float_free  — round only                    (twist)
#   int0        — round, floor 0                (edges, ramp_ms)
#   int1        — round, floor 1                (advance)
#   tri_bool    — True/False/"toggle"           (polygon, flip; steps-only)
#   toggle_str  — "on"/"off"/"toggle"           (toggle_action; steps-only)
FieldKind = str

_TOGGLE_KINDS = ("tri_bool", "toggle_str")


# ── signal resolution ────────────────────────────────────────────────────────

def resolve_signal(
    binding: ValueBinding,
    beats: list | None,
    sections: list | None,
    now_ms: int,
) -> Optional[float]:
    """Current value of the binding's signal at song position now_ms, 0-1."""
    if binding.signal == "section_energy":
        return _section_energy(sections, now_ms)
    return _beat_signal(beats, binding, now_ms)


def _section_energy(sections: list | None, now_ms: int) -> Optional[float]:
    if not sections:
        return None
    best = None
    for sec in sections:
        start = int(sec.get("start_ms", 0))
        end = int(sec.get("end_ms", 0))
        if start <= now_ms < end:
            best = sec
            break
    if best is None:
        # Before the first / after the last section: use the nearest one.
        best = min(
            sections,
            key=lambda s: min(
                abs(int(s.get("start_ms", 0)) - now_ms),
                abs(int(s.get("end_ms", 0)) - now_ms),
            ),
        )
    val = best.get("energy_rms")
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return None


def _beat_signal(beats: list | None, binding: ValueBinding, now_ms: int) -> Optional[float]:
    if not beats:
        return None
    ms_list = [int(b.get("ms", 0)) for b in beats]
    i = bisect_left(ms_list, now_ms)
    # Nearest of the two neighbors (semantics of _beat_intensity_now).
    if i >= len(beats):
        i = len(beats) - 1
    elif i > 0 and abs(ms_list[i - 1] - now_ms) <= abs(ms_list[i] - now_ms):
        i -= 1

    n = binding.window_beats
    if n <= 0:
        window = beats[i : i + 1]
    elif binding.window_dir == "past":
        window = beats[max(0, i - n + 1) : i + 1]
    elif binding.window_dir == "future":
        window = beats[i : i + n]
    else:  # centered
        half = n // 2
        start = max(0, i - half)
        window = beats[start : start + n]

    vals = []
    for b in window:
        try:
            vals.append(float(b.get(binding.signal)))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    return max(0.0, min(1.0, sum(vals) / len(vals)))


# ── value coercion ───────────────────────────────────────────────────────────

def apply_binding(binding: ValueBinding, sig: Optional[float], kind: FieldKind):
    """Coerce the signal into the field's value space. Returns the resolved
    value, or None meaning "no-op — leave the field unset" (callers decide
    what unset means per field)."""
    if binding.mode == "map" and kind in _TOGGLE_KINDS:
        logger.warning(
            "ValueBinding: map mode is invalid for toggle fields — using fallback")
        return binding.fallback

    if binding.mode == "steps":
        if sig is None:
            return binding.fallback
        chosen = None
        for step in binding.steps:  # validator keeps these ascending
            if sig >= step.threshold:
                chosen = step.value
        if chosen is None:
            return binding.fallback
        return _coerce(chosen, kind)

    # map mode
    if sig is None:
        if binding.fallback is not None:
            return _coerce(binding.fallback, kind)
        sig = 0.5  # neutral — matches the compiler's eff_intensity convention
    span = binding.in_max - binding.in_min
    if span == 0:
        t = 1.0 if sig >= binding.in_min else 0.0
    else:
        t = max(0.0, min(1.0, (sig - binding.in_min) / span))
    out = binding.out_min + t * (binding.out_max - binding.out_min)
    return _coerce(out, kind)


def _coerce(value, kind: FieldKind):
    if kind in _TOGGLE_KINDS:
        return value  # bools / "toggle" / "on"/"off" pass through
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if kind == "float01":
        return round(max(0.0, min(1.0, v)), 4)
    if kind == "float_pm1":
        return round(max(-1.0, min(1.0, v)), 4)
    if kind == "int0":
        return max(0, int(round(v)))
    if kind == "int1":
        return max(1, int(round(v)))
    return round(v, 4)  # float_free


# ── action-level resolution ──────────────────────────────────────────────────

# (owner attr, field, kind) tables per action type.
_ASPECT_FIELDS = (
    ("number", "float01"),
    ("star", "float01"),
    ("edges", "int0"),
    ("twist", "float_free"),
    ("x_offset", "float_pm1"),
    ("y_offset", "float_pm1"),
    ("polygon", "tri_bool"),
    ("flip", "tri_bool"),
)


def has_bindings(action) -> bool:
    t = getattr(action, "type", "")
    if t == "morph_step":
        if isinstance(action.ramp_ms, ValueBinding):
            return True
        for tgt in action.targets:
            if isinstance(tgt.ramp_ms, ValueBinding):
                return True
            av = tgt.absolute_value
            if any(isinstance(getattr(av, f), ValueBinding) for f, _ in _ASPECT_FIELDS):
                return True
        return False
    if t == "morph_color":
        return isinstance(action.advance, ValueBinding) or isinstance(action.ramp_ms, ValueBinding)
    if t == "ledfx_effect_param":
        if isinstance(action.ramp_ms, ValueBinding):
            return True
        return any(
            isinstance(p.target_value, ValueBinding) or isinstance(p.toggle_action, ValueBinding)
            for p in action.params
        )
    return False


def resolve_action_bindings(action, signal_fn: SignalFn):
    """Return a copy of `action` with every ValueBinding replaced by its
    resolved scalar. Returns the SAME object when nothing is bound (hot path).
    Signals are memoized per (signal, window, dir) so all bound fields in one
    action read one coherent instant."""
    if not has_bindings(action):
        return action

    cache: dict[tuple, Optional[float]] = {}

    def sig_for(b: ValueBinding) -> Optional[float]:
        key = (b.signal, b.window_beats, b.window_dir)
        if key not in cache:
            cache[key] = signal_fn(b)
        return cache[key]

    def rv(value, kind: FieldKind):
        if isinstance(value, ValueBinding):
            return apply_binding(value, sig_for(value), kind)
        return value

    new = action.model_copy(deep=True)
    t = action.type
    if t == "morph_step":
        new.ramp_ms = rv(new.ramp_ms, "int0")
        for tgt in new.targets:
            tgt.ramp_ms = rv(tgt.ramp_ms, "int0")
            av = tgt.absolute_value
            for field, kind in _ASPECT_FIELDS:
                setattr(av, field, rv(getattr(av, field), kind))
    elif t == "morph_color":
        adv = rv(new.advance, "int1")
        new.advance = 1 if adv is None else adv
        new.ramp_ms = rv(new.ramp_ms, "int0")
    elif t == "ledfx_effect_param":
        new.ramp_ms = rv(new.ramp_ms, "int0")
        kept = []
        for p in new.params:
            p.toggle_action = rv(p.toggle_action, "toggle_str")
            # target_value ranges are param-specific (catalog min/max), so no
            # 0-1 clamp here — the author's out_min/out_max defines the range.
            tv = rv(p.target_value, "float_free")
            if tv is None:
                # A bound target_value that resolved to no-op: dropping the
                # change is safer than firing 0.0.
                continue
            p.target_value = tv
            kept.append(p)
        new.params = kept
    return new


def static_ramp_ms(value, signal_fn: SignalFn) -> Optional[int]:
    """Resolve a possibly-bound ramp_ms for plan-time arithmetic (beat
    timeline max())."""
    if isinstance(value, ValueBinding):
        return apply_binding(value, signal_fn(value), "int0")
    return value
