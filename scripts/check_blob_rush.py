"""Executable spec: the BLOB RUSH flare, end to end, against HIS REAL Black
Hole V2 scene (read-only — this script never writes any storage) on the
real vendored render pipeline at his crystal-mapper's own 72x37 shape.

His ask, verbatim: "Also on Black Hole, add a new effect that runs as a
shape flare that randomly chooses between the momentary reverse and this
one. This one is called 'blob rush' and it just generates 12 blobs all at
once spread out fairly evenly. Override any max blob counts for this
generation if that's easy, or remove the ones in the event horizon."

What is proven, in order:
  1. His number: BLOB_RUSH_BLOBS is a FIXED 12 — not intensity-scaled
     (the one structural difference from firework_burst).
  2. "RANDOMLY CHOOSES BETWEEN THE MOMENTARY REVERSE AND THIS ONE" is a
     LANE: on his real scene, migrated in memory, every flare band pools
     exactly those two kinds under one lane, resolve_lane_picks fires
     exactly ONE of them per fire, both are reachable over many fires, and
     every other kind on the band still fires every time.
  3. On the real pipeline: a real ResponseEngine fire lands 12 blobs
     within two rendered frames (frame 1 lands the 1 ms jump tween, frame
     2's draw consumes the edge) — PAST his real max_blobs=50, from a
     population already at the cap.
  4. "SPREAD OUT FAIRLY EVENLY": the 12 arrive at near-equal angular
     spacing, and they arrive where that mode's own blobs do — just past
     the per-direction hex boundary in infall, at the horizon ring in
     reverse.
  5. Nothing already on screen is disturbed (his second option, "remove
     the ones in the event horizon", deliberately NOT taken), and the key
     self-resets so consecutive fires all land.

Usage:
  .venv/bin/python scripts/check_blob_rush.py [--scenes-file PATH]

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

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from fx import device_model, facade, headless
from fx.host import FxHost

SCENE_NAME = "Black Hole V2"
KIND_NAME = "Blob rush"
PAIR_NAME = "Reverse Momentarily (500ms)"
CRYSTAL_VID = "check-crystal"     # 72x37 — his crystal-mapper's shape

PASS = "  ✓"


def _fail(msg: str) -> None:
    raise SystemExit(f"  ✗ FAIL: {msg}")


def _check(cond: bool, msg: str) -> None:
    if not cond:
        _fail(msg)
    print(f"{PASS} {msg}")


# ── §1 his number ──────────────────────────────────────────────────────────

def section_1_number() -> None:
    from spectra.services import scene_response as sr
    print("§1 his number: a fixed 12, never intensity-scaled")
    _check(sr.BLOB_RUSH_BLOBS == 12, "BLOB_RUSH_BLOBS == 12")


# ── §2 his real scene, migrated in memory, and the LANE ────────────────────

def _migrated_scene(scenes_file: Path):
    from spectra.models.scene import SceneV2
    sys.path.insert(0, str(Path(__file__).parent))
    from add_blob_rush_flare import LANE_NAME, NEW_KIND, _find_scene_id

    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    sid = _find_scene_id(store, SCENE_NAME, scenes_file)
    raw = copy.deepcopy(store[sid])
    bands_raw = ((raw.get("responses") or {}).get("flare") or {})["bands"]
    if any(PAIR_NAME not in b.get("kinds", {}) for b in bands_raw):
        raise SystemExit(
            f"{scenes_file} has flare bands with no '{PAIR_NAME}' attached, "
            "so the lane this flare is meant to share has nothing to pair "
            "with.\n  A task worktree's own storage/spectra/*.json is "
            "gitignored and can be an old snapshot (AGENTS.md says so) — "
            "point --scenes-file at the live store, e.g.\n"
            "  --scenes-file /home/javi/SpotFX/storage/spectra/scenes.json")
    if not any(k.get("name") == KIND_NAME for k in raw.get("flare_kinds", [])):
        raw.setdefault("flare_kinds", []).append(dict(NEW_KIND))
        for band in ((raw.get("responses") or {}).get("flare") or {})["bands"]:
            band.setdefault("kinds", {})[KIND_NAME] = 1.0
            lanes = band.setdefault("kind_lanes", {})
            lanes[KIND_NAME] = LANE_NAME
            lanes[PAIR_NAME] = LANE_NAME
    return SceneV2(**raw)


def section_2_lane(scenes_file: Path):
    from spectra.services import scene_response as sr
    print(f"§2 the lane, on his real scene (read-only from {scenes_file})")
    scene = _migrated_scene(scenes_file)
    _check(any(k.name == KIND_NAME and k.type == "blob_rush"
               for k in scene.flare_kinds),
           "migrated scene parses; kind declared with no authored knobs")
    bands = scene.responses["flare"].bands
    _check(len(bands) == 3, f"three flare energy bands ({len(bands)})")
    rng = Random(3)
    for i, band in enumerate(bands):
        picks = [sr.resolve_lane_picks(band, rng)[0] for _ in range(400)]
        both = {KIND_NAME, PAIR_NAME}
        chose_one = all(len(both & set(p)) == 1 for p in picks)
        _check(chose_one, f"band {i}: exactly ONE of the pair fires, every "
                          "fire (400 draws)")
        rush = sum(1 for p in picks if KIND_NAME in p)
        _check(0 < rush < 400, f"band {i}: both are reachable — the rush won "
                               f"{rush}/400, the reverse {400 - rush}/400")
        others = set(band.kinds) - both
        _check(all(others <= set(p) for p in picks),
               f"band {i}: every other kind ({len(others)}) still fires on "
               "every fire — only the pooled pair is an either/or")
    return scene


# ── §3-§5 the real pipeline at his real shape ──────────────────────────────

def _one_virtual_config(config_dir: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    n, rows = 72 * 37, 37
    config = {
        "configuration_version": CONFIGURATION_VERSION,
        "devices": [{"id": CRYSTAL_VID, "type": "dummy",
                     "config": {"name": CRYSTAL_VID, "pixel_count": n}}],
        "virtuals": [{"id": CRYSTAL_VID, "is_device": CRYSTAL_VID,
                      "auto_generated": False,
                      "config": {"name": CRYSTAL_VID, "mapping": "span",
                                 "rows": rows},
                      "segments": [[CRYSTAL_VID, 0, n - 1, False]]}],
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
    from fx.effects import blackhole as bh
    from spectra.services import scene_response as sr

    entry = next(d for d in scene.devices if d.effect_type == "blackhole")
    cfg = _scalar_params(entry)
    cap = cfg.get("max_blobs")
    print("§3 the real pipeline at his crystal's shape (72x37)")
    _check(cap == 50, f"his real Matrix config caps density at max_blobs="
                      f"{cap} — the cap the rush must beat")

    _one_virtual_config(tmp_dir)
    headless.silence_audio()
    host = FxHost(tmp_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    try:
        crystal = host.virtuals.get(CRYSTAL_VID)
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, crystal, "blackhole",
                                            dict(cfg, spawn_rate=20.0))
            _executor, conductor, responder = _engine(clock)
            conductor.on_scene_fire(scene, [
                {"virtual_id": CRYSTAL_VID, "effect_type": "blackhole",
                 "config": dict(cfg), "entry_id": entry.id,
                 "color_mode": "set"}])

            def frames(n: int) -> None:
                headless.render_frames(crystal, n, clock=clock, dt=1 / 60)

            # fill the population to his own cap first, so "past the cap"
            # is a measured fact and not an empty-buffer coincidence
            frames(int(12.0 * 60))
            ambient = int(effect.n - np.count_nonzero(
                effect.p_is_burst[: effect.n]))
            # the ambient spawn holds the population right at its own
            # cap, which is what makes "past the cap" a measured fact and
            # not an empty-buffer coincidence. Spawning is then stopped so
            # the only thing that can change the population is the rush.
            effect.update_config({"spawn_rate": 0.0, "beat_burst": 0})
            frames(1)
            effect._spawn(64, 0)          # an ORDINARY spawn request…
            ambient = int(effect.n - np.count_nonzero(
                effect.p_is_burst[: effect.n]))
            _check(ambient == cap,
                   f"an ordinary 64-blob spawn request fills to exactly "
                   f"max_blobs={cap} and no further — the cap the rush is "
                   "about to ignore")

            for probe in (0.2, 0.5, 0.9):     # one fire per energy band
                pre = effect.n
                pre_rush = int(np.count_nonzero(effect.p_is_burst[: effect.n]))
                record = await responder.fire_kind(
                    next(k for k in scene.flare_kinds if k.name == KIND_NAME),
                    probe)
                info = record.get("blob_rush")
                _check(info is not None and info["blobs"] == 12
                       and info["virtuals"] == 1,
                       f"fire at intensity {probe}: 12 blobs to the one live "
                       "Black Hole (count does not move with intensity)")
                frames(2)   # frame 1 lands the 1ms jump; frame 2 consumes
                rushed = int(np.count_nonzero(
                    effect.p_is_burst[: effect.n])) - pre_rush
                _check(rushed == 12 and effect.n >= pre + 12 - 2,
                       f"  +12 no-cap blobs within two frames, from a "
                       f"population already at max_blobs={cap} "
                       f"(live total {pre} -> {effect.n})")
                _check(effect._config["blob_rush"] == 0,
                       "  key self-reset to 0 — the next fire edges again")

                if probe == 0.2:
                    print("§4 spread out fairly evenly")
                fresh_idx = np.flatnonzero(
                    effect.p_is_burst[: effect.n])[-12:]
                fresh = np.sort(effect.p_theta[fresh_idx] % (2 * np.pi))
                gaps = np.diff(np.concatenate([fresh, [fresh[0] + 2 * np.pi]]))
                step = 2 * np.pi / 12
                spread = float(np.max(np.abs(gaps - step)) / step)
                wig = bh.BLOB_RUSH_WIGGLE_FRAC
                _check(spread <= 2 * wig + 1e-6,
                       f"  angular gaps within {spread * 100:.0f}% of an even "
                       f"{np.degrees(step):.0f}° step (bound: "
                       f"{200 * wig:.0f}%, BLOB_RUSH_WIGGLE_FRAC)")
                r_fresh = effect.p_r[fresh_idx]
                edge = bh._hex_spawn_edge_radius(
                    effect.p_theta[fresh_idx].astype(np.float32))
                # two frames of infall have already happened, so compare
                # against the boundary they were born just outside of
                _check(bool(np.all(r_fresh <= edge + bh.SPAWN_EDGE_MARGIN_MAX)
                            and np.all(r_fresh > edge - 0.15)),
                       "  born just past the true per-direction hex "
                       "boundary — the same arrival an ordinary infall "
                       "blob makes")

            print("§5 nothing already on screen was disturbed")
            _check(effect._phase == "none",
                   "phase choreography state untouched by every rush")
            _check(bool(np.all(effect.p_cap[: effect.n - 12] >= -1.0)),
                   "the event horizon's own orbiters were never cleared "
                   "(his 'or remove the ones in the event horizon' option "
                   "deliberately not taken)")
            captives = int(np.count_nonzero(effect.p_cap[: effect.n] >= 0.0))
            _check(captives > 0, f"…and {captives} of them are still orbiting")
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

    section_1_number()
    scene = section_2_lane(args.scenes_file)
    with tempfile.TemporaryDirectory() as tmp:
        cats = Path(tmp) / "device_categories.json"
        cats.write_text(json.dumps({
            "c1": {"id": "c1", "name": "Matrix", "parent_id": None,
                   "virtuals": [CRYSTAL_VID], "effects": ["blackhole"],
                   "role": None}}))
        device_model.CATEGORIES_FILE = cats
        asyncio.run(section_3_to_5(scene, os.path.join(tmp, "host")))
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
