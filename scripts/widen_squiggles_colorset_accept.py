"""One-time migration: widen "Squiggles V2"'s colour-set accept list from
its narrow 7-set allowlist to accept_all_sets=True (owner ask, 2026-08-19:
"widen what squiggles accepts").

WHY THE RESTRICTION EXISTED (established from the effect, not guessed):
Squiggles paints thin, sparse chains onto an otherwise-empty frame
(`fx/effects/squiggles.py::draw()` starts every frame from
`np.zeros((h, w, 3))`) — a real headless render (fx.headless, no live
storage/hardware touched) measured under 2% of pixels lit in normal
operation. The base render pipeline
(`fx/effects/__init__.py::get_pixels()`) composites the effect's
`background_color`/`background_mode` onto every "dark" pixel whenever
`bg_color_use` is true (i.e. whenever the configured background isn't
functionally black) — so ANY colour set authoring a bright `bg_color`
(the `Mid - *` family: `#ff0000 @ 0.5`, etc.) floods nearly the entire
frame: the SAME headless harness measured 100% of pixels flipping
"visibly bright" under a Mid-style background, vs 1–5% normally (see
`tests/test_squiggles_colorset_widen.py`). The seven accepted "Orbit -
*" sets all share one shape: `bg_color=#000000` on their Matrix-scoped
entry, which leaves `bg_color_use=False` — no wash. The restriction was
real and load-bearing, not arbitrary metadata.

THE FIX IS NOT A BIGGER ALLOWLIST — it removes the constraint at its
source, reusing a mechanism the codebase already has for exactly this
problem: `config/effect_params.json`'s per-effect `no_background_color`
registry flag (`fx.device_model.bg_color_blocked()`), already applied to
`radial` ("a non-black background washes the panel") and to `pacman`
(the OTHER sparse/black-canvas Matrix effect — also `buf =
np.zeros(...)` then `Image.fromarray(buf)`, ALSO restricted to the same
7 sets; left untouched here, out of scope for a Squiggles-only ask,
see `docs/SPECTRA_SPEC.md`). Setting the same flag on `squiggles` (this
repo, separate commit under the same PR) makes every colour-set-driven
write path (`scene_compiler.py` x2, `drift_conductor.py`,
`scene_response.py`) skip writing `background_color` onto Squiggles
regardless of which set fires — proven at the render-pipeline level, not
assumed, in the accompanying test. Once the background can never wash,
the accept list is genuinely unnecessary: this script sets
`accept_all_sets=True` (clearing `accepted_set_ids`), the SAME shape
every other Matrix scene already uses (Black Hole V2/Orbits
V2/STAR/Fireworks V2/Dancers V2/Eye V2 all accept_all_sets=True).

Does NOT touch the seven "Orbit - *" colour sets themselves (their
authored `bg_color=#000000` entries are load-bearing for every OTHER
scene that draws from them in Hybrid mode — see CLAUDE.md "An authored
black bg_color on a colour set is LOAD-BEARING IN HYBRID") and does NOT
touch Pacman V2's own accept list (a different scene, out of scope for
this ask even though it shares the same underlying mechanism).

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() (see
scripts/set_scene_colorset_preference.py's own docstring for the full
reasoning — model_dump_json() re-serializes every field in current
canonical form, incl. the legacy flare-band migration shim, which is a
far bigger change than "widen the accept list"). Loads the RAW JSON
dict, uses SceneV2 only to READ (name match, current value, diagnostic
printout), writes back by setting exactly two keys —
`accept_all_sets`/`accepted_set_ids` — on the untouched raw dict entry.

Dry-run by default; --apply writes the raw store (atomic tmp+replace,
indent=2, matching scene_store's own on-disk format) after copying it to
storage/spectra/backups/scenes-squiggles-accept-<stamp>.json. Idempotent.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config
from spectra.models.scene import SceneV2

TARGET_SCENE_NAME = "Squiggles V2"


def _describe(scene: SceneV2) -> str:
    return (f"  accept_all_sets: {scene.accept_all_sets!r}\n"
           f"  accepted_set_ids: {scene.accepted_set_ids!r}\n"
           f"  disabled: {scene.disabled!r}\n"
           f"  display_availability: {scene.display_availability!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))

    matches = [sid for sid, raw in store.items()
              if raw.get("name") == TARGET_SCENE_NAME]
    if not matches:
        raise SystemExit(f"scene '{TARGET_SCENE_NAME}' not found in "
                         f"{args.scenes_file} — refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"scene '{TARGET_SCENE_NAME}' matches {len(matches)} "
                         f"scenes in {args.scenes_file} — refusing to guess which one")
    sid = matches[0]
    scene = SceneV2(**store[sid])   # read-only: value confirmation + diagnostics
    print(f"— {TARGET_SCENE_NAME} ({sid}):")
    print(_describe(scene))

    if scene.accept_all_sets:
        print("  already accept_all_sets=True — nothing to do")
        return

    print("  -> accept_all_sets = True, accepted_set_ids = []\n")

    if not args.apply:
        print(f"DRY RUN — would patch {TARGET_SCENE_NAME} in {args.scenes_file} "
              "(use --apply). Only accept_all_sets/accepted_set_ids change; "
              "every other field on disk is left byte-identical.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"scenes-squiggles-accept-{stamp}.json"
    shutil.copy2(args.scenes_file, backup_path)
    print(f"backed up {args.scenes_file} -> {backup_path}")

    store[sid]["accept_all_sets"] = True
    store[sid]["accepted_set_ids"] = []

    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent), prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"patched {TARGET_SCENE_NAME} in {args.scenes_file} "
          "(accept_all_sets/accepted_set_ids only — verify with a before/after diff)")


if __name__ == "__main__":
    main()
