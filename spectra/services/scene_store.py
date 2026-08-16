"""SPECTRA scene CRUD store: storage/spectra/scenes.json keyed by scene id.
Ported from spot-effects scene_v2_store (same guarantees) against SPECTRA's
own storage; writes are atomic. Set-filters stay per-set only: accepted_set_ids
may reference kind="set" Colour Sets exclusively — the API rejects group ids
on save, and loading migrates any legacy group reference to the group's
member sets so the UI never holds filter contents it cannot display."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from spectra import config
from spectra.models.scene import SceneV2
from spectra.services import color_sets

logger = logging.getLogger(__name__)


def _expand_group_refs(scene: SceneV2) -> SceneV2:
    """Replace any group-card id in accepted_set_ids with the group's member
    set ids (recursive, cycle-guarded), preserving order and deduplicating.
    Ids matching no card (deleted sets) are kept verbatim — dropping them
    silently is exactly the trap this migration closes."""
    if not scene.accepted_set_ids:
        return scene
    cards = {c.id: c for c in color_sets.list_all()}
    if not any(cards[i].kind == "group" for i in scene.accepted_set_ids if i in cards):
        return scene
    raw_members = _group_members()
    expanded: list[str] = []
    seen: set[str] = set()

    def _add(set_id: str) -> None:
        if set_id in seen:
            return
        card = cards.get(set_id)
        if card is not None and card.kind == "group":
            seen.add(set_id)  # cycle guard only — the group id itself is dropped
            for member_id in raw_members.get(set_id, []):
                _add(member_id)
            return
        seen.add(set_id)
        expanded.append(set_id)

    for set_id in scene.accepted_set_ids:
        _add(set_id)
    logger.info("SPECTRA scene '%s': expanded group refs %s -> %s",
                scene.name, scene.accepted_set_ids, expanded)
    scene.accepted_set_ids = expanded
    return scene


def _group_members() -> dict[str, list[str]]:
    """group id → member set ids."""
    return {c.id: [m.color_set_id for m in c.members]
            for c in color_sets.list_all() if c.kind == "group"}


def group_ids_in_filter(scene: SceneV2) -> list[str]:
    """Group-card ids illegally present in accepted_set_ids (validation)."""
    cards = {c.id: c for c in color_sets.list_all()}
    return [i for i in scene.accepted_set_ids
            if i in cards and cards[i].kind == "group"]


def _load_raw() -> dict:
    if config.SCENES_FILE.exists():
        try:
            return json.loads(config.SCENES_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("spectra scenes.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    path = config.SCENES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def list_all() -> list[SceneV2]:
    return [_expand_group_refs(SceneV2(**v)) for v in _load_raw().values()]


def get_by_id(scene_id: str) -> Optional[SceneV2]:
    raw = _load_raw()
    if scene_id in raw:
        return _expand_group_refs(SceneV2(**raw[scene_id]))
    return None


def save(scene: SceneV2) -> None:
    raw = _load_raw()
    raw[scene.id] = json.loads(scene.model_dump_json())
    _save_raw(raw)
    logger.info("Saved SPECTRA scene: %s (%d device entries)",
                scene.name, len(scene.devices))


def delete(scene_id: str) -> bool:
    raw = _load_raw()
    if scene_id not in raw:
        return False
    del raw[scene_id]
    _save_raw(raw)
    return True
