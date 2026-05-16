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
    """Treat numeric aspect values as 0..1 and scale to the param's own [min, max] range.
    Falls back to the raw value if metadata is missing or already-bounded."""
    meta = _ep.get_param_meta(effect_type, param_name)
    if not meta:
        return value
    lo = meta.get("min")
    hi = meta.get("max")
    if lo is None or hi is None or (lo == 0 and hi == 1):
        return value
    return round(lo + (hi - lo) * max(0.0, min(1.0, value)), 4)


def _patch_numeric(effect_type: str, aspect_id: str, val: AspectValue) -> dict:
    """brightness / reactivity / blur — apply a 0..1 number to every raw param the aspect maps."""
    if val.number is None:
        return {}
    out: dict = {}
    for pname in morph_aspects.params_for_aspect(effect_type, aspect_id):
        out[pname] = _scale_to_param_range(val.number, effect_type, pname)
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


def _patch_shape(effect_type: str, val: AspectValue) -> dict:
    """shape aspect — write only the sub-fields the user set AND only those the effect supports.

    Sub-field → param mapping (resolved via the `aspect` tag in effect_params.json):
      polygon → `polygon`  (radial only)
      star    → `star`     (radial only)
      edges   → `edges`    (radial only)
      twist   → `twist`    (radial only)
      flip    → `flip` (power/melt) or `ring` (equalizer2d) or `spin_sign` (radial)
    """
    out: dict = {}
    # The fields' canonical raw-param names per effect:
    shape_params = morph_aspects.params_for_aspect(effect_type, "shape")
    name_set = set(shape_params)

    if val.polygon is not None and "polygon" in name_set:
        out["polygon"] = val.polygon
    if val.star is not None and "star" in name_set:
        out["star"] = val.star
    if val.edges is not None and "edges" in name_set:
        out["edges"] = int(val.edges)
    if val.twist is not None and "twist" in name_set:
        out["twist"] = val.twist
    if val.flip is not None:
        # power / melt use "flip"; equalizer2d uses "ring"; radial uses "spin_sign"
        for candidate in ("flip", "ring", "spin_sign"):
            if candidate in name_set:
                out[candidate] = val.flip
                break
    return out


def _patch_for_aspect(effect_type: str, aspect_id: str, val: AspectValue) -> dict:
    if aspect_id in ("brightness", "reactivity", "blur"):
        return _patch_numeric(effect_type, aspect_id, val)
    if aspect_id == "color":
        return _patch_color(effect_type, val)
    if aspect_id == "bg_color":
        return _patch_bg_color(effect_type, val)
    if aspect_id == "shape":
        return _patch_shape(effect_type, val)
    return {}


# ─── Compile ─────────────────────────────────────────────────────────────────

def compile_target(target: MorphTarget, virtual_cache: dict, default_ramp_ms: Optional[int] = None) -> list[ConcreteWrite]:
    """Translate one MorphTarget into per-virtual concrete writes.

    `virtual_cache` is `state.ledfx_virtual_cache` (or equivalent shape). Virtuals
    not present in the cache are skipped — the executor is expected to top up the
    cache via `ledfx_client.get_virtual()` before calling this when needed.

    `default_ramp_ms` is the MorphStepAction.ramp_ms; target.ramp_ms overrides it.
    """
    if target.mode == "nudge":
        raise NotImplementedError("Morph nudge mode lands in Phase 7")

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
        cur_type = (cached.get("effect") or {}).get("type")
        if not cur_type:
            continue

        # Effect-aspect: switch effect type (or no-op if already on it)
        if target.aspect == "effect":
            new_type = target.absolute_value.effect_type
            if not new_type or new_type == cur_type:
                continue
            if new_type not in morph_aspects.supported_effects():
                continue
            # Resume the user's last-known config for this (virtual, effect)
            # pair if we have one; otherwise fall back to taste-neutral defaults
            # from effect_params.json.
            starter = morph_effect_state.get(vid, new_type) or morph_aspects.effect_defaults(new_type) or {}
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
        patch = _patch_for_aspect(cur_type, target.aspect, target.absolute_value)
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
