"""SceneV2 → per-virtual LedFX writes through the api/ledfx_client.py seam.
dry_run=True (default; the UI test-fire) stops at the seam — no LedFX I/O.
Flare bands / choreography are carried by the model but not evaluated here yet
(they need fire-time intensity + transition plumbing; engine increment)."""
from __future__ import annotations

import logging
from typing import Any

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


def compile_scene(scene: SceneV2) -> list[dict[str, Any]]:
    """[{virtual_id, effect_type, config}] — pure; categories expand to member
    virtuals, then virtual entries override."""
    writes: dict[str, dict[str, Any]] = {}
    for kind in ("category", "virtual"):
        for dev in scene.devices:
            if dev.target_kind != kind:
                continue
            if kind == "category":
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
    return list(writes.values())


async def fire_scene(scene: SceneV2, *, dry_run: bool = True) -> dict[str, Any]:
    writes = compile_scene(scene)
    if not dry_run:
        from api import ledfx_client
        for w in writes:
            await ledfx_client.set_virtual_effect(
                w["virtual_id"], w["effect_type"], w["config"], is_switch=True)
        logger.info("SceneV2 '%s' fired: %d virtual writes", scene.name, len(writes))
    return {"dry_run": dry_run, "writes": writes}
