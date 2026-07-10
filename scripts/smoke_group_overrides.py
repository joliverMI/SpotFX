"""
Offline smoke test for Color Group overrides + nested-category resolution.

Runs entirely against fakes — no LedFX or SpotFX server needed:
  * device categories are redirected to a temp file (nested Parent/Child tree)
  * the LedFX client write/refresh calls are monkeypatched to record locally
  * temp Color Set/Group cards are saved to storage/color_sets.json and
    deleted afterwards (same convention as smoke_color_set.py)

USAGE
  .venv/bin/python scripts/smoke_group_overrides.py

WHAT IT CHECKS
  1. Category recursion: a Set scoped to "Smoke Parent" also colors the
     virtuals of nested "Smoke Child".
  2. Nested override: a Group override scoped to the child category replaces
     only its field (background_brightness) on only the child's devices; the
     Set's values survive everywhere else.
  3. Beyond-Set override: an override scoped to a category the Set doesn't
     cover applies its explicit fields there — and does NOT drag along the
     Set's colors or the black-accent default.
  4. Superset override: an override scope covering the Set's whole scope
     simply wins for its fields on every device.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params
effect_params.load()

from api import ledfx_client                                             # noqa: E402
from models.state import state                                           # noqa: E402
from models.color_set import ColorSetCard, ColorSetEntry, GroupMember    # noqa: E402
from models.music_event import SetColorAction, MorphScope                # noqa: E402
from services import color_set_store, device_category_service            # noqa: E402
from services import morph_effect_state                                  # noqa: E402
from services.trigger_engine import TriggerEngine                        # noqa: E402

GRAD_A = "linear-gradient(90deg, #ff0000 0%, #ffaa00 100%)"
GRAD_B = "linear-gradient(90deg, #00aaff 0%, #aa00ff 100%)"

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def _fake_categories() -> None:
    """Point device_category_service at a temp file with a nested tree."""
    cats = {
        "smoke-parent": {"id": "smoke-parent", "name": "Smoke Parent",
                         "parent_id": None, "virtuals": ["a1", "a2"], "effects": []},
        "smoke-child":  {"id": "smoke-child", "name": "Smoke Child",
                         "parent_id": "smoke-parent", "virtuals": ["b1"], "effects": []},
        "smoke-other":  {"id": "smoke-other", "name": "Smoke Other",
                         "parent_id": None, "virtuals": ["c1"], "effects": []},
    }
    tmp = Path(tempfile.mkstemp(suffix="_smoke_categories.json")[1])
    tmp.write_text(json.dumps(cats), encoding="utf-8")
    device_category_service.CATEGORIES_FILE = tmp


def _seed_cache() -> None:
    state.ledfx_virtual_cache.clear()
    for vid in ("a1", "a2", "b1", "c1"):
        state.ledfx_virtual_cache[vid] = {"effect": {"type": "power", "config": {
            "gradient": "linear-gradient(90deg, #111111 0%, #222222 100%)",
            "background_color": "#000000",
            "background_mode": "additive",
            "brightness": 0.5,
            "background_brightness": 0.5,
            "sparks_color": "#ffffff",
        }}}


def _patch_network() -> None:
    async def _noop_put(vid, etype, cfg):
        return None

    async def _noop_refresh(self, vids):
        return None

    ledfx_client.set_virtual_effect = _noop_put
    ledfx_client.ramp_gradient_params = _noop_put  # unused at ramp_ms=0
    ledfx_client.ramp_effect_params = _noop_put
    ledfx_client.server_tween_enabled = lambda: False
    TriggerEngine._refresh_effect_types = _noop_refresh
    morph_effect_state.save_many = lambda updates: None


def _cfg(vid: str) -> dict:
    return state.ledfx_virtual_cache[vid]["effect"]["config"]


async def main() -> None:
    _fake_categories()
    _patch_network()

    base_set = ColorSetCard(name="[smoke] Base", kind="set", entries=[
        ColorSetEntry(scope=MorphScope(categories=["Smoke Parent"]),
                      color_kind="gradient", color_value=GRAD_A,
                      bg_color="#110000", brightness=0.9, background_brightness=0.6),
    ])
    group_nested = ColorSetCard(
        name="[smoke] Group nested/beyond", kind="group",
        members=[GroupMember(color_set_id=base_set.id)],
        entries=[
            # nested: child category inside the Set's parent-category scope
            ColorSetEntry(scope=MorphScope(categories=["Smoke Child"]),
                          background_brightness=0.2),
            # beyond the Set's coverage entirely
            ColorSetEntry(scope=MorphScope(categories=["Smoke Other"]),
                          bg_color="#222222"),
        ])
    group_superset = ColorSetCard(
        name="[smoke] Group superset", kind="group",
        members=[GroupMember(color_set_id=base_set.id)],
        entries=[ColorSetEntry(scope=MorphScope(categories=["Smoke Parent"]),
                               color_kind="gradient", color_value=GRAD_B)])
    created = [base_set, group_nested, group_superset]
    for c in created:
        color_set_store.save(c)

    engine = TriggerEngine()
    action = lambda ref: SetColorAction(ref_id=ref, ramp_ms=0, preserve_effect=False)  # noqa: E731

    try:
        print("Category recursion:")
        got = effect_params.get_virtuals_for_category("Smoke Parent")
        check("parent scope includes child category's virtuals", got == ["a1", "a2", "b1"], f"got {got}")

        print("Nested + beyond-Set overrides (fire group):")
        _seed_cache()
        await engine._execute_set_color(action(group_nested.id), await_ramps=True)
        check("a1 keeps Set gradient", _cfg("a1")["gradient"] == GRAD_A)
        check("a1 keeps Set bg_brightness", _cfg("a1")["background_brightness"] == 0.6)
        check("a1 accent defaulted to black by Set", _cfg("a1")["sparks_color"] == "#000000")
        check("b1 (nested child) gets Set gradient", _cfg("b1")["gradient"] == GRAD_A)
        check("b1 (nested child) bg_brightness overridden", _cfg("b1")["background_brightness"] == 0.2)
        check("b1 keeps Set brightness", _cfg("b1")["brightness"] == 0.9)
        check("c1 (beyond Set) gets override bg_color", _cfg("c1")["background_color"] == "#222222")
        check("c1 gradient untouched", "#111111" in _cfg("c1")["gradient"])
        check("c1 accent NOT force-cleared", _cfg("c1")["sparks_color"] == "#ffffff")
        check("c1 brightness untouched", _cfg("c1")["brightness"] == 0.5)

        print("Superset override (fire group):")
        _seed_cache()
        await engine._execute_set_color(action(group_superset.id), await_ramps=True)
        for vid in ("a1", "a2", "b1"):
            check(f"{vid} gradient replaced by override", _cfg(vid)["gradient"] == GRAD_B)
        check("a1 keeps Set bg_color (field not overridden)", _cfg("a1")["background_color"] == "#110000")
        check("c1 untouched by superset group", _cfg("c1")["background_color"] == "#000000")

        print("Plain Set fire still works (no overrides):")
        _seed_cache()
        await engine._execute_set_color(action(base_set.id), await_ramps=True)
        check("b1 covered via nested category", _cfg("b1")["gradient"] == GRAD_A)
        check("c1 untouched", _cfg("c1")["background_color"] == "#000000")
    finally:
        for c in created:
            color_set_store.delete(c.id)

    print(f"\n{'ALL PASS' if not FAILURES else f'{len(FAILURES)} FAILURE(S): ' + ', '.join(FAILURES)}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    asyncio.run(main())
