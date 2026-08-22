"""Executable spec: the FIREWORK BURST flare, end to end, against HIS REAL
Fireworks V2 scene (read-only — this script never writes any storage) on
the real vendored render pipeline at his real device shapes.

His ask, verbatim: "make a flare meant to line up with a burst of
fireworks on top of the standard ones in the fireworks scene. 3 for 0
intensity and 6 for 1 intensity, scaled linearly. put it in every energy
intensity in the scene."

What is proven, in order:
  1. His exact numbers: firework_burst_rockets is 3 at intensity 0.0, 6 at
     1.0, linear between, clamped outside — the color_rotate
     _intensity_scaled shape, same helper.
  2. His real scene, migrated (in memory — the real write is
     scripts/add_fireworks_burst_flare.py --apply, an operator step):
     parses under the current model, and EVERY flare energy band selects
     the kind — "every energy intensity in the scene", not a lane.
  3. LINE UP, on the real pipeline: a real ResponseEngine fire lands real
     payoff particles on the real vendored fireworks (72x37, his crystal's
     shape) AND fireworks1d (17px, his largest strip) effects within TWO
     rendered frames of the trigger (frame 1 lands the 1 ms jump tween,
     frame 2's spawn consumes the edge) — never queued for a beat, which
     is why this is not beat_burst.
  4. ON TOP OF THE STANDARD ONES: the scene's own live particles survive
     the burst untouched — same count in front of the buffer, ages
     advancing normally, lives/colours unchanged, phase state unchanged.
     ignore_cap: the strip's own max_blobs=6 (his real value) does not
     swallow a 24-particle burst.
  5. The key self-resets to 0, so the NEXT band fire (same or different
     count) edges again — three consecutive band fires all land.

Usage:
  .venv/bin/python scripts/check_firework_burst.py [--scenes-file PATH]

--scenes-file defaults to the live store (read-only). No LedFX service, no
HTTP, no audio hardware, no storage writes.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).parent.parent))

from fx import device_model, facade, headless
from fx.host import FxHost

SCENE_NAME = "Fireworks V2"
KIND_NAME = "Firework Burst"

CRYSTAL_VID = "check-crystal"     # 72x37 — his crystal-mapper's shape
STRIP_VID = "check-strip"         # 17px — his largest strip

PASS = "  ✓"


def _fail(msg: str) -> None:
    raise SystemExit(f"  ✗ FAIL: {msg}")


def _check(cond: bool, msg: str) -> None:
    if not cond:
        _fail(msg)
    print(f"{PASS} {msg}")


# ── §1 his exact numbers ───────────────────────────────────────────────────

def section_1_numbers() -> None:
    from spectra.services import scene_response as sr
    print("§1 his exact numbers (3 at 0, 6 at 1, linear, clamped)")
    _check(sr.firework_burst_rockets(0.0) == 3, "intensity 0.0 -> 3 rockets")
    _check(sr.firework_burst_rockets(1.0) == 6, "intensity 1.0 -> 6 rockets")
    _check(sr.firework_burst_rockets(0.5) == round(4.5), "0.5 -> round(4.5)")
    _check(sr.firework_burst_rockets(-2.0) == 3
           and sr.firework_burst_rockets(9.0) == 6,
           "out-of-range intensity clamps, never extrapolates")


# ── §2 his real scene, migrated in memory ──────────────────────────────────

def _migrated_scene(scenes_file: Path):
    from spectra.models.scene import SceneV2
    sys.path.insert(0, str(Path(__file__).parent))
    from add_fireworks_burst_flare import NEW_KIND, _find_scene_id

    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    sid = _find_scene_id(store, SCENE_NAME, scenes_file)
    raw = copy.deepcopy(store[sid])
    if not any(k.get("name") == KIND_NAME
               for k in raw.get("flare_kinds", [])):
        raw.setdefault("flare_kinds", []).append(dict(NEW_KIND))
        for band in ((raw.get("responses") or {}).get("flare") or {})["bands"]:
            band.setdefault("kinds", {})[KIND_NAME] = 1.0
    return SceneV2(**raw)


def section_2_scene(scenes_file: Path):
    from spectra.services import scene_response as sr
    print(f"§2 his real scene, migrated (read-only from {scenes_file})")
    scene = _migrated_scene(scenes_file)
    _check(any(k.name == KIND_NAME and k.type == "firework_burst"
               for k in scene.flare_kinds),
           "migrated scene parses; kind declared with no authored knobs")
    bands = scene.responses["flare"].bands
    _check(len(bands) == 3, f"three flare energy bands ({len(bands)})")
    for probe in (0.0, 0.2, 0.35, 0.5, 0.7, 0.9, 1.0):
        band = sr.select_band(bands, probe)
        _check(band is not None and band.kinds.get(KIND_NAME) == 1.0
               and KIND_NAME not in band.kind_lanes,
               f"intensity {probe}: band selects '{KIND_NAME}' x1.0, "
               "directly (no lane)")
    return scene


# ── §3-§5 the real pipeline at his real shapes ─────────────────────────────

def _two_virtual_config(config_dir: str) -> None:
    """write_headless_config's own shape, twice: his crystal's 72x37 matrix
    and his largest strip's 17px."""
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    pairs = [(CRYSTAL_VID, 72 * 37, 37), (STRIP_VID, 17, 1)]
    config = {
        "configuration_version": CONFIGURATION_VERSION,
        "devices": [
            {"id": vid, "type": "dummy",
             "config": {"name": vid, "pixel_count": n}}
            for vid, n, _rows in pairs],
        "virtuals": [
            {"id": vid, "is_device": vid, "auto_generated": False,
             "config": {"name": vid, "mapping": "span", "rows": rows},
             "segments": [[vid, 0, n - 1, False]]}
            for vid, n, rows in pairs],
    }
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(config, f)


