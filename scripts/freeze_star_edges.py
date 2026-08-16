"""Stop STAR's edge count moving mid-run — the Admiral's final word,
2026-08-15, superseding the first cut of this fix: "i will make it very
simple just delete whatever portion of any Flair was changing edges. but
initial can be 3 to 6." Resolves OQ-6 / §54 (docs/SPECTRA_SPEC.md).

Two edge-changing mechanisms are deleted here, both of them, no survivor —
all his own explicit word, not silently decided (see
docs/spectra-star-edges-freeze.md, the durable record of exactly what each
one was and how to restore it):

  1. The Matrix device's `edges` param was a signal="random" ValueBinding
     re-rolled on demand by the "Dice Re-roll" flare kind
     (services/scene_response.py::_reroll, attached to all three flare
     bands) — that mid-run re-roll is now impossible: the replacement
     binding is marked `sticky=True` (models/binding.py), which _reroll
     skips on purpose. Fire-time resolution is UNCHANGED — scene_compiler.
     resolve_scene() never looks at `sticky` — so a fresh scene start still
     rolls a value; nothing after that start moves it again.
  2. "Flare patch 0.7-1" and "Drop patch 0.7-1" (both `type: "permanent"`)
     each explicitly patched `edges` to 6.0 alongside spin/star — both
     retire their `edges` key entirely. spin/star are untouched.

Initial value: a UNIFORM roll over every integer 3, 4, 5, 6 (his own words,
"3 to 6," read as inclusive of every integer in that range, not the three
non-uniform values — 6/3/5 at 40/40/20% — the old binding actually rolled).
Expressed with the existing steps mechanism: four equal-width bands,
thresholds 0.0/0.25/0.5/0.75, one each per value — the mechanism supports
this natively, no new binding shape needed. Independent draw (dice=None) —
not correlated with `star`'s own roll; nothing asked for that correlation.

--restore undoes exactly what THIS fix changes: back to the 6/3/5 dice
binding + both patches' edges override, i.e. whatever is actually deployed
in his room immediately before this migration runs. It does NOT reach back
further to his pre-SPECTRA-rebuild legacy scene (a plain static `edges =
6`, no binding, no steps, neither patch present at all) — that's a bigger,
separate finding, recorded for provenance below and in
docs/spectra-star-edges-freeze.md / AGENTS.md, not something this script
acts on.

PROVENANCE (kept because it explains a fact about his system that outlives
this task, not because it drove the value above — his explicit "3 to 6"
stands regardless): his LEGACY STAR authored `edges` as a bare static `6`
— no signal binding, no steps, and NEITHER "Flare patch"/"Drop patch" kind
exists anywhere in the legacy per-band param_patch data. The 6/3/5 dice
binding and both patches were introduced during the SPECTRA rebuild by an
agent, not by him — he never asked for any of it, and noticed only because
his six-pointed star stopped being six-pointed. See AGENTS.md for the
general rule this instance is evidence for.

Targets scene id d3aab04c… in storage/spectra/scenes.json BY ID — the live
store names it STAR. Dry-run by default either direction; --apply writes
(atomic, whole store, indent=2 — the store's own format). Idempotent.
--restore switches direction but still needs --apply to actually write,
same as freezing.

DO NOT deliver this by re-running scripts/seed_spectra_from_v2.py: that
seeder REBUILDS the SPECTRA store from the legacy world and would erase
this fix (and, per the provenance note, would NOT reproduce --restore's
target either — it would give back the deeper, pre-rebuild static 6). This
script is the supported migration path both ways.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config
from spectra.models.binding import ValueBinding
from spectra.models.scene import ParamTarget, SceneV2

STAR_ID = "d3aab04c-7e23-4693-bd26-16bad45792a6"

# His words: "initial can be 3 to 6" — read as every integer 3/4/5/6,
# uniform (firstmate's explicit reading, not inferred). Four equal steps,
# independent roll (no dice letter — nothing asked for correlation with
# `star`).
STICKY_EDGES_BINDING = {
    "bind": "signal", "signal": "random", "window_beats": 0,
    "window_dir": "past", "mode": "steps", "in_min": 0.0, "in_max": 1.0,
    "out_min": 0.0, "out_max": 1.0,
    "steps": [{"threshold": 0.0, "value": 3.0},
              {"threshold": 0.25, "value": 4.0},
              {"threshold": 0.5, "value": 5.0},
              {"threshold": 0.75, "value": 6.0}],
    "fallback": 3.0, "random_sign": False, "dice": None, "sticky": True,
}

# What's actually deployed in his room right now, immediately before this
# fix — what --restore gives back. Also written out in full in
# docs/spectra-star-edges-freeze.md, the durable, git-tracked record — kept
# here too so --restore is a real one-step command, and so the two copies
# can be diffed against each other.
RETIRED_EDGES_BINDING = {
    "bind": "signal", "signal": "random", "window_beats": 0,
    "window_dir": "past", "mode": "steps", "in_min": 0.0, "in_max": 1.0,
    "out_min": 0.0, "out_max": 1.0,
    "steps": [{"threshold": 0.0, "value": 6.0},
              {"threshold": 0.4, "value": 3.0},
              {"threshold": 0.8, "value": 5.0}],
    "fallback": 6.0, "random_sign": False, "dice": "a",
}
RETIRED_EDGES_TARGET = {"mode": "absolute", "value": 6.0,
                        "offset": None, "lo": None, "hi": None}
RETIRED_PATCH_KIND_NAMES = ("Flare patch 0.7–1", "Drop patch 0.7–1")

# His TRUE original, pre-SPECTRA-rebuild — informational only (see the
# module docstring's PROVENANCE note). Not what --restore reproduces.
LEGACY_EDGES_STATIC_VALUE = 6


def with_star_edges_frozen(raw_scene: dict) -> dict:
    """The scene with the fix applied. Validates through SceneV2 FIRST (not
    after) so a legacy-shaped store — param_patch under responses, no
    top-level flare_kinds yet — auto-migrates into named kinds before the
    two patches are touched; operating on the raw dict directly would
    silently miss them on anything not already re-saved in canonical form.
    Raises if the scene has no Matrix/radial entry."""
    scene = SceneV2(**raw_scene)
    matrix = [d for d in scene.devices
             if d.target == "Matrix" and d.effect_type == "radial"]
    if not matrix:
        raise SystemExit(
            f"scene '{raw_scene.get('name')}' has no Matrix/radial entry — "
            "refusing to guess where the fix belongs")
    for dev in matrix:
        if "edges" in dev.params:
            dev.params["edges"] = ValueBinding(**STICKY_EDGES_BINDING)
    for kind in scene.flare_kinds:
        if kind.name in RETIRED_PATCH_KIND_NAMES:
            kind.params.pop("edges", None)
    return json.loads(scene.model_dump_json())


def with_star_edges_restored(raw_scene: dict) -> dict:
    """The inverse of with_star_edges_frozen — re-applies the exact 6/3/5
    dice binding + both patches' edges override, i.e. exactly what's
    deployed today, immediately before this fix. Only touches what the fix
    touched."""
    scene = SceneV2(**raw_scene)
    matrix = [d for d in scene.devices
             if d.target == "Matrix" and d.effect_type == "radial"]
    for dev in matrix:
        dev.params["edges"] = ValueBinding(**RETIRED_EDGES_BINDING)
    for kind in scene.flare_kinds:
        if kind.name in RETIRED_PATCH_KIND_NAMES:
            kind.params["edges"] = ParamTarget(**RETIRED_EDGES_TARGET)
    return json.loads(scene.model_dump_json())


def _write(store: dict, path: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", action="store_true",
                        help="undo the fix instead of applying it (back to "
                             "what's deployed today — see the module "
                             "docstring for why that's not his deeper "
                             "legacy original)")
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    if STAR_ID not in store:
        raise SystemExit(f"scene {STAR_ID} (STAR) not in {args.scenes_file}")

    transform = with_star_edges_restored if args.restore else with_star_edges_frozen
    verb = "restore" if args.restore else "fix"
    migrated = transform(store[STAR_ID])
    if migrated == store[STAR_ID]:
        print(f"'{migrated['name']}' already has the {verb} applied — nothing to do")
        return

    matrix = next(d for d in migrated["devices"]
                  if d["target"] == "Matrix" and d["effect_type"] == "radial")
    patched = [k["name"] for k in migrated["flare_kinds"]
              if k["name"] in RETIRED_PATCH_KIND_NAMES]
    print(f"— {migrated['name']} ({STAR_ID}): Matrix edges -> "
          f"{matrix['params'].get('edges')!r}; {len(patched)} flare "
          f"kind(s) touched ({', '.join(patched)})")
    if not args.apply:
        print(f"\nDRY RUN ({verb}) — would update the scene in "
              f"{args.scenes_file} (use --apply)")
        return

    store[STAR_ID] = migrated
    _write(store, args.scenes_file)
    print(f"wrote {args.scenes_file}")


if __name__ == "__main__":
    main()
