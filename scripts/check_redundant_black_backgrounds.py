#!/usr/bin/env python3
"""Read-only evidence script for the "Black Hole ignores Light mode" report
(docs/SPECTRA_SPEC.md §72).

Finds every ColorSetEntry across storage/color_sets.json that authors a
black bg_color (the redundant-background pattern the Admiral asked about),
and buckets them by (bg_mode, background_brightness) so the two shapes he
already spotted -- overwrite@1.0 (Black Hole/Orbit) vs additive@None
(Line - *) -- are visible, plus anything that doesn't fit either bucket.

Never writes anything. Defaults to spectra.config.COLOR_SETS_FILE (this
repo's own storage/color_sets.json); pass --path to point at a different
copy (e.g. a backup, or another worktree's storage) without touching config.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_BLACK = {"#000000", "#000", "black", "rgb(0,0,0)"}


def find_black_backgrounds(color_sets: dict) -> list[dict]:
    hits = []
    for set_id, card in color_sets.items():
        for idx, entry in enumerate(card.get("entries", [])):
            bg = entry.get("bg_color")
            if bg and str(bg).lower() in _BLACK:
                hits.append({
                    "set_id": set_id,
                    "set_name": card.get("name"),
                    "entry_index": idx,
                    "bg_mode": entry.get("bg_mode"),
                    "background_brightness": entry.get("background_brightness"),
                    "scope_categories": entry.get("scope", {}).get("categories"),
                    "scope_virtual_ids": entry.get("scope", {}).get("virtual_ids"),
                })
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=None,
                        help="Path to color_sets.json (default: spectra.config.COLOR_SETS_FILE)")
    args = parser.parse_args()

    if args.path is not None:
        path = args.path
    else:
        from spectra import config
        path = config.COLOR_SETS_FILE

    color_sets = json.loads(path.read_text(encoding="utf-8"))
    hits = find_black_backgrounds(color_sets)

    by_shape: dict[tuple, list[dict]] = {}
    for h in hits:
        key = (h["bg_mode"], h["background_brightness"])
        by_shape.setdefault(key, []).append(h)

    print(f"Source: {path}")
    print(f"Total entries with a black bg_color: {len(hits)}")
    print(f"Distinct colour sets affected: {len({h['set_name'] for h in hits})}")
    print()
    for shape, items in sorted(by_shape.items(), key=lambda kv: -len(kv[1])):
        mode, brightness = shape
        print(f"  bg_mode={mode!r} background_brightness={brightness!r} -> {len(items)} entries")
    print()
    for h in sorted(hits, key=lambda h: (h["set_name"] or "")):
        print(f"  {h['set_name']!r:28} entry#{h['entry_index']} "
              f"bg_mode={h['bg_mode']!r} bg_bright={h['background_brightness']!r} "
              f"scope_cats={h['scope_categories']} scope_virtual_ids={h['scope_virtual_ids']}")


if __name__ == "__main__":
    main()
