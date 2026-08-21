#!/usr/bin/env python3
"""Real-fixture proof for the UPDATE-effect placeholder (2026-08-20, his
ask: "make update scene act like a double intensity flare until we build
it out specifically" — spectra/services/scene_response.py's on_update).

What this closes: the minimum dwell (shipped 2026-08-20) defers a scene
change to engine.fire_scene_update_event, which calls on_update. The
ORIGINAL on_update fired only the active scene's named, type="permanent"
SceneV2.update_kind — and 8 of his 9 real scenes have no update_kind
authored (checked below, against his real data), so almost every deferred
dwell held with NOTHING VISIBLE HAPPENING. on_update now doubles the given
intensity and runs it through the SAME band-selection + kind-execution a
genuine "flare" ResponseClass fire already uses (_execute_band, shared
with on_event) — no new authoring, works on every scene that already has
a Flare response.

A harness alone doesn't prove this closes the real gap (AGENTS.md: "a
passing suite proves nothing about his room" — tonight's own crash and the
inert flare-preview shipped past every check). So this script:

  1. Reads his REAL scene library (his primary checkout, NEVER this
     worktree's own gitignored storage/spectra/ copy — AGENTS.md's own
     warning on that point), read-only, to show the actual precondition:
     how many of his 9 real scenes have update_kind authored (the OLD
     mechanism's only path to visibility) vs. how many have a "flare"
     response the NEW mechanism can use.
  2. Fires on_update against a REAL scene ("Black Hole V2") on the real,
     unmodified production ResponseEngine/DriftConductor/FacadeExecutor
     over fx.headless's vendored render pipeline (real blackhole1d effect,
     real device_model registry) — proving an actual write lands on a
     real effect config, not just that a record dict looks right.
  3. Proves the doubling changes behaviour, not just a number: his real
     band edges (0/0.35/0.7/1.0) mean intensity 0.4 (a plausible dwell
     intensity) lands in the MIDDLE band un-doubled but the TOP band
     (which also carries a MOMENTARY gain kind) once doubled to 0.8 —
     exercising the exact release-scheduling fix made to
     engine.fire_scene_update_event alongside on_update itself.
  4. Proves the accepted clamp: intensity >= 0.5 doubles past 1.0 and
     lands exactly at 1.0, never higher.

No live storage write, no LedFX I/O, no audio hardware — fx.headless's
offline dummy device and a temp SPECTRA_STORAGE/device-category file only.
GETs (reads) only against his real checkout's storage/spectra/scenes.json.
Run from repo root: .venv/bin/python scripts/check_update_effect_double_intensity.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from random import Random

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REAL_SCENES = Path("/home/javi/SpotFX/storage/spectra/scenes.json")

td = Path(tempfile.mkdtemp(prefix="spectra-update-effect-"))

from fx import device_model  # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import facade, headless  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402
from spectra.models.sequencer import SequencerConfig  # noqa: E402
from spectra.services import color_journey as cj  # noqa: E402
from spectra.services.drift_conductor import DriftConductor  # noqa: E402
from spectra.services.fx_executor import FacadeExecutor  # noqa: E402
from spectra.services.room_controls import RoomControlState  # noqa: E402
from spectra.services.scene_response import (DICE_REROLL_GLIDE_MS,
                                              ResponseEngine)

VID = "Strips"


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def _run(coro):
    return asyncio.run(coro)


def _load_real_scenes() -> dict:
    if not REAL_SCENES.is_dir() and not REAL_SCENES.is_file():
        raise SystemExit(f"real scene fixture not found: {REAL_SCENES}")
    return json.loads(REAL_SCENES.read_text())


def _engine(clock):
    """Same production wiring test_spectra_engine.py's _engine() helper
    uses (executor swapped for the S3 delta) — no colour-set selector
    configured (empty color_set_entries), so a scene's attached "Colour
    Jump" kind returns "selector_unconfigured" and never touches the
    room/eligible-sets machinery this script doesn't set up."""
    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0,
        drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: cj.RoomColorState(),
        room_save=lambda st: None,
        set_position=lambda sid: None,
        set_cards=lambda: [],
        sequencer_config=lambda: SequencerConfig(),
        gradient_profiles=lambda: {},
        room_controls=lambda: RoomControlState(),
        rng=Random(2026))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(2026),
        clock=lambda: clock.now,
        sequencer_config=lambda: SequencerConfig(),
        curve_profiles=lambda: {},
        eligible_sets=lambda sc: {},
        room_load=lambda: cj.RoomColorState(),
        room_save=lambda st: None)
    return executor, conductor, responder


def part1_real_library_precondition(scenes: dict) -> SceneV2:
    print("== Part 1: the real precondition (9 of his real scenes) ==")
    with_update_kind = 0
    with_flare_response = 0
    black_hole = None
    for raw in scenes.values():
        scene = SceneV2(**raw)
        if scene.update_kind is not None:
            with_update_kind += 1
        if scene.responses.get("flare") is not None:
            with_flare_response += 1
        if scene.name == "Black Hole V2":
            black_hole = scene
    print(f"  scenes: {len(scenes)}  "
          f"with update_kind authored: {with_update_kind}  "
          f"with a 'flare' response: {with_flare_response}")
    check(black_hole is not None, "'Black Hole V2' present in his real library")
    check(black_hole.update_kind is None,
          "Black Hole V2 has NO update_kind authored — the OLD on_update "
          "would have looked this up, found nothing, and done nothing")
    check(with_update_kind < len(scenes),
          "most of his real scenes have no update_kind — the OLD "
          "mechanism's coverage gap, confirmed against real data")
    check(with_flare_response == len(scenes),
          "every one of his real scenes has a 'flare' response the NEW "
          "placeholder can use — nothing new to author")
    print()
    return black_hole


