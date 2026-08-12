"""
Offline smoke test for the `brightness` action (multiplier semantics).

Runs entirely without LedFX or the SpotFX server: seeds a fake virtual into
the state cache, monkeypatches the ledfx_client write seams + scope resolver,
and drives TriggerEngine._execute_brightness through absolute / repeat /
nudge / binding scenarios, asserting on the writes and the multiplier state.

USAGE
  .venv/bin/python scripts/smoke_brightness.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import effect_params

effect_params.load()

from api import ledfx_client                               # noqa: E402
from models.state import state                             # noqa: E402
from models.music_event import BrightnessAction, NumericNudge  # noqa: E402
from models.value_binding import ValueBinding              # noqa: E402
from services import morph_compiler, morph_effect_state    # noqa: E402
from services import trigger_engine as te_mod              # noqa: E402
from services.trigger_engine import TriggerEngine          # noqa: E402

VID = "smoke-brightness-virt"
writes: list[tuple[str, str, dict]] = []


async def _fake_set_virtual_effect(vid, etype, config, **kw):
    writes.append(("instant", vid, dict(config)))
    cfg = state.ledfx_virtual_cache[vid]["effect"]["config"]
    cfg.update(config)


async def _fake_ramp_effect_params(vid, etype, patch, ramp_ms, **kw):
    writes.append(("ramp", vid, dict(patch)))
    cfg = state.ledfx_virtual_cache[vid]["effect"]["config"]
    cfg.update(patch)


def _seed():
    state.ledfx_virtual_cache[VID] = {
        "effect": {"type": "power", "config": {"brightness": 0.8, "background_brightness": 0.4}},
    }


async def main() -> None:
    ledfx_client.set_virtual_effect = _fake_set_virtual_effect
    ledfx_client.ramp_effect_params = _fake_ramp_effect_params
    morph_compiler.resolve_scope = lambda scope: [VID]
    morph_effect_state.save_many = lambda updates: None

    eng = TriggerEngine()

    async def _no_refresh(vids):
        return None
    eng._refresh_effect_types = _no_refresh

    _seed()

    def cfg():
        return state.ledfx_virtual_cache[VID]["effect"]["config"]

    # 1. absolute fg ×0.5 → base derived from cache (0.8), write 0.4
    writes.clear()
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="absolute", brightness_value=0.5, ramp_ms=0))
    assert abs(cfg()["brightness"] - 0.4) < 1e-6, cfg()
    assert abs(eng._bright_mult[VID]["fg"] - 0.5) < 1e-9
    assert abs(eng._bright_base[VID]["fg"] - 0.8) < 1e-9
    assert cfg()["background_brightness"] == 0.4  # bg kept

    # 2. same fire again → no compounding, no write
    writes.clear()
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="absolute", brightness_value=0.5, ramp_ms=0))
    assert not writes, writes
    assert abs(cfg()["brightness"] - 0.4) < 1e-6

    # 3. nudge fg +0.2 → mult 0.7 → 0.8 × 0.7 = 0.56
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="nudge",
        brightness_nudge=NumericNudge(amount=0.2), ramp_ms=0))
    assert abs(eng._bright_mult[VID]["fg"] - 0.7) < 1e-9
    assert abs(cfg()["brightness"] - 0.56) < 1e-6, cfg()

    # 4. nudge clamps at 1.0
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="nudge",
        brightness_nudge=NumericNudge(amount=0.9), ramp_ms=0))
    assert eng._bright_mult[VID]["fg"] == 1.0
    assert abs(cfg()["brightness"] - 0.8) < 1e-6

    # 5. bg absolute ×0.25 via a ⚡ binding (constant map), fg kept
    await eng._execute_brightness(BrightnessAction(
        bg_mode="absolute",
        bg_value=ValueBinding(signal="trigger_intensity", out_min=0.25, out_max=0.25,
                              fallback=0.25),
        ramp_ms=0))
    assert abs(eng._bright_mult[VID]["bg"] - 0.25) < 1e-9
    assert abs(cfg()["background_brightness"] - 0.1) < 1e-6, cfg()
    assert abs(cfg()["brightness"] - 0.8) < 1e-6  # fg untouched

    # 6. simulate the Set Color seam: authored entry value × current mult
    #    (mirrors the multiply in _execute_set_color)
    entry_bright = 0.6
    eng._bright_base.setdefault(VID, {})["fg"] = entry_bright
    expected = entry_bright * eng._bright_mult[VID]["fg"]
    assert abs(expected - 0.6) < 1e-9  # mult is 1.0 after clamp test

    # 7. keep/keep = no-op even with values present
    writes.clear()
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="keep", brightness_value=0.1,
        bg_mode="keep", bg_value=0.1, ramp_ms=0))
    assert not writes

    # 8. wrap bounce: mult 1.0, nudge +0.4 with wrap → reflects to 0.6,
    #    direction flips for the next fire
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="nudge",
        brightness_nudge=NumericNudge(amount=0.4, wrap=True), ramp_ms=0))
    assert abs(eng._bright_mult[VID]["fg"] - 0.6) < 1e-9, eng._bright_mult[VID]
    assert eng._nudge_dir[f"{VID}::__bright_fg__"] == -1

    # 9. UNMODELED effect (radial has no brightness entry in effect_params):
    #    brightness/background_brightness are LedFX BASE schema params, so the
    #    write must still land — base falls back to the schema default 1.0.
    state.ledfx_virtual_cache[VID] = {"effect": {"type": "radial", "config": {}}}
    eng._bright_mult.pop(VID, None)
    eng._bright_base.pop(VID, None)
    writes.clear()
    await eng._execute_brightness(BrightnessAction(
        brightness_mode="absolute", brightness_value=0.3, ramp_ms=0))
    assert writes, "unmodeled-effect brightness write was skipped"
    assert abs(cfg()["brightness"] - 0.3) < 1e-6, cfg()

    # 10. ramp_override (scene/group/chooser cascade) replaces the action ramp:
    #     the write goes out as a ramp with the override's duration
    ramped: list[tuple] = []
    async def _capture_ramp(vid, etype, patch, ramp_ms, **kw):
        ramped.append((dict(patch), ramp_ms))
        state.ledfx_virtual_cache[vid]["effect"]["config"].update(patch)
    ledfx_client.ramp_effect_params = _capture_ramp
    await eng._execute_brightness(
        BrightnessAction(brightness_mode="absolute", brightness_value=0.8, ramp_ms=0),
        await_ramps=True, ramp_override=1234)
    assert ramped and ramped[0][1] == 1234, ramped
    ledfx_client.ramp_effect_params = _fake_ramp_effect_params

    # 11. chooser-level ramp_ms binding resolves via _ramp_override
    #     (trigger_intensity 0 → 1500ms, 1 → 250ms, inverted map)
    from services import trigger_engine as _te
    for intensity, expect in ((0.0, 1500), (1.0, 250), (0.5, 875)):
        tok = _te._FIRE_INTENSITY.set(intensity)
        try:
            got = eng._ramp_override(
                ValueBinding(signal="trigger_intensity", mode="map",
                             in_min=0.0, in_max=1.0, out_min=1500, out_max=250),
                None)
        finally:
            _te._FIRE_INTENSITY.reset(tok)
        assert got == expect, (intensity, got)
    # None at this level → inherited flows through
    assert eng._ramp_override(None, 777) == 777
    # own override wins over inherited
    assert eng._ramp_override(300, 777) == 300

    print("smoke_brightness: all scenarios OK")


if __name__ == "__main__":
    asyncio.run(main())
