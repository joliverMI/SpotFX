"""
SpotFX — LedFX scene → starter Morph Set importer.

Reads a LedFX scene snapshot via `GET /api/scenes` (which already includes
each virtual's effect type + config) and converts it into a `morph_set`
MusicEvent the user can then edit in the builder. One lane per active,
imported, in-scope virtual; each lane has a single MorphStep alternative
with per-aspect targets that approximate the scene's state.

Filtering rules:
  • virtual.action must be "activate" (skip "stop" / "ignore")
  • virtual.type must be in morph_aspects.supported_effects()
    (`power`/`melt`/`radial`/`equalizer2d` — noise/concentric out of scope)
  • virtual_id must exist in a SpotFX device category

Numeric aspect reconstruction:
  Picks the first numeric param tagged with the aspect on the effect (the
  "primary" param — usually `brightness` for Brightness, `bass_decay_rate`
  / `reactivity` / `spin_multiplier` for Reactivity, `blur` for Blur),
  then back-solves the abstract 0..1 AspectValue.number from the param's
  [min, max] and aspect_scale. Other bundle params (e.g. background_brightness
  on power) will land at whatever the abstract value × their own scale
  produces — close to but not necessarily identical to the original scene.
  The import is meant as a starting point; users will tune from here.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from api import ledfx_client
from models.music_event import (
    AspectValue, MorphLane, MorphScope, MorphStepAction, MorphTarget, MusicEvent,
)
from services import effect_params, morph_aspects

logger = logging.getLogger(__name__)

_GRADIENTS_FILE = Path(__file__).parent.parent / "storage" / "gradients.json"


def _load_gradients() -> list[dict]:
    if not _GRADIENTS_FILE.exists():
        return []
    try:
        data = json.loads(_GRADIENTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_gradients(data: list[dict]) -> None:
    _GRADIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _GRADIENTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _register_scene_gradients(scene_name: str, gradient_strings: set[str]) -> None:
    """Append any gradient strings not already in storage/gradients.json under
    auto-generated names ('From <scene>: 1', '… : 2', …). Dedup by `value`."""
    if not gradient_strings:
        return
    existing = _load_gradients()
    existing_values = {g.get("value") for g in existing}
    new_strings = [s for s in sorted(gradient_strings) if s not in existing_values]
    if not new_strings:
        return
    for idx, val in enumerate(new_strings, start=1):
        existing.append({
            "id":    str(uuid.uuid4()),
            "name":  f"From {scene_name}: {idx}",
            "value": val,
        })
    _save_gradients(existing)
    logger.info("scene_absorb: added %d gradient(s) to library from scene '%s'",
                len(new_strings), scene_name)


def _numeric_aspect_target(vid: str, etype: str, aspect_id: str, cfg: dict) -> Optional[MorphTarget]:
    """Build a brightness/reactivity/blur MorphTarget by back-solving the
    abstract 0..1 value from the scene's primary param. Returns None when
    the aspect has no numeric param on this effect, or the param isn't in cfg."""
    params = morph_aspects.params_for_aspect(etype, aspect_id)
    if not params:
        return None

    primary = None
    primary_meta = None
    for p in params:
        meta = effect_params.get_param_meta(etype, p) or {}
        if meta.get("type") in ("numeric", "integer"):
            primary = p
            primary_meta = meta
            break
    if primary is None:
        return None

    val = cfg.get(primary)
    if val is None:
        return None

    lo = primary_meta.get("min", 0.0)
    hi = primary_meta.get("max", 1.0)
    scale = primary_meta.get("aspect_scale") or 1.0
    span = max(hi - lo, 1e-6)
    abs_pos = (float(val) - lo) / span / max(scale, 1e-6)
    abs_pos = max(0.0, min(1.0, abs_pos))

    return MorphTarget(
        scope=MorphScope(virtual_ids=[vid]),
        aspect=aspect_id,
        mode="absolute",
        absolute_value=AspectValue(number=round(abs_pos, 4)),
    )


def _color_target(vid: str, etype: str, cfg: dict) -> Optional[MorphTarget]:
    for p in morph_aspects.params_for_aspect(etype, "color"):
        val = cfg.get(p)
        if not val:
            continue
        # Strings only — gradient CSS or hex
        if not isinstance(val, str):
            continue
        kind = "gradient" if "gradient(" in val else "solid"
        return MorphTarget(
            scope=MorphScope(virtual_ids=[vid]),
            aspect="color",
            mode="absolute",
            absolute_value=AspectValue(color_kind=kind, color_value=val),
        )
    return None