async def part2_real_write_lands(scene: SceneV2) -> None:
    print("== Part 2: a real write lands on his real Black Hole V2 scene ==")
    strips_dev = next(d for d in scene.devices if d.target == VID)
    check(strips_dev.effect_type == "blackhole1d",
          "Strips device is blackhole1d, matching his real scene")

    host = await headless.start_headless_host(
        str(td / "update-effect"), device_id=VID)
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    try:
        with headless.fake_clock() as clock:
            baseline = {"spawn_rate": 1.0, "beat_burst": 2.0, "brightness": 1.0}
            effect = headless.attach_effect(host, virtual, "blackhole1d",
                                            dict(baseline))
            executor, conductor, responder = _engine(clock)
            conductor.on_scene_fire(scene, [{
                "virtual_id": VID, "effect_type": "blackhole1d",
                "config": dict(baseline), "entry_id": strips_dev.id,
                "color_mode": "set"}])

            # His real band edges: [0, 0.35), [0.35, 0.7), [0.7, 1.0].
            # 0.4 lands MIDDLE un-doubled; doubled to 0.8 it lands TOP —
            # the band that also carries a MOMENTARY gain kind.
            record = await responder.on_update(0.4)
            check(record["class"] == "update", "record still labelled 'update'")
            check(record["intensity"] == 0.4, "records the ORIGINAL intensity")
            check(record["doubled_intensity"] == pytest_approx(0.8),
                  "doubles it to 0.8")
            check(record["result"] == "applied",
                  "a real band was selected and executed — not a no-op")
            check(record["band"] == {"intensity_min": 0.7, "intensity_max": 1.0},
                  "the TOP band fired — 0.4 alone would have picked the "
                  "MIDDLE band; only the doubled 0.8 reaches this one")

            kind_names = {k["name"] for k in record["kinds"]}
            check("Flare patch 0.7–1" in kind_names,
                  "the top band's permanent patch kind executed")
            check("Flare gain 0.7–1" in kind_names,
                  "the top band's MOMENTARY gain kind executed too")

            # Nothing lands on the render pipeline until frames advance
            # past the glide — a real glide, not a same-frame snap.
            check(effect._config["spawn_rate"] == 1.0,
                  "not yet landed one frame before the glide completes")
            glide_frames = int(DICE_REROLL_GLIDE_MS / 1000 / (1 / 60)) + 2
            headless.render_frames(virtual, glide_frames, clock=clock, dt=1 / 60)
            check(effect._config["spawn_rate"] == pytest_approx(2.0),
                  "spawn_rate landed at the patch's declared 2.0")
            check(effect._config["beat_burst"] == pytest_approx(6.0),
                  "beat_burst landed at the patch's declared 6.0")

            # The momentary gain kind pends a release — this is exactly
            # what engine.fire_scene_update_event now schedules
            # (pending_hold_groups/_release_after_hold) that the ORIGINAL
            # on_update never needed to, because it only ever fired
            # permanent kinds.
            check(responder.pending_hold_groups() != [],
                  "a momentary release is pending after firing — the real "
                  "reason fire_scene_update_event now schedules releases")
            released = await responder.flush_releases()
            check(released >= 1, "the pending brightness spike releases")
            headless.render_frames(virtual, 200, clock=clock, dt=1 / 60)
            check(effect._config["brightness"] == pytest_approx(1.0),
                  "brightness eased back to the carried baseline after release")

            print("  -> a deferred dwell on his real Black Hole V2 scene "
                  "now visibly flares: spawn_rate 1.0->2.0, beat_burst "
                  "2.0->6.0, plus a brightness spike-and-release — where "
                  "the OLD mechanism produced zero writes.\n")
    finally:
        facade.set_host(None)
        await host.shutdown()


async def part3_clamp(scene: SceneV2) -> None:
    print("== Part 3: the accepted clamp — double never exceeds 1.0 ==")
    with headless.fake_clock() as clock:
        _, conductor, responder = _engine(clock)
        conductor.on_scene_fire(scene, [])
        for raw in (0.5, 0.6, 0.9, 1.0):
            record = await responder.on_update(raw)
            check(record["doubled_intensity"] == 1.0,
                  f"intensity {raw} doubles-and-clamps to 1.0, not {raw * 2}")
    print()


def pytest_approx(x, tol=1e-6):
    class _Approx:
        def __eq__(self, other):
            return abs(other - x) <= tol
    return _Approx()


def main() -> None:
    scenes = _load_real_scenes()
    black_hole = part1_real_library_precondition(scenes)
    _run(part2_real_write_lands(black_hole))
    _run(part3_clamp(black_hole))
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
