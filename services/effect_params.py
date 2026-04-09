"""
SpotFX — Effect parameter registry.

Loads config/effect_params.json and provides lookup helpers for:
  - resolving unified labels → raw LedFX param names per effect type
  - listing available labels for a category or globally
  - listing all virtual IDs (for global-scope actions)
"""
from __future__ import annotations
import json
from pathlib import Path

_CONFIG: dict = {}


def load() -> None:
    """Load config/effect_params.json into memory. Called once at startup."""
    global _CONFIG
    path = Path(__file__).parent.parent / "config" / "effect_params.json"
    _CONFIG = json.loads(path.read_text(encoding="utf-8"))


def get_virtuals_for_category(category: str) -> list[str]:
    from services.device_category_service import get_category_by_name
    cat = get_category_by_name(category)
    return cat.virtuals if cat else []


def get_effects_for_category(category: str) -> list[str]:
    from services.device_category_service import get_category_by_name
    cat = get_category_by_name(category)
    return cat.effects if cat else []


def get_all_virtual_ids() -> list[str]:
    """Return flat list of every virtual id across all categories."""
    from services.device_category_service import list_categories
    return [v for cat in list_categories() for v in cat.virtuals]


def resolve_param(effect_type: str, label: str) -> str | None:
    """Return raw param_name for a given effect type + unified label. None if not found."""
    params = _CONFIG.get("effects", {}).get(effect_type, {}).get("params", {})
    for name, meta in params.items():
        if meta.get("label") == label:
            return name
    return None


def resolve_params(effect_type: str, label: str) -> list[str]:
    """Return ALL param_names for a given effect type + unified label (may be >1 if shared label)."""
    params = _CONFIG.get("effects", {}).get(effect_type, {}).get("params", {})
    return [name for name, meta in params.items() if meta.get("label") == label]


def get_param_meta(effect_type: str, param_name: str) -> dict | None:
    """Return the full metadata dict for a specific param, or None if not found."""
    return _CONFIG.get("effects", {}).get(effect_type, {}).get("params", {}).get(param_name)


def _collect_labels(effect_list: list[str]) -> list[dict]:
    """Return deduplicated label metadata for a list of effect type names."""
    seen: set[str] = set()
    out: list[dict] = []
    for eff in effect_list:
        for name, meta in _CONFIG.get("effects", {}).get(eff, {}).get("params", {}).items():
            lbl = meta["label"]
            if lbl not in seen and meta["type"] in ("numeric", "integer", "toggle", "color", "gradient", "polar", "move_xy", "move_polar"):
                seen.add(lbl)
                out.append({
                    "label":        lbl,
                    "type":         meta["type"],
                    "smooth":       meta.get("smooth", False),
                    "min":          meta.get("min"),
                    "max":          meta.get("max"),
                    "flip_sign":    meta.get("flip_sign", False),
                    "scale_offset": meta.get("scale_offset", False),
                })
    return out


def get_labels_for_category(category: str) -> list[dict]:
    """Return deduplicated labels available for a category (across all its effects)."""
    return _collect_labels(get_effects_for_category(category))


def get_all_labels() -> list[dict]:
    """Return deduplicated labels across ALL effects (for global scope)."""
    all_effects = list(_CONFIG.get("effects", {}).keys())
    return _collect_labels(all_effects)
