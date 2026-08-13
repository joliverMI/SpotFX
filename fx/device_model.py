"""Shared device model (SpotFX-authored, NOT vendored fork code).

The owner's architecture decision names the device model — device categories,
the effect-parameter registry, virtual topology — as SHARED LIBRARY, so both
spot-effects and SPECTRA resolve targets against one truth. This module is
the library form: file-backed, read-only, no engine imports. It carries the
two compiler touches the SceneV2 design moves behind the shared seam
(`services/effect_params` lookups and `morph_compiler.resolve_scope`).

spot-effects keeps its own `services/effect_params` / `device_category_service`
until it is replaced (untouched-until-switchover doctrine); SPECTRA imports
only this module. Reads are mtime-cached; call `refresh()` to force a reload.

Paths are module-level so executable specs can point them at temp files.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).parent.parent
EFFECT_PARAMS_FILE = _REPO_ROOT / "config" / "effect_params.json"
CATEGORIES_FILE = _REPO_ROOT / "storage" / "device_categories.json"

_registry_cache: tuple[int, dict] | None = None
_categories_cache: tuple[int, dict] | None = None


def refresh() -> None:
    global _registry_cache, _categories_cache
    _registry_cache = None
    _categories_cache = None


def _load_cached(path: Path, cache: tuple[int, dict] | None) -> tuple[tuple[int, dict], dict]:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return (0, {}), {}
    if cache is not None and cache[0] == mtime:
        return cache, cache[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    return (mtime, data), data


def registry() -> dict:
    global _registry_cache
    _registry_cache, data = _load_cached(EFFECT_PARAMS_FILE, _registry_cache)
    return data


def _categories_raw() -> dict:
    global _categories_cache
    _categories_cache, data = _load_cached(CATEGORIES_FILE, _categories_cache)
    return data


# ── categories / virtual topology ────────────────────────────────────────────

def list_categories() -> list[dict]:
    return list(_categories_raw().values())


def get_category_by_name(name: str) -> Optional[dict]:
    for cat in list_categories():
        if cat.get("name") == name:
            return cat
    return None


def category_subtree(category: str) -> list[dict]:
    """The named category and every descendant, parent-first; [] if unknown."""
    root = get_category_by_name(category)
    if not root:
        return []
    cats = list_categories()
    out: list[dict] = []
    seen: set[str] = set()  # guards against parent_id cycles

    def _walk(c: dict) -> None:
        if c["id"] in seen:
            return
        seen.add(c["id"])
        out.append(c)
        for child in cats:
            if child.get("parent_id") == c["id"]:
                _walk(child)

    _walk(root)
    return out


def get_virtuals_for_category(category: str) -> list[str]:
    """Virtuals of the named category AND every descendant (dedup'd,
    parent-first) — a category target covers its whole subtree."""
    out: list[str] = []
    seen: set[str] = set()
    for cat in category_subtree(category):
        for v in cat.get("virtuals", []):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


def get_effects_for_category(category: str) -> list[str]:
    """The subtree's union of curated effect lists (dedup'd, parent-first)."""
    out: list[str] = []
    seen: set[str] = set()
    for cat in category_subtree(category):
        for e in cat.get("effects", []):
            if e not in seen:
                seen.add(e)
                out.append(e)
    return out


def get_all_virtual_ids() -> list[str]:
    return [v for cat in list_categories() for v in cat.get("virtuals", [])]


def get_virtuals_for_role(role: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for cat in list_categories():
        if cat.get("role") == role:
            for vid in cat.get("virtuals", []):
                if vid not in seen:
                    seen.add(vid)
                    out.append(vid)
    return out


def resolve_scope(virtual_ids: list[str] = (), categories: list[str] = (),
                  roles: list[str] = ()) -> list[str]:
    """Union of virtual_ids ∪ category-subtree virtuals ∪ role virtuals,
    always intersected with the imported set; empty scope = all imported.
    Mirrors spot-effects' morph_compiler.resolve_scope — never writes to
    virtuals the device model doesn't own."""
    imported = set(get_all_virtual_ids())
    if not virtual_ids and not categories and not roles:
        return list(dict.fromkeys(get_all_virtual_ids()))
    out: list[str] = []
    seen: set[str] = set()

    def _add(vid: str) -> None:
        if vid and vid not in seen and vid in imported:
            seen.add(vid)
            out.append(vid)

    for vid in virtual_ids:
        _add(vid)
    for cat in categories:
        for vid in get_virtuals_for_category(cat):
            _add(vid)
    for role in roles:
        for vid in get_virtuals_for_role(role):
            _add(vid)
    return out


# ── effect-parameter registry ────────────────────────────────────────────────

def effect_types() -> list[str]:
    return list(registry().get("effects", {}).keys())


def effect_params(effect_type: str) -> dict[str, dict]:
    return registry().get("effects", {}).get(effect_type, {}).get("params", {})


def get_param_meta(effect_type: str, param_name: str) -> Optional[dict]:
    return effect_params(effect_type).get(param_name)


def bg_color_blocked(effect_type: str) -> bool:
    """True when the effect opts out of background_color writes
    (`no_background_color` registry flag — e.g. radial renders a source
    virtual's frames; a non-black background washes the panel)."""
    return bool(registry().get("effects", {}).get(effect_type, {})
                .get("no_background_color"))


def round_int_params(effect_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Round integer-typed params so LedFX schema validation never sees a
    float where an int belongs (mirrors the spot-effects client's guard)."""
    params = effect_params(effect_type)
    out = dict(config)
    for name, value in out.items():
        meta = params.get(name)
        if meta and meta.get("type") == "integer" and isinstance(value, float):
            out[name] = int(round(value))
    return out
