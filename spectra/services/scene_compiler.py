"""SPECTRA scene → per-virtual writes, through the shared-library device
model and the one write seam (fx_seam).

Two stages, deliberately separate (report §2.3):

  resolve_scene(scene, ctx) — every ValueBinding → scalar via
      binding_resolver (map/steps/fallback/random_sign/dice, coercion from
      the shared param registry). Returns a fully-scalar deep copy plus a
      resolution report (the editor's test-fire panel shows exactly what a
      real fire at that intensity would send). A binding resolving to None
      leaves its field unset — the fire doesn't touch that param.

  compile_scene(resolved, color_set) — the pure SceneV2 compiler, ported
      verbatim in semantics: "all" expands to every imported virtual,
      categories to member subtrees, narrower entries override wider ones
      (all < category < virtual); color_set colours land only on mode="set"
      entries; fixed entries pin their own.

fire_scene() is the API entry: dry_run=True (default) stops at the seam —
no LedFX I/O, writes + resolution report returned for display. The real
fire goes through fx_seam.apply_writes (HTTP to the external LedFX service
until S3 hands SPECTRA the lights in-process through the same seam).
"""
from __future__ import annotations

import logging
from random import Random
from typing import Any, Optional

from fx import device_model
from spectra.models.binding import ValueBinding
from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.services import binding_resolver, fx_seam
from spectra.services.binding_resolver import FireContext
from spectra.services.color_sets import ColorSetCard, ColorSetEntry

logger = logging.getLogger(__name__)


def resolve_scene(scene: SceneV2, ctx: FireContext) -> SceneV2:
    """Deep copy with every binding resolved to a scalar in its param's
    value space. ctx.resolved collects the per-binding report."""
    resolved = scene.model_copy(deep=True)
    for dev in resolved.devices:
        for pname, value in list(dev.params.items()):
            if not isinstance(value, ValueBinding):
                continue
            meta = device_model.get_param_meta(dev.effect_type, pname)
            kind, lo, hi = binding_resolver.kind_for_meta(meta)
            out = binding_resolver.apply_binding(value, ctx, kind, lo, hi)
            ctx.resolved.append({
                "entry": dev.target or "all", "param": pname,
                "signal": value.signal, "dice": value.dice, "value": out})
            if out is None:
                del dev.params[pname]
            else:
                dev.params[pname] = out
        for field in ("brightness", "background_brightness"):
            value = getattr(dev, field)
            if not isinstance(value, ValueBinding):
                continue
            out = binding_resolver.apply_binding(
                value, ctx, binding_resolver.KIND_NUMERIC, 0.0, 1.0)
            ctx.resolved.append({
                "entry": dev.target or "all", "param": field,
                "signal": value.signal, "dice": value.dice, "value": out})
            setattr(dev, field, out)
    return resolved


def _entry_config(dev: SceneDeviceConfig) -> dict[str, Any]:
    config: dict[str, Any] = dict(dev.params)
    if dev.color.mode == "fixed":
        if dev.color.color_value:
            # LedFX gradient params accept solid hex and gradient strings.
            config["gradient"] = dev.color.color_value
        if dev.color.bg_color and not device_model.bg_color_blocked(dev.effect_type):
            config["background_color"] = dev.color.bg_color
        if dev.color.bg_mode:
            config["background_mode"] = dev.color.bg_mode
    if dev.brightness is not None:
        config["brightness"] = dev.brightness
    if dev.background_brightness is not None:
        config["background_brightness"] = dev.background_brightness
    return config


def _set_entry_by_virtual(color_set: ColorSetCard) -> dict[str, ColorSetEntry]:
    by_vid: dict[str, ColorSetEntry] = {}
    for entry in color_set.entries:
        for vid in device_model.resolve_scope(entry.scope.virtual_ids,
                                              entry.scope.categories,
                                              entry.scope.roles):
            by_vid[vid] = entry
    return by_vid


