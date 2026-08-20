"""One-time migration: mark his ENUMERATED rainbow colour sets/groups with
ColorSetCard.is_rainbow = True (models/color_set.py, spectra/services/
rainbow_select.py — owner ask 2026-08-20, `data/two-dimensional-drift-
gradient-and-rainb-imfg/HIS-VERBATIM-WORDS.md`).

His words: "The 3 hype sets and it's group, as well as black hole rainbow.
are the only current rainbow." ENUMERATED, never inferred from name — his
own instruction: "Do not infer more from names — several of his other sets
have colourful names and are not rainbows." So this script matches by exact
(kind, name) against his live storage/color_sets.json, refusing to guess on
zero or ambiguous matches, same discipline as
scripts/set_scene_colorset_preference.py.

RAW-DICT PATCH: reads/writes the raw JSON dict directly, setting exactly one
key (is_rainbow) per matched card, rather than round-tripping every card
through models.color_set.ColorSetCard's own model_dump_json() — the same
"don't touch fields you didn't mean to touch" discipline
set_scene_colorset_preference.py established for scene storage.

Dry-run by default; --apply backs up storage/color_sets.json to
storage/backups/color-sets-rainbow-<stamp>.json first, then writes
atomically (tmp+replace). Idempotent — an already-marked card is reported
unchanged and left untouched.
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

TARGETS = [
    ("set", "Hype 1"),
    ("set", "Hype 2"),
    ("set", "Hype 3"),
    ("group", "Hype"),
    ("set", "Black Hole Rainbow"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--color-sets-file", type=Path,
                        default=config.COLOR_SETS_FILE,
                        help="colour sets store (default: the live one)")
    args = parser.parse_args()

    if not args.color_sets_file.exists():
        raise SystemExit(f"no {args.color_sets_file} — nothing to migrate")
    store = json.loads(args.color_sets_file.read_text(encoding="utf-8"))

    by_kind_name: dict[tuple[str, str], list[str]] = {}
    for cid, raw in store.items():
        by_kind_name.setdefault((raw.get("kind", "set"), raw.get("name")), []).append(cid)

    to_patch: list[str] = []
    for kind, name in TARGETS:
        matches = by_kind_name.get((kind, name), [])
        if not matches:
            raise SystemExit(f"{kind} '{name}' not found in {args.color_sets_file} — "
                             "refusing to guess; check the name against the live store")
        if len(matches) > 1:
            raise SystemExit(f"{kind} '{name}' matches {len(matches)} cards in "
                             f"{args.color_sets_file} — refusing to guess which one")
        cid = matches[0]
        current = bool(store[cid].get("is_rainbow", False))
        print(f"— {kind} '{name}' ({cid}): is_rainbow={current}")
        if current:
            print("  already marked rainbow — nothing to do\n")
            continue
        to_patch.append(cid)
        print("  -> is_rainbow = True\n")

    if not to_patch:
        print("all five cards already marked rainbow — nothing to do")
        return

    if not args.apply:
        print(f"DRY RUN — would patch {len(to_patch)} card(s) in {args.color_sets_file} "
              "(use --apply). Only the is_rainbow key changes; every other "
              "field on disk is left byte-identical.")
        return

    backup_dir = args.color_sets_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"color-sets-rainbow-{stamp}.json"
    shutil.copy2(args.color_sets_file, backup_path)
    print(f"backed up {args.color_sets_file} -> {backup_path}")

    for cid in to_patch:
        store[cid]["is_rainbow"] = True   # the ONLY key touched

    fd, tmp = tempfile.mkstemp(dir=str(args.color_sets_file.parent),
                               prefix=".color_sets-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.color_sets_file)
    print(f"patched {len(to_patch)} card(s) in {args.color_sets_file} "
          "(is_rainbow only — verify with a before/after diff)")


if __name__ == "__main__":
    main()
