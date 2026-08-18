"""One-time migration: declare two new named FlareKind entries on STAR —
his ask, verbatim: "It should also have a flare to reverse Direction and
another one to reverse momentarily for 500 milliseconds."

WHAT "REVERSE DIRECTION" MEANS ON radial (established, not assumed —
docs/SPECTRA_SPEC.md §78 carries the full trace): the
Fireworks V2 "Reverse Direction" kind Sonic authored earlier the same day
targets `reverse` (a plain boolean toggle on fireworks/fireworks1d, meaning
implode-vs-explode) — `radial`'s own CONFIG_SCHEMA (fx/effects/radial.py)
has no `reverse` key at all, so that kind cannot be reused verbatim on
STAR's Matrix entry. Direction on radial lives in `spin`: a single signed
numeric (fx/effects/radial.py accepts [-1.0, 1.0]; STAR's own binding and
its existing "Flare patch" kinds only ever write it positive, 0.1-1.0).
`spin_sign` ("Flip", maps_to spin, sign_control) is registry metadata for
a translation that only ever existed in legacy spot-effects
(services/morph_compiler.py's _sign_control_patch) — never ported to
spectra/ — and radial.py's CONFIG_SCHEMA has no spin_sign key regardless;
writing it would land as an inert extra key the effect never reads (see
config/effect_params.json's own note on spin_sign, and legacy's own
morph_compiler.py docstring: "LedFX has no bool to receive, so writing the
virtual name would be an inert no-op key"). So both new kinds target
`spin` directly, negative, matching the magnitude his own "Flare patch
0.35-0.7"/"Flare patch 0.7-1" kinds already use (0.55) — a value already
proven in range for both the registry's declared window and the real
vendored schema.

ONE MECHANISM, TWO KINDS, NOT THREE FEATURES: a permanent flip and a
500ms momentary flip are the same ParamTarget-on-spin mechanism at two
FlareKind types — not a third, separate "reverse" thing. The 500ms
MOMENTARY case was already a general, working mechanism before this
script (FlareKind.hold_ms, proven by Fireworks V2's own "Reverse
Direction" kind, which is in fact the momentary/500ms shape despite its
permanent-sounding name) — this script's own contribution is the STAR-
specific `spin` target and the (separately fixed) glide-vs-jump gate now
correctly applying to it, not a new hold mechanism.

WHY BOTH GLIDE, NOT SNAP: `spin`'s registry `smooth` flag was retagged
true the same pass this script shipped in (config/effect_params.json,
verified against fx/effects/radial.py + fx/utils.py's nonlinear_log, which
is continuous through zero and negative x) and scene_response._move_params
was fixed to respect a param-patch kind's smooth verdict the same way
_reroll already respects it for dice re-rolls. Together: these two new
kinds glide over DICE_REROLL_GLIDE_MS when they fire, not jump — a
"reverse" that snaps instantly would read as another broken star, not a
fluid effect.

MOMENTARY DOES NOT RE-ROLL: "Reverse Momentarily (500ms)" is type=momentary
with only a `spin` ParamTarget — no jump field is legal on a non-drift_jump
kind (FlareKind._shape enforces this), so it structurally cannot re-roll
STAR's dice-bound star/edges. Its params are independent of whatever Dice
Re-roll does in the same event.

DECLARED, NOT BAND-ATTACHED — matching precedent, not an oversight:
Fireworks V2's own "Reverse Direction" kind is declared in flare_kinds but
attached to zero bands (scene_console.apply_flare_kind only ever touches
flare_kinds, never responses/band.kinds — this is a hard scope boundary,
not a missed step; band attachment is the UI's own click-to-attach chip on
the band strip, ResponseTab.tsx/BandStrip.tsx). This script follows the
same shape: the two kinds land available and ready, and Javi (or whoever
edits the Scenes page) picks which band(s) fire them and at what scale.

Uses the SAME production write path Sonic's scene console uses
(scene_console.apply_flare_kind) rather than a raw-JSON patch: unlike a
single-scalar-field edit (see scripts/set_scene_colorset_preference.py's
own reasoning for why THAT script avoids scene_store.save()), adding a
FlareKind is exactly what apply_flare_kind exists for — full FlareKind
validation, a whole-scene re-validate, and a verified pre-write backup
(scene_console._write_and_verify_backup) all come for free, and the
model's own _migrate_flare_kinds pass is a documented no-op on a scene
that already carries a canonical `flare_kinds` key (true of STAR).

Idempotent: a kind already present under the same name is left alone
(reported, not overwritten) unless --force. Dry-run by default; --apply
performs the write. Not run against live storage by this build — an
operator/deploy step, same convention as
scripts/set_scene_colorset_preference.py and scripts/seed_star_strips.py.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra.models.scene import FlareKind
from spectra.services import scene_console, scene_store

SCENE_NAME = "STAR"
SPIN_REVERSE_VALUE = -0.55   # negation of his own "Flare patch 0.35-0.7"/"0.7-1" spin magnitude

NEW_KINDS = [
    {
        "name": "Reverse Direction",
        "type": "permanent",
        "jump": None,
        "params": {"spin": {"mode": "absolute", "value": SPIN_REVERSE_VALUE}},
        "gain": 1.0,
        "hold_ms": None,
    },
    {
        "name": "Reverse Momentarily (500ms)",
        "type": "momentary",
        "jump": None,
        "params": {"spin": {"mode": "absolute", "value": SPIN_REVERSE_VALUE}},
        "gain": 1.0,
        "hold_ms": 500,
    },
]


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
    normalizing NEW_KINDS's terse literals through the model before comparing
    against _existing()'s already-normalized dumps, so a real match isn't
    mistaken for a shape drift."""
    return FlareKind.model_validate(kind).model_dump(mode="json")


