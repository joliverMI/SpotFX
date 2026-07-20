"""
SpotFX — Morph compiler.

Turns one `MorphTarget` into a list of concrete LedFX writes per affected
virtual. Pure function: no side effects, no LedFX calls. The trigger-engine
executor is responsible for actually dispatching the writes.

A `ConcreteWrite` is either:
  - kind="patch":  apply `patch` (dict of {raw_param: value}) to `virtual_id`'s
                   current effect of `effect_type`. Values may be bool / int /
                   float / str (gradient or hex). The executor splits these into
                   instant vs. ramp using the param's `smooth` flag.
  - kind="switch": switch `virtual_id` to a new effect type with `starter_config`.
                   Always instant (LedFX has no in-band effect-switch fade).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from models.music_event import MorphTarget, AspectValue, MorphScope
from services import effect_params as _ep
from services import morph_aspects
from services import morph_effect_state


# ─── Output type ─────────────────────────────────────────────────────────────

@dataclass
class ConcreteWrite:
    virtual_id: str
    effect_type: str                       # the current effect type at compile time
    kind: Literal["patch", "switch"]
    patch: Optional[dict] = None           # populated when kind="patch"
    new_effect_type: Optional[str] = None  # populated when kind="switch"
    starter_config: Optional[dict] = None  # populated when kind="switch"
    ramp_ms: Optional[int] = None


# ─── Scope resolution ────────────────────────────────────────────────────────

def resolve_scope(scope: MorphScope) -> list[str]:
    """Union of virtual_ids ∪ virtuals in categories ∪ virtuals in roles.
    Empty scope = all imported virtuals (global).

    Always intersected with the set of virtuals SpotFX has imported into device
    categories. virtual_ids that name an un-imported LedFX virtual are silently
    dropped — SpotFX never writes to virtuals it doesn't own.
    """
    imported = set(_ep.get_all_virtual_ids())

    if not scope.virtual_ids and not scope.categories and not scope.roles:
        return list(imported)

    from services.device_category_service import get_virtuals_for_role

    out: list[str] = []
    seen: set[str] = set()

    def _add(vid: str) -> None:
        if vid and vid not in seen and vid in imported:
            seen.add(vid)
            out.append(vid)

    for vid in scope.virtual_ids:
        _add(vid)
    for cat in scope.categories:
        for vid in _ep.get_virtuals_for_category(cat):
            _add(vid)
    for role in scope.roles:
        for vid in get_virtuals_for_role(role):
            _add(vid)
    return out


# ─── Aspect → patch translation ──────────────────────────────────────────────

def _scale_to_param_range(value: float, effect_type: str, param_name: str) -> float:
    """Map a 0..1 aspect value into the param's own [min, max] range.
    Falls back to the raw value if metadata is missing or already-bounded 0..1."""
    meta = _ep.get_param_meta(effect_type, param_name)
    if not meta:
        return value
    lo = meta.get("min")
    hi = meta.get("max")
    if lo is None or hi is None or (lo == 0 and hi == 1):
        return value
    return round(lo + (hi - lo) * max(0.0, min(1.0, value)), 4)


def _patch_numeric(
    effect_type: str,
    aspect_id: str,
    target: MorphTarget,
    current_config: dict,
    intensity: Optional[float],
) -> dict:
    """Distribute one AspectValue.number (mode=absolute) or one nudge_amount
    (mode=nudge, modulated by beat intensity) across every NUMERIC param
    tagged with `aspect_id` on `effect_type`.

    Per-param `aspect_scale` (default 1.0) caps each contributor's reach: on
    power, `bass_decay_rate` at scale 1.0 reaches the top of its range when
    Reactivity=1.0, while `sparks_decay_rate` at scale 0.6 only reaches 0.6.

    Non-numeric params with the same aspect tag (e.g. `sparks_color` under
    `aspect: reactivity`) are filtered — they're in the aspect's UI bucket
    but aren't driven by the numeric slider.

    Nudge math:
        eff_intensity = intensity if intensity is not None else 0.5
        factor        = 1.0 + (eff_intensity - 0.5) * intensity_scale
        # nudge_amount is in abstract 0..1 space; scale to each param's range
        param_delta   = nudge_amount * aspect_scale * (hi - lo) * factor
        new_value     = clamp(current + param_delta, lo, hi)

    A factor of 1.0 keeps the raw nudge; (intensity - 0.5) lets intensity_scale
    bias the delta both up (loud beats) and down (quiet beats) symmetrically.
    """
    val = target.absolute_value
    out: dict = {}
    is_nudge = target.mode == "nudge"

    if not is_nudge and val.number is None:
        return {}

    eff_intensity = intensity if intensity is not None else 0.5
    factor = 1.0 + (eff_intensity - 0.5) * (target.intensity_scale or 0.0)

    for pname in morph_aspects.params_for_aspect(effect_type, aspect_id):
        meta = _ep.get_param_meta(effect_type, pname) or {}
        if meta.get("type") not in ("numeric", "integer"):
            continue
        scale = meta.get("aspect_scale")
        if scale is None:
            scale = 1.0
        # Per-target weight override (UI: reactivity "per-param scale weights").
        # Keyed by "{effect_type}.{param}"; replaces the catalog default scale
        # for this param. Applies to both absolute and nudge math below.
        override = (val.scale_overrides or {}).get(f"{effect_type}.{pname}")
        if override is not None:
            scale = override
        lo = meta.get("min", 0.0)
        hi = meta.get("max", 1.0)

        if is_nudge:
            param_delta = (target.nudge_amount or 0.0) * scale * (hi - lo) * factor
            current = current_config.get(pname)
            if current is None:
                current = (lo + hi) / 2  # neutral fallback if cache lacks the param
            current = float(current)
            # magnitude_only params (radial `spin`) store a signed value but are
            # driven in magnitude space — the sign is owned by spin_sign/Flip and
            # re-applied at write time. Nudge the magnitude, not the signed value.
            if meta.get("magnitude_only"):
                current = abs(current)
            new_val = current + param_delta
        else:
            scaled = max(0.0, min(1.0, val.number * scale))
            new_val = lo + (hi - lo) * scaled

        new_val = max(lo, min(hi, new_val))
        out[pname] = round(new_val, 4)
    return out


def _patch_color(effect_type: str, val: AspectValue) -> dict:
    """color aspect — gradient OR solid hex applied to the effect's `gradient` (or `bg_color`
    fallback if no gradient param exists)."""
    if not val.color_value:
        return {}
    targets = morph_aspects.params_for_aspect(effect_type, "color")
    if not targets:
        # No 'color'-aspect param on this effect — silently skip (e.g. radial, equalizer2d).
        return {}
    return {pname: val.color_value for pname in targets}


def _patch_bg_color(effect_type: str, val: AspectValue) -> dict:
    if not val.bg_color:
        return {}
    return {pname: val.bg_color for pname in morph_aspects.params_for_aspect(effect_type, "bg_color")}


def _resolve_bool_aspect(value, current) -> bool:
    """Translate the polygon/flip tri-state into a final bool.
      True / False  → as-is
      "toggle"      → flip the current cached value
    Caller guarantees `value` is not None.
    """
    if value == "toggle":
        return not bool(current)
    return bool(value)


def _nudged_numeric(
    effect_type: str,
    param_name: str,
    nudge,
    current_config: dict,
    intensity: Optional[float],
    vid: Optional[str] = None,
    nudge_dir: Optional[dict] = None,
):
    """Resolve a per-Shape-sub-field nudge for one numeric raw param.
    Returns the clamped new value, rounded to 4 decimals.

    factor = 1 + (intensity - 0.5) * nudge.scale
    delta  = nudge.amount * (hi - lo) * factor          # in frontend space
    new    = clamp(current + delta, lo, hi)             # in frontend space

    Integer params (e.g. radial `edges`): `nudge.amount` is an absolute unit
    delta (1 = ±1 edge), NOT a fraction of the range, and the result is rounded
    to the nearest integer.

    Wrap (`nudge.wrap` + a `nudge_dir` state dict): instead of clamping at a
    boundary, reflect the overshoot back into range and reverse the per-(vid,
    param) direction stored in `nudge_dir`, so repeated fires bounce back and
    forth. No-op (plain clamp) when wrap is off or no state dict is provided.

    For `scale_offset` params (x_offset / y_offset), the schema's [min, max]
    is the FRONTEND −1..1 range while LedFX stores 0..1. The current cached
    value is converted into frontend space before the math runs, and the
    result is converted back at the end.
    """
    meta = _ep.get_param_meta(effect_type, param_name) or {}
    lo = meta.get("min", 0.0)
    hi = meta.get("max", 1.0)
    # Per-nudge min/max override (None = use the effect param's full range). For
    # scale_offset params the override is in frontend −1..1 space, matching `lo`/`hi`.
    if getattr(nudge, "lo", None) is not None:
        lo = float(nudge.lo)
    if getattr(nudge, "hi", None) is not None:
        hi = float(nudge.hi)
    if hi < lo:
        lo, hi = hi, lo
    is_integer = meta.get("type") == "integer"
    scale_offset = bool(meta.get("scale_offset"))
    eff_intensity = intensity if intensity is not None else 0.5
    factor = 1.0 + (eff_intensity - 0.5) * float(nudge.scale or 0.0)

    wrap = bool(getattr(nudge, "wrap", False)) and nudge_dir is not None
    dir_key = f"{vid}::{param_name}"
    direction = nudge_dir.get(dir_key, 1) if wrap else 1

    # Integer params nudge in raw units; everything else in fractions of range.
    if is_integer:
        delta = float(nudge.amount or 0.0) * factor
    else:
        delta = float(nudge.amount or 0.0) * (hi - lo) * factor
    delta *= direction

    cur_raw = current_config.get(param_name)
    if cur_raw is None:
        current_fe = (lo + hi) / 2.0
    elif scale_offset:
        # LedFX 0..1 → frontend −1..1
        current_fe = (float(cur_raw) - 0.5) * 2.0
    else:
        current_fe = float(cur_raw)

    raw_new = current_fe + delta
    if wrap and hi > lo:
        if raw_new > hi:
            new_fe = hi - (raw_new - hi)      # reflect off the top
            nudge_dir[dir_key] = -direction
        elif raw_new < lo:
            new_fe = lo + (lo - raw_new)      # reflect off the bottom
            nudge_dir[dir_key] = -direction
        else:
            new_fe = raw_new
        new_fe = max(lo, min(hi, new_fe))     # guard against a >range overshoot
    else:
        new_fe = max(lo, min(hi, raw_new))

    if scale_offset:
        # frontend −1..1 → LedFX 0..1
        return round(new_fe / 2.0 + 0.5, 4)
    if is_integer:
        return int(round(new_fe))   # nearest integer
    return round(new_fe, 4)


def _patch_shape(
    effect_type: str,
    val: AspectValue,
    current_config: dict,
    mode: str = "absolute",
    intensity: Optional[float] = None,
    vid: Optional[str] = None,
    nudge_dir: Optional[dict] = None,
) -> dict:
    """shape aspect — write only the sub-fields the user set AND only those the effect supports.

    Sub-field → param mapping (resolved via the `aspect` tag in effect_params.json):
      polygon → `polygon`  (radial only)
      star    → `star`     (radial only)
      edges   → `edges`    (radial only)
      twist   → `twist`    (radial only)
      flip    → `flip` (power/melt) or `ring` (equalizer2d) or `spin_sign` (radial)

    Booleans (polygon, flip): tri-state True / False / "toggle" regardless of mode —
    "toggle" reads current cached value and flips it; nudge doesn't have a natural
    meaning for booleans, so they always use absolute_value's polygon/flip slots.

    Numeric sub-fields (star, edges, twist): when mode == "nudge" AND the matching
    *_nudge spec is present, compute current + amount * (hi - lo) * factor (clamped).
    Otherwise write the absolute_value sub-field if set.
    """
    out: dict = {}
    shape_params = morph_aspects.params_for_aspect(effect_type, "shape")
    name_set = set(shape_params)
    is_nudge = (mode == "nudge")

    # Booleans (polygon, flip, reverse) — always absolute-mode tri-state regardless of target.mode
    if val.polygon is not None and "polygon" in name_set:
        out["polygon"] = _resolve_bool_aspect(val.polygon, current_config.get("polygon", False))
    if val.flip is not None:
        # power / melt use "flip"; equalizer2d uses "ring"; radial uses "spin_sign"
        for candidate in ("flip", "ring", "spin_sign"):
            if candidate in name_set:
                out[candidate] = _resolve_bool_aspect(val.flip, current_config.get(candidate, False))
                break
    if val.reverse is not None and "reverse" in name_set:  # blackhole flow direction
        out["reverse"] = _resolve_bool_aspect(val.reverse, current_config.get("reverse", False))

    # Numerics: nudge if mode=nudge AND nudge spec present; else absolute.
    # `scale_offset` params (x_offset / y_offset) live in frontend −1..1 space
    # on the AspectValue but in LedFX 0..1 space on the wire — convert at write.
    for key in ("star", "edges", "twist", "x_offset", "y_offset", "swirl", "horizon_scale"):
        if key not in name_set:
            continue
        meta = _ep.get_param_meta(effect_type, key) or {}
        scale_offset = bool(meta.get("scale_offset"))
        nudge_spec = getattr(val, f"{key}_nudge", None)
        if is_nudge and nudge_spec is not None:
            # _nudged_numeric already returns LedFX-space when scale_offset is set
            v = _nudged_numeric(effect_type, key, nudge_spec, current_config, intensity,
                                vid=vid, nudge_dir=nudge_dir)
            out[key] = int(v) if key == "edges" else v
        else:
            abs_val = getattr(val, key, None)
            if abs_val is None:
                continue
            if scale_offset:
                # frontend −1..1 → LedFX 0..1
                out[key] = round(float(abs_val) / 2.0 + 0.5, 4)
            elif key == "edges":
                out[key] = int(abs_val)
            else:
                # clamp to the param's registered range so bound/edge values
                # can't fail LedFX schema validation (e.g. horizon_scale ≤ 0.8)
                lo, hi = meta.get("min"), meta.get("max")
                v = float(abs_val)
                if lo is not None:
                    v = max(lo, v)
                if hi is not None:
                    v = min(hi, v)
                out[key] = round(v, 4)
    return out


def _patch_for_aspect(
    effect_type: str,
    aspect_id: str,
    target: MorphTarget,
    current_config: dict,
    intensity: Optional[float],
    vid: Optional[str] = None,
    nudge_dir: Optional[dict] = None,
) -> dict:
    val = target.absolute_value
    if aspect_id in ("brightness", "reactivity", "blur"):
        return _patch_numeric(effect_type, aspect_id, target, current_config, intensity)
    # Non-numeric aspects: nudge has no meaning, silently behave as absolute.
    if aspect_id == "color":
        return _patch_color(effect_type, val)
    if aspect_id == "bg_color":
        return _patch_bg_color(effect_type, val)
    if aspect_id == "shape":
        return _patch_shape(effect_type, val, current_config,
                            mode=target.mode, intensity=intensity,
                            vid=vid, nudge_dir=nudge_dir)
    return {}


# ─── Compile ─────────────────────────────────────────────────────────────────

def compile_target(
    target: MorphTarget,
    virtual_cache: dict,
    default_ramp_ms: Optional[int] = None,
    intensity: Optional[float] = None,
    nudge_dir: Optional[dict] = None,
    *,
    accent_per_vid: Optional[dict[str, str]] = None,
) -> list[ConcreteWrite]:
    """Translate one MorphTarget into per-virtual concrete writes.

    `virtual_cache` is `state.ledfx_virtual_cache` (or equivalent shape). Virtuals
    not present in the cache are skipped — the executor is expected to top up the
    cache via `ledfx_client.get_virtual()` before calling this when needed.

    `default_ramp_ms` is the MorphStepAction.ramp_ms; target.ramp_ms overrides it.

    `intensity` is a pre-resolved 0..1 beat-level value matching
    `target.intensity_source`; only consulted when `target.mode == "nudge"`.
    Pass None when no beat data is available (e.g. test fires) — nudge falls
    back to a neutral 0.5 so the result is still well-defined.

    `accent_per_vid` (keyword-only): for effect-switch targets, the new
    effect's accent / third color (sparks_color on power, peak_color on eq2d)
    is always written so it never inherits a stale per-effect default. Source
    priority: an explicit `target.absolute_value.accent_color` override, else
    this map's entry for the virtual (the last fired Color Set's 3rd color —
    the engine builds this from `_last_accent_by_vid`), else black. Pass None
    (e.g. before any Color Set has fired) and switches fall back to black.
    """
    effective_ramp = target.ramp_ms if target.ramp_ms is not None else default_ramp_ms
    writes: list[ConcreteWrite] = []
    virtuals = resolve_scope(target.scope)

    for vid in virtuals:
        cached = virtual_cache.get(vid)
        # Defensive: LedFX bulk responses can carry non-dict scalar fields
        # under top-level keys ("paused", etc.). Skip anything not shaped
        # like a virtual record.
        if not isinstance(cached, dict):
            continue
        cur_eff = cached.get("effect") or {}
        cur_type = cur_eff.get("type")
        if not cur_type:
            continue
        cur_cfg = cur_eff.get("config") or {}

        # Effect-aspect: switch effect type (or re-assert accent if already on it)
        if target.aspect == "effect":
            new_type = target.absolute_value.effect_type
            if not new_type:
                continue
            if new_type not in morph_aspects.supported_effects():
                continue

            # Resolve the accent / third color this target wants on `new_type`:
            # an explicit per-step override wins, else the last fired Color Set's
            # 3rd color for this virtual, else black. None when the effect has no
            # accent param (melt / radial).
            accent_param = morph_aspects.accent_param_for(new_type)
            accent_val = None
            if accent_param:
                accent_val = (
                    target.absolute_value.accent_color
                    or (accent_per_vid or {}).get(vid)
                    or "#000000"
                )

            if new_type == cur_type:
                # Already on the target effect — don't restart it (a re-sent
                # `type` would recreate the effect). But still keep the accent
                # in sync so a device that was already on power ends up matching
                # a sibling that switched TO power in the same step (otherwise
                # the two desync: the switcher gets the accent, this one keeps a
                # stale/default value). Skip when it already matches.
                if (accent_param and accent_val is not None
                        and str(cur_cfg.get(accent_param, "")).strip().lower()
                            != str(accent_val).strip().lower()):
                    writes.append(ConcreteWrite(
                        virtual_id=vid,
                        effect_type=cur_type,
                        kind="patch",
                        patch={accent_param: accent_val},
                        ramp_ms=effective_ramp,
                    ))
                continue

            # Resume the user's last-known config for this (virtual, effect)
            # pair if we have one; otherwise fall back to taste-neutral defaults
            # from effect_params.json.
            starter = morph_effect_state.get(vid, new_type) or morph_aspects.effect_defaults(new_type) or {}

            # Always write the accent so a switch never inherits a stale
            # per-effect default (LedFX fills power's sparks_color with white
            # otherwise).
            if accent_param:
                starter[accent_param] = accent_val

            writes.append(ConcreteWrite(
                virtual_id=vid,
                effect_type=cur_type,
                kind="switch",
                new_effect_type=new_type,
                starter_config=starter,
                ramp_ms=effective_ramp,
            ))
            continue

        # Param-patch aspects
        patch = _patch_for_aspect(cur_type, target.aspect, target, cur_cfg, intensity,
                                  vid=vid, nudge_dir=nudge_dir)
        if not patch:
            continue
        writes.append(ConcreteWrite(
            virtual_id=vid,
            effect_type=cur_type,
            kind="patch",
            patch=patch,
            ramp_ms=effective_ramp,
        ))

    return writes
