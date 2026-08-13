"""Bake per-param `default` into config/effect_params.json — the effect's
REAL default, so the UI can initialize a newly enabled param to it instead
of 0/true (Scenes UI decision 4).

Source order per numeric/integer/toggle param:
  1. the effect's tuned `defaults` blob in the registry itself (Javi's
     tuning-gate values — what the setters actually fire, cf.
     docs/ADDING_EFFECTS.md Phase 3);
  2. the raw default from the vendored fx effect schema (fx/ @ the
     VENDOR.md commit);
  3. sign-control toggles (`sign_control: true`): the sign of their
     `maps_to` param's resolved default.
Params with none of the three are skipped and reported (the UI falls back
to min/false).

Dry-run by default; --apply rewrites config/effect_params.json in place.
Idempotent. Re-run after a fx/ vendor update (check_scene_v2.py asserts the
baked values still match the schemas).
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path

import voluptuous as vol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REGISTRY_FILE = Path(__file__).resolve().parent.parent / "config" / "effect_params.json"
BAKED_TYPES = ("numeric", "integer", "toggle")
# Registry effect ids that differ from their fx module name.
MODULE_ALIAS = {"noise": "noise2d"}


def schema_defaults(effect_id: str) -> dict[str, object]:
    """{raw_param_name: default} from the effect class's extended schema."""
    mod = importlib.import_module(f"fx.effects.{MODULE_ALIAS.get(effect_id, effect_id)}")
    for _, cls in inspect.getmembers(mod, inspect.isclass):
        if cls.__module__ == mod.__name__ and hasattr(cls, "CONFIG_SCHEMA"):
            out: dict[str, object] = {}
            for key in cls.schema().schema:
                if isinstance(key, vol.Optional) and key.default is not vol.UNDEFINED:
                    out[str(key.schema)] = key.default() if callable(key.default) else key.default
            return out
    raise LookupError(f"no CONFIG_SCHEMA class in fx.effects.{effect_id}")


def bake(registry: dict) -> tuple[int, list[str]]:
    """Set meta['default'] in place; returns (changed_count, skipped_labels)."""
    changed, skipped = 0, []
    for effect_id, effect in registry["effects"].items():
        params = effect.get("params") or {}
        if not params:
            continue
        defaults = schema_defaults(effect_id)
        defaults.update({k: v for k, v in (effect.get("defaults") or {}).items()
                         if isinstance(v, (int, float, bool))})  # tuned wins
        for name, meta in params.items():
            if meta.get("type") not in BAKED_TYPES:
                continue
            if name in defaults:
                value = defaults[name]
            elif meta.get("sign_control") and meta.get("maps_to") in defaults:
                value = float(defaults[meta["maps_to"]]) >= 0  # On = positive sign
            else:
                skipped.append(f"{effect_id}.{name}")
                continue
            if meta.get("type") == "toggle":
                value = bool(value)
            if meta.get("default") != value:
                meta["default"] = value
                changed += 1
    return changed, skipped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write config/effect_params.json")
    args = ap.parse_args()

    registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    changed, skipped = bake(registry)
    total = sum(1 for e in registry["effects"].values()
                for m in (e.get("params") or {}).values() if m.get("type") in BAKED_TYPES)
    baked = sum(1 for e in registry["effects"].values()
                for m in (e.get("params") or {}).values()
                if m.get("type") in BAKED_TYPES and "default" in m)
    print(f"editable params: {total}; with default after bake: {baked}; changed: {changed}")
    for s in skipped:
        print(f"skipped (no schema default): {s}")
    if args.apply:
        REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n",
                                 encoding="utf-8")
        print(f"wrote {REGISTRY_FILE}")
    else:
        print("dry run — pass --apply to write")


if __name__ == "__main__":
    main()
