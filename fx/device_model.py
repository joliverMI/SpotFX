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

import importlib
import inspect
import json
from pathlib import Path
from typing import Any, Optional

import voluptuous as vol

_REPO_ROOT = Path(__file__).parent.parent
EFFECT_PARAMS_FILE = _REPO_ROOT / "config" / "effect_params.json"
CATEGORIES_FILE = _REPO_ROOT / "storage" / "device_categories.json"

_registry_cache: tuple[int, dict] | None = None
_categories_cache: tuple[int, dict] | None = None
_param_description_cache: dict[str, dict[str, str]] = {}
_schema_default_cache: dict[str, dict[str, Any]] = {}

# Registry effect ids that differ from their fx module name — mirrors
# scripts/backfill_param_defaults.py's own MODULE_ALIAS (kept as a second,
# independent copy on purpose: that script is a one-off maintenance tool,
# this module is imported at request time by both processes).
_EFFECT_MODULE_ALIAS = {"noise": "noise2d"}


def refresh() -> None:
    global _registry_cache, _categories_cache
    _registry_cache = None
    _categories_cache = None
    _param_description_cache.clear()
    _schema_default_cache.clear()


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


# The vendored effects carrying the charge/lull/drop phase machinery: the
# `phase` ("none"|"charge"|"lull"|"drop") + `phase_progress` (0→1) config
# pair, edge-detected in config_updated and consumed per draw, with the
# shared orphan watchdog (fx/effects/particle_handoff.phase_release_due).
# Matches the original SpotFX program's PHASE_EFFECTS set; deliberately NOT
# part of the effect-parameter registry below — phase keys ride ONLY
# dedicated phase writes, never editor surfaces or band patches.
PHASE_EFFECTS = frozenset({
    "blackhole", "blackhole1d", "orbits", "orbits1d", "radial",
    "fireworks", "fireworks1d", "squiggles", "dancer", "eye",
})

# The vendored effects carrying the flare-driven payoff burst: the
# `burst_rockets` config key (an instant "explode N payoff rockets NOW"
# count, edge-detected in config_updated, consumed per draw, self-reset to
# 0 after firing — the drop payoff's own spawn shape, see each effect's
# _flare_burst). Like the phase keys above, deliberately NOT part of the
# effect-parameter registry below — burst_rockets rides ONLY the dedicated
# firework_burst flare write (spectra scene_response._firework_burst),
# never editor surfaces or band patches.
FIREWORK_BURST_EFFECTS = frozenset({"fireworks", "fireworks1d"})

# The vendored effects carrying the flare-driven BLOB RUSH: the `blob_rush`
# config key (an instant "spawn this many blobs NOW, evenly spread" count,
# edge-detected in config_updated, consumed per draw, self-reset to 0 after
# firing — see fx/effects/blackhole.py's _blob_rush). Same discipline as
# the two sets above: deliberately NOT part of the effect-parameter
# registry below, so it rides ONLY the dedicated blob_rush flare write
# (spectra scene_response._blob_rush), never an editor surface or a band
# patch. 2D Blackhole only — blackhole1d is a 1px ring view of the same
# field with no hex boundary to arrive from and its own per-strip
# population; his ask named Black Hole's event horizon and its max blob
# counts, and mirroring it there was not asked for.
BLOB_RUSH_EFFECTS = frozenset({"blackhole"})


# ── effect-parameter registry ────────────────────────────────────────────────

def effect_types() -> list[str]:
    return list(registry().get("effects", {}).keys())


def effect_params(effect_type: str) -> dict[str, dict]:
    return registry().get("effects", {}).get(effect_type, {}).get("params", {})


def get_param_meta(effect_type: str, param_name: str) -> Optional[dict]:
    return effect_params(effect_type).get(param_name)


def _effect_class(effect_type: str):
    """The vendored fx effect class carrying `effect_type`'s own
    CONFIG_SCHEMA, or None if the module/class can't be found — same
    module-resolution technique as scripts/backfill_param_defaults.py's
    schema_defaults()."""
    module_name = _EFFECT_MODULE_ALIAS.get(effect_type, effect_type)
    try:
        mod = importlib.import_module(f"fx.effects.{module_name}")
    except ImportError:
        return None
    for _, cls in inspect.getmembers(mod, inspect.isclass):
        if cls.__module__ == mod.__name__ and hasattr(cls, "CONFIG_SCHEMA"):
            return cls
    return None


