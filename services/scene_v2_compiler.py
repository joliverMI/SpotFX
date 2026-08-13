"""SceneV2 → per-virtual LedFX writes through the api/ledfx_client.py seam.
dry_run=True (default; the UI test-fire) stops at the seam — no LedFX I/O.
Flare bands / choreography are carried by the model but not evaluated here yet
(they need fire-time intensity + transition plumbing; engine increment).

color_set (optional): the ColorSetCard whose colours own this fire's
mode="set" device entries — the sequencer's colour-set selector passes its
pick here so scene and palette land in ONE compile (one pass through the
write-plane gate). None keeps today's behavior: set-mode entries carry no
colour params. Scope resolution reuses morph_compiler.resolve_scope (file-
backed device topology, offline-safe); later set entries win shared
virtuals. Only the colour vocabulary the fixed path already speaks is
applied (gradient / background / brightness) — accent and ramp stay with
the legacy colour pipeline until the full colour compiler increment."""
from __future__ import annotations

import logging
from typing import Any, Optional

from models.color_set import ColorSetCard, ColorSetEntry
from models.scene_v2 import SceneDeviceConfig, SceneV2
from services import effect_params

logger = logging.getLogger(__name__)


def _entry_config(dev: SceneDeviceConfig) -> dict[str, Any]:
    config: dict[str, Any] = dict(dev.params)
    if dev.color.mode == "fixed":
        if dev.color.color_value:
            # LedFX gradient params accept solid hex and gradient strings.
            config["gradient"] = dev.color.color_value
        if dev.color.bg_color and not effect_params.bg_color_blocked(dev.effect_type):
            config["background_color"] = dev.color.bg_color
        if dev.color.bg_mode:
            config["background_mode"] = dev.color.bg_mode
    if dev.brightness is not None:
        config["brightness"] = dev.brightness
    if dev.background_brightness is not None:
        config["background_brightness"] = dev.background_brightness
    return config


def _set_entry_by_virtual(color_set: ColorSetCard) -> dict[str, ColorSetEntry]:
    from services.morph_compiler import resolve_scope
    by_vid: dict[str, ColorSetEntry] = {}
    for entry in color_set.entries:
        for vid in resolve_scope(entry.scope):
            by_vid[vid] = entry
    return by_vid


def _apply_set_colors(config: dict[str, Any], effect_type: str,
                      entry: ColorSetEntry) -> dict[str, Any]:
    config = dict(config)   # never mutate the config shared across virtuals
    if entry.color_value:
        config["gradient"] = entry.color_value
    if entry.bg_color and not effect_params.bg_color_blocked(effect_type):
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
    """[{virtual_id, effect_type, config}] — pure; "all" expands to every
    imported virtual, categories to member virtuals, and narrower entries
    override wider ones (all < category < virtual). color_set colours land only
    on mode="set" device entries; mode="fixed" pins its own colours regardless."""
    writes: dict[str, dict[str, Any]] = {}
    set_mode_vids: set[str] = set()
    for kind in ("all", "category", "virtual"):
        for dev in scene.devices:
            if dev.target_kind != kind:
                continue
            if kind == "all":
                virtual_ids = list(dict.fromkeys(effect_params.get_all_virtual_ids()))
                if not virtual_ids:
                    logger.warning("SceneV2 %s: all-devices entry resolves to no "
                                   "virtuals (no categories imported)", scene.name)
            elif kind == "category":
                virtual_ids = effect_params.get_virtuals_for_category(dev.target)
                if not virtual_ids:
                    logger.warning("SceneV2 %s: category '%s' resolves to no virtuals",
                                   scene.name, dev.target)
            else:
                virtual_ids = [dev.target]
            config = _entry_config(dev)
            for vid in virtual_ids:
                writes[vid] = {
                    "virtual_id": vid,
                    "effect_type": dev.effect_type,
                    "config": config,
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


async def fire_scene(scene: SceneV2, *, color_set: Optional[ColorSetCard] = None,
                     dry_run: bool = True) -> dict[str, Any]:
    writes = compile_scene(scene, color_set)
    if not dry_run:
        from api import ledfx_client
        for w in writes:
            await ledfx_client.set_virtual_effect(
                w["virtual_id"], w["effect_type"], w["config"], is_switch=True)
        logger.info("SceneV2 '%s' fired: %d virtual writes%s", scene.name,
                    len(writes),
                    f" (colour set '{color_set.name}')" if color_set else "")
    return {"dry_run": dry_run, "writes": writes}
