"""
SpotFX — Device category CRUD service.

Manages device_categories.json, which stores user-defined groupings of
LedFX virtuals with their associated effect types.  On first startup the
file is seeded from the static categories in config/effect_params.json.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from models.device_category import DeviceCategory

logger = logging.getLogger(__name__)

CATEGORIES_FILE = Path(__file__).parent.parent / "storage" / "device_categories.json"


# ── Raw I/O ──────────────────────────────────────────────────────────────────

def _load_raw() -> dict:
    if CATEGORIES_FILE.exists():
        try:
            return json.loads(CATEGORIES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_raw(data: dict) -> None:
    CATEGORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATEGORIES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── CRUD ─────────────────────────────────────────────────────────────────────

def list_categories() -> list[DeviceCategory]:
    return [DeviceCategory(**v) for v in _load_raw().values()]


def get_category(cat_id: str) -> Optional[DeviceCategory]:
    raw = _load_raw()
    if cat_id in raw:
        return DeviceCategory(**raw[cat_id])
    return None


def get_category_by_name(name: str) -> Optional[DeviceCategory]:
    """Lookup by name string (case-insensitive) for backward compat."""
    for v in _load_raw().values():
        if v.get("name", "").lower() == name.lower():
            return DeviceCategory(**v)
    return None


def save_category(cat: DeviceCategory) -> None:
    raw = _load_raw()
    raw[cat.id] = json.loads(cat.model_dump_json())
    _save_raw(raw)


def delete_category(cat_id: str) -> bool:
    raw = _load_raw()
    if cat_id not in raw:
        return False
    # Re-parent children to top-level
    for v in raw.values():
        if v.get("parent_id") == cat_id:
            v["parent_id"] = None
    del raw[cat_id]
    _save_raw(raw)
    return True


# ── Role helpers ─────────────────────────────────────────────────────────────

def get_virtuals_for_role(role: str) -> list[str]:
    """Return all virtual IDs across categories with the given role."""
    seen: set[str] = set()
    result: list[str] = []
    for cat in list_categories():
        if cat.role == role:
            for v in cat.virtuals:
                if v not in seen:
                    seen.add(v)
                    result.append(v)
    return result


# ── Seed migration ───────────────────────────────────────────────────────────

def seed_from_effect_params() -> None:
    """One-time migration: populate device_categories.json from the static
    categories in config/effect_params.json.  Skips if file already exists
    and has entries."""
    if _load_raw():
        return  # already seeded

    config_path = Path(__file__).parent.parent / "config" / "effect_params.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read effect_params.json for seeding: %s", exc)
        return

    categories = config.get("categories", {})
    data: dict = {}
    for idx, (name, info) in enumerate(categories.items()):
        cat = DeviceCategory(
            name=name,
            virtuals=info.get("virtuals", []),
            effects=info.get("effects", []),
            sort_order=idx,
        )
        data[cat.id] = json.loads(cat.model_dump_json())

    _save_raw(data)
    logger.info("Seeded %d device categories from effect_params.json", len(data))


def migrate_roles() -> None:
    """Assign default roles to known categories if not already set."""
    raw = _load_raw()
    changed = False
    for v in raw.values():
        if v.get("role"):
            continue
        name = v.get("name", "").lower()
        if name == "singles":
            v["role"] = "ambient"
            changed = True
            logger.info("Migrated role 'ambient' to category '%s'", v["name"])
    if changed:
        _save_raw(raw)