def _engine(clock):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now, curve_profiles=lambda: {})
    return executor, conductor, responder


def _scalar_params(entry) -> dict:
    """The entry's own authored params with each ValueBinding collapsed to
    its fallback — enough to attach a real effect instance; binding
    resolution itself is the compiler's spec, not this one's."""
    out = {}
    for key, val in (entry.params or {}).items():
        if isinstance(val, dict):
            val = val.get("fallback")
        if hasattr(val, "fallback"):
            val = val.fallback
        if val is not None and not isinstance(val, dict):
            out[key] = val
    return out


async def section_3_to_5(scene, tmp_dir: str) -> None:
    from fx.effects.fireworks1d import PAYOFF_LIFE as PAYOFF_LIFE_1D
    from spectra.services import scene_response as sr

    print("§3 line up: real fires land on the real pipeline at his shapes")
    entry_2d = next(d for d in scene.devices if d.effect_type == "fireworks")
    entry_1d = next(d for d in scene.devices if d.effect_type == "fireworks1d")
    cfg_2d = _scalar_params(entry_2d)
    cfg_1d = _scalar_params(entry_1d)
    _check(cfg_1d.get("max_blobs") == 6,
           f"his real strip config caps density at max_blobs="
           f"{cfg_1d.get('max_blobs')} — the cap the burst must beat")

    _two_virtual_config(tmp_dir)
    headless.silence_audio()
    host = FxHost(tmp_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    try:
        crystal = host.virtuals.get(CRYSTAL_VID)
        strip = host.virtuals.get(STRIP_VID)
        with headless.fake_clock() as clock:
            fx2d = headless.attach_effect(host, crystal, "fireworks", cfg_2d)
            fx1d = headless.attach_effect(host, strip, "fireworks1d", cfg_1d)
            executor, conductor, responder = _engine(clock)
            conductor.on_scene_fire(scene, [
                {"virtual_id": CRYSTAL_VID, "effect_type": "fireworks",
                 "config": dict(cfg_2d), "entry_id": entry_2d.id,
                 "color_mode": "set"},
                {"virtual_id": STRIP_VID, "effect_type": "fireworks1d",
                 "config": dict(cfg_1d), "entry_id": entry_1d.id,
                 "color_mode": "set"},
            ])

            def frames(n: int) -> None:
                for _ in range(n):
                    headless.render_frames(crystal, 1, clock=clock, dt=0)
                    headless.render_frames(strip, 1, clock=clock, dt=1 / 60)

            # the scene's own standard show, already flying
            frames(2)
            fx1d._spawn_firework()
            fx2d._spawn_burst(12)
            own_1d, own_2d = fx1d.n, fx2d.n
            own_life = fx1d.f_life[:own_1d].copy()
            own_grad = fx1d.f_grad[:own_1d].copy()
            own_age = fx1d.f_age[:own_1d].copy()

            expected = []
            for probe in (0.2, 0.5, 0.9):     # one fire per energy band
                rockets = sr.firework_burst_rockets(probe)
                pre_1d, pre_2d = fx1d.n, fx2d.n
                record = await responder.on_event("flare", probe)
                info = record.get("firework_burst")
                _check(info is not None and info["rockets"] == rockets
                       and info["virtuals"] == 2,
                       f"band fire at {probe}: {rockets} rockets to both "
                       "fireworks virtuals")
                frames(2)   # frame 1 lands the 1ms jump; frame 2 spawns
                _check(fx1d.n == pre_1d + rockets * 4,
                       f"  strip: +{rockets * 4} payoff particles within "
                       "two frames (2 staggered pairs x2 per rocket, past "
                       "max_blobs=6)")
                # per-rocket size follows the LIVE burst_size — his own
                # band patch kinds ("Flare patch …" set burst_size 6/9/14)
                # land in the same fire, before the burst, so a
                # high-intensity burst's rockets are bigger, exactly as
                # the real drop payoff's own would be after that patch
                per_rocket_2d = max(int(round(fx2d.burst_size * 2.5)), 24)
                _check(fx2d.n == pre_2d + rockets * per_rocket_2d,
                       f"  crystal: +{rockets * per_rocket_2d} payoff "
                       f"particles within two frames ({rockets} giant "
                       f"bursts x {per_rocket_2d} at the band-patched "
                       f"burst_size={fx2d.burst_size})")
                _check(fx1d._config["burst_rockets"] == 0
                       and fx2d._config["burst_rockets"] == 0,
                       "  key self-reset to 0 — next fire will edge again")
                expected.append(rockets)

            print("§4 on top of the standard ones — his show never breaks")
            _check((fx1d.f_life[:own_1d] == own_life).all()
                   and (fx1d.f_grad[:own_1d] == own_grad).all(),
                   "the scene's own particles: same lives, same colours, "
                   "still first in the buffer")
            _check((fx1d.f_age[:own_1d] > own_age).all(),
                   "…and still aging normally — never restarted or reset")
            _check(fx1d._phase == "none" and fx2d._phase == "none",
                   "phase choreography state untouched by every burst")
            new_1d = fx1d.f_life[own_1d:fx1d.n]
            _check(float(new_1d.min()) >= cfg_1d.get("burst_life", 1.2)
                   * PAYOFF_LIFE_1D * 0.8 - 1e-6,
                   "burst particles carry the payoff's own stretched "
                   "lives (PAYOFF_LIFE) — his drop-payoff look, not an "
                   "ordinary launch")

            print("§5 three consecutive band fires all landed "
                  f"(edge re-arms): rockets per fire = {expected}")
    finally:
        facade.set_host(None)
        await host.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    from spectra import config as scfg
    parser.add_argument("--scenes-file", type=Path, default=scfg.SCENES_FILE,
                        help="SPECTRA scenes store to READ (never written)")
    args = parser.parse_args()

    section_1_numbers()
    scene = section_2_scene(args.scenes_file)
    with tempfile.TemporaryDirectory() as tmp:
        cats = Path(tmp) / "device_categories.json"
        cats.write_text(json.dumps({
            "c1": {"id": "c1", "name": "Matrix", "parent_id": None,
                   "virtuals": [CRYSTAL_VID], "effects": ["fireworks"],
                   "role": None},
            "c2": {"id": "c2", "name": "Strips", "parent_id": None,
                   "virtuals": [STRIP_VID], "effects": ["fireworks1d"],
                   "role": None}}))
        device_model.CATEGORIES_FILE = cats
        asyncio.run(section_3_to_5(scene, os.path.join(tmp, "host")))
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