def _apply_set_colors(config: dict[str, Any], effect_type: str,
                      entry: ColorSetEntry) -> dict[str, Any]:
    config = dict(config)   # never mutate the config shared across virtuals
    if entry.color_value:
        config["gradient"] = entry.color_value
    if entry.bg_color and not device_model.bg_color_blocked(effect_type):
        config["background_color"] = entry.bg_color
    if entry.bg_mode:
        config["background_mode"] = entry.bg_mode
    if entry.brightness is not None:
        config["brightness"] = entry.brightness
    if entry.background_brightness is not None:
        config["background_brightness"] = entry.background_brightness
    return config


def compile_scene(scene: SceneV2,
                  color_set: Optional[ColorSetCard] = None) -> list[dict[str, Any]]:
    """[{virtual_id, effect_type, config}] — pure. Callers pass a RESOLVED
    scene (resolve_scene first); a stray binding here is a programming error
    and fails loudly rather than serializing into a LedFX config."""
    for dev in scene.devices:
        for pname, value in dev.params.items():
            if isinstance(value, ValueBinding):
                raise ValueError(
                    f"compile_scene got an unresolved binding on '{pname}' — "
                    "run resolve_scene first")
    writes: dict[str, dict[str, Any]] = {}
    set_mode_vids: set[str] = set()
    for kind in ("all", "category", "virtual"):
        for dev in scene.devices:
            if dev.target_kind != kind:
                continue
            if kind == "all":
                virtual_ids = list(dict.fromkeys(device_model.get_all_virtual_ids()))
                if not virtual_ids:
                    logger.warning("scene %s: all-devices entry resolves to no "
                                   "virtuals (no categories imported)", scene.name)
            elif kind == "category":
                virtual_ids = device_model.get_virtuals_for_category(dev.target)
                if not virtual_ids:
                    logger.warning("scene %s: category '%s' resolves to no virtuals",
                                   scene.name, dev.target)
            else:
                virtual_ids = [dev.target]
            config = _entry_config(dev)
            for vid in virtual_ids:
                # entry_id/color_mode ride along for the S2 engine (drift
                # declarations and palette mechanics follow the WINNING entry
                # per virtual); the write seams read only the first three keys.
                writes[vid] = {
                    "virtual_id": vid,
                    "effect_type": dev.effect_type,
                    "config": config,
                    "entry_id": dev.id,
                    "color_mode": dev.color.mode,
                }
                if dev.color.mode == "set":
                    set_mode_vids.add(vid)
                else:
                    set_mode_vids.discard(vid)
    if color_set is not None:
        by_vid = _set_entry_by_virtual(color_set)
        for vid in set_mode_vids:
            entry = by_vid.get(vid)
            if entry is None:
                continue
            w = writes[vid]
            w["config"] = _apply_set_colors(w["config"], w["effect_type"], entry)
    return list(writes.values())


async def fire_scene(scene: SceneV2, *, intensity: float = 0.5,
                     color_set: Optional[ColorSetCard] = None,
                     dry_run: bool = True,
                     rng: Random | None = None) -> dict[str, Any]:
    """Resolve at the given intensity, compile, and (live only) send through
    the seam. The returned resolution report + writes are the test-fire
    display: dry and live runs share every step up to the seam."""
    ctx = FireContext(intensity, rng=rng)
    resolved = resolve_scene(scene, ctx)
    writes = compile_scene(resolved, color_set)
    if not dry_run:
        await fx_seam.apply_writes(writes)
        logger.info("SPECTRA scene '%s' fired at intensity %.2f: %d virtual "
                    "writes%s", scene.name, intensity, len(writes),
                    f" (colour set '{color_set.name}')" if color_set else "")
        # Re-baseline the evolution engine: drift's declared life restarts
        # from these initial conditions. The ORIGINAL scene rides along —
        # the response engine re-rolls its intact 🎲 bindings.
        from spectra.services import engine
        engine.on_scene_fired(scene, writes,
                              color_set.id if color_set else None)
    return {"dry_run": dry_run, "intensity": intensity, "writes": writes,
            "resolved_bindings": ctx.resolved, "dice_rolls": ctx.dice_rolls()}
