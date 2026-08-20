#!/usr/bin/env python3
"""Read-only, real-data proof for the light-mode background-clear fix (PR
fm/spectra-light-mode-clear-to-mode-bg, his ruling "do option three").

Defect: in "light" mode, Light paints its forced background ONCE
(dark_light.py's reconcile write) and never re-asserts it; every later
colour-set-driven scene fire writes its own background over it, and 30
entries across 22 of his real colour sets author literal #000000, which in
overwrite mode clears whatever Light just painted and it never comes back
(his report: effects "start with a background color appropriately and then
go dark"). Fix: room_controls.resolve_authored_bg_color substitutes the
room's own Light colour (display_light_bg_color) for an authored #000000,
but ONLY in "light" mode — "default" (hybrid)/"dark" are untouched.

This drives the real, unmodified scene_compiler.compile_scene/fire_scene
against a READ-ONLY copy of his real storage — the primary checkout
(/home/javi/SpotFX), never this worktree's own gitignored copy (see
AGENTS.md's "A worktree's own storage/spectra/*.json is gitignored and
untracked" warning) — picking a real (colour set, scene) pair: "Black Hole
- Blue" (one of the 22 black-authoring sets, Matrix-scoped) fired onto
"Black Hole V2" (one of his three named effects, `blackhole`, on the
Matrix category -> crystal-mapper).

The pass mark (his own words):
  1. In LIGHT mode, background_color reaching the wire is his light-mode
     colour (display_light_bg_color, currently #7800be) rather than
     #000000.
  2. The same fire in HYBRID still carries #000000.

Also reports back on "Calm - Purple"/"Calm - Cyan" (his crystal
background-brightness-authority note from tonight's carry-forward deploy):
neither authors literal #000000 (both author #ff9940), so this fix's
substitution never touches them — confirmed against real storage, not
assumed.

Write points #3/#4/#5 (scene_response._color_jump, drift_conductor.
apply_color_set/_journey_leg) are proven in tests/test_light_mode_bg_clear.py
against a RecordingExecutor (no live storage needed there — response/drift
engine mechanics, not colour-set data). This script is the real-data half.

Never touches live storage or a live instance — GET-only file reads,
nothing here writes anything, ever.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from spectra.models.scene import SceneV2  # noqa: E402
from spectra.services.binding_resolver import FireContext  # noqa: E402
from spectra.services.color_sets import ColorSetCard  # noqa: E402
from spectra.services.scene_compiler import compile_scene, resolve_scene  # noqa: E402

REAL_COLOR_SETS = Path("/home/javi/SpotFX/storage/color_sets.json")
REAL_SCENES = Path("/home/javi/SpotFX/storage/spectra/scenes.json")

BLACK_HOLE_BLUE_ID = "6b7d1a80-42f5-44e8-9583-b4d0b5874a1d"
BLACK_HOLE_V2_ID = "e9b44a88-77b9-4eb9-ae2a-859d3ecd6dc1"
CALM_PURPLE_ID = "15a767a0-13ae-451e-bca2-185aafca7e3e"
CALM_CYAN_ID = "a56aeb74-4c52-4c76-867f-120f7bf97f39"
CRYSTAL = "crystal-mapper"

# His real room_controls.json tonight (storage/spectra/room_controls.json,
# primary checkout): display_mode="light", display_light_bg_color="#7800be".
LIGHT_BG = "#7800be"


def _real_pair() -> tuple[ColorSetCard, SceneV2]:
    color_sets = json.loads(REAL_COLOR_SETS.read_text())
    card = ColorSetCard(**color_sets[BLACK_HOLE_BLUE_ID])
    assert card.name == "Black Hole - Blue"
    matrix_entry = next(e for e in card.entries if "Matrix" in e.scope.categories)
    assert matrix_entry.bg_color == "#000000", \
        "precondition: this entry must author a literal black background"

    scenes = json.loads(REAL_SCENES.read_text())
    scene = SceneV2(**scenes[BLACK_HOLE_V2_ID])
    assert scene.name == "Black Hole V2"
    matrix_dev = next(d for d in scene.devices if d.target == "Matrix")
    assert matrix_dev.effect_type == "blackhole", \
        "expected one of his three named effects (fireworks/blackhole/squiggles)"
    return card, scene


def part1_main_path() -> None:
    print("== Part 1: scene_compiler.compile_scene -- write points #1/#2 (main path) ==")
    card, scene = _real_pair()
    resolved = resolve_scene(scene, FireContext(0.5, rng=Random(20260820)))

    light_writes = compile_scene(resolved, card, display_mode="light",
                                 light_bg_color=LIGHT_BG)
    light_write = next(w for w in light_writes if w["virtual_id"] == CRYSTAL)
    print(f"  LIGHT  mode -> {CRYSTAL} background_color = "
          f"{light_write['config']['background_color']!r}")
    assert light_write["config"]["background_color"] == LIGHT_BG, \
        f"expected his light-mode colour {LIGHT_BG!r}"

    hybrid_writes = compile_scene(resolved, card, display_mode="default",
                                  light_bg_color=LIGHT_BG)
    hybrid_write = next(w for w in hybrid_writes if w["virtual_id"] == CRYSTAL)
    print(f"  HYBRID mode -> {CRYSTAL} background_color = "
          f"{hybrid_write['config']['background_color']!r}")
    assert hybrid_write["config"]["background_color"] == "#000000", \
        "hybrid must be byte-identical to before this fix"
    print(f"  -> CONFIRMED: real 'Black Hole - Blue' onto real 'Black Hole V2' "
          f"({light_write['effect_type']} effect) -- LIGHT substitutes his "
          f"room's Light colour; HYBRID still carries #000000.\n")


async def part1b_fire_scene_entry_point(tmp_dir: str) -> None:
    """The actual production API entry point (fire_scene), not just
    compile_scene directly -- proves the room_controls load this fix adds
    to fire_scene threads display_mode/display_light_bg_color through.
    dry_run=True throughout: never touches fx_seam, never reaches a wire."""
    print("== Part 1b: scene_compiler.fire_scene (dry-run) -- the real API entry point ==")
    from spectra import config as scfg
    from spectra.services import scene_compiler

    card, scene = _real_pair()
    orig = scfg.ROOM_CONTROLS_FILE
    try:
        for mode, expect in (("light", LIGHT_BG), ("default", "#000000")):
            path = Path(tmp_dir) / f"room_controls_{mode}.json"
            path.write_text(json.dumps({"display_mode": mode,
                                        "display_light_bg_color": LIGHT_BG}))
            scfg.ROOM_CONTROLS_FILE = path
            result = await scene_compiler.fire_scene(
                scene, intensity=0.5, color_set=card, dry_run=True,
                rng=Random(20260820))
            write = next(w for w in result["writes"] if w["virtual_id"] == CRYSTAL)
            print(f"  {mode:8} -> {CRYSTAL} background_color = "
                  f"{write['config']['background_color']!r}")
            assert write["config"]["background_color"] == expect
    finally:
        scfg.ROOM_CONTROLS_FILE = orig
    print("  -> CONFIRMED at the real fire_scene entry point "
          "(dry_run=True throughout -- DO NOT DEPLOY; nothing here reached "
          "fx_seam or a live wire).\n")


def part2_calm_sets_not_moved_again() -> None:
    print("== Part 2: report-back -- did this fix move 'Calm - Purple'/'Calm - "
          "Cyan' again? ==")
    from spectra.services import room_controls as rc

    color_sets = json.loads(REAL_COLOR_SETS.read_text())
    for set_id, label in ((CALM_PURPLE_ID, "Calm - Purple"),
                          (CALM_CYAN_ID, "Calm - Cyan")):
        card = ColorSetCard(**color_sets[set_id])
        assert card.name == label
        entry = card.entries[0]
        resolved_light = rc.resolve_authored_bg_color(
            entry.bg_color, "light", LIGHT_BG)
        moved = resolved_light != entry.bg_color
        print(f"  {label:14} authors bg_color={entry.bg_color!r} "
              f"background_brightness={entry.background_brightness!r} "
              f"-> resolve_authored_bg_color(light) = {resolved_light!r} "
              f"({'MOVED AGAIN' if moved else 'unaffected'})")
        assert not moved, (
            f"{label} authors {entry.bg_color!r}, not literal #000000 -- "
            "this fix's substitution only ever triggers on an exact "
            "authored black, so it must be a no-op here")
    print("  -> CONFIRMED: neither authors a literal #000000 (both author "
          "#ff9940) -- this fix does NOT move their brightness authority "
          "again. Reporting back as asked, not just asserting it.\n")


async def main() -> None:
    part1_main_path()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        await part1b_fire_scene_entry_point(tmp_dir)
    part2_calm_sets_not_moved_again()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
