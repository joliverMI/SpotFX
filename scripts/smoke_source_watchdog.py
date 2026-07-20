"""
Offline smoke test for the radial source-virtual healing:

  1. effect-switch starter merges defaults UNDER the resume snapshot, so a
     partial snapshot can never drop source_virtual;
  2. source watchdog repairs a consumer whose source_virtual is "unknown";
  3. source watchdog restores the source virtual's last-seen effect when it
     loses its effect;
  4. source watchdog reactivates a deactivated source virtual;
  5. repairs need two consecutive faulty polls (no fighting transitions).

USAGE
  .venv/bin/python scripts/smoke_source_watchdog.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from api import ledfx_client                                   # noqa: E402
from models.music_event import (                               # noqa: E402
    AspectValue,
    MorphScope,
    MorphStepAction,
    MorphTarget,
)
from models.state import state                                 # noqa: E402
from services import morph_effect_state, source_watchdog       # noqa: E402
from services.trigger_engine import TriggerEngine              # noqa: E402

VID = "crystal-mapper"
SRC = "radial-dummy"

passed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        sys.exit(1)


calls: list[tuple] = []


async def rec_set_virtual_effect(vid, etype, config):
    calls.append(("put", vid, etype, dict(config)))


async def rec_set_virtual_active(vid, active):
    calls.append(("active", vid, active))


async def rec_post_virtual_effect(vid, etype, config):
    calls.append(("post", vid, etype, dict(config)))


ledfx_client.set_virtual_effect = rec_set_virtual_effect
ledfx_client.set_virtual_active = rec_set_virtual_active
ledfx_client.post_virtual_effect = rec_post_virtual_effect


async def main() -> None:
    engine = TriggerEngine()
    morph_effect_state.load()

    # 1 — switch starter: defaults fill holes in a partial resume snapshot
    real_get = morph_effect_state.get
    morph_effect_state.get = lambda vid, etype: (
        {"spin": 0.7} if (vid, etype) == (VID, "radial") else real_get(vid, etype)
    )
    state.ledfx_virtual_cache[VID] = {
        "effect": {"type": "blackhole", "config": {"swirl": 3.0}},
        "config": {},
        "active": True,
    }
    calls.clear()
    await engine._execute_action(MorphStepAction(
        ramp_ms=0,
        targets=[MorphTarget(
            scope=MorphScope(virtual_ids=[VID]),
            aspect="effect",
            absolute_value=AspectValue(effect_type="radial"),
        )],
    ))
    morph_effect_state.get = real_get
    switches = [c for c in calls if c[0] == "put" and c[2] == "radial"]
    check("switch to radial issued", len(switches) >= 1, repr(calls))
    starter = switches[0][3]
    check("partial snapshot keeps its own keys (spin=0.7)",
          starter.get("spin") == 0.7, repr(starter))
    check("defaults fill source_virtual into partial snapshot",
          starter.get("source_virtual") == SRC, repr(starter))

    # 2 — watchdog repairs source_virtual == "unknown" (after 2 strikes)
    state.ledfx_virtual_cache.clear()
    source_watchdog._strikes.clear()
    source_watchdog._last_seen.clear()
    state.ledfx_virtual_cache[VID] = {
        "effect": {"type": "radial", "config": {"source_virtual": "unknown"}},
        "active": True,
    }
    state.ledfx_virtual_cache[SRC] = {
        "effect": {"type": "melt", "config": {"speed": 0.5}},
        "active": True,
    }
    calls.clear()
    await source_watchdog.check_and_repair()
    check("no repair on first strike", not calls, repr(calls))
    await source_watchdog.check_and_repair()
    check("unknown source repaired on second strike",
          any(c[0] == "put" and c[1] == VID and c[3].get("source_virtual") == SRC
              for c in calls), repr(calls))
    check("cache updated after repair",
          state.ledfx_virtual_cache[VID]["effect"]["config"]["source_virtual"] == SRC, "")

    # 3 — watchdog restores the source's lost effect from last-seen memory
    calls.clear()
    await source_watchdog.check_and_repair()  # healthy pass: remembers melt on SRC
    state.ledfx_virtual_cache[SRC] = {"effect": {}, "active": True}
    await source_watchdog.check_and_repair()
    check("no source restore on first strike", not calls, repr(calls))
    await source_watchdog.check_and_repair()
    check("source effect restored via POST from last-seen (melt)",
          any(c[0] == "post" and c[1] == SRC and c[2] == "melt"
              and c[3].get("speed") == 0.5 for c in calls), repr(calls))

    # 4 — watchdog reactivates a deactivated source
    calls.clear()
    state.ledfx_virtual_cache[SRC] = {
        "effect": {"type": "melt", "config": {"speed": 0.5}},
        "active": False,
    }
    await source_watchdog.check_and_repair()
    await source_watchdog.check_and_repair()
    check("inactive source reactivated",
          any(c[0] == "active" and c[1] == SRC and c[2] is True for c in calls),
          repr(calls))

    print(f"\nall {passed} checks passed")


if __name__ == "__main__":
    asyncio.run(main())
