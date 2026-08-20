"""One-time migration: declare a "Reverse Momentarily (500ms)" FlareKind on
Black Hole V2, Orbits V2, and Squiggles V2 — his ask, verbatim: "add a
momentary flare that runs at all intensity levels to black hole, orbits,
and squiggles. it toggles the reverse parameter for 500ms and then
switches back."

MOMENTARY, ANCHORED LIKE ANY OTHER FLARE — NOT A DROP: he confirmed
momentary flares anchor the END of their first switch to the trigger
mark, then hold, then flip back — the same shape every other momentary
kind in this codebase already uses (see FlareKind's own docstring,
spectra/models/scene.py). This is NOT start-anchored like a drop; crossing
those two rules was the single most likely way to build this wrong, so
this script does not touch anchoring at all — hold_ms=500 on a `momentary`
kind already gets the right anchor for free from trigger_engine's existing
lead-time machinery (transition_phases.py), same as STAR's own
"Reverse Momentarily (500ms)" kind (scripts/add_star_reverse_flares.py).

`reverse` MEANS SOMETHING DIFFERENT ON EACH EFFECT (config/effect_params.json):
  squiggles — "Flip travel: every chain turns around and retraces its path"
  orbits    — flips spin_sign (rotation direction)
  blackhole — reverse=False is INFALL MODE; reverse=True flies blobs
              OUTWARD instead of inward — a fundamental behaviour
              inversion, not a direction flip, and by far the most
              dramatic of the three.

FLAG (not resolved here — his own instruction: say so rather than let him
discover it in his room): Black Hole's flare_kinds already include
charge/lull/drop-driven phase choreography (the vendored blackhole.py
swallow/build machinery scene_response._drive_phase arms) alongside this
new momentary reverse. A 500ms OUTWARD burst firing mid-implosion (e.g.
during a charge build or right on a drop) will visually fight the
choreography's own inward pull for that half-second — neither this script
nor the underlying mechanism gates one against the other. Whether that's
wanted (a dramatic accent) or unwanted (visual noise) is a room judgment
call, best made watching it live once band-attached, not by us muting it.

ALL INTENSITY LEVELS — DECLARED, NOT BAND-ATTACHED, MATCHING PRECEDENT:
scene_console.apply_flare_kind's write surface only ever touches
flare_kinds, never responses/band.kinds — a HARD SCOPE BOUNDARY
(spectra/services/scene_console.py's own docs), not a missed step; band
attachment is the Scenes page's own Lane Rack drag-to-attach action
(FlareLaneRack.tsx), a human decision, same as every other named kind in
this codebase (STAR's own two reverse kinds shipped the same way — see
scripts/add_star_reverse_flares.py). "Runs at all intensity levels" is
therefore a build constraint on the KIND itself, not something this script
enforces by band: the kind carries no intensity gate of its own (no
`display_availability`/mode check, no scale-dependent behaviour beyond the
absolute target every band scale=1.0 already lands verbatim) — attaching
it to every one of a scene's existing flare bands (so it fires regardless
of which band the trigger's intensity falls in) is the one remaining step,
left for Javi via the Lane Rack, same as every other kind here.

TOGGLE-PARAM CORRECTNESS (found and fixed alongside this script, NOT a
pre-existing capability): `reverse` is a `type: "toggle"` param
(config/effect_params.json) and ParamTarget.value is a plain float field —
an authored True/False silently coerces to 1.0/0.0 (spectra/models/scene.py),
which the real effect's CONFIG_SCHEMA (`bool` exactly, voluptuous, no
coercion) would then reject on write (fx/effects/__init__.py::
_apply_config, validate=True logs a warning and drops the whole write,
never raises — a flare that looked declared and attached but silently did
nothing). scene_response._compute_param_moves now special-cases
KIND_TOGGLE params to land a real bool, and drift_conductor.VirtualState.
param_baseline / scene_response._carried_value now track a toggle's bool
baseline (previously explicitly excluded — comment said "NUMERIC
baselines" by design) so the momentary release ALSO lands a real bool
back, not `None`-skipped. Proven end to end on the real vendored
`squiggles` effect: tests/test_spectra_engine.py::
test_momentary_toggle_param_flare_lands_a_real_bool_and_releases.

TARGET VALUE: absolute `True` on all three — the dramatic/notable state
per the effect table above (blackhole: infall→outward; orbits: flip spin;
squiggles: chains retrace), matching every one of these scenes' authored
Matrix-device baseline (`reverse: false` on Black Hole V2 / Squiggles V2's
Matrix entry). Orbits V2's Matrix `reverse` is itself dice-bound (a 50/50
signal="random" steps binding, storage/spectra/scenes.json) — an absolute
True target is sometimes a visual no-op when that fire's own dice already
landed True; ParamTarget has no "invert whatever the current baseline is"
mode (offset mode explicitly excludes bool baselines — unresolvable,
skipped, same as an unknown registry param), so a fixed absolute value is
the only expressible target, same limitation STAR's own reverse kinds
already accepted for `spin`.

Same production write path as scripts/add_star_reverse_flares.py
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

KIND_NAME = "Reverse Momentarily (500ms)"
TARGET_SCENE_NAMES = ["Black Hole V2", "Orbits V2", "Squiggles V2"]

NEW_KIND = {
    "name": KIND_NAME,
    "type": "momentary",
    "jump": None,
    "params": {"reverse": {"mode": "absolute", "value": True}},
    "gain": 1.0,
    "hold_ms": 500,
}


def _find_scene_id(name: str) -> str:
    matches = [s for s in scene_store.list_all() if s.name == name]
    if not matches:
        raise SystemExit(f"scene '{name}' not found — refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"scene '{name}' matches {len(matches)} scenes — refusing to guess which one")
    return matches[0].id


def _existing(scene_id: str) -> dict[str, dict]:
    scene = scene_store.get_by_id(scene_id)
    return {k.name: k.model_dump(mode="json") for k in scene.flare_kinds}


def _normalized(kind: dict) -> dict:
    """FlareKind's own model_dump shape (ParamTarget fills offset/lo/hi=None) —
    normalizing NEW_KIND's terse literal through the model before comparing
    against _existing()'s already-normalized dumps, so a real match isn't
    mistaken for a shape drift."""
    return FlareKind.model_validate(kind).model_dump(mode="json")


async def _apply(scene_id: str, kind: dict) -> dict:
    return await scene_console.apply_flare_kind(
        scene_id,
        name=kind["name"], type=kind["type"], jump=kind["jump"],
        params=kind["params"], gain=kind["gain"], hold_ms=kind["hold_ms"],
        source="script:add_momentary_reverse_flares")


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

    to_apply: list[tuple[str, str, dict]] = []  # (scene_id, scene_name, kind)
    for scene_name in TARGET_SCENE_NAMES:
        scene_id = _find_scene_id(scene_name)
        current = _existing(scene_id)
        already = current.get(KIND_NAME)
        norm = _normalized(NEW_KIND)
        same_shape = already is not None and all(
            already.get(f) == norm[f] for f in ("type", "jump", "params", "gain", "hold_ms"))
        if same_shape:
            print(f"'{KIND_NAME}' already present on {scene_name}, identical shape — skipping")
            continue
        if already is not None and not args.force:
            print(f"'{KIND_NAME}' already exists on {scene_name} with a DIFFERENT shape "
                  f"— pass --force to overwrite it: {already}")
            continue
        to_apply.append((scene_id, scene_name, NEW_KIND))
        verb = "update" if already is not None else "create"
        print(f"would {verb} '{KIND_NAME}' (momentary, hold_ms=500) "
              f"on {scene_name}: params={NEW_KIND['params']}")

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
            print(f"applied to {scene_name}: {result['summary']}")

    asyncio.run(_run())
    print(f"\ndone — {len(to_apply)} flare kind write(s) applied. "
          "Not attached to any band; attach via the Scenes page's Lane Rack "
          "when ready to fire them (attach to every band on a scene for "
          "\"runs at all intensity levels\").")


if __name__ == "__main__":
    main()
