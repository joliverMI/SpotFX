"""One-time migration: retarget "First Group"'s Hue-category colour-set
override onto the LIVE `hues` virtual (pixel-brightness-chain report,
§6/§9: "First Group's 'Hue' category override reaches no live virtual —
the Hue category holds the inactive hue-lights/dining-hues, not hues".

`spectra/services/color_set_groups.py::resolve_for_fire` layers a group's
own override `entries` onto a member Set per virtual, per field, resolving
each entry's `scope` (`virtual_ids`/`categories`/`roles`,
`fx.device_model.resolve_scope`) to concrete virtual ids at fire time. His
real "First Group" carries an entry scoped to the **category** "Hue"
(brightness 0.72, background_brightness 0.5) — but the devices actually
driving his 17 Hue bulbs sit on the **Singles** category under the `hues`
virtual; "Hue" names the inactive `hue-lights`/`dining-hues` virtuals
(LedFX blender machinery, not in the live path), so the override is
layered onto nothing real and never reaches a bulb.

The fix is a scope change, nothing else: `categories: ["Hue"]` ->
`virtual_ids: ["hues"]`. His authored values (brightness 0.72,
background_brightness 0.5) are untouched.

RAW-DICT PATCH, same discipline as scripts/mark_rainbow_color_sets.py and
scripts/set_scene_colorset_preference.py: reads/writes the raw JSON dict
directly and touches exactly the one entry's `scope` key, never a
model_dump_json() round-trip of the whole card, and never another group.

`storage/color_sets.json` has no in-memory cache in front of it
(services/color_set_store.py re-reads the file on every call), so this is
safe to apply whether spot-effects is running or not.

Dry-run by default; --apply backs up storage/color_sets.json to
storage/backups/color-sets-first-group-hue-<stamp>.json first, then writes
atomically (tmp+replace). Idempotent — an already-retargeted entry is
reported unchanged and left untouched. Refuses (raising rather than
guessing) if "First Group" is missing, duplicated, or its Hue-category
override entry cannot be found unambiguously, or if its stored values
don't match the ones this migration is written for (0.72 / 0.5) — a
drifted value means someone already touched it since the report was
written, and this script should not silently paper over that.

Run from repo root:
    .venv/bin/python scripts/retarget_first_group_hue_override.py
    .venv/bin/python scripts/retarget_first_group_hue_override.py --apply
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

GROUP_NAME = "First Group"
STALE_CATEGORY = "Hue"
TARGET_VIRTUAL_ID = "hues"
EXPECTED_BRIGHTNESS = 0.72
EXPECTED_BACKGROUND_BRIGHTNESS = 0.5


def _find_group(store: dict) -> tuple[str, dict]:
    matches = [(cid, raw) for cid, raw in store.items()
              if raw.get("kind") == "group" and raw.get("name") == GROUP_NAME]
    if not matches:
        raise SystemExit(f"group '{GROUP_NAME}' not found — refusing to "
                         "guess; check the name against the live store")
    if len(matches) > 1:
        raise SystemExit(f"group '{GROUP_NAME}' matches {len(matches)} "
                         "cards — refusing to guess which one")
    return matches[0]


def _already_retargeted(entry: dict) -> bool:
    scope = entry.get("scope") or {}
    return (scope.get("virtual_ids") == [TARGET_VIRTUAL_ID]
            and not scope.get("categories")
            and entry.get("brightness") == EXPECTED_BRIGHTNESS
            and entry.get("background_brightness") == EXPECTED_BACKGROUND_BRIGHTNESS)


def _find_hue_entry(card: dict) -> tuple[int, dict, bool]:
    """Returns (index, entry, already_done). `already_done` is True when
    this script has already retargeted this exact entry (idempotent
    re-run) — found by its RESULT shape, not its stale "Hue" scope, since
    a successful first run removes the very thing the stale-category
    search looks for."""
    hue_hits = []
    done_hits = []
    for idx, entry in enumerate(card.get("entries") or []):
        scope = entry.get("scope") or {}
        if STALE_CATEGORY in (scope.get("categories") or []):
            hue_hits.append((idx, entry))
        elif _already_retargeted(entry):
            done_hits.append((idx, entry))
    if hue_hits:
        if len(hue_hits) > 1:
            raise SystemExit(f"'{GROUP_NAME}' has {len(hue_hits)} entries "
                             f"scoped to '{STALE_CATEGORY}' — refusing to "
                             "guess which one")
        idx, entry = hue_hits[0]
        return idx, entry, False
    if done_hits:
        if len(done_hits) > 1:
            raise SystemExit(f"'{GROUP_NAME}' has {len(done_hits)} entries "
                             f"already retargeted to virtual_ids="
                             f"[{TARGET_VIRTUAL_ID!r}] — refusing to guess "
                             "which one is the one this migration landed")
        idx, entry = done_hits[0]
        return idx, entry, True
    raise SystemExit(f"'{GROUP_NAME}' has no entry scoped to the "
                     f"'{STALE_CATEGORY}' category and none already "
                     f"retargeted to virtual_ids=[{TARGET_VIRTUAL_ID!r}] "
                     "with the expected values — nothing to retarget "
                     "(the data has changed since the report)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--color-sets-file", type=Path,
                        default=config.COLOR_SETS_FILE,
                        help="colour sets store (default: the live one)")
    args = parser.parse_args()

    if not args.color_sets_file.exists():
        raise SystemExit(f"no {args.color_sets_file} — nothing to migrate")
    store = json.loads(args.color_sets_file.read_text(encoding="utf-8"))

    cid, card = _find_group(store)
    idx, entry, already_done = _find_hue_entry(card)
    scope = entry.get("scope") or {}

    brightness = entry.get("brightness")
    bg_brightness = entry.get("background_brightness")
    print(f"— group '{GROUP_NAME}' ({cid}), entries[{idx}]: "
          f"scope.categories={scope.get('categories')!r}  "
          f"scope.virtual_ids={scope.get('virtual_ids')!r}  "
          f"brightness={brightness!r}  background_brightness={bg_brightness!r}")

    if already_done:
        print(f"  already retargeted to virtual_ids=[{TARGET_VIRTUAL_ID!r}] "
              "— nothing to do")
        return

    if brightness != EXPECTED_BRIGHTNESS or bg_brightness != EXPECTED_BACKGROUND_BRIGHTNESS:
        raise SystemExit(
            f"the entry's values ({brightness!r}, {bg_brightness!r}) don't "
            f"match what the report measured ({EXPECTED_BRIGHTNESS!r}, "
            f"{EXPECTED_BACKGROUND_BRIGHTNESS!r}) — someone already "
            f"touched this since; refusing to guess")

    print(f"  -> scope.categories = []  scope.virtual_ids = "
          f"[{TARGET_VIRTUAL_ID!r}]")

    if not args.apply:
        print(f"DRY RUN — would patch {args.color_sets_file} (use --apply). "
              "Only this one entry's scope changes; every other field on "
              "disk, and every other group, is left byte-identical.")
        return

    backup_dir = args.color_sets_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"color-sets-first-group-hue-{stamp}.json"
    shutil.copy2(args.color_sets_file, backup_path)
    print(f"backed up {args.color_sets_file} -> {backup_path}")

    new_scope = dict(scope)
    new_scope["categories"] = []
    new_scope["virtual_ids"] = [TARGET_VIRTUAL_ID]
    store[cid]["entries"][idx]["scope"] = new_scope   # the ONLY key touched

    fd, tmp = tempfile.mkstemp(dir=str(args.color_sets_file.parent),
                               prefix=".color_sets-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.color_sets_file)
    print(f"patched {args.color_sets_file}: '{GROUP_NAME}' entries[{idx}] "
          f"now scoped to virtual_ids=[{TARGET_VIRTUAL_ID!r}] "
          "(verify with a before/after diff)")


if __name__ == "__main__":
    main()
