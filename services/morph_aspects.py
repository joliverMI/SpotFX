"""
SpotFX — Morph aspect registry.

An "Aspect" is a user-facing grouping of one or more LedFX raw params (e.g.
"Brightness" groups `brightness` + `background_brightness`; "Shape" groups
`polygon`/`star`/`edges`/`twist` on radial plus `flip` on power/melt).

Aspects are the vocabulary of Morph Steps. The raw mapping lives in
config/effect_params.json under each param's "aspect" field, so updates to
the catalog happen in one place.

Out-of-scope (deliberate):
  - Speed and Zoom are NOT aspects.
  - noise and concentric effects are not in `supported_effects` for the
    Effect aspect picker. Their params have no "aspect" annotations.
"""
from __future__ import annotations

from services import effect_params as _ep


ASPECT_IDS: list[str] = [
    "shape", "effect", "color", "bg_color", "reactivity", "brightness", "blur",
]


def _morph_block() -> dict:
    return _ep._CONFIG.get("morph", {})


def aspect_labels() -> dict[str, str]:
    """Return {aspect_id: display label}. Falls back to the id if unlabeled."""
    labels = _morph_block().get("aspect_labels", {})
    return {aid: labels.get(aid, aid.replace("_", " ").title()) for aid in ASPECT_IDS}


def supported_effects() -> list[str]:
    """Effect types currently in-scope for the Effect aspect picker."""
    return list(_morph_block().get("supported_effects", []))


def params_for_aspect(effect_type: str, aspect_id: str) -> list[str]:
    """Raw param names on `effect_type` that belong to `aspect_id`.

    The Effect aspect is a special case: it represents switching the effect
    type itself, not a param patch — returns [] here. Callers should detect
    aspect_id == "effect" and route to the effect-switch path.
    """
    if aspect_id == "effect":
        return []
    params = _ep._CONFIG.get("effects", {}).get(effect_type, {}).get("params", {})
    return [name for name, meta in params.items() if meta.get("aspect") == aspect_id]


def aspect_for_param(effect_type: str, param_name: str) -> str | None:
    meta = _ep.get_param_meta(effect_type, param_name)
    return meta.get("aspect") if meta else None


def accent_param_for(effect_type: str) -> str | None:
    """Raw param name that holds the 'third / accent color' for an effect, or
    None if the effect doesn't have one (melt / radial). Used by the morph
    compiler to set the accent from the last Color Set's 3rd color (else black)
    on an effect switch — see compile_target's switch branch."""
    params = _ep._CONFIG.get("effects", {}).get(effect_type, {}).get("params", {})
    for name, meta in params.items():
        if meta.get("accent"):
            return name
    return None


def effect_defaults(effect_type: str) -> dict | None:
    """Starter config when switching TO `effect_type`. None if effect isn't in-scope."""
    if effect_type not in supported_effects():
        return None
    return dict(_ep._CONFIG.get("effects", {}).get(effect_type, {}).get("defaults", {}))


def aspect_param_meta() -> dict:
    """UI-facing metadata for every aspect-tagged param on each supported
    effect: {etype: {pname: {label, type, min, max, aspect, aspect_scale,
    distribute}}}. Feeds the per-param editors (the Reactivity menu) so the
    frontend gets ranges/labels without a second endpoint."""
    out: dict = {}
    for etype in supported_effects():
        params = _ep._CONFIG.get("effects", {}).get(etype, {}).get("params", {})
        out[etype] = {
            name: {
                "label":        meta.get("label", name),
                "type":         meta.get("type"),
                "min":          meta.get("min"),
                "max":          meta.get("max"),
                "aspect":       meta.get("aspect"),
                "aspect_scale": meta.get("aspect_scale"),
                "distribute":   meta.get("distribute", True),
            }
            for name, meta in params.items() if meta.get("aspect")
        }
    return out


def aspect_catalog() -> dict:
    """Full snapshot for the UI: ids, labels, supported effects, and per-effect param mappings."""
    effects = supported_effects()
    return {
        "aspect_ids":        ASPECT_IDS,
        "aspect_labels":     aspect_labels(),
        "supported_effects": effects,
        "per_effect_params": {
            etype: {aid: params_for_aspect(etype, aid) for aid in ASPECT_IDS}
            for etype in effects
        },
        "effect_defaults": {etype: effect_defaults(etype) for etype in effects},
        "param_meta":      aspect_param_meta(),
    }
