"""
Live smoke test for Color Sets + the Morph Color step.

Fires a Color Set (and a cycling Group) against the live LedFX backend
without spinning up the full SpotFX server. Verifies that a Morph Color
step pushes FG color, BG color, and background_mode to the scoped devices.

USAGE
  .venv/bin/python scripts/smoke_color_set.py

WHAT IT DOES
  1. Loads effect_params (so the color compiler can resolve params).
  2. Polls the live LedFX virtual state once and seeds the local cache.
  3. Builds a temporary Color Set (one entry per actionable virtual) and a
     Group of two Color Sets, saves them to storage/color_sets.json.
  4. Fires a Morph Color step for the Set, then fires the Group 3× to show
     cycle selection advancing.
  5. Prints before/after color/bg_color/background_mode per virtual.
  6. Deletes the temporary cards it created.

CAVEAT
  SpotFX shouldn't be running and actively writing to the same LedFX while
  this runs — they'd be competing publishers. systemctl --user stop spotfx.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params
effect_params.load()

from api import ledfx_client                              # noqa: E402
from models.state import state                            # noqa: E402
from models.color_set import ColorSetCard, ColorSetEntry, GroupMember  # noqa: E402
from models.music_event import MorphColorAction, MorphScope            # noqa: E402
from services import color_set_store                       # noqa: E402
from services.trigger_engine import TriggerEngine          # noqa: E402


def _summary(vid: str, data: dict) -> str:
    eff = data.get("effect") or {}
    cfg = eff.get("config") or {}
    etype = eff.get("type", "?")
    schema = effect_params._CONFIG.get("effects", {}).get(etype, {}).get("params", {})
    show = [n for n, m in schema.items() if m.get("aspect") in ("color", "bg_color")]
    show += [n for n in ("background_mode",) if n in schema]

    def _fmt(name):
        v = cfg.get(name)
        if isinstance(v, str) and len(v) > 40:
            v = v[:37] + "…"
        return f"{name}={v}"

    body = ", ".join(_fmt(k) for k in show if k in cfg) or "(no color params)"
    return f"  {vid:24s}  type={etype:12s}  {body}"


def _entries_for(vids: list[str], gradient: str, bg: str, bg_mode: str | None):
    return [ColorSetEntry(
        scope=MorphScope(virtual_ids=[vid]),
        color_kind="gradient", color_value=gradient,
        bg_color=bg, bg_mode=bg_mode, ramp_ms=400,
    ) for vid in vids]


async def main() -> None:
    print("Polling live LedFX state…")
    live = (await ledfx_client.get_all_virtuals() or {}).get("virtuals") or {}
    imported = set(effect_params.get_all_virtual_ids())
    actionable = {k: v for k, v in live.items()
                  if k in imported and isinstance(v, dict) and (v.get("effect") or {}).get("type")}
    state.ledfx_virtual_cache.update(actionable)
    print(f"Cached {len(actionable)} imported+active virtuals\n")
    if not actionable:
        print("No actionable virtuals — is LedFX running with imported effects? Aborting.")
        return

    vids = sorted(actionable)
    print("BEFORE:")
    for vid in vids:
        print(_summary(vid, actionable[vid]))

    GRAD_A = "linear-gradient(90deg, #ff0000 0%, #ffaa00 100%)"
    GRAD_B = "linear-gradient(90deg, #00aaff 0%, #aa00ff 100%)"

    set_a = ColorSetCard(name="[smoke] Hot", kind="set",
                         entries=_entries_for(vids, GRAD_A, "#110000", "overwrite"))
    set_b = ColorSetCard(name="[smoke] Cool", kind="set",
                         entries=_entries_for(vids, GRAD_B, "#000011", "additive"))
    group = ColorSetCard(name="[smoke] Group", kind="group", mode="cycle", cycle_behavior="wrap",
                         members=[GroupMember(color_set_id=set_a.id, weight=1),
                                  GroupMember(color_set_id=set_b.id, weight=1)])
    created = [set_a, set_b, group]
    for c in created:
        color_set_store.save(c)

    engine = TriggerEngine()

    try:
        print("\nFiring Morph Color step for Set '[smoke] Hot' (await_ramps=True)…")
        await engine._execute_morph_color(MorphColorAction(ref_id=set_a.id, ramp_ms=400), await_ramps=True)
        await asyncio.sleep(0.3)
        after = (await ledfx_client.get_all_virtuals() or {}).get("virtuals") or {}
        print("AFTER (Set):")
        for vid in vids:
            if isinstance(after.get(vid), dict):
                print(_summary(vid, after[vid]))

        print("\nFiring Group 3× (cycle) — expect Hot → Cool → Hot:")
        for i in range(3):
            await engine._execute_morph_color(MorphColorAction(ref_id=group.id, pick_mode="cycle", ramp_ms=200), await_ramps=True)
            chosen = engine._color_cursor.get(group.id)
            picked = color_set_store.get_by_id(group.members[chosen].color_set_id)
            print(f"  fire {i+1}: cursor={chosen} → {picked.name if picked else '?'}")
    finally:
        for c in created:
            color_set_store.delete(c.id)
        print("\nCleaned up temporary cards.")


if __name__ == "__main__":
    asyncio.run(main())
