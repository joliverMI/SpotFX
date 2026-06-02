"""
SpotFX — Color Set CRUD store.

Single JSON file `storage/color_sets.json` keyed by card `id`. Holds both
Color Sets (kind="set") and Groups (kind="group"). Mirrors the conventions of
services/setlist_store.py.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from config import PROFILES_DIR
from models.color_set import ColorSetCard

logger = logging.getLogger(__name__)

COLOR_SETS_FILE = PROFILES_DIR.parent / "color_sets.json"


def _load_raw() -> dict:
    if COLOR_SETS_FILE.exists():
        try:
            return json.loads(COLOR_SETS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("color_sets.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COLOR_SETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_all() -> list[ColorSetCard]:
    return [ColorSetCard(**v) for v in _load_raw().values()]


def get_by_id(card_id: str) -> Optional[ColorSetCard]:
    raw = _load_raw()
    if card_id in raw:
        return ColorSetCard(**raw[card_id])
    return None


def save(card: ColorSetCard) -> None:
    raw = _load_raw()
    raw[card.id] = json.loads(card.model_dump_json())
    _save_raw(raw)
    logger.info("Saved Color Set card: %s (kind=%s)", card.name, card.kind)


def delete(card_id: str) -> bool:
    raw = _load_raw()
    if card_id not in raw:
        return False
    del raw[card_id]
    _save_raw(raw)
    return True
