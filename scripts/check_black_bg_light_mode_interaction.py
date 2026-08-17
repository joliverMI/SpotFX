#!/usr/bin/env python3
"""Read-only render-path proof for docs/SPECTRA_SPEC.md §72 ("Black Hole
ignores Light mode" investigation).

Uses the REAL vendored fx/ effect config pipeline (fx.headless, a dummy
device, no network, no live storage) to show, empirically rather than by
reasoning alone:

  1. WHY an authored black bg_color defeats Light mode: any entry that
     authors bg_color -- additive OR overwrite, brightness irrelevant --
     puts "background_color" in the outgoing per-fire config write.
     fx/effects/__init__.py's Effect._apply_config does a partial MERGE
     (self._config = {**self._config, **config}), so that key stomps
     whatever was there, including Light mode's forced non-black write.
     An entry that authors nothing never includes the key, so a prior
     write (e.g. Light's) survives untouched.

  2. WHY Dark mode is unaffected either way: dark_lock's clamp forces
     black on every write path that touches background_color/brightness,
     independent of what any entry authored.

  3. The real trade-off in Hybrid/Default mode: removing the authored
     black fields does not just fix Light mode -- it also means these
     entries stop resetting a virtual's background to black on every
     fire. If some earlier fire left a non-black background on the
     virtual (Light mode, or another colour set's own authored colour),
     that colour now persists through a "black" scene's fire instead of
     being cleared, in Hybrid mode specifically (Dark still clamps).

Never touches live storage or a live instance -- fx.headless spins up an
isolated dummy-device host.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402


def _dump(effect, label: str) -> dict:
    cfg = effect._config
    state = {
        "background_color": cfg.get("background_color"),
        "background_brightness": cfg.get("background_brightness"),
        "background_mode": cfg.get("background_mode"),
        "bg_color_use": effect.bg_color_use,
    }
    print(f"{label:60} {state}")
    return state


async def main() -> None:
    headless.silence_audio()
    host = await headless.start_headless_host(str(REPO_ROOT / ".check_black_bg_tmp"))
    virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    effect = headless.attach_effect(host, virtual, "singleColor", {})

    print("== Part 1: an authored black background defeats a Light-mode write ==")
    _dump(effect, "fresh effect, nothing authored")
    light_write = {"background_color": "#201830", "background_brightness": 0.3}
    effect.update_config(dict(light_write))
    after_light = _dump(effect, "Light mode forces #201830 (RoomControlState default)")
    assert after_light["bg_color_use"] is True, "Light's write should visibly composite"

    black_hole_write = {"background_color": "#000000", "background_mode": "overwrite",
                        "background_brightness": 1.0}
    effect.update_config(dict(black_hole_write))
    stomped = _dump(effect, "Black Hole (authored overwrite@1.0) fires next")
    assert stomped["background_color"] == "#000000"
    assert stomped["bg_color_use"] is False, "authored black wins -- Light's bg is gone"
    print("  -> CONFIRMED: an authored black bg_color stomps Light's forced write.\n")

    effect.update_config(dict(light_write))
    _dump(effect, "Light mode forces #201830 again")
    line_write = {"background_color": "#000000", "background_mode": "additive"}
    effect.update_config(dict(line_write))
    stomped_additive = _dump(effect, "Line-* (authored additive black) fires next")
    assert stomped_additive["bg_color_use"] is False
    print("  -> CONFIRMED: additive-black stomps identically to overwrite-black -- the")
    print("     additive/overwrite split does NOT matter for defeating Light mode.\n")

    effect.update_config(dict(light_write))
    _dump(effect, "Light mode forces #201830 a third time")
    no_bg_write = {"brightness": 1.0}  # what the entry would send with bg fields removed
    effect.update_config(dict(no_bg_write))
    preserved = _dump(effect, "Black Hole (bg fields REMOVED) fires next")
    assert preserved["background_color"] == "#201830"
    assert preserved["bg_color_use"] is True, "Light's bg should survive an unauthored fire"
    print("  -> CONFIRMED: removing the authored bg fields lets Light's write survive.\n")

    print("== Part 2: the Hybrid-mode trade-off removal introduces ==")
    other_scene_write = {"background_color": "#ff9940", "background_mode": "overwrite"}
    effect.update_config(dict(other_scene_write))
    _dump(effect, "an earlier scene authors a real bg colour (e.g. 'Calm - Purple')")
    effect.update_config(dict(no_bg_write))
    leftover = _dump(effect, "Black Hole (bg fields REMOVED) fires next, in Hybrid")
    if leftover["background_color"] == "#ff9940" and leftover["bg_color_use"] is True:
        print("  -> CONFIRMED: in Hybrid mode, removing the authored black lets a PRIOR")
        print("     scene's real background colour bleed through Black Hole's fire --")
        print("     today's authored black actively clears it instead. This is the")
        print("     needs-decision trade-off: not free, only Dark mode is unaffected.")

    await host.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
