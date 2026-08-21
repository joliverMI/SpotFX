"""One-time migration: declare a "Colour Rotate & Back" FlareKind on every
scene — his ask, verbatim: "similar to the reverse flare, make a color
rotate and back flare that rotates the colors of the foreground by a
number of degrees that scales with intensity. at 0 intensity, rotate 60
degrees. at 1 intensity, rotate 180 degrees. It should reach the full
rotation at the trigger point. It then dwells for an amount also tied to
intensity: at 0, it dwells 1000ms and at 1 it dwells 400ms. Ramp up is
similarly scaled, 0 intensity it is 1000ms, 1 is 250ms. fade back with 1.5
times the ramp times for each. it should be at all levels, and should be a
color flare and concur with some shape flares."

UNLIKE THE REVERSE FLARE, THIS IS NOT EFFECT-SCOPED. `reverse` only exists
as a param on blackhole/orbits/squiggles, so that migration named three
scenes explicitly. This kind targets `state.gradient` — the live
FOREGROUND colour every SET-MODE virtual carries, regardless of which
effect is running (config/effect_params.json has no bearing on it at all;
`gradient` is a scene colour assignment, never a per-effect registry
param) — so there is no natural "only applies to N effects" narrowing the
way there was for reverse. His own scope word is unqualified plural,
"declare it on the scenes," not a named subset — so this script targets
EVERY scene in the store, not a hand-picked list.

ALL FOUR SCALED QUANTITIES ARE COMPUTED, NEVER AUTHORED: rotation degrees,
ramp-in ms, dwell ms, and fade-back ms all come from the fire's own
intensity via spectra/services/scene_response.py's color_rotate_* family
(COLOR_ROTATE_DEG_GENTLE=60/HARD=180, _RAMP_MS_GENTLE=1000/HARD=250,
_DWELL_MS_GENTLE=1000/HARD=400, _FADE_FACTOR=1.5x the ramp) — his own
numbers, exact. FlareKind.type="color_rotate" therefore carries no
jump/params/gain/hold_ms of its own (the model rejects any); this script
declares the kind with nothing but a name and a type.

ANCHORING IS THE FLARE RULE, NOT THE DROP RULE: his own words, "it should
reach the full rotation at the trigger point" — the ramp-in ENDS on the
mark, same as a momentary flare's first switch (not a drop, which STARTS
on the mark). trigger_engine._response_switch_lead_ms now takes the max of
the existing dice-glide lead and scene_response.color_rotate_lead_ms (a
NEW, separate function — this kind's ramp is intensity-scaled, so it can't
share the dice-reroll glide's single fixed DICE_REROLL_GLIDE_MS constant)
— once this kind is attached to a band, the trigger engine will fire it
early by exactly its own ramp_ms so the completed rotation lands on the
mark. Proven, not asserted: scripts/check_color_rotate.py and
tests/test_color_rotate.py.

DECLARED, NEVER ATTACHED — HIS DATA, HIS CALL (matching every prior
FlareKind migration in this codebase): a scene's flare_kinds list is
scoped, agent-writable data (scene_console.apply_flare_kind); a band's
kinds map is his own authored attachment, changed only through the Scenes
page's Lane Rack. This script only ever calls apply_flare_kind — it never
touches responses/bands on any scene.

Same production write path as scripts/add_momentary_reverse_flares.py
(scene_console.apply_flare_kind — full validation, a verified pre-write
backup, idempotent by name). Dry-run by default; --apply performs the
write. Not run against live storage by this build — an operator/deploy
step, same convention as every other migration script here.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra.models.scene import FlareKind
from spectra.services import scene_console, scene_store

KIND_NAME = "Colour Rotate & Back"

NEW_KIND = {
    "name": KIND_NAME,
    "type": "color_rotate",
    "jump": None,
    "params": {},
    "gain": 1.0,
    "hold_ms": None,
}


def _normalized(kind: dict) -> dict:
    """FlareKind's own model_dump shape — normalizing NEW_KIND's terse
    literal through the model before comparing against a scene's own
    already-normalized dumps, so a real match isn't mistaken for a shape
    drift (same convention as add_momentary_reverse_flares.py)."""
    return FlareKind.model_validate(kind).model_dump(mode="json")


async def _apply(scene_id: str, kind: dict) -> dict:
    return await scene_console.apply_flare_kind(
        scene_id,
        name=kind["name"], type=kind["type"], jump=kind["jump"],
        params=kind["params"], gain=kind["gain"], hold_ms=kind["hold_ms"],
        source="script:add_color_rotate_flares")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--force", action="store_true",
                        help="re-apply even if a kind with the same name already exists "
                             "on a scene (overwrites that kind's shape — apply_flare_kind's "
                             "own update-by-name behaviour)")
    args = parser.parse_args()

    scenes = scene_store.list_all()
    if not scenes:
        print("no scenes in the store — nothing to do")
        return

    norm = _normalized(NEW_KIND)
    to_apply: list[tuple[str, str, dict]] = []  # (scene_id, scene_name, kind)
    for scene in scenes:
        existing = {k.name: k.model_dump(mode="json") for k in scene.flare_kinds}
        already = existing.get(KIND_NAME)
        same_shape = already is not None and all(
            already.get(f) == norm[f] for f in ("type", "jump", "params", "gain", "hold_ms"))
        if same_shape:
            print(f"'{KIND_NAME}' already present on {scene.name!r}, identical shape — skipping")
            continue
        if already is not None and not args.force:
            print(f"'{KIND_NAME}' already exists on {scene.name!r} with a DIFFERENT shape "
                  f"— pass --force to overwrite it: {already}")
            continue
        to_apply.append((scene.id, scene.name, NEW_KIND))
        verb = "update" if already is not None else "create"
        print(f"would {verb} '{KIND_NAME}' (color_rotate) on {scene.name!r}")

    if not to_apply:
        print("nothing to do")
        return

    if not args.apply:
        print(f"\nDRY RUN — would apply {len(to_apply)} flare kind write(s) "
              "via scene_console.apply_flare_kind (use --apply). Each write is backed up "
              "first (scene_console._write_and_verify_backup) — declared only, "
              "never attached to a band; attach via the Scenes page's Lane Rack.")
        return

    async def _run() -> None:
        for scene_id, scene_name, kind in to_apply:
            result = await _apply(scene_id, kind)
            print(f"applied to {scene_name!r}: {result['summary']}")

    asyncio.run(_run())
    print(f"\ndone — {len(to_apply)} flare kind write(s) applied. "
          "Not attached to any band; attach via the Scenes page's Lane Rack "
          "when ready to fire them.")


if __name__ == "__main__":
    main()