def _bg_color_target(vid: str, etype: str, cfg: dict) -> Optional[MorphTarget]:
    for p in morph_aspects.params_for_aspect(etype, "bg_color"):
        val = cfg.get(p)
        if isinstance(val, str) and val:
            return MorphTarget(
                scope=MorphScope(virtual_ids=[vid]),
                aspect="bg_color",
                mode="absolute",
                absolute_value=AspectValue(bg_color=val),
            )
    return None


def _shape_target(vid: str, etype: str, cfg: dict) -> Optional[MorphTarget]:
    """Capture any shape sub-fields present in the scene config."""
    sv = AspectValue()
    found = False
    name_set = set(morph_aspects.params_for_aspect(etype, "shape"))

    if "polygon" in name_set and "polygon" in cfg:
        sv.polygon = bool(cfg["polygon"]); found = True
    if "star" in name_set and "star" in cfg:
        try: sv.star = float(cfg["star"]); found = True
        except (TypeError, ValueError): pass
    if "edges" in name_set and "edges" in cfg:
        try: sv.edges = int(cfg["edges"]); found = True
        except (TypeError, ValueError): pass
    if "twist" in name_set and "twist" in cfg:
        try: sv.twist = float(cfg["twist"]); found = True
        except (TypeError, ValueError): pass
    # flip → one of {flip, ring, spin_sign} depending on effect
    for flip_key in ("flip", "ring", "spin_sign"):
        if flip_key in name_set and flip_key in cfg:
            sv.flip = bool(cfg[flip_key]); found = True
            break

    if not found:
        return None
    return MorphTarget(
        scope=MorphScope(virtual_ids=[vid]),
        aspect="shape",
        mode="absolute",
        absolute_value=sv,
    )


def _targets_for_virtual(vid: str, etype: str, cfg: dict) -> list[MorphTarget]:
    """Build the full target list for one (virtual, effect, config) tuple."""
    out: list[MorphTarget] = []

    # Always include the effect-type itself so re-firing the import puts the
    # virtual back on this effect even if it had drifted away.
    out.append(MorphTarget(
        scope=MorphScope(virtual_ids=[vid]),
        aspect="effect",
        mode="absolute",
        absolute_value=AspectValue(effect_type=etype),
    ))

    for aspect_id in ("brightness", "reactivity", "blur"):
        t = _numeric_aspect_target(vid, etype, aspect_id, cfg)
        if t: out.append(t)

    for builder in (_color_target, _bg_color_target, _shape_target):
        t = builder(vid, etype, cfg)
        if t: out.append(t)

    return out


async def import_scene(scene_id: str) -> Optional[MusicEvent]:
    """Fetch the scene and build a starter morph_set MusicEvent. Returns None
    if the scene is missing or has no importable (active + imported + in-scope)
    virtuals."""
    scenes = await ledfx_client.get_scenes()
    match = next((s for s in scenes if s.get("id") == scene_id), None)
    if match is None:
        logger.warning("scene_absorb: scene '%s' not found on LedFX", scene_id)
        return None

    supported = set(morph_aspects.supported_effects())
    imported = set(effect_params.get_all_virtual_ids())
    scene_name = match.get("name") or scene_id

    lanes: list[MorphLane] = []
    skipped: list[str] = []
    seen_gradients: set[str] = set()
    for vid, v in (match.get("virtuals") or {}).items():
        if not isinstance(v, dict):
            continue
        if v.get("action") != "activate":
            continue
        etype = v.get("type")
        if not etype:
            continue
        if etype not in supported:
            skipped.append(f"{vid}:{etype}(unsupported)")
            continue
        if vid not in imported:
            skipped.append(f"{vid}(not-imported)")
            continue
        cfg = v.get("config") or {}
        # Collect every gradient string this virtual's config uses so we can
        # auto-register them into SpotFX's gradient library. Skip solid hex
        # strings — those don't live in the library.
        for p in morph_aspects.params_for_aspect(etype, "color"):
            cv = cfg.get(p)
            if isinstance(cv, str) and "gradient(" in cv:
                seen_gradients.add(cv)
        targets = _targets_for_virtual(vid, etype, cfg)
        if not targets:
            continue
        step = MorphStepAction(ramp_ms=500, targets=targets)
        lanes.append(MorphLane(name=vid, labels=[], alternatives=[step]))

    if not lanes:
        logger.info("scene_absorb: scene '%s' had no importable virtuals (skipped: %s)", scene_id, skipped)
        return None

    # Auto-register any gradient strings the scene used that aren't already in
    # the SpotFX library, so the Color editor's dropdown can show them.
    _register_scene_gradients(scene_name, seen_gradients)

    return MusicEvent(
        name=f"Import: {scene_name}",
        event_type="morph_set",
        color="#FFD700",
        labels=["imported-scene"],
        morph_lanes=lanes,
    )