def schema_default(effect_type: str, param_name: str) -> Any:
    """The vendored effect's OWN default for `param_name` — read live off
    `cls.schema()` exactly like param_descriptions() reads descriptions —
    i.e. the value an effect genuinely runs at for a param nothing ever
    authored. None when the effect/param can't be resolved or the key
    declares no default. Voluptuous wraps every declared default in a
    `default_factory` callable; it's called here so callers get the value,
    never the factory. Cached per process alongside descriptions (same
    redeploy-bound staleness argument)."""
    cache = _schema_default_cache.get(effect_type)
    if cache is None:
        cache = {}
        cls = _effect_class(effect_type)
        if cls is not None:
            try:
                markers = cls.schema().schema
            except Exception:
                markers = {}
            for key in markers:
                raw = getattr(key, "default", None)
                if raw is None or raw is vol.UNDEFINED:
                    continue
                try:
                    cache[str(key.schema)] = raw() if callable(raw) else raw
                except Exception:
                    continue
        _schema_default_cache[effect_type] = cache
    return cache.get(param_name)


def resting_default(effect_type: str, param_name: str) -> Any:
    """What `param_name` rests at on `effect_type` when NOTHING holds it —
    the effect's own schema default first (ground truth: it's what the
    running instance was built with), the registry's `default` as the
    fallback for a param the vendored schema doesn't declare one for. The
    one resolution shared by the response engine's momentary release
    (spectra/services/scene_response.py — the value a spike on a
    never-authored param returns to, so it can't be stranded for lack of
    a baseline) and the parameter watchdog (spectra/services/
    param_watchdog.py — the value it expects an unheld toggle to read).
    Two readers, one definition, so they can never disagree on "resting".
    None when neither source knows — a caller must then skip, never
    invent."""
    value = schema_default(effect_type, param_name)
    if value is not None:
        return value
    meta = get_param_meta(effect_type, param_name)
    return None if meta is None else meta.get("default")


def param_descriptions(effect_type: str) -> dict[str, str]:
    """{param_name: description}, read LIVE off the vendored effect's own
    CONFIG_SCHEMA (voluptuous `description=` kwarg on each key, merged
    across the class's full MRO by its own `.schema()` classmethod) — the
    literal text the effect's author wrote for what a param does. Never a
    second hand-maintained copy: this is what makes Sonic's parameter
    catalogue (spectra/services/scene_console.py's get_param_info)
    incapable of describing a parameter that no longer behaves that way —
    a vendor update to fx/effects/*.py changes this text for free, with
    nothing else to edit. Cached per process (`refresh()` clears it,
    mirroring the registry's own cache — the vendored .py source doesn't
    change without a redeploy, unlike the file-backed registry)."""
    if effect_type in _param_description_cache:
        return _param_description_cache[effect_type]
    cls = _effect_class(effect_type)
    out: dict[str, str] = {}
    if cls is not None:
        for key in cls.schema().schema:
            desc = getattr(key, "description", None)
            if desc and isinstance(desc, str):
                out[str(key.schema)] = desc
    _param_description_cache[effect_type] = out
    return out


def param_catalogue(effect_type: str) -> dict[str, dict]:
    """One effect's full discovery view, param name -> {label, type, min,
    max, options, default, description}: type/range/default come from the
    shared registry (config/effect_params.json, the same data every write
    path already validates against — see effect_params()); description is
    read live from the vendored schema (param_descriptions(), above).
    Neither half is hand-typed a second time here."""
    descriptions = param_descriptions(effect_type)
    out: dict[str, dict] = {}
    for name, meta in effect_params(effect_type).items():
        entry: dict[str, Any] = {
            "label": meta.get("label", name),
            "type": meta.get("type"),
            "description": descriptions.get(name),
        }
        for field in ("min", "max", "options", "default", "unit"):
            if field in meta:
                entry[field] = meta[field]
        out[name] = entry
    return out


def bg_color_blocked(effect_type: str) -> bool:
    """True when the effect opts out of background_color writes
    (`no_background_color` registry flag — e.g. radial renders a source
    virtual's frames; a non-black background washes the panel)."""
    return bool(registry().get("effects", {}).get(effect_type, {})
                .get("no_background_color"))


def accent_param_for(effect_type: str) -> Optional[str]:
    """Raw param name holding the effect's "third / accent color"
    (`sparks_color` on power), or None if the effect has no accent slot.
    Ported from spot-effects' services/morph_aspects.accent_param_for —
    same registry, same `"accent": true` flag (see config/effect_params.json)."""
    for name, meta in effect_params(effect_type).items():
        if meta.get("accent"):
            return name
    return None


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