async def _apply(scene_id: str, kind: dict) -> dict:
    return await scene_console.apply_flare_kind(
        scene_id,
        name=kind["name"], type=kind["type"], jump=kind["jump"],
        params=kind["params"], gain=kind["gain"], hold_ms=kind["hold_ms"],
        source="script:add_star_reverse_flares")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--force", action="store_true",
                        help="re-apply even if a kind with the same name already exists "
                             "(overwrites that kind's shape — apply_flare_kind's own "
                             "update-by-name behaviour)")
    args = parser.parse_args()

    scene_id = _find_scene_id(SCENE_NAME)
    current = _existing(scene_id)

    to_apply = []
    for kind in NEW_KINDS:
        already = current.get(kind["name"])
        norm = _normalized(kind)
        same_shape = already is not None and all(
            already.get(f) == norm[f] for f in ("type", "jump", "params", "gain", "hold_ms"))
        if same_shape:
            print(f"'{kind['name']}' already present on {SCENE_NAME}, identical shape — skipping")
            continue
        if already is not None and not args.force:
            print(f"'{kind['name']}' already exists on {SCENE_NAME} with a DIFFERENT shape "
                  f"— pass --force to overwrite it: {already}")
            continue
        to_apply.append(kind)
        verb = "update" if already is not None else "create"
        hold_bit = f", hold_ms={kind['hold_ms']}" if kind["hold_ms"] is not None else ""
        print(f"would {verb} '{kind['name']}' ({kind['type']}{hold_bit}) "
              f"on {SCENE_NAME}: params={kind['params']}")

    if not to_apply:
        print("nothing to do")
        return

    if not args.apply:
        print(f"\nDRY RUN — would apply {len(to_apply)} flare kind(s) to {SCENE_NAME} "
              "via scene_console.apply_flare_kind (use --apply). Each write is backed up "
              "first (scene_console._write_and_verify_backup) — these are declared only, "
              "never attached to a band; attach via the Scenes page.")
        return

    async def _run() -> None:
        for kind in to_apply:
            result = await _apply(scene_id, kind)
            print(f"applied: {result['summary']}")

    asyncio.run(_run())
    print(f"\ndone — {len(to_apply)} flare kind(s) applied to {SCENE_NAME}. "
          "Not attached to any band; attach via the Scenes page when ready to fire them.")


if __name__ == "__main__":
    main()
