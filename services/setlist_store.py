"""
SpotFX — Set List CRUD store.

Single JSON file `storage/setlists.json` keyed by Set List `id`. Mirrors
the conventions of training_profile_manager / triggerless profile storage.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import PROFILES_DIR
from models.setlist import Setlist

logger = logging.getLogger(__name__)

SETLISTS_FILE = PROFILES_DIR.parent / "setlists.json"


def _load_raw() -> dict:
    if SETLISTS_FILE.exists():
        try:
            return json.loads(SETLISTS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("setlists.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    SETLISTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETLISTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_all() -> list[Setlist]:
    return [Setlist(**v) for v in _load_raw().values()]


def get_by_id(setlist_id: str) -> Optional[Setlist]:
    raw = _load_raw()
    if setlist_id in raw:
        return Setlist(**raw[setlist_id])
    return None


def get_by_context_uri(context_uri: str) -> Optional[Setlist]:
    if not context_uri:
        return None
    for v in _load_raw().values():
        if v.get("context_uri") == context_uri:
            return Setlist(**v)
    return None


def save(setlist: Setlist) -> None:
    raw = _load_raw()
    if not setlist.created_at:
        setlist.created_at = datetime.now(timezone.utc).isoformat()
    raw[setlist.id] = json.loads(setlist.model_dump_json())
    _save_raw(raw)
    logger.info("Saved Set List: %s (context=%s)", setlist.name, setlist.context_uri)


def delete(setlist_id: str) -> bool:
    raw = _load_raw()
    if setlist_id not in raw:
        return False
    del raw[setlist_id]
    _save_raw(raw)
    return True
